# Tests

- `unit/`: isolated schema, policy, updater, and metric behavior.
- `integration/`: contracts between stores, models, and state transitions.
- `e2e/`: complete agent runs under fixed configurations.
- `fixtures/`: deterministic candidates, segments, evidence, and expected traces.

Integration and end-to-end tests create a minimal synthetic project root under
pytest's temporary directory. They never write into the repository's real `runs/`
directory. The `mock/v1/expected/` artifacts are byte-exact UTF-8/LF golden files.

Phase 2 uses `fixtures/preprocessing/v1/` for the canonical source fixture and its
expected portable artifact tree. The fixture has two users, three items, six behavior
events, and six segments. Item IDs are `item_a/item_b/item_c`, and every item uses
`segment_1/segment_2`, so the persistent Stores can replace the Phase 1 mock Stores.
The fixture covers timestamp/all-null sequences plus file/range segment locators. Its
media files are small checksummed opaque bytes; tests do not decode them.

Phase 2 golden comparison includes generated behavior sequences, feature/proxy
records, indexes, root manifests, and the release manifest. Machine-local execution
IDs, timestamps, absolute roots, paths, Git/platform metadata, reports, and
created/reused outcomes are validated semantically rather than byte-for-byte. API and
CLI equivalence means equal stable result fields, exact release references, data
versions, counts, and portable artifact bytes in independent fresh synthetic projects.
An exact release is loaded with the same validated root registry; the persistent-Store
smoke uses the Phase 2 data version and filesystem Store descriptors while retaining
the other Mock components, Controller semantics, and action budget.

All Phase 2 integration/end-to-end roots—including source, processed, features, and
runs—must live under pytest temporary storage. Tests never touch repository-local data,
artifacts, or runs, and remain offline, CPU-only, and independent of real datasets,
MLLMs, GPU, FFmpeg, or undeclared system tools. Cross-platform path grammar is tested
portably; real symlink/junction tests are capability-based, with the Ubuntu symlink
case required in CI.
