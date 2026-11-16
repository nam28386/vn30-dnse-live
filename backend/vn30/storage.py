"""Append-only raw journal, separate normalized DuckDB, explicit Parquet export."""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

import duckdb
import polars as pl

from .contracts import MARKET_RECORD


class Journal:
    def __init__(self, root: Path):
        self.run_id = uuid4().hex
        self.root = root / self.run_id
        (self.root / "raw").mkdir(parents=True)
        (self.root / "normalized").mkdir()
        self.raw = (self.root / "raw" / "events.jsonl").open("a", encoding="utf-8")
        self.db = duckdb.connect(str(self.root / "normalized" / "market.duckdb"))
        self.db.execute(
            "CREATE TABLE records (event_id VARCHAR PRIMARY KEY, kind VARCHAR, available_at TIMESTAMPTZ, payload JSON)"
        )
        self.db.execute("CREATE TABLE derived (id VARCHAR, available_at TIMESTAMPTZ, payload JSON)")
        self.db.execute("CREATE TABLE rejected (raw_id VARCHAR, reason VARCHAR)")
        self.seen = set()

    def ingest(self, payload: dict):
        wire = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        digest = hashlib.sha256(wire.encode()).hexdigest()
        # Raw fixture payload stays unchanged; wrapper contains content hash, not credentials.
        self.raw.write(json.dumps({"sha256": digest, "payload": payload}) + "\n")
        self.raw.flush()
        record = MARKET_RECORD.validate_python({**payload, "raw_ref": f"sha256:{digest}"})
        if record.event_id in self.seen:
            raise ValueError("duplicate event ID")
        self.db.execute(
            "INSERT INTO records VALUES (?, ?, ?, ?)",
            [record.event_id, record.kind, record.available_at, record.model_dump_json()],
        )
        self.seen.add(record.event_id)
        return record

    def derived(self, record):
        self.db.execute(
            "INSERT INTO derived VALUES (?, ?, ?)",
            [record.event_id, record.available_at, record.model_dump_json()],
        )

    def reject(self, raw_id, reason):
        self.db.execute("INSERT INTO rejected VALUES (?, ?)", [raw_id, reason])

    def export(self):
        # Columnar envelope retains nested versioned JSON without schema coercion.
        for table in ("records", "derived"):
            rows = self.db.execute(f"SELECT * FROM {table}").fetchall()
            names = [d[0] for d in self.db.description]
            if rows:
                pl.DataFrame(rows, schema=names, orient="row").write_parquet(
                    self.root / "normalized" / f"{table}.parquet"
                )

    def close(self):
        self.raw.close()
        self.db.close()
