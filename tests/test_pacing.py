"""Cadencement des appels sortants vers l'API Discogs — SPEC-META-001, tâche 10.

Le quota authentifié est de 60 requêtes/minute et il est **global au jeton**.
FastAPI servant les endpoints synchrones dans un pool de threads, deux lots
peuvent se chevaucher : c'est le cadenceur partagé, pas une variable locale à la
requête, qui tient la garantie. D'où ce test avec deux threads concurrents.
"""

import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server  # noqa: E402


def _reset():
    server._pace_last = 0.0


class TestPaceDiscogs:
    def test_premier_appel_immediat(self):
        """Une passe ne doit pas commencer par une seconde d'attente inutile."""
        _reset()
        start = time.monotonic()
        server._pace_discogs()
        assert time.monotonic() - start < 0.2

    def test_appels_successifs_espaces_d_une_seconde(self):
        _reset()
        server._pace_discogs()
        start = time.monotonic()
        server._pace_discogs()
        assert time.monotonic() - start >= 0.9

    def test_appels_concurrents_ne_doublent_pas_la_cadence(self):
        """🔴 Le cas qui justifie le verrou partagé : deux requêtes HTTP
        simultanées ne doivent pas produire deux appels dans la même seconde."""
        _reset()
        stamps: list[float] = []
        lock = threading.Lock()

        def worker():
            server._pace_discogs()
            with lock:
                stamps.append(time.monotonic())

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        stamps.sort()
        assert len(stamps) == 3
        for earlier, later in zip(stamps, stamps[1:]):
            assert later - earlier >= 0.9
