import sqlite3
from config import DB_PATH


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS releases (
            release_id  INTEGER PRIMARY KEY,
            artist      TEXT NOT NULL,
            title       TEXT NOT NULL,
            genre       TEXT,
            style       TEXT,
            year        INTEGER,
            label       TEXT,
            country     TEXT
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS releases_fts
        USING fts5(artist, title, release_id UNINDEXED, content=releases, content_rowid=release_id);

        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    conn.commit()
    conn.close()


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


def get_releases_count() -> int:
    conn = get_conn()
    row = conn.execute("SELECT COUNT(*) as cnt FROM releases").fetchone()
    conn.close()
    return row["cnt"]
