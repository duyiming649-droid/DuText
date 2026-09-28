from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
WORKSPACE = DATA_DIR / "workspace"
SAMPLES_DIR = ROOT / "samples"
TOOLS_DIR = ROOT / "tools"
STATIC_DIR = Path(__file__).resolve().parent / "static"

HOST = "127.0.0.1"
PORT = 8765
COMPILE_TIMEOUT_SEC = 300
