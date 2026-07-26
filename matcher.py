import re
import sqlite3
from rapidfuzz import fuzz
from database import get_conn
from config import MATCH_THRESHOLD


_NOISE = re.compile(
    r"\s*[\(\[](feat\.?|ft\.?|remix|edit|mix|version|original|radio|extended|club|instrumental|dub|vip|bootleg)[^\)\]]*[\)\]]",
    re.IGNORECASE,
)
_FEAT = re.compile(r"\s+(feat\.?|ft\.?)\s+.+$", re.IGNORECASE)


def normalize(text: str) -> str:
    text = _NOISE.sub("", text)
    text = _FEAT.sub("", text)
    return text.lower().strip()


def _score(candidate_artist: str, candidate_title: str, query_artist: str, query_title: str) -> float:
    sa = fuzz.token_sort_ratio(normalize(candidate_artist), query_artist)
    st = fuzz.token_sort_ratio(normalize(candidate_title), query_title)
    return sa * 0.4 + st * 0.6


def match_track(artist: str, title: str) -> dict | None:
    q_artist = normalize(artist)
    q_title = normalize(title)

    conn = get_conn()

    # FTS pour réduire les candidats
    try:
        rows = conn.execute(
            """
            SELECT r.release_id, r.artist, r.title, r.genre, r.style, r.year, r.label, r.country
            FROM releases_fts f
            JOIN releases r ON r.release_id = f.release_id
            WHERE releases_fts MATCH ?
            LIMIT 50
            """,
            (f'"{q_artist}" OR "{q_title}"',),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []

    conn.close()

    if not rows:
        return None

    best = None
    best_score = 0.0

    for row in rows:
        score = _score(row["artist"], row["title"], q_artist, q_title)
        if score > best_score:
            best_score = score
            best = row

    if best_score < MATCH_THRESHOLD:
        return None

    return {
        "matched": True,
        "score": round(best_score),
        "release_id": best["release_id"],
        "genre": best["genre"].split("|") if best["genre"] else [],
        "style": best["style"].split("|") if best["style"] else [],
        "year": best["year"],
        "label": best["label"],
        "country": best["country"],
    }
