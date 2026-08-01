# Experiment Runs

Each Phase 1 run writes to an exclusive directory containing
`resolved_config.json`, `trace.jsonl`, and `result.json`. Reproducibility fields
include the seed, data version, component descriptors, and available Git metadata.
Timing, token, frame, and cost telemetry are intentionally deferred to the real
perception phase.

Run outputs are ignored by Git.
