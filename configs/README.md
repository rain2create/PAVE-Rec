# Configurations

Runtime and experiment configuration lives here.

- `base.yaml` will contain shared defaults.
- `mock.yaml` will extend `base.yaml` for the deterministic mock vertical slice.
- `experiments/` will contain named configs that may extend `mock.yaml`.

Configuration selects component implementations and parameters. It must not
contain business logic or silently settle research choices that remain TBD.

Phase 1 uses one relative `extends` path per file. Mappings merge recursively;
scalars and lists replace their parent values. Cycles, unknown fields, unknown
component IDs, absolute fixture/output paths, and paths escaping the project root
are invalid. PyYAML only parses YAML; strict/frozen Pydantic v2 models validate
the final merged configuration. CLI `key=value` overrides are not supported.

Phase 1 tests do not relax these path rules. Integration/E2E tests create a minimal
temporary project root under pytest `tmp_path`, including `pyproject.toml`, configs,
the versioned fixture, and `runs/`. The test config still uses project-relative
`fixture_path` and `output_root`; only the synthetic project root itself is temporary.

## Phase 2 preprocessing roots

P2-02 does not relax the Phase 1 rules above. It introduces a separate, typed
preprocessing root registry for large data and artifacts that may live outside the
repository. Root declarations live in preprocessing YAML, not dataset manifests,
CLI root overrides, or environment-variable interpolation.

Each declaration maps a portable root ID to an existing project-relative or
absolute directory and an application-level access mode:

```yaml
storage:
  roots:
    source: {path: data/raw/phase2-fixture, access: read_only}
    processed: {path: data/processed, access: write_new}
    features: {path: artifacts/features, access: write_new}
```

All resolved roots must be distinct and non-overlapping. Portable manifests and
`ResourceRef` values contain only root IDs and canonical relative POSIX keys;
machine-specific absolute roots may appear only in a local, gitignored execution
report that is excluded from data identity and golden artifacts. Read-only roots
are never mutated, and write-new roots do not overwrite, delete, or move existing
resources by default. The filesystem resolver rejects cross-platform absolute or
ambiguous keys and any child symlink/junction escape.

## Phase 2 feature semantics

P2-05 requires semantic preprocessing config to select item attributes explicitly;
the extractor does not automatically copy all `SourceItem.metadata` into model
features. Attribute mapping, structural extractor descriptors/config, record schema,
and artifact codec affect output and therefore enter `DataIdentity`.

The first proxy baseline is no-network, CPU-only, and does not decode media. It
produces structural per-item/per-segment JSON records with empty payload refs;
workers and logging remain operational settings outside data identity.

## Phase 2 preprocessing config

P2-07 uses a separate strict/frozen `Phase2PreprocessingConfig` loaded by
`load_preprocessing_config()`. Files live under `configs/preprocessing/` and use the
same deterministic single-parent `extends` semantics as Phase 1, but Phase 1's
models and loader are not widened. A machine-local child config may override root
paths when that file is explicitly gitignored. This is a repository/operational
policy, not a runtime Git check: the loader must also work in non-Git synthetic
projects. Runtime still requires the whole config chain to remain inside the project
root and validates the complete root graph. Committed fixture configs use only
portable project-relative roots.

The top-level fields are fixed as:

```text
schema_version
source.manifest_ref
storage.roots
output.processed_root_id / output.features_root_id
codecs
features.item_attributes / features.segment_attributes
components
limits
```

The exact source manifest ref must carry a full SHA-256 checksum. Codec selectors
are explicit rather than inferred from extensions; the baseline accepts canonical
JSON/JSONL with no compression. Offline component selectors are `canonical`
behavior processing, `manifest` segment definitions, and `structural` item/proxy
extractors. Selectors use explicit constructor mappings—never dynamic imports or
plugin discovery.

Each feature attribute rule contains `source_key`, `output_key`, `value_type`, and
`required`. Item and segment rules read only the corresponding top-level metadata.
Supported baseline types are string, integer, finite number, boolean, and
homogeneous string/integer/finite-number lists. Missing optional/null values are
omitted; required missing/null or mismatched values fail without coercion.

Every config explicitly supplies positive `max_items`, `max_behavior_events`,
`max_total_segments`, and `max_segments_per_item` limits. These are adjustable
execution safety lines, not hard-coded dataset sizes: exceeding one fails without
truncation, while raising it for a larger dataset needs no code change. Limits do
not constrain clip duration or enter the data-version hash.

Only `python -m pave_rec.cli.preprocess --config <path>` is supported in the first
baseline. There are no CLI root/component/feature overrides, dry-run, resume,
force, no-reuse, or environment interpolation options.

## Phase 2 runtime release pinning

Persistent runtime Stores are constructed from one exact release reference with a
logical root/key, full `p2-<64hex>` version, and SHA-256 checksum. They do not select
`latest`, scan directories, or use mtimes. The item-feature Store, segment Store,
and filesystem resolver share one immutable loaded release, preventing a single
Agent run from combining processed artifacts from two releases.

