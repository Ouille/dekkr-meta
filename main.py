import time
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import cover_fetcher
import importer
import matcher
from config import PORT, DISCOGS_TOKEN, INDEX_TRACKS, MATCH_THRESHOLD
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


@app.get("/status")
def status():
    imp = importer.get_progress()
    counts = get_counts()
    return {
        "db_ready": counts["entries"] > 0,
        "releases_count": counts["releases"],
        "entries_count": counts["entries"],
        "dump_date": get_meta("dump_date"),
        "index_tracks": INDEX_TRACKS,
        "match_threshold": MATCH_THRESHOLD,
        "discogs_token": bool(DISCOGS_TOKEN),
        "import": imp,
    }


@app.post("/match")
def match(req: MatchRequest):
    result = matcher.match_track(req.artist, req.title)
    if result is None:
        return {"matched": False, "score": 0}
    return {**result, "url_cover": cover_fetcher.get_cover_url(result["release_id"])}


@app.post("/match/batch")
def match_batch(items: list[BatchItem], covers: bool = True):
    """Matche un lot. Les appels API pochettes sont cadencés à 1/s ;
    les morceaux non matchés n'en consomment aucun."""
    conn = get_conn()
    fetch_covers = covers and bool(DISCOGS_TOKEN)
    results, last_call = [], 0.0

    try:
        for item in items:
            result = matcher.match_track(item.artist, item.title, conn=conn)
            if result is None:
                results.append({"id": item.id, "matched": False, "score": 0})
                continue

            url_cover = None
            if fetch_covers:
                wait = 1.0 - (time.monotonic() - last_call)
                if wait > 0:
                    time.sleep(wait)
                url_cover = cover_fetcher.get_cover_url(result["release_id"])
                last_call = time.monotonic()

            results.append({"id": item.id, **result, "url_cover": url_cover})
    finally:
        conn.close()

    return results


@app.post("/db/update")
def db_update(force: bool = False):
    imp = importer.get_progress()
    if imp["running"]:
        raise HTTPException(status_code=409, detail="Import déjà en cours")

    dump_date = get_meta("dump_date")
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
    uvicorn.run("main:app", host="127.0.0.1", port=PORT)
