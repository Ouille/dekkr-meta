import os
from dotenv import load_dotenv

load_dotenv()

PORT = int(os.getenv("PORT", 7433))
MATCH_THRESHOLD = int(os.getenv("MATCH_THRESHOLD", 85))
DISCOGS_TOKEN = os.getenv("DISCOGS_TOKEN", "")
DB_PATH = os.getenv("DB_PATH", "discogs.db")
DUMP_URL = "https://data.discogs.com/data/"
