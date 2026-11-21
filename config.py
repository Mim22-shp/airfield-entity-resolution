import os
from dotenv import load_dotenv

load_dotenv()

DB_URL = os.environ.get("AIRFIELDS_DB_URL")
if not DB_URL:
    raise RuntimeError(
        "AIRFIELDS_DB_URL is not set. Copy .env.example to .env and fill it in."
    )