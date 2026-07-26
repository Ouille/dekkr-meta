import re
import sqlite3
from rapidfuzz import fuzz

from config import MATCH_THRESHOLD
from database import get_conn

# Bruit courant dans les noms de fichiers DJ : (Original Mix), [Remix], feat. X…
_PAREN = re.compile(
    r"\s*[\(\[]\s*(feat\.?|ft\.?|with|remix|rmx|edit|mix|version|ver\.?|original|"
    r"radio|extended|club|instrumental|dub|vip|bootleg|remaster\w*)\b[^\)\]]*[\)\]]",
    re.IGNORECASE,
)
_FEAT = re.compile(r"\s+(feat\.?|ft\.?|featuring)\s+.+$", re.IGNORECASE)
_LEAD_NUM = re.compile(r"^\s*\d{1,3}\s*[-._)]\s*")
_PUNCT = re.compile(r"[^\w\s&]", re.UNICODE)
_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    text = _LEAD_NUM.sub("", text or "")
    text = _PAREN.sub(" ", text)
    text = _FEAT.sub("", text)
    text = _PUNCT.sub(" ", text)
    return _WS.sub(" ", text).strip().casefold()


def _tokens(text: str) -> list[str]:
    return [t for t in text.split() if len(t) > 1 or t.isdigit()]


def _fts_group(tokens: list[str]) -> str:
    return " ".join(f'"{t}"' for t in tokens)


def _score(cand_artist: str, cand_title: str, q_artist: str, q_title: str) -> float:
    sa = fuzz.token_sort_ratio(normalize(cand_artist), q_artist)
    st = fuzz.token_sort_ratio(normalize(cand_title), q_title)
    return sa * 0.4 + st * 0.6


_SQL = """
    SELECT e.release_id, e.artist, e.title,
           r.genre, r.style, r.year, r.label, r.country
    FROM entries_fts f
    JOIN entries  e ON e.id = f.rowid
    JOIN releases r ON r.release_id = e.release_id
    WHERE entries_fts MATCH ?
    LIMIT ?
"""


def _candidates(conn: sqlite3.Connection, q_artist: str, q_title: str, limit: int):
    at, tt = _tokens(q_artist), _tokens(q_title)
    queries = []
    if at and tt:
        queries.append(f"artist:({_fts_group(at)}) AND title:({_fts_group(tt)})")
    if tt:
        queries.append(f"title:({_fts_group(tt)})")
    if at:
        queries.append(f"artist:({_fts_group(at)})")

    for q in queries:
        try:
            rows = conn.execute(_SQL, (q, limit)).fetchall()
        except sqlite3.OperationalError:
            continue
        if rows:
            return rows
    return []


def match_track(artist: str, title: str, conn: sqlite3.Connection | None = None,
                threshold: int | None = None, limit: int = 200) -> dict | None:
    own = conn is None
    conn = conn or get_conn()
    threshold = MATCH_THRESHOLD if threshold is None else threshold

    q_artist, q_title = normalize(artist), normalize(title)
    if not q_title and not q_artist:
        if own:
            conn.close()
        return None

    rows = _candidates(conn, q_artist, q_title, limit)

    best, best_score = None, 0.0
    for row in rows:
        s = _score(row["artist"], row["title"], q_artist, q_title)
        if s > best_score:
            best, best_score = row, s

    if own:
        conn.close()

    if best is None or best_score < threshold:
        return None

    return {
        "matched": True,
        "score": round(best_score, 1),
        "release_id": best["release_id"],
        "matched_artist": best["artist"],
        "matched_title": best["title"],
        "genre": best["genre"].split("|") if best["genre"] else [],
        "style": best["style"].split("|") if best["style"] else [],
        "year": best["year"],
        "label": best["label"],
        "country": best["country"],
    }