The exact release ref is the portable identity handoff, not a self-contained physical
locator. `ReleaseLoader` must also receive the trusted validated root registry derived
from config; absolute root paths never move into ResourceRef or portable manifests.

`preprocess_from_config()` returns the exact release ref needed by P2-06 together
with the data version and local execution report path. P2-08 uses that handoff
with the same validated root registry for the persistent-Store Agent smoke test.
Phase 1 config and `run_from_config()` remain unchanged; a real runtime
experiment-config selector is deferred until a later phase actually consumes real
Stores. A raw media ref may keep its upstream version—the no-mixing rule applies to
the processed release snapshot, not every resource-version string.

## Phase 3 lifecycle configs and runtime pinning

P3-07 keeps the Phase 1 and Phase 2 config models/loaders unchanged. Phase 3 adds
separate strict/frozen config kinds under `configs/phase3/` for derived sequences,
item semantics, SASRec training, Memory snapshots/audit, runtime, and evaluation. They use
the same deterministic single-parent inheritance semantics, but foreign/unknown
fields fail and training/build/runtime/metric parameters do not share one giant
schema.

Implementation status (2026-08-05): Phase 3 is `Completed`. All lifecycle models,
APIs, and CLI routes are implemented and accepted. This includes the
Tsinghua adapter, derived sequences, pinned BGE-M3 semantics, SASRec training,
Dynamic Memory, Memory audit, full-catalog evaluation, zero-budget runtime, and
saved-output replay. Local acceptance is `275 passed, 2 skipped`, 90.03% branch
coverage, and clean Ruff checks. Required GitHub Actions run `30975939269` for
completion commit `5e78957` passed on Ubuntu/Python 3.10, Ubuntu/Python 3.12,
and Windows/Python 3.12.

Each lifecycle declares only the roots it needs and reuses the typed root-registry
path/access rules. Machine-local child configs may bind portable root IDs to external
absolute directories; physical paths are operational and excluded from portable
artifact identity. A Phase 3 runtime record stores root IDs/access roles plus exact
checksummed refs for the P2 release, P3 derived dataset, item-semantic artifact,
SASRec checkpoint, Memory snapshot, and `AgentInputBundle`. It never discovers
`latest`, scans output directories, interpolates environment variables, or persists
absolute root/model-cache paths, credentials, or tokens in the Agent run artifacts.

The bundle carries one `p3-positive-item-history-v1` projection: the complete,
untruncated `positive_v1` item sequence before the exact cutoff. The full-exposure
cutoff remains a separate identity. Bootstrap binds the exact Memory snapshot and
validates both identities before producing the existing `AgentRunRequest`; Memory
does not discover a snapshot from the tuple, and SASRec alone applies OOV filtering
and recent-50 internally.

The first real runtime selector set is `artifact` User Memory, `sasrec` Initial
Ranker, persistent filesystem Stores, the existing State/Stop/Trace components, and
role-specific unavailable guards for Phase 4/5 components. Unavailable guards require
`max_perception_actions=0`; they fail if accidentally called. The fixed zero-budget
smoke therefore builds a real Recommendation State and stops `budget_exhausted`
before Information Need.

The shared Python lifecycle APIs are exposed through one thin command family:

```text
python -m pave_rec.cli.phase3 derive       --config configs/phase3/derived.yaml
python -m pave_rec.cli.phase3 semantics    --config configs/phase3/semantic.yaml
python -m pave_rec.cli.phase3 train-ranker --config configs/phase3/sasrec_train.yaml
python -m pave_rec.cli.phase3 memory       --config configs/phase3/memory.yaml
python -m pave_rec.cli.phase3 memory-audit --config configs/phase3/memory_audit.yaml
python -m pave_rec.cli.phase3 evaluate     --config configs/phase3/evaluate_sasrec_test.yaml
python -m pave_rec.cli.phase3 run          --config configs/phase3/runtime_zero_budget.yaml
python -m pave_rec.cli.phase3 replay       --run-dir <exact-run-directory>
```

The CLI contains no lifecycle/business logic and does not provide semantic
`key=value`, root, component, force, resume, or latest overrides. P3-08 fixes the
evaluation kind to exact full-catalog warm-target ranking with primary `NDCG@10`,
secondary `HR@10`, `NDCG@20`, `HR@20`, `MRR@10`, and `Recall@100`, plus separate
all-target warm/cold coverage. The config pins the derived split/subsets, ranker or
checkpoint, candidate/filter/metric recipes, K values, and seed; it cannot switch to
development sampled candidates while claiming a primary result.

Each evaluation publishes an immutable manifest, aggregate metrics, and per-target
outcomes behind an exact ref. Per-target outcomes include the ordered Top-100 result
used to audit the future Agent candidate handoff, but do not persist the full-catalog
score matrix or expose target labels as online features. Multi-seed summaries pin the
three per-seed evaluation refs; the first engineering run may use seed `20260804`
without claiming a final stochastic result. Agent runs continue to contain exactly
`resolved_config.json`, `trace.jsonl`, and `result.json`; large artifacts remain
external behind their exact refs.
