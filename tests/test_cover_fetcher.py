"""Tests de la récupération des pochettes — SPEC-META-001, tâche 10.

Aucun appel réseau : le client Discogs est remplacé par un double. Ce qui est
testé ici n'est pas l'API mais **la distinction absence / panne**, dont dépend
la mémoire de l'appelant. Se tromper de côté condamne définitivement des
releases qui ont pourtant une pochette.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import cover_fetcher  # noqa: E402


class FakeRelease:
    def __init__(self, images):
        self._images = images

    def fetch(self, _field):
        return self._images


class FakeClient:
    """Client Discogs de substitution. `images=None` déclenche une panne."""

    def __init__(self, images):
        self._images = images

    def release(self, _release_id):
        if self._images is None:
            raise ConnectionError("réseau indisponible")
        return FakeRelease(self._images)


@pytest.fixture
def with_client(monkeypatch):
    def install(images):
        monkeypatch.setattr(cover_fetcher, "get_client", lambda: FakeClient(images))
    return install


class TestFetchCover:
    def test_image_presente(self, with_client):
        with_client([{"uri": "https://i.discogs.com/abc.jpeg"}])
        res = cover_fetcher.fetch_cover(3235)
        assert res.url == "https://i.discogs.com/abc.jpeg"
        assert res.failed is False

    def test_premiere_image_retenue(self, with_client):
        with_client([{"uri": "https://i.discogs.com/1.jpeg"}, {"uri": "https://i.discogs.com/2.jpeg"}])
        assert cover_fetcher.fetch_cover(3235).url == "https://i.discogs.com/1.jpeg"

    def test_release_sans_image_est_une_absence_certaine(self, with_client):
        """Réponse obtenue, liste vide : inutile de réessayer un jour."""
        with_client([])
        res = cover_fetcher.fetch_cover(3235)
        assert res.url is None
        assert res.failed is False

    def test_panne_reseau_est_reessayable(self, with_client):
        """🔴 Le cas qui compte : sans `failed`, l'appelant écrirait une absence
        définitive sur une release qui a une pochette."""
        with_client(None)
        res = cover_fetcher.fetch_cover(3235)
        assert res.url is None
        assert res.failed is True

    def test_sans_jeton_est_reessayable(self, monkeypatch):
        """Un jeton renseigné plus tard doit pouvoir rattraper ces releases."""
        monkeypatch.setattr(cover_fetcher, "get_client", lambda: None)
        res = cover_fetcher.fetch_cover(3235)
        assert res.url is None
        assert res.failed is True

    def test_image_sans_uri(self, with_client):
        """Entrée présente mais sans `uri` : absence, pas panne."""
        with_client([{"type": "primary"}])
        res = cover_fetcher.fetch_cover(3235)
        assert res.url is None
        assert res.failed is False


class TestCause:
    """La cause de l'échec REMONTE À L'APPELANT.

    🔴 Elle ne peut pas être journalisée sur place : l'exe est construit
    `console=False`, une trace imprimée n'irait nulle part. Sans ce champ, un
    quota dépassé, un jeton refusé et une release disparue se lisaient d'un même
    « réseau ou quota » — trois corrections différentes sous un seul message.
    Mesuré au terrain le 2026-07-28 : 58 % d'échecs, cause inconnue.
    """

    def test_le_succes_ne_porte_aucune_cause(self, with_client):
        with_client([{"uri": "https://i.discogs.com/abc.jpeg"}])
        assert cover_fetcher.fetch_cover(3235).error is None

    def test_absence_certaine_non_plus(self, with_client):
        with_client([])
        assert cover_fetcher.fetch_cover(3235).error is None

    def test_la_panne_nomme_son_type_et_son_message(self, with_client):
        with_client(None)
        err = cover_fetcher.fetch_cover(3235).error
        assert "ConnectionError" in err
        assert "réseau indisponible" in err

    def test_le_jeton_absent_le_dit_en_clair(self, monkeypatch):
        monkeypatch.setattr(cover_fetcher, "get_client", lambda: None)
        assert cover_fetcher.fetch_cover(3235).error == "jeton Discogs absent"

    def test_le_code_http_est_extrait_quand_il_existe(self, monkeypatch):
        """C'est LUI qui sépare un quota (429) d'un jeton refusé (401)."""

        class HTTPError(Exception):
            status_code = 429

        class Boom:
            def release(self, _id):
                raise HTTPError("too many requests")

        monkeypatch.setattr(cover_fetcher, "get_client", lambda: Boom())
        err = cover_fetcher.fetch_cover(3235).error
        assert "429" in err
        assert "too many requests" in err

    def test_message_long_tronque(self, monkeypatch):
        """Le champ voyage dans une réponse JSON par morceau : pas de pavé."""

        class Boom:
            def release(self, _id):
                raise RuntimeError("x" * 500)

        monkeypatch.setattr(cover_fetcher, "get_client", lambda: Boom())
        assert len(cover_fetcher.fetch_cover(3235).error) < 200

    def test_exception_sans_message(self, monkeypatch):
        """Ne doit pas produire un « RuntimeError: » orphelin."""

        class Boom:
            def release(self, _id):
                raise RuntimeError()

        monkeypatch.setattr(cover_fetcher, "get_client", lambda: Boom())
        assert cover_fetcher.fetch_cover(3235).error == "RuntimeError"


class TestGetCoverUrl:
    """La forme simplifiée, utilisée par /match et /match/batch."""

    def test_rend_l_url(self, with_client):
        with_client([{"uri": "https://i.discogs.com/abc.jpeg"}])
        assert cover_fetcher.get_cover_url(3235) == "https://i.discogs.com/abc.jpeg"

    @pytest.mark.parametrize("images", [[], None])
    def test_rend_none_sans_distinguer(self, with_client, images):
        with_client(images)
        assert cover_fetcher.get_cover_url(3235) is None
