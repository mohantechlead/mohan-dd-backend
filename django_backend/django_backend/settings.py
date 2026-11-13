import dj_database_url
import datetime
from pathlib import Path
from datetime import timedelta
import os
import secrets

try:
    import django_heroku
except ImportError:
    django_heroku = None

BASE_DIR = Path(__file__).resolve().parent.parent

# ==============================
# Local .env support
# ==============================
# Heroku (and any shell export) always wins: existing env vars are never
# overridden. The file itself is gitignored, so secrets stay local.
def _load_env_file(path: Path) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and not os.environ.get(key):
            os.environ[key] = value


_load_env_file(Path(__file__).resolve().with_name(".env"))
_load_env_file(BASE_DIR / ".env")

# ==============================
# Core settings
# ==============================

def _load_secret_key():
    env_key = os.environ.get("DJANGO_SECRET_KEY")
    if env_key:
        return env_key
    # Local fallback only: stable key in a gitignored file created on first run.
    key_file = Path(__file__).resolve().with_name("secret_key.txt")
    try:
        stored = key_file.read_text().strip() if key_file.exists() else ""
        if stored:
            return stored
        generated = secrets.token_urlsafe(48)
        key_file.write_text(generated)
        return generated
    except OSError:
        return secrets.token_urlsafe(48)


SECRET_KEY = _load_secret_key()

DEBUG = os.environ.get("DJANGO_DEBUG", "false").lower() == "true"

# AI assistant (read key from environment; never commit secrets)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")

ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1,.herokuapp.com").split(",")

SITE_ID = 1

WEBSITE_URL = "http://localhost:8000"

# ==============================
# JWT / Auth
# ==============================

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
    # Users stay signed in until they log out: the access token is refreshed
    # automatically while this refresh token is valid.
    "REFRESH_TOKEN_LIFETIME": timedelta(days=3650),
    "ROTATE_REFRESH_TOKENS": False,
    "BLACKLIST_AFTER_ROTATION": False,
    "UPDATE_LAST_LOGIN": True,
    "SIGNING_KEY": SECRET_KEY,
    "ALGORITHM": "HS512",
}

ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_USERNAME_REQUIRED = False
ACCOUNT_AUTHENTICATION_METHOD = False

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
}

AUTH_USER_MODEL = "accounts.User"

# ==============================
# CORS
# ==============================

CORS_ALLOWED_ORIGINS = [
    "http://127.0.0.1:3000",
    "http://localhost:3000",
    "https://mohan-dd-frontend-1ef4128343ba.herokuapp.com",
] + [
    origin.strip()
    for origin in os.environ.get("CORS_ORIGINS", "").split(",")
    if origin.strip()
]

CSRF_TRUSTED_ORIGINS = [
    "https://mohan-dd-frontend-1ef4128343ba.herokuapp.com",
] + [
    origin.strip()
    for origin in os.environ.get("CORS_ORIGINS", "").split(",")
    if origin.strip()
]

# ==============================
# Applications
# ==============================

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # third-party
    "ninja_extra",
    "ninja_jwt",
    "corsheaders",

    # internal
    "accounts",
    "accounting",
    "inventory",
]

# ==============================
# Middleware
# ==============================

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# ==============================
# URLs / WSGI
# ==============================

ROOT_URLCONF = "django_backend.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


WSGI_APPLICATION = "django_backend.wsgi.application"

# ==============================
# Database
# ==============================
# Resolution order:
#   1. LOCAL_DATABASE_URL  - set in the gitignored .env, pins this machine to
#                            the local Postgres even if a global DATABASE_URL
#                            is exported for some other project.
#   2. DATABASE_URL        - Heroku (and any explicit shell override).
#   3. Local Postgres      - development default.
# dj_database_url.config() would read DATABASE_URL itself, so parse the chosen
# URL directly to make LOCAL_DATABASE_URL authoritative.
_DATABASE_URL = (
    os.environ.get("LOCAL_DATABASE_URL")
    or os.environ.get("DATABASE_URL")
    or "postgres://postgres:tsedi@localhost:5432/mohanPLC"
)

