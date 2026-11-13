"""Unzip and test the worker while denying access to the repo and host Python."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile

from bundle import verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory(prefix="Lyrics Pro portability ") as temporary:
        temporary = Path(temporary).resolve()
        subprocess.run(["/usr/bin/ditto", "-x", "-k", str(args.archive.resolve()), str(temporary)], check=True)
        apps = list(temporary.glob("*/Lyrics Pro.app"))
        if len(apps) != 1:
            raise RuntimeError("Archive must contain exactly one Lyrics Pro app")
        app = apps[0].rename(temporary / "Relocated Lyrics Pro.app")
        verify(app)
        worker = app / "Contents/Helpers/LyricsBackend.app/Contents/MacOS/lyrics-pro-worker"
        test_home = temporary / "Recipient Home"
        test_home.mkdir()
        environment = {"HOME": str(test_home), "PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8",
                       "TMPDIR": str(temporary), "PYINSTALLER_RESET_ENVIRONMENT": "1"}
        blocked = {root, Path(sys.base_prefix).resolve(), Path("/opt/homebrew"), Path("/usr/local"),
                   Path.home() / ".local/share/uv/python", Path.home() / ".local/share/mise"}
        # sandbox-exec is used only as a test harness, never at app runtime.
        policy = "(version 1) (allow default) (deny network*) (deny appleevent-send) "
        policy += " ".join(f"(deny file-read* (subpath {json.dumps(str(path))}))" for path in blocked)
        policy += f" (deny file-write* (subpath {json.dumps(str(app))}))"
        sandbox = ["/usr/bin/sandbox-exec", "-p", policy]
        def run(command, **kwargs):
            return subprocess.run(sandbox + command, cwd=test_home, env=environment,
                                  capture_output=True, text=True, timeout=30, **kwargs)
        denial = run(["/bin/cat", str(root / "pyproject.toml")])
        if denial.returncode == 0:
            raise RuntimeError("Isolation check failed: repository is still readable")
        readonly = run(["/usr/bin/touch", str(app / "should-not-be-writable")])
        if readonly.returncode == 0:
            raise RuntimeError("Isolation check failed: app bundle is writable")
        checked = run([str(worker), "--self-check"], check=True)
        report = json.loads(checked.stdout)
        if not report["ok"] or report["architecture"] != "arm64":
            raise RuntimeError(f"Invalid worker self-check: {report}")
        print("Offline self-check passed with repository/host Python/network access denied and app read-only.")
        for _ in range(2):  # Both first launch and a fresh reconnect process.
            process = subprocess.Popen(sandbox + [str(worker)], cwd=test_home, env=environment,
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                stdout, stderr = process.communicate('{"version":2,"type":"shutdown","payload":{}}\n', timeout=15)
            finally:
                if process.poll() is None:
                    if os.getpgid(process.pid) == process.pid:
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                    process.wait()
            messages = [json.loads(line) for line in stdout.splitlines()]
            if process.returncode != 0 or not any(message.get("type") == "ready" and message.get("version") == 2 for message in messages):
                raise RuntimeError(f"Worker protocol failed: {stdout}\n{stderr}")
            if "worker_stop" not in stderr:
                raise RuntimeError("Worker failed to shut down cleanly")
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                pass
            else:
                raise RuntimeError("Worker left a process group behind")
        print("Packaged worker startup, NDJSON readiness, shutdown, and restart passed.")
        print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
