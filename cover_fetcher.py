import discogs_client as dc
from config import DISCOGS_TOKEN

_client: dc.Client | None = None


def get_client() -> dc.Client:
    global _client
    if _client is None:
        _client = dc.Client("dekkr-meta/1.0", user_token=DISCOGS_TOKEN)
    return _client


def get_cover_url(release_id: int) -> str | None:
    if not DISCOGS_TOKEN:
        return None
    try:
        client = get_client()
        release = client.release(release_id)
        images = release.fetch("images")
        if images:
            return images[0].get("uri")
    except Exception:
        pass
    return None
