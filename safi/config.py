import os
from pathlib import Path

_BASE_DIR = Path(__file__).resolve().parents[1]
try:
    from dotenv import load_dotenv

    load_dotenv(_BASE_DIR / ".env")
except Exception:
    pass

ROOT_DIR = Path(os.environ.get("SAFI_ROOT_DIR", _BASE_DIR))
TEMPLATES_DIR = Path(os.environ.get("SAFI_TEMPLATES_DIR", ROOT_DIR / ".safi" / "templates"))
ROOT_KNOWLEDGE_FILE = ROOT_DIR / ".safi" / "root-knowledge.yaml"
DEFAULT_DB_PATH = Path(os.environ.get("SAFI_DB_PATH", ROOT_DIR / "safi_root.db"))
OPENAPI_FILE = ROOT_DIR / "openapi.yaml"
DEMO_MANIFEST_FILE = ROOT_DIR / ".safi" / "service-expert.yaml"

ROOT_EXPERT_ID = "__root__"
SERVICE_NAME = "safi-root-service-expert"
SERVICE_VERSION = "013.1.0"

LLM_ENDPOINT = os.environ.get("SAFI_LLM_ENDPOINT", "").strip()
LLM_API_KEY = os.environ.get("SAFI_LLM_API_KEY", "").strip()
LLM_MODEL = os.environ.get("SAFI_LLM_MODEL", "gpt-4o-mini").strip()
LLM_TIMEOUT = float(os.environ.get("SAFI_LLM_TIMEOUT", "30"))
