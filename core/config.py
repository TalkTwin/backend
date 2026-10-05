import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import URL

# loading .evn file
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# allowing to set environment variables in the .env file
DB_HOST = os.getenv("DB_HOST")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

# Check for missing required environment variables
required = {
    "DB_HOST": DB_HOST,
    "DB_NAME": DB_NAME,
    "DB_USER": DB_USER,
    "DB_PASSWORD": DB_PASSWORD,
}


missing = [key for key, value in required.items() if not value]

if missing:
    raise RuntimeError(
        f"Missing environment variables: {', '.join(missing)}"
    )

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

# voice clip storage (local disk now, MinIO/S3 swap later via core/storage.py)
BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", str(BASE_DIR / "storage")))
MAX_AUDIO_MB = int(os.getenv("MAX_AUDIO_MB", "10"))
ALLOWED_AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".webm"}
MAX_IMAGE_MB = int(os.getenv("MAX_IMAGE_MB", "10"))
ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

# hard caps for normal users' own keys (admins bypass via /v1/admin/*)
NORMAL_KEY_RATE_MAX = int(os.getenv("NORMAL_KEY_RATE_MAX", "60"))
NORMAL_KEY_CONCURRENT_MAX = int(os.getenv("NORMAL_KEY_CONCURRENT_MAX", "2"))

DATABASE_URL = URL.create(
    drivername="postgresql+psycopg2",
    username=DB_USER,
    password=DB_PASSWORD,
    host=DB_HOST,
    port=DB_PORT,
    database=DB_NAME,
)