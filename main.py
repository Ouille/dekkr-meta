import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import importer
import matcher
import cover_fetcher as dc_client
from config import PORT
from database import init_db, get_releases_count, get_meta


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="dekkr-meta", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "https://*.vercel.app"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Modèles ---

class MatchRequest(BaseModel):
    artist: str
    title: str


class BatchItem(BaseModel):
    id: str
    artist: str
    title: str


# --- Endpoints ---

@app.get("/status")
def status():
    imp = importer.get_progress()
    return {
        "db_ready": get_releases_count() > 0,
        "releases_count": get_releases_count(),
        "dump_date": get_meta("dump_date"),
        "import_running": imp["running"],
        "import_step": imp["step"],
        "import_inserted": imp["inserted"],
        "import_error": imp["error"],
    }


@app.post("/match")
def match(req: MatchRequest):
    result = matcher.match_track(req.artist, req.title)
    if result is None:
        return {"matched": False, "score": 0}

    url_cover = dc_client.get_cover_url(result["release_id"])
    return {**result, "url_cover": url_cover}


@app.post("/match/batch")
def match_batch(items: list[BatchItem]):
    results = []
    for i, item in enumerate(items):
        result = matcher.match_track(item.artist, item.title)
        if result is None:
            results.append({"id": item.id, "matched": False})
            continue

        # Rate limit : 1 appel API/s pour les pochettes
        if i > 0:
            time.sleep(1)
        url_cover = dc_client.get_cover_url(result["release_id"])
        results.append({"id": item.id, **result, "url_cover": url_cover})

    return results


@app.post("/db/update")
def db_update(force: bool = False):
    imp = importer.get_progress()
    if imp["running"]:
        raise HTTPException(status_code=409, detail="Import déjà en cours")

    dump_date = get_meta("dump_date")
    if dump_date and not force:
        from datetime import datetime
        try:
            age = (datetime.utcnow() - datetime.strptime(dump_date, "%Y%m%d")).days
            if age < 31:
                return {
                    "status": "skipped",
                    "message": f"Dump récent ({age} jours). Passer force=true pour forcer."
                }
        except ValueError:
            pass

    importer.run_import()
    return {"status": "started", "message": "Téléchargement du dump en cours..."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=PORT, reload=False)
