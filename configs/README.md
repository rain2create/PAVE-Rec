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
