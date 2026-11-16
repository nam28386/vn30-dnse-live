"""Run a deterministic bounded fixture and export provenance-preserving artifacts."""

import hashlib
import importlib.metadata
import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from vn30.service import ResearchService


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


service = ResearchService(Path(".data/exports"))
try:
    service.bootstrap(180)
    service.journal.export()
    revision = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], capture_output=True, text=True)
    source_files = sorted(
        [
            *Path("backend/vn30").rglob("*.py"),
            *Path("scripts").glob("*.py"),
            *Path("frontend/src").glob("*.tsx"),
            *Path("frontend/src").glob("*.ts"),
            Path("pyproject.toml"),
            Path("uv.lock"),
            Path("frontend/package-lock.json"),
        ]
    )
    source_hashes = {str(p): digest(p) for p in source_files}
    artifact_files = [
        service.journal.root / "raw/events.jsonl",
        service.journal.root / "normalized/records.parquet",
        service.journal.root / "normalized/derived.parquet",
    ]
    manifest = {
        "research_id": "vn30-observation-v0.1",
        "status": "SYNTHETIC_ENGINEERING_FIXTURE",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_id": service.journal.run_id,
        "fixture": "vn30.adapters.mock:v1",
        "steps": 180,
        "schema_version": "1.0.0",
        "feature_version": "1.0.0",
        "live_connection": False,
        "clock": "simulated availability order",
        "hypothesis": None,
        "split": None,
        "model": None,
        "evaluation": "software invariants only",
        "code_revision": revision.stdout.strip() or None,
        "source_sha256": source_hashes,
        "artifacts_sha256": {str(p.relative_to(service.journal.root)): digest(p) for p in artifact_files},
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": {p: importlib.metadata.version(p) for p in ("fastapi", "pydantic", "polars", "duckdb")},
        "events": len(service.manager.events),
        "rejects": service.rejected,
    }
    (service.journal.root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(service.journal.root)
finally:
    service.journal.close()
