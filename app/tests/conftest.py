from __future__ import annotations

import os

# Test-time defaults so app.config doesn't fail on missing required vars.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://axiom:axiom@127.0.0.1:5432/axiom")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/0")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-32-bytes-min-please")
# 32 zero bytes b64-encoded — only used for AES key validation in tests
os.environ.setdefault("AES_MASTER_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("LOG_LEVEL", "WARNING")
