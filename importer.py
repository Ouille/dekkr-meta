import gzip
import io
import re
import sqlite3
import threading
import xml.sax
import xml.sax.handler
import requests
from datetime import datetime
from config import DB_PATH, DUMP_URL
from database import get_conn, set_meta


# État de progression partagé
progress: dict = {"running": False, "step": "", "inserted": 0, "error": None}
_lock = threading.Lock()


def _set_progress(**kwargs):
    with _lock:
        progress.update(kwargs)


def get_progress() -> dict:
    with _lock:
        return dict(progress)


def _latest_dump_url() -> str:
    """Trouve l'URL du dump releases le plus récent sur data.discogs.com."""
    now = datetime.utcnow()
    for month_offset in range(3):
        y = now.year
        m = now.month - month_offset
        if m <= 0:
            m += 12
            y -= 1
        prefix = f"{y:04d}-{m:02d}"
        url = f"{DUMP_URL}{prefix}/"
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                match = re.search(r'discogs_(\d{8})_releases\.xml\.gz', r.text)
                if match:
                    return f"{url}discogs_{match.group(1)}_releases.xml.gz", match.group(1)
        except Exception:
            pass
    raise RuntimeError("Impossible de trouver le dump Discogs")


class _ReleaseHandler(xml.sax.handler.ContentHandler):
    BATCH_SIZE = 5000

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.cur = conn.cursor()
        self._reset()
        self._batch: list[tuple] = []
        self._count = 0
        self._in: dict[str, bool] = {}

    def _reset(self):
        self._id = None
        self._title = ""
        self._artists: list[str] = []
        self._genres: list[str] = []
        self._styles: list[str] = []
        self._year = None
        self._labels: list[str] = []
        self._country = ""
        self._buf = ""
        self._in = {}

    def startElement(self, name, attrs):
        self._in[name] = True
        self._buf = ""
        if name == "release":
            self._reset()
            self._id = int(attrs.get("id", 0))

    def characters(self, content):
        self._buf += content

    def endElement(self, name):
        self._in[name] = False
        val = self._buf.strip()

        if name == "title" and self._in.get("release") and not self._in.get("tracklist"):
            self._title = val
        elif name == "name" and self._in.get("artists") and not self._in.get("extraartists"):
            self._artists.append(val)
        elif name == "genre":
            self._genres.append(val)
        elif name == "style":
            self._styles.append(val)
        elif name == "year":
            try:
                self._year = int(val)
            except ValueError:
                pass
        elif name == "name" and self._in.get("labels"):
            self._labels.append(val)
        elif name == "country":
            self._country = val
        elif name == "release":
            if self._id and self._title and self._artists:
                self._batch.append((
                    self._id,
                    self._artists[0],
                    self._title,
                    "|".join(self._genres) or None,
                    "|".join(self._styles) or None,
                    self._year,
                    self._labels[0] if self._labels else None,
                    self._country or None,
                ))
            if len(self._batch) >= self.BATCH_SIZE:
                self._flush()

        self._buf = ""

    def _flush(self):
        self.cur.executemany(
            "INSERT OR REPLACE INTO releases VALUES (?,?,?,?,?,?,?,?)",
            self._batch,
        )
        self.conn.commit()
        self._count += len(self._batch)
        _set_progress(inserted=self._count)
        self._batch.clear()

    def endDocument(self):
        if self._batch:
            self._flush()


def _rebuild_fts(conn: sqlite3.Connection):
    conn.execute("INSERT INTO releases_fts(releases_fts) VALUES('rebuild')")
    conn.commit()


def run_import():
    """Lance l'import dans un thread séparé."""
    t = threading.Thread(target=_do_import, daemon=True)
    t.start()


def _do_import():
    _set_progress(running=True, step="Recherche du dump...", inserted=0, error=None)
    try:
        url, date_str = _latest_dump_url()
        _set_progress(step=f"Téléchargement {url}...")

        conn = get_conn()
        # Vider les tables avant ré-import
        conn.execute("DELETE FROM releases")
        conn.execute("INSERT INTO releases_fts(releases_fts) VALUES('delete-all')")
        conn.commit()

        handler = _ReleaseHandler(conn)
        parser = xml.sax.make_parser()
        parser.setContentHandler(handler)

        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            _set_progress(step="Import en cours...")
            with gzip.open(io.BufferedReader(r.raw), "rb") as gz:
                parser.parse(gz)

        _set_progress(step="Reconstruction index FTS...")
        _rebuild_fts(conn)
        conn.close()

        set_meta("dump_date", date_str)
        _set_progress(running=False, step="Terminé")

    except Exception as e:
        _set_progress(running=False, step="Erreur", error=str(e))
