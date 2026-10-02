"""Renew job ownership while computing; fail closed if a renewal fails."""
from contextlib import contextmanager
from threading import Event, Thread
from graphword.jobs import InvalidJobTransition


@contextmanager
def keep_claim_alive(jobs, claim, lease_seconds):
    stopped = Event()
    failures = []

    def renew_loop():
        while not stopped.wait(max(0.1, lease_seconds / 3)):
            try:
                jobs.renew(claim, lease_seconds)
            except Exception as error:
                failures.append(error)
                return

    thread = Thread(target=renew_loop, name="graphword-lease", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join()  # Never confirm while an in-flight renewal can modify state.
    if failures:
        raise InvalidJobTransition("lease renewal failed; result must not be published") from failures[0]
