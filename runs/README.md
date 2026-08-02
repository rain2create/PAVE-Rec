# Experiment Runs

Each Phase 1 run writes to an exclusive directory containing
`resolved_config.json`, `trace.jsonl`, and `result.json`. Reproducibility fields
include the seed, data version, component descriptors, and available Git metadata.
Timing, token, frame, and cost telemetry are intentionally deferred to the real
perception phase.

Run outputs are ignored by Git.

Phase 2 preprocessing executions use a separate local namespace:

```text
runs/preprocessing/<execution_id>/execution_report.json
```

The directory is created only after preprocessing config and storage-root
validation succeed. The report records success/failure, created/reused outcome,
data/release identity when known, configured and resolved roots, component and
tool provenance, counts, staging locations, and a sanitized declared error. It may
contain machine-local absolute paths and timestamps, so it is excluded from
portable releases, data-version identity, and golden comparisons.

Execution IDs are generated automatically as a UTC timestamp plus eight lowercase
hex characters. Preprocessing CLI does not accept an override. A declared failure
after directory creation writes a failed report on a best-effort basis; it never
turns a partial bundle into a complete release or masks the original failure.
