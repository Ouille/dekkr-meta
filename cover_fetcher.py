"""Récupération des URLs de pochettes via l'API Discogs.

⚠️ On ne télécharge ni ne stocke jamais l'image : les CGU Discogs classent les
images en *Restricted Data*. Seule l'URL circule, et elle est durable — le CDN
annonce `max-age=31536000` sur une URL dérivée de l'ID de release, sans
signature ni expiration courte.
"""

from typing import NamedTuple

import discogs_client as dc

from config import cfg

_client: dc.Client | None = None
_client_token: str | None = None


def get_client() -> dc.Client | None:
    """Client Discogs, reconstruit si le jeton a changé dans les Paramètres."""
    global _client, _client_token
    token = cfg.discogs_token
    if not token:
        return None
    if _client is None or _client_token != token:
        _client = dc.Client("dekkr-meta/1.0", user_token=token)
        _client_token = token
    return _client


class CoverResult(NamedTuple):
    """Issue d'une tentative, absence et panne distinguées.

    🔴 Rendre `None` dans les deux cas serait un piège : l'appelant persiste le
    résultat pour ne pas réinterroger 700 releases à chaque session, et une
    coupure réseau écrirait alors une absence définitive sur des releases qui
    ont bel et bien une pochette. Même leçon que `classifyCoverAttempt` côté
    DekkR (SPEC-DRIVE-003) : un incident passager ne doit rien écrire.
    """

    url: str | None
    #: L'appel lui-même a échoué (réseau, quota, jeton refusé) — réessayable.
    failed: bool


def fetch_cover(release_id: int) -> CoverResult:
    client = get_client()
    if client is None:
        return CoverResult(None, failed=True)
    try:
        images = client.release(release_id).fetch("images")
    except Exception:
        return CoverResult(None, failed=True)
    # Réponse obtenue : une release sans image est une absence CERTAINE.
    if images:
        return CoverResult(images[0].get("uri"), failed=False)
    return CoverResult(None, failed=False)


def get_cover_url(release_id: int) -> str | None:
    """Forme simplifiée pour `/match` et `/match/batch`, qui n'ont pas de mémoire
    à protéger : pour eux, absence et panne se valent."""
    return fetch_cover(release_id).url