DATABASES = {"default": dj_database_url.parse(_DATABASE_URL, conn_max_age=0)}

# ==============================
# Password validation
# ==============================

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ==============================
# Internationalization
# ==============================

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ==============================
# Session
# ==============================

SESSION_COOKIE_AGE = 1800  # 30 minutes
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_SAVE_EVERY_REQUEST = True

LOGOUT_REDIRECT_URL = "login_user"

# ==============================
# Static / Media
# ==============================

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# ==============================
# Default PK
# ==============================

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ==============================
# Email
# ==============================

# SMTP credentials must come from the environment (never from code).
# Without them, log emails to console instead of sending.
EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.gmail.com")
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_USE_TLS = True
EMAIL_TIMEOUT = 30
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER or "webmaster@localhost"
if EMAIL_HOST_USER and EMAIL_HOST_PASSWORD:
    EMAIL_BACKEND = os.environ.get(
        "EMAIL_BACKEND",
        "django.core.mail.backends.smtp.EmailBackend",
    )
else:
    EMAIL_BACKEND = os.environ.get(
        "EMAIL_BACKEND",
        "django.core.mail.backends.console.EmailBackend",
    )

# Shared recipients for inventory notifications (comma-separated emails).
# Uses NOTIFICATION_EMAIL_RECIPIENTS first, then falls back to legacy
# OVER_UNDER_DELIVERY_RECIPIENTS for backward compatibility.
NOTIFICATION_EMAIL_RECIPIENTS = [
    r.strip()
    for r in os.environ.get(
        "NOTIFICATION_EMAIL_RECIPIENTS",
        os.environ.get(
            "OVER_UNDER_DELIVERY_RECIPIENTS",
            "selamabraha@mohanplc.com,sol@mohanplc.com,Kapil@mohanint.com,Harsh@mohanplc.com,Mayuraddis@gmail.com,Amritakaur2612@gmail.com,amentemati@gmail.com",
        ),
    ).split(",")
    if r.strip()
]

# Backward-compatible alias for any existing references.
OVER_UNDER_DELIVERY_RECIPIENTS = [
    r.strip()
    for r in os.environ.get(
        "OVER_UNDER_DELIVERY_RECIPIENTS",
        ",".join(NOTIFICATION_EMAIL_RECIPIENTS),
    ).split(",")
    if r.strip()
]

# Recipients for warehouse storage expiry notifications (comma-separated emails).
# Falls back to NOTIFICATION_EMAIL_RECIPIENTS when unset.
WAREHOUSE_EXPIRATION_RECIPIENTS = [
    r.strip()
    for r in os.environ.get(
        "WAREHOUSE_EXPIRATION_RECIPIENTS",
        ",".join(NOTIFICATION_EMAIL_RECIPIENTS),
    ).split(",")
    if r.strip()
]

# For testing: set EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
# to print emails to console instead of sending

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "loggers": {
        "inventory": {
            "handlers": ["console"],
            "level": "INFO",
        },
    },
}

# ==============================
# Ninja JWT
# ==============================

NINJA_JWT = {
    "ACCESS_TOKEN_LIFETIME": datetime.timedelta(minutes=60),
    # Users stay signed in until they log out: the frontend refreshes the
    # access token automatically while this refresh token is valid.
    "REFRESH_TOKEN_LIFETIME": datetime.timedelta(days=3650),
}

# ==============================
# Heroku (when deployed)
# ==============================

if django_heroku:
    django_heroku.settings(locals())
    # django-heroku re-reads DATABASE_URL and would otherwise undo the
    # LOCAL_DATABASE_URL choice above on developer machines.
    if os.environ.get("LOCAL_DATABASE_URL"):
        DATABASES["default"] = dj_database_url.parse(_DATABASE_URL, conn_max_age=0)
