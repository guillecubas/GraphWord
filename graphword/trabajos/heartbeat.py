"""Renovar la reserva durante el cálculo e impedir confirmar si falla la renovación."""
from contextlib import contextmanager
from threading import Event, Thread
from graphword.trabajos.jobs import InvalidJobTransition


@contextmanager
def keep_claim_alive(jobs, claim, lease_seconds):
    # Este evento avisa al hilo de renovación de que debe terminar.
    stopped = Event()
    failures = []

    def renew_loop():
        # Esperar un tercio de la reserva deja margen para renovarla a tiempo.
        while not stopped.wait(max(0.1, lease_seconds / 3)):
            try:
                jobs.renew(claim, lease_seconds)
            except Exception as error:
                failures.append(error)
                return

    thread = Thread(target=renew_loop, name="graphword-lease", daemon=True)
    thread.start()
    try:
        # El bloque with ejecuta aquí el cálculo del worker.
        yield
    finally:
        stopped.set()
        thread.join()  # Esperar la última renovación antes de confirmar el resultado.
    if failures:
        raise InvalidJobTransition("lease renewal failed; result must not be published") from failures[0]
