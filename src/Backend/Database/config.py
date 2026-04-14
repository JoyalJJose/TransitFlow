import os

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_NAME = os.environ.get("DB_NAME", "transitflow")
DB_USER = os.environ.get("DB_USER", "transitflow")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "transitflow_dev")

MIN_POOL_CONNECTIONS = int(os.environ.get("DB_MIN_CONNECTIONS", "2"))
MAX_POOL_CONNECTIONS = int(os.environ.get("DB_MAX_CONNECTIONS", "10"))
