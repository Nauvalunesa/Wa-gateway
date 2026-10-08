"""Environment loading, runtime directories, and persistent cookie signing key."""
import logging
import os
from pathlib import Path
import secrets

from dotenv import load_dotenv

load_dotenv()
logging.getLogger("neonize").setLevel(logging.WARNING)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
system_db_path = "storage/system.db"


def prepare_runtime() -> str:
    """Prepare writable directories and return the persistent session secret."""
    os.makedirs("storage", exist_ok=True)
    os.makedirs("static/uploads", exist_ok=True)
    secret_path = Path("storage/.session-secret")
    if not secret_path.exists():
        secret_path.write_text(secrets.token_hex(32))
        secret_path.chmod(0o600)
    return os.getenv("GATEWAY_SESSION_SECRET") or secret_path.read_text().strip()
