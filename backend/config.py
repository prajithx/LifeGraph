"""Environment-backed application configuration."""

import os
import secrets
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BACKEND_DIR.parent


class Config:
    DEBUG = os.getenv("LIFEGRAPH_DEBUG", "false").lower() == "true"
    HOST = os.getenv("LIFEGRAPH_HOST", "127.0.0.1")
    PORT = int(os.getenv("LIFEGRAPH_PORT", "5000"))
    SECRET_KEY = os.getenv("LIFEGRAPH_SECRET_KEY") or secrets.token_hex(32)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("LIFEGRAPH_COOKIE_SECURE", "false").lower() == "true"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 12
    WTF_CSRF_ENABLED = True
    RATELIMIT_STORAGE_URI = os.getenv("LIFEGRAPH_RATE_LIMIT_STORAGE_URI", "memory://")
    MAIL_SERVER = os.getenv("LIFEGRAPH_MAIL_SERVER")
    MAIL_PORT = int(os.getenv("LIFEGRAPH_MAIL_PORT", "587"))
    MAIL_USERNAME = os.getenv("LIFEGRAPH_MAIL_USERNAME")
    MAIL_PASSWORD = os.getenv("LIFEGRAPH_MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.getenv("LIFEGRAPH_MAIL_SENDER")
    PUBLIC_BASE_URL = os.getenv("LIFEGRAPH_PUBLIC_URL")
    TIMEZONE = os.getenv("LIFEGRAPH_TIMEZONE", "Asia/Kolkata")
    MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024
    MAX_CONTENT_LENGTH = MAX_UPLOAD_SIZE_BYTES + 64 * 1024
    DATABASE_PATH = os.getenv(
        "LIFEGRAPH_DATABASE_PATH",
        str(BACKEND_DIR / "instance" / "lifegraph.db"),
    )
    FRONTEND_DIR = PROJECT_DIR / "frontend"
    UPLOAD_DIRECTORY = os.getenv("LIFEGRAPH_UPLOAD_DIRECTORY") or str(
        BACKEND_DIR / "instance" / "uploads"
    )
