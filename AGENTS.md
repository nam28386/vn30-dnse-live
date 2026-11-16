# Research and coding guardrails

- Read-only market research. Never add order placement, modification, cancellation, execution or account endpoints.
- Default to MOCK. Do not request, print, log, persist, or commit credentials.
- Use existing checkout; do not create worktrees unless explicitly requested.
- Official SDK calls must be verified against the pinned reference in docs/DNSE.md. Do not guess vendor semantics.
- DNSE quotes are aggregated MBP; never infer order identity or queue position. Vendor side is an inference, not confirmed exchange aggressor identity.
- Keep immutable raw and normalized data separate; link them by ID/hash. Never silently repair history.
- Preserve source, receive, processing and availability clocks. No future information, forward joins, or premature markouts.
- Feature changes require version, formula, units, dependencies, availability, quality rules and meaningful tests.
- No ML, backtests, automated signals, or trading recommendations in v0.1.
- Use deterministic fixtures. Report only actually executed tests and connections.
- Run `uv run pytest`, `uv run ruff check backend`, and frontend `npm test` / `npm run build` after relevant changes.
