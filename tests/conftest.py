import os

os.environ.setdefault("GCP_PROJECT", "test-project")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://headroom:headroom@localhost:5432/headroom"
)
