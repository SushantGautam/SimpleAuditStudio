"""Run the SimpleAudit Platform dev server."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
# Prefer the local SimpleAudit checkout (v0.1.10).
_SA = Path.home() / "simpleaudit"
if (_SA / "simpleaudit").is_dir():
    sys.path.insert(0, str(_SA))

# Load .env
_env = ROOT / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run("app.api:app", host="127.0.0.1", port=8321, reload=False)
