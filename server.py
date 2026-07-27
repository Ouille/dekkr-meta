"""API HTTP de dekkr-meta (FastAPI)."""

import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import cover_fetcher
import importer
import matcher
from config import cfg
from database import init_db, get_conn, get_counts, get_meta


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="dekkr-meta", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?|https://.*\.vercel\.app",
    allow_methods=["*"],
    allow_headers=["*"],
)


class MatchRequest(BaseModel):
    artist: str
    title: str


class BatchItem(BaseModel):
    id: str
    artist: str
    title: str


class CoverItem(BaseModel):
    id: str
    release_id: int


@app.get("/status")
def status():
    counts = get_counts() if cfg.db_exists else {"releases": 0, "entries": 0}
    return {
        "db_ready": counts["entries"] > 0,
        "db_path": cfg.db_path,
        "db_size_gb": round(cfg.db_size_gb, 2),
        "releases_count": counts["releases"],
        "entries_count": counts["entries"],
        "dump_date": get_meta("dump_date") if cfg.db_exists else None,
        "index_tracks": cfg.index_tracks,
        "match_threshold": cfg.match_threshold,
        "discogs_token": bool(cfg.discogs_token),
        "import": importer.get_progress(),
    }


def _require_db():
    if not cfg.db_exists:
        raise HTTPException(
            status_code=503,
            detail="Base Discogs absente — lancer l'import depuis l'icône dekkr-meta",
        )


@app.post("/match")
def match(req: MatchRequest):
    _require_db()
    result = matcher.match_track(req.artist, req.title)
    if result is None:
        return {"matched": False, "score": 0}
    return {**result, "url_cover": cover_fetcher.get_cover_url(result["release_id"])}


_pace_lock = threading.Lock()
_pace_last = 0.0


def _pace_discogs() -> None:
    """Attend son tour avant un appel à l'API Discogs (1 par seconde).

    Le quota authentifié (60/min) est **global au jeton** : un cadenceur par
    requête HTTP le dépasserait dès que deux lots se chevauchent — et FastAPI
    sert les endpoints synchrones dans un pool de threads, donc le cas se
    produit. Le verrou est tenu pendant l'attente, ce qui sérialise
    volontairement les appels sortants.
    """
    global _pace_last
    with _pace_lock:
        delay = 1.0 - (time.monotonic() - _pace_last)
        if delay > 0:
            time.sleep(delay)
        _pace_last = time.monotonic()


@app.post("/match/batch")
def match_batch(items: list[BatchItem], covers: bool = True):
    """Matche un lot. Les appels API pochettes sont cadencés à 1/s ;
    les morceaux non matchés n'en consomment aucun."""
    _require_db()
    conn = get_conn()
    fetch_covers = covers and bool(cfg.discogs_token)
    results = []

    try:
        for item in items:
            result = matcher.match_track(item.artist, item.title, conn=conn)
            if result is None:
                results.append({"id": item.id, "matched": False, "score": 0})
                continue

            url_cover = None
            if fetch_covers:
                _pace_discogs()
                url_cover = cover_fetcher.get_cover_url(result["release_id"])

            results.append({"id": item.id, **result, "url_cover": url_cover})
    finally:
        conn.close()

    return results


@app.post("/covers")
def covers(items: list[CoverItem]):
    """URLs de pochettes pour des releases **déjà appariées** — SPEC-META-001, tâche 10.

    Endpoint distinct de `/match/batch` : l'appelant connaît déjà ses
    `release_id`, et rejouer tout le matching pour rafraîchir des pochettes
    coûterait cher pour rien. Cela découple surtout les deux rythmes — le
    matching répond en millisecondes, les pochettes en une seconde par morceau.

    Rend une entrée par `id` demandé, `failed` distinguant une **absence
    certaine** (`url_cover: null, failed: false` — la release n'a pas d'image)
    d'un **incident passager** (`failed: true`), que l'appelant ne doit pas
    mémoriser comme définitif.
    """
    if not cfg.discogs_token:
        raise HTTPException(
            status_code=503,
            detail="Jeton Discogs absent — le renseigner dans les Paramètres de dekkr-meta",
        )

    results = []
    for item in items:
        _pace_discogs()
        res = cover_fetcher.fetch_cover(item.release_id)
        results.append({"id": item.id, "url_cover": res.url, "failed": res.failed})
    return results


@app.post("/db/update")
def db_update(force: bool = False):
    if importer.get_progress()["running"]:
        raise HTTPException(status_code=409, detail="Import déjà en cours")

    dump_date = get_meta("dump_date") if cfg.db_exists else None
    if dump_date and not force:
        try:
            age = (datetime.utcnow() - datetime.strptime(dump_date, "%Y%m%d")).days
            if age < 31:
                return {
                    "status": "skipped",
                    "message": f"Dump vieux de {age} jours. Utiliser force=true pour forcer.",
                }
        except ValueError:
            pass

    importer.run_import()
    return {"status": "started", "message": "Import lancé — suivre /status"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=cfg.port)
