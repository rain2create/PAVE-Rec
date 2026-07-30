# Local Data

- `raw/`: immutable source data.
- `interim/`: intermediate preprocessing outputs.
- `processed/`: validated datasets consumed by training or evaluation.

Dataset contents are local and ignored by Git. Every generated dataset must
carry source-version and preprocessing-version metadata.
