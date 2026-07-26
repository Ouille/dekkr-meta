import os
from dotenv import load_dotenv

load_dotenv()

PORT = int(os.getenv("PORT", 7433))
MATCH_THRESHOLD = int(os.getenv("MATCH_THRESHOLD", 85))
DISCOGS_TOKEN = os.getenv("DISCOGS_TOKEN", "")
DB_PATH = os.getenv("DB_PATH", "discogs.db")

# Indexer les titres de la tracklist en plus du titre de la sortie.
# Indispensable pour matcher des fichiers "morceau" (cas normal d'un DJ) ;
# multiplie le volume de la base par ~6.
INDEX_TRACKS = os.getenv("INDEX_TRACKS", "1") == "1"

DUMP_INDEX = "https://data.discogs.com/?prefix=data%2F2026%2F"
