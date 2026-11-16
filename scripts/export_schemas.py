"""Export stable JSON Schema artifacts for all eight research contracts."""

import json
from pathlib import Path

from vn30 import contracts

root = Path("docs/schemas/1.0.0")
root.mkdir(parents=True, exist_ok=True)
for name in (
    "MarketTrade",
    "QuoteSnapshot",
    "MarketIndex",
    "InstrumentMetadata",
    "SessionState",
    "FeatureSnapshot",
    "ShockEvent",
    "FeedQualityState",
):
    schema = getattr(contracts, name).model_json_schema()
    (root / f"{name}.json").write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
print(f"Exported 8 versioned schemas into {root}")
