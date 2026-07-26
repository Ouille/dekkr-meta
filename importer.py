import re
import sqlite3
import threading
import time
import xml.sax
import xml.sax.handler
import zlib
import requests

from config import DUMP_INDEX, INDEX_TRACKS
from database import get_conn, init_db, tune_for_bulk, rebuild_fts, set_meta

# --- État de progression partagé ---
_progress: dict = {
    "running": False, "step": "", "releases": 0, "entries": 0,
    "mb_read": 0.0, "error": None,
}
_lock = threading.Lock()


def _set(**kw):
    with _lock:
        _progress.update(kw)


def get_progress() -> dict:
    with _lock:
        return dict(_progress)


# --- Résolution du dump le plus récent ---

def resolve_latest_dump() -> tuple[str, str]:
    """Retourne (url, date YYYYMMDD) du dump releases le plus récent."""
    r = requests.get(DUMP_INDEX, timeout=30)
    r.raise_for_status()
    dates = sorted(set(re.findall(r"discogs_(\d{8})_releases\.xml\.gz", r.text)))
    if not dates:
        raise RuntimeError("Aucun dump releases trouvé sur data.discogs.com")
    latest = dates[-1]
    url = (
        "https://data.discogs.com/?download=data%2F"
        f"{latest[:4]}%2Fdiscogs_{latest}_releases.xml.gz"
    )
    return url, latest


# --- Parsing SAX ---

_YEAR = re.compile(r"(\d{4})")


class ReleaseHandler(xml.sax.handler.ContentHandler):
    """Extrait sorties + tracklist du dump Discogs.

    Le suivi d'imbrication se fait par pile d'éléments : les balises homonymes
    (`name` sous artist / company / label) sont ainsi désambiguïsées par leur
    parent réel, pas par un drapeau global.
    """

    BATCH = 20_000

    def __init__(self, conn: sqlite3.Connection, index_tracks: bool = True):
        self.conn = conn
        self.cur = conn.cursor()
        self.index_tracks = index_tracks
        self.stack: list[str] = []
        self.buf: list[str] = []
        self._rel_batch: list[tuple] = []
        self._ent_batch: list[tuple] = []
        self.n_rel = 0
        self.n_ent = 0
        self._new_release()

    def _new_release(self):
        self.rid = None
        self.artist = None
        self.title = None
        self.genres: list[str] = []
        self.styles: list[str] = []
        self.year = None
        self.label = None
        self.country = None
        self.tracks: list[str] = []

    # -- SAX --

    def startElement(self, name, attrs):
        self.stack.append(name)
        self.buf = []

        if name == "release":
            self._new_release()
            try:
                self.rid = int(attrs.get("id") or 0)
            except ValueError:
                self.rid = None
        elif name == "label" and self.label is None and self._parent() == "labels":
            self.label = attrs.get("name")

    def characters(self, content):
        self.buf.append(content)

    def endElement(self, name):
        val = "".join(self.buf).strip()
        parent = self._parent()
        gparent = self._grandparent()

        if name == "title" and parent == "release":
            self.title = val
        elif name == "name" and parent == "artist" and gparent == "artists":
            if self.artist is None:
                self.artist = val
        elif name == "genre" and parent == "genres":
            self.genres.append(val)
        elif name == "style" and parent == "styles":
            self.styles.append(val)
        elif name == "country" and parent == "release":
            self.country = val
        elif name == "released" and parent == "release":
            m = _YEAR.search(val)
            if m:
                self.year = int(m.group(1))
        elif name == "title" and parent == "track":
            if val:
                self.tracks.append(val)
        elif name == "release":
            self._emit()

        self.buf = []
        if self.stack:
            self.stack.pop()

    def endDocument(self):
        self._flush()

    def _parent(self) -> str | None:
        return self.stack[-2] if len(self.stack) >= 2 else None

    def _grandparent(self) -> str | None:
        return self.stack[-3] if len(self.stack) >= 3 else None

    # -- Écriture --

    def _emit(self):
        if not self.rid or not self.artist:
            return

        self._rel_batch.append((
            self.rid, self.artist, self.title,
            "|".join(self.genres) or None,
            "|".join(self.styles) or None,
            self.year, self.label, self.country,
        ))
        self.n_rel += 1

        # Couples cherchables : titre de la sortie + chaque titre de morceau.
        seen: set[str] = set()
        titles = [self.title] if self.title else []
        if self.index_tracks:
            titles += self.tracks
        for t in titles:
            k = t.casefold()
            if k in seen:
                continue
            seen.add(k)
            self._ent_batch.append((self.rid, self.artist, t))
        self.n_ent += len(seen)

        if len(self._ent_batch) >= self.BATCH:
            self._flush()

    def _flush(self):
        if self._rel_batch:
            self.cur.executemany(
                "INSERT OR REPLACE INTO releases VALUES (?,?,?,?,?,?,?,?)",
                self._rel_batch,
            )
            self._rel_batch.clear()
        if self._ent_batch:
            self.cur.executemany(
                "INSERT INTO entries (release_id, artist, title) VALUES (?,?,?)",
                self._ent_batch,
            )
            self._ent_batch.clear()
        self.conn.commit()
        _set(releases=self.n_rel, entries=self.n_ent)


