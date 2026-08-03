# Generated Artifacts

- `features/`: item and segment features.
- `checkpoints/`: trained model checkpoints.
- `oracle/`: teacher evidence and expected-gain labels.

Generated artifacts are ignored by Git and must include provenance metadata.

Phase 2 feature artifacts are published as immutable root bundles. Each bundle
manifest records the deterministic data version, identity digest, canonical
resource refs, `sha256:<64hex>` checksums, byte sizes, and applicable record counts.
The processed-root release manifest references all root bundle manifests and is
the sole completion marker for a multi-root version.

Machine paths, timestamps, Git/platform details, and created/reused status belong
to a separate local execution report; they do not enter portable manifests or the
data-version hash. Existing or orphan bundles are reused only after full integrity
verification. Default overwrite, deletion, cross-root move, and force-publish are
not allowed.

P2-05's first feature codec writes one canonical JSON resource per typed
`ItemFeatureRecord` and `SegmentProxyRecord`. A public `ResourceRef` therefore
identifies exactly one record and checksum; opaque item/segment IDs are not used
directly as filesystem paths. P2-06 hashes canonical item or item/segment identity
JSON with full SHA-256 and uses the first two hex characters only as directory
fan-out:

```text
bundles/<data_version>/item-features/<first2>/<full-item-hash>.json
bundles/<data_version>/segment-proxies/<first2>/<full-segment-hash>.json
```

The processed bundle carries checksummed `ItemFeatureStoreIndex` and
`SegmentStoreIndex` artifacts. Both are sorted by item ID, cover the same source
item catalog, and reference only resources declared by the exact release. Runtime
loads that release and the two indexes once; store queries then use immutable
in-memory mappings without opening payload records.

The structural baseline has empty feature payload lists and never writes tensors
or ndarrays into JSON. Future dense or sharded codecs may publish `.npy`,
safetensors, Parquet, or other versioned payloads through typed
`FeaturePayloadRef` entries without changing the Phase 1 public references.

A filesystem resolver verifies release membership, safe root/key containment,
declared byte size, and full checksum when a payload is actually resolved. Typed
record loaders validate schema and item/segment identity separately. There is no
`latest` discovery, unverified streaming, overwrite, or cross-release Store mixing
in the Phase 2 baseline. The resolver receives physical root bindings only from a
trusted validated config registry; portable refs and manifests never embed them.
