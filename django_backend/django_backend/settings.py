import dj_database_url
import datetime
from pathlib import Path
from datetime import timedelta
import os

try:
    import django_heroku
except ImportError:
    django_heroku = None

BASE_DIR = Path(__file__).resolve().parent.parent

# ==============================
# Core settings
# ==============================

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "django-insecure-change-this-in-production")

DEBUG = os.environ.get("DJANGO_DEBUG", "false").lower() == "true"

ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1,.herokuapp.com").split(",")

SITE_ID = 1

WEBSITE_URL = "http://localhost:8000"

# ==============================
# JWT / Auth
# ==============================

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
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
# Database (SQLite only)
# ==============================

DATABASES = {
    "default": dj_database_url.config(
        # Use DATABASE_URL env var if set, otherwise fall back to local Postgres.
        default=os.environ.get(
            "DATABASE_URL",
            "postgres://postgres:tsedi@localhost:5432/mohan_plc",
        ),
    )
}

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

# Default to real SMTP delivery. Override via env when needed, e.g.
# EMAIL_BACKEND=django.core.mail.backends.dummy.EmailBackend
EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND",
    "django.core.mail.backends.dummy.EmailBackend",
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.gmail.com")
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "tech@mohanplc.com")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "llcbqsjcpgyzbqvc")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_USE_TLS = True
EMAIL_TIMEOUT = 30
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER

# Shared recipients for inventory notifications (comma-separated emails).
# Uses NOTIFICATION_EMAIL_RECIPIENTS first, then falls back to legacy
# OVER_UNDER_DELIVERY_RECIPIENTS for backward compatibility.
NOTIFICATION_EMAIL_RECIPIENTS = [
    r.strip()
    for r in os.environ.get(
        "NOTIFICATION_EMAIL_RECIPIENTS",
        os.environ.get(
            "OVER_UNDER_DELIVERY_RECIPIENTS",
            "sol@mohanplc.com,Kapil@mohanint.com,Harsh@mohanplc.com,Mayuraddis@gmail.com,Amritakaur2612@gmail.com",
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
    "REFRESH_TOKEN_LIFETIME": datetime.timedelta(days=7),
}

# ==============================
# Heroku (when deployed)
# ==============================

if django_heroku:
    django_heroku.settings(locals())
