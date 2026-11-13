"""Single-flight background jobs that the worker loop polls for results."""

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from threading import Event

from .models import LookupCancelled


class Cancellation:
    """A job token cancelled by its own request or by the worker's shutdown."""

    def __init__(self, parent):
        self.parent = parent
        self.local = Event()

    def is_set(self):
        return self.parent.is_set() or self.local.is_set()

    def set(self):
        self.local.set()

    def check(self):
        if self.is_set():
            raise LookupCancelled("Lyrics request cancelled.")


@dataclass
class Job:
    future: Future
    kind: str
    # (track key, generation) the job was started for; stale results are discarded.
    context: tuple | None
    token: Cancellation
    payload: object = None

    def current(self, context) -> bool:
        return self.context == context and not self.token.is_set()


class JobSlot:
    """A serial worker running at most one job; cancelled jobs finish unobserved."""

    def __init__(self, name: str, cancelled):
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix=name)
        self.cancelled = cancelled
        self.job: Job | None = None

    @property
    def busy(self) -> bool:
        return self.job is not None

    def start(self, kind: str, context, work, *, payload=None) -> Job:
        """Run ``work(token)`` on the pool."""
        token = Cancellation(self.cancelled)
        self.job = Job(self.pool.submit(work, token), kind, context, token, payload)
        return self.job

    def take_done(self) -> Job | None:
        job = self.job
        if job is None or not job.future.done():
            return None
        self.job = None
        return job

    def cancel(self):
        if self.job:
            self.job.token.set()

    def shutdown(self):
        self.pool.shutdown(wait=True, cancel_futures=True)
