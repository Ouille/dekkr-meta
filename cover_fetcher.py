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


def get_cover_url(release_id: int) -> str | None:
    client = get_client()
    if client is None:
        return None
    try:
        images = client.release(release_id).fetch("images")
        if images:
            return images[0].get("uri")
    except Exception:
        pass
    return None
