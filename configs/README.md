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
