# Tests

- `unit/`: isolated schema, policy, updater, and metric behavior.
- `integration/`: contracts between stores, models, and state transitions.
- `e2e/`: complete agent runs under fixed configurations.
- `fixtures/`: deterministic candidates, segments, evidence, and expected traces.

Integration and end-to-end tests create a minimal synthetic project root under
pytest's temporary directory. They never write into the repository's real `runs/`
directory. The `mock/v1/expected/` artifacts are byte-exact UTF-8/LF golden files.
