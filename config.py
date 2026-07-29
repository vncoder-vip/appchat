import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    PORT = int(os.getenv("PORT", 5000))
    ENV = os.getenv("FLASK_ENV", "development")
    SECRET_KEY = os.getenv("SECRET_KEY", "flask-secret-key-clerk-clone-98765")
    
    # Database
    _raw_db = os.getenv("DATABASE_URL", "").strip()
    if _raw_db:
        if _raw_db.startswith("sqlite:///"):
            if os.environ.get('VERCEL'):
                import tempfile
                tmp = tempfile.gettempdir().replace('\\', '/')
                SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp}/app.db"
            else:
                SQLALCHEMY_DATABASE_URI = _raw_db
        else:
            SQLALCHEMY_DATABASE_URI = _raw_db
    else:
        SQLALCHEMY_DATABASE_URI = "sqlite:///dev.db"
    
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 300, "pool_timeout": 5}

    JWT_ACCESS_SECRET = os.getenv("JWT_ACCESS_SECRET", "access-token-secret-key-12345")
    JWT_REFRESH_SECRET = os.getenv("JWT_REFRESH_SECRET", "refresh-token-secret-key-12345")
    JWT_ACCESS_EXPIRES_IN_MINUTES = 15
    JWT_REFRESH_EXPIRES_IN_DAYS = 7

    # Google OAuth
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")

    # SMTP
    SMTP_HOST = os.getenv("SMTP_HOST", "smtp.mailtrap.io")
    SMTP_PORT = int(os.getenv("SMTP_PORT", 2525))
    SMTP_USER = os.getenv("SMTP_USER", "")
    SMTP_PASS = os.getenv("SMTP_PASS", "")
    SMTP_FROM = os.getenv("SMTP_FROM", "no-reply@clerk-clone.local")

    # Sanity - 10 projects
    SANITY_PROJECT_ID = os.getenv("SANITY_PROJECT_ID", "")
    SANITY_DATASET = os.getenv("SANITY_DATASET", "production")
    SANITY_API_TOKEN = os.getenv("SANITY_API_TOKEN", "")
    SANITY_API_VERSION = os.getenv("SANITY_API_VERSION", "v2024-01-01")

    for i in range(2, 11):
        vars()[f'SANITY_PROJECT_ID{i}'] = os.getenv(f"SANITY_PROJECT_ID{i}", "")
        vars()[f'SANITY_DATASET{i}'] = os.getenv(f"SANITY_DATASET{i}", "production")
        vars()[f'SANITY_API_TOKEN{i}'] = os.getenv(f"SANITY_API_TOKEN{i}", "")
        vars()[f'SANITY_API_VERSION{i}'] = os.getenv(f"SANITY_API_VERSION{i}", "v2024-01-01")

    RATE_LIMIT_WINDOW_MINUTES = 15
    RATE_LIMIT_MAX = 100
    BRUTE_FORCE_MAX_ATTEMPTS = 5