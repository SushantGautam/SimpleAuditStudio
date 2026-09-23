"""
Seed the platform: register model endpoints (from the live gateway's /v1/models)
and import a built-in scenario pack as version 1 of a scenario set.

Idempotent-ish: safe to re-run; it only adds what is missing.

The API key is read from the SIMULACHAT_API_KEY environment variable (set in
.env), never hardcoded here.
"""

import os
import sys
from pathlib import Path

# Load .env if present (SIMPLE, no dependency).
_env = Path(__file__).resolve().parent.parent / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# Prefer the local SimpleAudit checkout (v0.1.10) over any older installed copy.
_SA = Path.home() / "simpleaudit"
if (_SA / "simpleaudit").is_dir():
    sys.path.insert(0, str(_SA))

from app import db, models, scenarios  # noqa: E402

BASE_URL = "https://simulachat.sushant.pp.ua/api/v1"
SECRET_REF = "SIMULACHAT_API_KEY"


def seed_models() -> None:
    existing = {e["model_id"] for e in models.list_endpoints()}
    registry = [
        ("Default (Qwen3.8-27B)", "default"),
        ("Qwen3.8-27B", "Qwen3.8-27B"),
        ("Qwen3.8-27B FP8", "qwen3-8-27b-fp8"),
        ("GLM-5.2 FP8", "glm-5-2-fp8"),
        ("Qwen3.8 Flash NVFP4", "nvidia/Qwen3.8-Flash-Next-NVFP4"),
    ]
    for display, model_id in registry:
        if model_id in existing:
            continue
        models.add_endpoint(
            display_name=display,
            provider="openai",
            base_url=BASE_URL,
            model_id=model_id,
            capabilities={"vision": False},
            default_parameters={},
            secret_reference=SECRET_REF,
        )
        print(f"  + model endpoint: {display} ({model_id})")


def seed_scenarios() -> None:
    sets = scenarios.list_sets()
    if any(s["name"].lower() == "safety" for s in sets):
        print("  safety set already present, skipping import")
        return
    vid = scenarios.import_pack("safety", "Safety")
    v = scenarios.get_version(vid)
    print(f"  + imported 'safety' pack -> set '{v['set_name']}' v{v['version']} ({v['scenario_count']} scenarios)")


def main() -> None:
    db.init_db()
    print("Seeding SimpleAudit Platform...")
    seed_models()
    seed_scenarios()
    print("\nModel registry:")
    for e in models.list_endpoints():
        print(f"  [{e['id']}] {e['display_name']}  ->  {e['model_id']} @ {e['base_url']}")
    print("\nScenario sets:")
    for s in scenarios.list_sets():
        print(f"  [{s['id']}] {s['name']}  latest v{s['latest_version']}  ({s['scenario_count']} scenarios)")


if __name__ == "__main__":
    main()