# --- Flux gzip depuis HTTP, décompressé à la volée ---

class _GzipStream:
    """Fichier-like qui décompresse le dump au fil du téléchargement."""

    def __init__(self, response, max_bytes: int | None = None, on_read=None):
        self._it = response.iter_content(chunk_size=1 << 20)
        self._d = zlib.decompressobj(31)
        self._buf = b""
        self._raw = 0
        self._max = max_bytes
        self._on_read = on_read
        self._done = False

    def read(self, size: int = -1) -> bytes:
        while not self._done and (size < 0 or len(self._buf) < size):
            if self._max is not None and self._raw >= self._max:
                self._done = True
                break
            try:
                chunk = next(self._it)
            except StopIteration:
                self._done = True
                break
            self._raw += len(chunk)
            if self._on_read:
                self._on_read(self._raw)
            self._buf += self._d.decompress(chunk)

        if size < 0:
            out, self._buf = self._buf, b""
        else:
            out, self._buf = self._buf[:size], self._buf[size:]
        return out

    def close(self):
        self._done = True
        self._buf = b""


def import_dump(url: str, db_path: str | None = None,
                max_bytes: int | None = None,
                index_tracks: bool = INDEX_TRACKS) -> dict:
    """Importe le dump. `max_bytes` limite l'octet compressé lu (benchmark)."""
    t0 = time.time()
    conn = get_conn(db_path)
    tune_for_bulk(conn)
    init_db(conn)
    conn.execute("DELETE FROM entries")
    conn.execute("DELETE FROM releases")
    conn.commit()

    handler = ReleaseHandler(conn, index_tracks=index_tracks)
    parser = xml.sax.make_parser()
    parser.setContentHandler(handler)

    def _tick(raw):
        _set(mb_read=round(raw / 1024 / 1024, 1))

    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or 0)
        _set(step="Import en cours…")
        stream = _GzipStream(r, max_bytes=max_bytes, on_read=_tick)
        try:
            parser.parse(stream)
        except xml.sax.SAXParseException:
            # Flux tronqué volontairement (mode benchmark) : normal.
            if max_bytes is None:
                raise
            handler._flush()

    parse_s = time.time() - t0
    _set(step="Construction de l'index de recherche…")
    rebuild_fts(conn)
    conn.close()

    return {
        "releases": handler.n_rel,
        "entries": handler.n_ent,
        "mb_compressed": round(_progress["mb_read"], 1),
        "total_mb": round(total / 1024 / 1024, 1) if total else None,
        "parse_seconds": round(parse_s, 1),
        "total_seconds": round(time.time() - t0, 1),
    }


# --- Lancement asynchrone (API) ---

def run_import():
    threading.Thread(target=_do_import, daemon=True).start()


def _do_import():
    _set(running=True, step="Recherche du dump…", releases=0, entries=0,
         mb_read=0.0, error=None)
    try:
        url, date_str = resolve_latest_dump()
        _set(step=f"Dump {date_str} — téléchargement…")
        import_dump(url)
        set_meta("dump_date", date_str)
        set_meta("index_tracks", "1" if INDEX_TRACKS else "0")
        _set(running=False, step="Terminé")
    except Exception as e:
        _set(running=False, step="Erreur", error=str(e))
