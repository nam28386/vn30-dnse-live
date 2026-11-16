# Feature contract 1.0.0

All prices are VN30 index points; quantities are futures contracts. Quotes are aggregated MBP snapshots, not orders. `k=3` uses the first three **available** levels (fewer when the source provides fewer). No inferred queue identities.

| Feature | Definition | Units | Inputs | Quality / warmup |
|---|---|---|---|---|
| spread | a1 − b1 | points | quote | missing without both sides; null when stale |
| midprice | (a1 + b1) / 2 | points | quote | same as spread |
| depth | sum bid + ask quantities at top k | contracts | quote | same as spread |
| imbalance | (bid depth − ask depth) / total depth | ratio | quote | null if total depth is zero |
| microprice | (a1 × bid qty1 + b1 × ask qty1) / (bid qty1 + ask qty1) | points | quote | null if BBO quantity is zero |
| signed_volume | sign × latest trade quantity | contracts | trade | INFERRED for vendor/mock inference; unknown is null |
| cvd | session sum of known inferred signed volume | contracts | trade, session | INFERRED; INVALID if any unknown side or transport gap; partial sum retained |
| vwap | sum trade price × quantity / sum quantity | points | trade, session | all sides included; INVALID after a transport gap |
| ma21 | arithmetic mean of last 21 completed one-minute trade-bar closes | points | trade, session | WARMUP until 21 observed bars; INVALID after gap |
| basis | most recent futures trade − official VN30 index | points | trade, official index | null unless both fresh; estimated index excluded |
| quote_age | max(decision − source time, decision − availability, 0) | seconds | quote | MISSING before first quote; STALE above 15s |
| index_age | same for official VN30 | seconds | index | same freshness rule |

Every value carries its own `quality`, `available_at`, input record IDs and definition `version`. Session aggregates use recursive lineage: previous feature snapshot ID plus current input ID, so their full ancestry can be traced through DuckDB's derived journal without growing every payload. Raw references are content hashes.

## Information set

Replay uses an explicit simulated UTC decision clock. The UI converts display times to Asia/Ho_Chi_Minh (ICT). Values become available at processing decision time, never retroactively at exchange time. The engine requires input `available_at <= decision_time`, source event time no later than decision time, and nondecreasing decision time. Naive timestamps, non-finite prices, duplicate IDs, source regressions and mismatched sessions are rejected. Rejections stay auditable. Out-of-order records remain in normalized storage but do not rewrite feature history. This conservative rejection policy is explicit; it is not lossless exchange-time reconstruction.

One-minute bars are **trade bars**, not vendor OHLC. A bar is finalized when a later source-minute trade arrives; its close was unavailable as a completed bar before that observation. Empty minutes are not filled. MA21 means 21 observed completed minute bars, not 21 trades or necessarily 21 elapsed minutes. Current incomplete bar never enters MA21. Session or phase transitions reset all aggregates and book/index state. Transport gaps preserve partial aggregates with INVALID quality until the next session boundary. No historical backfill is silently merged into current state.

## Event contract 1.0.0

A descriptive flow shock requires trade size >=80 contracts (fixture threshold, **not empirically calibrated**). Known inferred side and a fresh two-sided quote are required; otherwise INVALID. Baseline is the latest available pre-trade mid/spread/top-k depth.

Lifecycle: DETECTED → ACTIVE on a subsequent observation → MARKOUT_PENDING after 2s → OBSERVING_RECOVERY after a valid markout → MATURED when markout and recovery are observed. Session boundaries, transport disconnects, >15s quote gaps, and incomplete windows after 120s CENSOR the event. INVALID/CENSORED events have distinct meanings.

Markout horizon = detection availability +30s. Select the **first arriving eligible quote** with source time AND availability at/after the horizon. Signed markout = inferred direction × (observed mid − baseline mid), in points. A carried pre-horizon quote never qualifies. No interpolation or future lookup occurs.

Initial impact = signed mid displacement on the first eligible post-shock quote. Retention = horizon markout / initial impact; null when denominator is zero. Negative retention is possible. Spread recovery is first post-shock quote with spread <= baseline; depth recovery is first with depth >= baseline. Times are seconds from detection availability. These describe return to baseline, not proof the shock caused a deterioration. A flat response may recover immediately. Event transitions and revised measurements are append-journaled; no final outcome is backdated to detection time.
