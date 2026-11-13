"""Bounded, cancellable JSON requests through the system curl."""

import json
import subprocess
from threading import Event
import time

from ..models import LookupCancelled, LookupFailure


CURL = "/usr/bin/curl"
DEADLINE_SECONDS = 17
USER_AGENT = "LyricsPro/0.1 (personal terminal prototype)"


def check_cancelled(cancelled: Event | None):
    if cancelled is not None and cancelled.is_set():
        raise LookupCancelled("Lyrics request cancelled.")


def run_curl(command: list[str], cancelled: Event | None = None):
    check_cancelled(cancelled)
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
        deadline = time.monotonic() + DEADLINE_SECONDS
        try:
            while True:
                check_cancelled(cancelled)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, DEADLINE_SECONDS)
                try:
                    stdout, stderr = process.communicate(timeout=min(0.2, remaining))
                    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
                except subprocess.TimeoutExpired:
                    continue
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()


def http_json(url: str, service: str, cancelled: Event | None = None, *, referer: str | None = None):
    """Return decoded JSON, or None for HTTP 404."""
    headers = ["--referer", referer] if referer else []
    try:
        response = run_curl(
            [CURL, "-4", "--compressed", "--silent", "--show-error", "--connect-timeout", "5",
             "--max-time", "15", "--max-filesize", "5000000", "--user-agent", USER_AGENT,
             *headers, "--write-out", "\n%{http_code}", url],
            cancelled,
        )
    except subprocess.TimeoutExpired as exc:
        raise LookupFailure(f"{service} request timed out.", retryable=True) from exc
    except FileNotFoundError as exc:
        raise LookupFailure("curl is required to retrieve lyrics.") from exc
    if response.returncode:
        error = response.stderr.decode("utf-8", errors="replace") if isinstance(response.stderr, bytes) else response.stderr
        raise LookupFailure(f"{service} network request failed: " + error.strip(), retryable=True)
    output = response.stdout.encode("utf-8") if isinstance(response.stdout, str) else response.stdout
    body, _, status_bytes = output.rpartition(b"\n")
    status = status_bytes.decode("ascii", errors="replace")
    if status == "404":
        return None
    if status != "200":
        raise LookupFailure(f"{service} returned HTTP {status}.",
                            retryable=status == "429" or status.startswith("5"))
    try:
        data = json.loads(body.decode("utf-8"))
    except ValueError as exc:
        raise LookupFailure(f"{service} returned invalid JSON.", retryable=True) from exc
    if data is None:
        raise LookupFailure(f"{service} returned an invalid response.", retryable=True)
    return data
