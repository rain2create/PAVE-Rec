# Local Data

- `raw/`: immutable source data.
- `interim/`: intermediate preprocessing outputs.
- `processed/`: validated datasets consumed by training or evaluation.

Dataset contents are local and ignored by Git. Every generated dataset must
carry source-version and preprocessing-version metadata.

Phase 2 generated datasets use the full deterministic `p2-<64hex>` data version
defined by the canonical source manifest/checksums, semantic preprocessing config,
content-producing component versions, and output schema/codec versions. Every
filesystem resource carries a `sha256:<64hex>` checksum and exact byte size.

Source resources are registered as typed `source_artifacts` entries in
`DataIdentity`; generated resources are registered in root bundle manifests. Their
union is the exact release-scoped resource inventory. A resolver must reject files
that are present under a configured root but absent from this inventory.

Version directories are immutable. A root bundle is not considered published by
its directory alone: only a fully verified release manifest published last under
the processed root marks the multi-root data version complete. Existing versions
may be reused only after full verification and are never silently overwritten.
Staging and orphan bundles remain undiscoverable until a valid release exists.

Runtime pins a complete release by its full data version and checksum, loads its
indexes once, and never infers a current version from directory contents or mtime.
The portable release ref is resolved through a trusted validated root registry; it
does not contain a machine path. The P1—P3 filesystem baseline uses one processed
release for both item features and segment catalogs; separate runs may intentionally
pin different releases. P4 may explicitly replace only the Segment Store with one
immutable derived media overlay that is exact-bound to that same base release and
item-catalog identity. The overlay is not a second processed release, cannot carry
behavior/items/labels, and uses a separate inventory-verifying resolver. Arbitrary
cross-release mixing remains forbidden.
