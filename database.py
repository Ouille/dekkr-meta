import sqlite3
from config import DB_PATH


def get_conn(path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def tune_for_bulk(conn: sqlite3.Connection):
    """Réglages SQLite pour un import massif (au prix de la durabilité)."""
    conn.executescript("""
        PRAGMA journal_mode = OFF;
        PRAGMA synchronous = OFF;
        PRAGMA temp_store = MEMORY;
        PRAGMA cache_size = -262144;   -- 256 Mo
    """)


def init_db(conn: sqlite3.Connection | None = None):
    own = conn is None
    conn = conn or get_conn()
    conn.executescript("""
        -- Métadonnées par sortie Discogs
        CREATE TABLE IF NOT EXISTS releases (
            release_id  INTEGER PRIMARY KEY,
            artist      TEXT,
            title       TEXT,
            genre       TEXT,
            style       TEXT,
            year        INTEGER,
            label       TEXT,
            country     TEXT
        );

        -- Une ligne par couple (artiste, titre) cherchable.
        -- Contient le titre de la sortie ET chaque titre de la tracklist.
        CREATE TABLE IF NOT EXISTS entries (
            id          INTEGER PRIMARY KEY,
            release_id  INTEGER NOT NULL,
            artist      TEXT NOT NULL,
            title       TEXT NOT NULL
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts
        USING fts5(artist, title, content='entries', content_rowid='id',
                   tokenize='unicode61 remove_diacritics 2');

        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    conn.commit()
    if own:
        conn.close()


def rebuild_fts(conn: sqlite3.Connection):
    conn.execute("INSERT INTO entries_fts(entries_fts) VALUES('rebuild')")
    conn.commit()


def get_meta(key: str) -> str | None:
    conn = get_conn()
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else None


def set_meta(key: str, value: str):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()


def get_counts() -> dict:
    conn = get_conn()
    try:
        rel = conn.execute("SELECT COUNT(*) c FROM releases").fetchone()["c"]
        ent = conn.execute("SELECT COUNT(*) c FROM entries").fetchone()["c"]
    except sqlite3.OperationalError:
        rel = ent = 0
    conn.close()
    return {"releases": rel, "entries": ent}
