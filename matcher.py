import re
import sqlite3
import unicodedata
from rapidfuzz import fuzz

from config import cfg
from database import get_conn

# Bruit courant dans les noms de fichiers DJ : (Original Mix), [Remix], feat. X…
_PAREN = re.compile(
    r"\s*[\(\[]\s*(feat\.?|ft\.?|with|remix|rmx|edit|mix|version|ver\.?|original|"
    r"radio|extended|club|instrumental|dub|vip|bootleg|remaster\w*)\b[^\)\]]*[\)\]]",
    re.IGNORECASE,
)
_FEAT = re.compile(r"\s+(feat\.?|ft\.?|featuring)\s+.+$", re.IGNORECASE)
_LEAD_NUM = re.compile(r"^\s*\d{1,3}\s*[-._)]\s*")
# Le tiret bas est un caractère de mot pour `\w` : sans le citer explicitement,
# « Original_Mix » resterait un seul jeton et échapperait au nettoyage.
_PUNCT = re.compile(r"[^\w\s&]|_", re.UNICODE)
_WS = re.compile(r"\s+")

# Mentions génériques en fin de titre, sans parenthèses : « Weltschmerz Original
# Mix ». L'adjectif est obligatoire : « Pastor Remix » distingue une version et
# doit être conservé, contrairement à « Original Mix » qui n'apprend rien.
_TAIL_GENERIC = re.compile(
    r"\s+(original|album|single|radio|extended|club|full|maxi|vocal)"
    r"\s+(mix|edit|version|cut)\s*$",
    re.IGNORECASE,
)
_TAIL_ORIGINAL = re.compile(r"\s+original\s*$", re.IGNORECASE)

# Suffixe d'homonymie propre à Discogs : « Yak (19) », « Culture Shock (2) ».
_DISAMBIG = re.compile(r"\s*\(\d+\)\s*$")


def _fold(text: str) -> str:
    """Replie les diacritiques — « Rüfüs » et « RUFUS » doivent se rejoindre.

    L'index FTS est construit avec `remove_diacritics 2` ; sans ce repli côté
    Python, la présélection trouvait le candidat mais le score le rejetait.
    """
    return "".join(
        c for c in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(c)
    )


def normalize(text: str) -> str:
    text = _LEAD_NUM.sub("", text or "")
    text = _PAREN.sub(" ", text)
    text = _FEAT.sub("", text)
    text = _PUNCT.sub(" ", text)
    text = _WS.sub(" ", text).strip()
    for _ in range(2):  # « … Original Mix » peut suivre « … Original »
        text = _TAIL_GENERIC.sub("", text)
        text = _TAIL_ORIGINAL.sub("", text)
    return _fold(text).strip().casefold()


def _tokens(text: str) -> list[str]:
    return [t for t in text.split() if len(t) > 1 or t.isdigit()]


def _fts_group(tokens: list[str]) -> str:
    return " ".join(f'"{t}"' for t in tokens)


def normalize_artist(text: str) -> str:
    """Comme `normalize`, mais retire le suffixe d'homonymie de Discogs.

    Discogs numérote les artistes homonymes : « Yak (19) », « PAX (11) ».
    C'est de la comptabilité interne à sa base, pas une partie du nom — et
    comme les chiffres survivent au découpage en jetons, le laisser faisait
    chuter le score d'un artiste pourtant identique.
    """
    return normalize(_DISAMBIG.sub("", text or ""))


def _artist_score(cand: str, q_artist: str) -> float:
    """Score d'artiste tolérant aux fichiers multi-artistes.

    Un fichier annonce souvent tous les intervenants (« Cari Golden, niiche »)
    là où Discogs n'enregistre que l'artiste principal (« Niiche »). Quand
    l'artiste Discogs est intégralement contenu dans celui du fichier, c'est
    la même sortie : on ne pénalise pas les noms surnuméraires.
    """
    c = normalize_artist(cand)
    base = fuzz.token_sort_ratio(c, q_artist)

    ct, qt = set(_tokens(c)), set(_tokens(q_artist))
    if not ct or not qt or ct == qt:
        return base

    # Garde-fou : un candidat trop court ou trop banal serait inclus partout.
    substantial = len(c.replace(" ", "")) >= 4 and any(len(t) >= 3 for t in ct)
    if substantial and ct <= qt:
        return 100.0
    return base


def _score(cand_artist: str, cand_title: str, q_artist: str, q_title: str) -> float:
    sa = _artist_score(cand_artist, q_artist)
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
    threshold = cfg.match_threshold if threshold is None else threshold

    q_artist, q_title = normalize(artist), normalize(title)
    if not q_title and not q_artist:
        if own:
            conn.close()
        return None

    rows = _candidates(conn, q_artist, q_title, limit)

    # Plancher d'artiste : un titre parfait rapporte déjà 60 points sur 100,
    # si bien qu'une ressemblance d'artiste de 62 % suffisait à passer le seuil.
    # Sur un titre courant — « Intro » compte 458 000 entrées — on finissait
    # toujours par trouver quelqu'un. Une correspondance dont l'artiste diffère
    # n'a pas de sens : on l'écarte avant de comparer.
    floor = cfg.min_artist_score

    best, best_score = None, 0.0
    for row in rows:
        sa = _artist_score(row["artist"], q_artist)
        if sa < floor:
            continue
        st = fuzz.token_sort_ratio(normalize(row["title"]), q_title)
        s = sa * 0.4 + st * 0.6
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
