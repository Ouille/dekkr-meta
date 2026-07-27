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


class TestGetCoverUrl:
    """La forme simplifiée, utilisée par /match et /match/batch."""

    def test_rend_l_url(self, with_client):
        with_client([{"uri": "https://i.discogs.com/abc.jpeg"}])
        assert cover_fetcher.get_cover_url(3235) == "https://i.discogs.com/abc.jpeg"

    @pytest.mark.parametrize("images", [[], None])
    def test_rend_none_sans_distinguer(self, with_client, images):
        with_client(images)
        assert cover_fetcher.get_cover_url(3235) is None
