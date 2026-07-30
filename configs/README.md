# Configurations

Runtime and experiment configuration lives here.

- `base.yaml` will contain shared defaults.
- `mock.yaml` will define the deterministic mock vertical slice.
- `experiments/` will contain named experiment overrides.

Configuration selects component implementations and parameters. It must not
contain business logic or silently settle research choices that remain TBD.
