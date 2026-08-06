# Module 09 — Offline Preprocessing
# 离线数据与特征预处理模块

## 1. 模块目标 Purpose

预先准备 online Agent 所需的 cheap features。

Online loop 不应该重复做高成本 preprocessing。

---

## 2. Behavior Sequence Preprocessing

P2-01 已确认 dataset-specific raw format 先通过显式 adapter 转换为通用 source
contract；第一条 Phase 2 baseline 使用已经符合该 contract 的 versioned fixture。
Source data 只读，preprocessing 不原地修复或覆盖源文件。

### 2.1 Source records

```python
class BehaviorEvent:
    user_id: str
    item_id: str
    interaction_index: int
    occurred_at_ms: int | None
    interaction_type: str
    value: float | None
    metadata: JsonObject


class SourceItem:
    item_id: str
    metadata: JsonObject


class SourceDatasetManifest:
    schema_version: str
    source_dataset_id: str
    source_dataset_version: str
    behavior_events_ref: ResourceRef
    items_ref: ResourceRef
    segment_definitions_ref: ResourceRef
    metadata: JsonObject
```

所有 IDs 都是 opaque、case-sensitive、非空 strings，不执行 trim 或类型强转。
`interaction_index` 是每个 user 从 0 开始连续递增的唯一行为顺序事实。
`occurred_at_ms` 是真实 Unix epoch milliseconds 或显式 `None`；同一 user 必须
全部提供 timestamps 或全部不提供，存在时必须非负并随 index 单调不减。不能为了
满足 schema 而生成伪造 epoch time。

不同 index 上的重复 item/action interactions 原样保留；重复
`(user_id, interaction_index)` 非法。`interaction_type` 是 dataset-defined 非空
string，`value` 是 finite float 或 `None`，Phase 2 不把它解释为训练 label。

Behavior 引用的每个 item 必须存在于 item catalog。`SourceItem` 不预设
“每个 item 只有一个原视频”；`segment_definitions_ref` 指向 P2-04 定义的
canonical records。没有 segment definition 的 item 合法并产生显式空
segment catalog。已声明的 segment resource 无法解析或 checksum 失败时
必须失败，不能静默变成无媒体 item。

Manifest 只保存逻辑 `ResourceRef`。受信任 config 负责声明 root ID 到真实路径的
映射；dataset manifest 不能自行声明 absolute storage roots。Root/path safety 由
P2-02 定义，checksum 和 data-version 公式由 P2-03 定义。

### 2.2 Processed records

```python
class SequenceInteraction:
    item_id: str
    interaction_index: int
    occurred_at_ms: int | None
    interaction_type: str
    value: float | None
    metadata: JsonObject


class UserBehaviorSequence:
    user_id: str
    interactions: tuple[SequenceInteraction, ...]
    metadata: JsonObject
```

`UserBehaviorSequence` 不同时保存另一份 `item_ids` list。Phase 3 的
User Memory/SASRec adapter 在 component boundary 确定性投影：

```python
history = tuple(event.item_id for event in sequence.interactions)
```

因此 P2-01 不修改 Phase 1 的 `AgentRunRequest`、`UserMemory` 或 `InitialRanker`
interface。

### 2.3 Encoding, ordering, and failures

- 第一条 codec 使用 canonical UTF-8/LF JSON manifest 和 JSONL records；后续
  codec 可以替换为 Parquet，但不能改变 logical schemas。
- Items 按 `item_id`、behavior events 按 `(user_id, interaction_index)`、processed
  sequences 按 `user_id` canonical ordering。
- Schemas 使用 strict/frozen validation、显式 null 和禁止 extra top-level fields。
- 空数据、identity/coverage/order 错误、unknown item、非法时间/value 和
  unresolved declared resources 在发布前失败；不能
  skip bad rows 或发布 partial bundle。
- Source parse/schema/coverage failure 使用 `DatasetValidationError` 并报告 logical
  filename/JSONL line；resource lookup/checksum failure 使用
  `ResourceResolutionError`。
- Phase 2 不生成 train/validation/test split、negative samples、candidates 或
  labels；这些属于 Phase 3 derived datasets。

这些 records 用于：

- SASRec
- long/short memory construction

---

## 3. Cheap Item Features

P2-05 的第一条 baseline 不训练或下载模型，不自动将全部 source metadata
当作 feature。Semantic config 显式选择 title/category/creator 等可用字段；
缺失的 optional value 不伪造 placeholder，configured type mismatch 使 validation
失败。

```python
class FeaturePayloadRef:
    name: str
    resource_ref: ResourceRef
    codec: str
    dtype: str | None
    shape: tuple[int, ...] | None
    metadata: JsonObject


class ItemFeatureRecord:
    schema_version: str
    item_id: str
    attributes: JsonObject
    segment_count: int
    payload_refs: tuple[FeaturePayloadRef, ...]
    metadata: JsonObject
```

Baseline 为每个 SourceItem 生成一个 record；即使 `attributes={}`，仍保存明确
`segment_count`。不保存 item-level duration，因为 mixed/gapped/overlapping segments
不一定存在单一客观 item duration。第一条 `payload_refs=()`。`attributes`
是可供模型消费的明确字段；`metadata` 只作 provenance/debug，默认不当作
模型特征。

通过统一 feature store 暴露。

```python
class ItemFeatureStore(Protocol):
    def load_refs(
        self,
        item_ids: tuple[str, ...],
    ) -> tuple[ItemFeatureRef, ...]:
        ...
```

---

## 4. Segment Definition and Ingestion

跨模块 Segment metadata 以
[`00_shared_domain_schemas.md`](00_shared_domain_schemas.md) 为准：

```python
class SegmentMeta:
    item_id: str
    segment_id: str
    start_ms: int
    end_ms: int
    media_ref: ResourceRef
    metadata: JsonObject
```

Phase 2 不预设 fixed duration。P2-04 的 manifest-driven baseline 加载外部明确
定义的 segments，支持两种互斥 locator：

```python
class SegmentDefinition:
    item_id: str
    segment_id: str
    sequence_index: int
    locator: FileLocator | RangeLocator
    metadata: JsonObject


class FileLocator:
    kind: Literal["file"]
    media_ref: ResourceRef
    duration_ms: int
    origin: OriginRange | None


class RangeLocator:
    kind: Literal["range"]
    media_ref: ResourceRef
    start_ms: int
    end_ms: int


class OriginRange:
    original_media_ref: ResourceRef
    start_ms: int
    end_ms: int
```

P2-04 只负责加载、校验、投影和版本化，不自动重切、补齐、复制或
重新编码媒体。Manual、fixed-window、scene-based 和 hybrid producers 未来
都生成同一 contract。独立 clip 不知道原视频时间时保留 `origin=None`，
其顺序由 `sequence_index` 表达，不伪造原时间。

Canonical definitions 必须显式保存 item-local 唯一 `segment_id` 和从 0 连续的
`sequence_index`。上游没有稳定 ID 时，adapter 在 canonical validation 前生成
`seg_<sequence_index:06d>`。全局 contract 允许变长、gap、overlap 和 mixed
file/range locators；更强的 coverage 约束属于具体 producer。

File duration 和 range/origin times 使用 integer milliseconds；ranges 使用
half-open `[start_ms, end_ms)`。`FileLocator.duration_ms > 0`，range/origin 在存在时
必须满足 `0 <= start_ms < end_ms`。第一条 baseline 信任 canonical 声明，
并校验 resource、byte size 和 checksum；不强制 FFmpeg/ffprobe。未来
MediaProbe 发现不一致时必须失败，不静默修正数据。

Phase 2 投影到现有 P1 runtime schema 时：

```text
FileLocator  -> SegmentMeta(media_ref=file_ref, start_ms=0, end_ms=duration_ms)
RangeLocator -> SegmentMeta(media_ref=source_ref, start_ms=start_ms, end_ms=end_ms)
```

因此原视频起止时间不是必填信息；独立 clip 的 `[0, duration_ms)` 只是
相对它自己的访问范围。P1 `SegmentMeta`、`ItemSegmentCatalog`、Store、
Controller 和 trace/replay contracts 不变。`sequence_index` 和可选 origin 保留在
canonical source `SegmentDefinition`，并由 preprocessing 内部 frozen、per-item
`ItemSegmentIndex` 组织。

`ItemSegmentIndex` 是 structural extractors、coverage validation 和 P1 projection 共用的
非持久化 typed intermediate，不单独发布或加入 generated golden tree。Canonical
SegmentDefinition source artifact 持久化 locator/origin provenance，SegmentProxyRecord
持久化 sequence/count，SegmentStoreIndex 持久化 runtime-compatible projection，避免创建
第三个 segment 事实来源。

---

## 5. Cheap Segment Proxy Features

P2-05 第一条 baseline 的 cheap proxy 只证明数据链路，不解码媒体，不生成
keyframe/motion/scene statistics、ASR/audio 或 learned embeddings。

```python
class SegmentProxyRecord:
    schema_version: str
    item_id: str
    segment_id: str
    duration_ms: int
    sequence_index: int
    segment_count: int
    attributes: JsonObject
    payload_refs: tuple[FeaturePayloadRef, ...]
    metadata: JsonObject


class SegmentProxyRef:
    item_id: str
    segment_id: str
    feature_ref: ResourceRef
    metadata: JsonObject
```

`duration_ms` 从 P2-04 locator 确定性派生；`0 <= sequence_index < segment_count`，
且同 item records 的 segment count 必须一致。不持久化可由 index/count
派生的 relative position，也不要求原视频时间 provenance。第一条
`attributes={}` 且 `payload_refs=()`。

`StructuralItemFeatureExtractor` 和 `StructuralSegmentProxyExtractor` 只输出 typed
records，不执行 I/O。Publisher 单独负责 canonical serialization、checksums 和
publication。缺失 optional source attribute 合法；输出 identity/coverage/order
不匹配、extractor execution failure 或任意 segment 缺失 proxy 都使整个
preprocessing 失败，不发布 partial bundle。

第一条 codec 为每个 ItemFeatureRecord/SegmentProxyRecord 生成一个独立
canonical JSON resource；每个 public `ResourceRef` 因此精确指向一个 record。
P2-06 将 canonical item identity 和 `(item_id, segment_id)` identity 分别计算完整
SHA-256，并以两位 digest prefix 做 directory fan-out；opaque IDs 不直接形成
filesystem keys。未来 dense/sharded payload 通过 `FeaturePayloadRef` 和新
codec/version 接入，不修改 P1 public refs、Controller 或 State。

---

## 6. Segment Store

```python
class SegmentStore(Protocol):
    def load_catalog(
        self,
        item_ids: tuple[str, ...],
    ) -> tuple[ItemSegmentCatalog, ...]:
        ...
```

P1-03 已确认 Store 只返回静态 metadata/references，不根据 Observation State
执行策略过滤。每个请求 item 都必须有显式 `ItemSegmentCatalog` entry；未观察
segment 从 Recommendation State 做确定性投影。权威接口和缺失资源语义见
[`00_component_interfaces.md`](00_component_interfaces.md)。

---

## 7. Data Versioning

P2-03 将 portable data identity 与 machine-local execution provenance 分开。
`data_version` 在生成 artifacts 前由 canonical `DataIdentity` 确定：

```text
DataIdentity
  identity_schema_version
  canonical validated SourceDatasetManifest
  source_artifacts sorted by ResourceRef identity
  semantic preprocessing config
  content-producing ComponentDescriptors in fixed role order
  output schema and codec versions

identity_digest = sha256(canonical_json_bytes(DataIdentity, pretty=False)).hexdigest()
data_version = "p2-" + identity_digest
```

正式版本使用完整 64 lowercase hexadecimal digest。Semantic config 包含 logical
root IDs、behavior/segmentation/proxy rules、schema/codec/compression settings 和
任何影响输出的 seed；不包含机器 absolute roots、config/staging paths、run ID、
workers/logging、timestamps、Git 或 platform metadata。输出 checksums 不进入
data-version 公式，避免循环依赖；同一 identity 产生不同 bytes 是确定性或
component-version contract failure。

`source_artifacts` 使用 `ArtifactEntry` shape，展开 behavior、items、segment
definitions 以及所有非 null locator media/origin refs。它记录每个 source ref 的
artifact/schema kind、checksum、`size_bytes` 和可选 `record_count`，按
`(store, key, version, checksum)` canonical ordering，并在计算 identity 前完整验证。

Config 的 exact `source.manifest_ref.checksum` 在 ingestion 时验证，但 identity 保存
canonical validated manifest object，而不是它的非语义 JSON 排版 bytes。只改变缩进、
空白或 object-key 顺序且 canonical content/referenced resources 不变时，data version
不变；canonical manifest fields 或任一 referenced artifact bytes/checksum 变化时版本
必须改变。

Phase 2 filesystem source/generated resources 必须使用
`sha256:<64 lowercase hex>` checksum，并记录 `size_bytes`；record artifacts 可以
记录 `record_count`。Checksum streaming 计算精确 bytes，size/mtime 不能替代 digest。
公共 `ResourceRef.checksum` 保持 optional，Phase 2 filesystem manifest/resolver
施加 required-checksum contract。

### 7.1 Portable manifests

```text
ArtifactEntry
  resource_ref
  artifact_kind
  schema_version
  size_bytes
  record_count: int | null

RootBundleManifest
  schema_version
  data_version
  root_id
  identity_digest
  artifacts

ReleaseManifest
  schema_version
  data_version
  identity
  root_bundle_manifest_refs sorted by (store, key)
  status: complete
```

Artifact entries 按 `(store, key)` canonical order。Root manifest 不自包含 checksum；
ReleaseManifest 记录每个 root manifest 的带 checksum ref，并允许从 embedded
identity 重算 data_version。Release 本身不自引用 checksum。

Runtime 可解析的 release inventory 只由
`DataIdentity.source_artifacts + all RootBundleManifest.artifacts` 组成；同一 storage
root 中未被这个 graph 声明的文件不因“路径存在”而自动获得授权。

Timestamp、Git commit/dirty、configured/resolved roots、Python/platform 和
`created`/`reused` outcome 写入单独 typed local `ExecutionReport`。它不进入
data-version hash、portable bundle 或 golden artifacts，默认 gitignored。
Portable record/manifest metadata 只能包含 deterministic semantic provenance；execution
ID、timestamp、absolute/config/staging paths 和其他 invocation-local values 禁止进入。

### 7.2 Multi-root publication and reuse

```text
validate inputs
→ compute identity/version
→ stage inside each write_new root
→ write and fully verify root bundles/manifests
→ atomic rename inside each individual root
→ exclusively publish processed/releases/<data_version>.json last
```

只有最后的 ReleaseManifest 存在并完整验证通过，版本才是 complete。不同 roots
可能位于不同 filesystems，不能宣称跨 root transaction。已有 release 只有在
identity、root manifests 和全部 resource checksums 一致时才 `reused`；任何 mismatch
使用 `ArtifactIntegrityError` 且不覆盖。没有 release 的完整 orphan root bundle
可以 full verification 后复用，partial files/staging 不可复用或被 Store discovery。

默认不删除 staging/orphan，也不提供 force overwrite。Staging/write/rename/final
exclusive-publish failure 使用 `ArtifactPublicationError`，不能产生 complete release。
大型数据 digest cache 和显式 maintenance/cleanup 留作后续扩展。

以下版本字段保持独立：

- `source_dataset_version`：upstream dataset version；
- `data_version`：Phase 2 recipe identity；
- `schema_version`：record/manifest structure；
- `ComponentDescriptor.version`：implementation semantics；
- `ResourceRef.checksum`：one resource's exact bytes；
- Git commit/dirty：local execution provenance。

---

## 8. Storage Roots and Path Safety

P2-02 允许 source/media/processed/features 位于 project root 外，但不允许把机器
absolute paths 写入 portable manifests 或 `ResourceRef`。Phase 2 preprocessing
config 使用独立、typed root registry：

```yaml
storage:
  roots:
    source: {path: data/raw/phase2-fixture, access: read_only}
    media: {path: D:/datasets/pave/videos, access: read_only}
    processed: {path: data/processed, access: write_new}
    features: {path: artifacts/features, access: write_new}
```

- Root map 可扩展；root IDs 使用 portable lowercase identifiers，并由
  `ResourceRef.store` 引用。
- Root paths 可以 project-relative 或 absolute；只有 root declaration 可以使用
  absolute path。CLI 不提供 root overrides，也不执行 environment interpolation。
- 所有 roots 必须预先存在并为 directories；解析真实路径后必须唯一、两两不重叠。
- `read_only` root 不写入、移动或删除；`write_new` root 只创建新 bundle/staging，
  不覆盖已有 bundle。
- Filesystem keys 使用 canonical relative POSIX grammar。拒绝 POSIX/Windows/UNC
  anchors、`.`/`..`/空 segments、反斜杠、control/reserved names、非 canonical
  Unicode 和 case-insensitive collisions。
- 显式 root 本身可以解析到 symlink/junction target；root 下的 child link escape
  和 writable-link escape 必须拒绝。最终 resolved path 必须仍在真实 root 内。
- Portable manifests/records/State/Trace 只保存 root ID、logical key、version 和
  checksum。机器 absolute roots 只允许进入 gitignored local execution report，
  并且不进入 data-version hash 或 golden artifacts。
- 非法 root graph 在创建 output 前以 `ConfigurationError` 失败；unsafe/missing
  resource resolution 使用 `ResourceResolutionError`。
- 默认不执行删除、覆盖或跨 root move。

Phase 1 的 fixture/output project-relative path contract 不变。Phase 2 使用单独的
root registry/resolver，不能全局放宽 Phase 1 config validator。

---

## 9. Persistent Stores and Resource Resolution

P2-06 的 runtime 从一个 exact `ReleaseManifest` ref 构造：ref 必须包含 root ID、
`releases/<full-data-version>.json` key、完整 `p2-<64hex>` version 和 SHA-256 checksum。
不支持 `latest`、mtime/directory discovery 或 orphan-bundle discovery。

```text
ReleaseLoader(trusted_validated_root_registry).load(exact_release_ref)
  -> immutable LoadedRelease
       |-- FilesystemItemFeatureStore
       |-- FilesystemSegmentStore
       `-- FilesystemResourceResolver
```

ReleaseLoader 每次 runtime construction 只执行一次 eager validation：release、embedded
identity/data version、root manifests、required indexes、resource graph、coverage 和
ordering 全部通过后才返回。两个 Stores 与 resolver 共享同一个 LoadedRelease；同一次
Agent run 不得分别选择 item release A 和 segment release B。不同 runs 可以固定不同
release，file/range locator 也仍可在一个 release 内混合。

### Phase 4 derived media-overlay amendment

上述规则继续约束 P2 `FilesystemItemFeatureStore`、`FilesystemSegmentStore` 和两个独立
processed releases，P1—P3 baseline/goldens 不改变。P4-01 另确认一个窄化、显式 selector：

```text
one exact base P2 LoadedRelease
        +
one exact derived media-overlay manifest bound to that release/item catalog
        ↓
MediaSubsetSegmentStore
```

Overlay 不是 `segment release B`，不包含 behavior、item features 或 labels，也不能从
`latest`/path/mtime 猜 base。Manifest 必须引用 exact base ReleaseManifest 和 Item Store
index/catalog identity，并用独立 inventory、size、SHA-256 和 safe root resolver 管理 media、
segment 和 proxy refs。Store 同时验证 base `LoadedRelease` 与 overlay：只有 base catalog
中的 item 合法；未被 overlay 覆盖的合法 item 返回 empty catalog；已声明但缺失/损坏的
resource、cross-release/catalog mismatch、unknown item 或 segment/proxy coverage drift 必须
fail closed，不能降级为空 catalog。

P2 resolver 继续只解析其 LoadedRelease inventory，不能增加 bypass。P4 media resolver 只
解析 overlay inventory。P4 runtime 的 exact artifact graph 同时记录 base release 和 overlay
refs；`AgentRunResult.data_version` 仍表示 base P2 data version。旧 P2/P3 component selectors
不得自动选择 overlay，原 tests/goldens/zero-budget runtime 必须 byte/semantic regression。

Exact release ref 是唯一 portable release identity handoff，但不是自包含的 physical
locator；root ID 到本机 path 的映射只能来自 trusted config。Preprocessing source
ingestion 在 release 尚未存在时使用 validated root registry 和同一 path-safety core；
runtime filesystem resolver 除路径/checksum 校验外还必须强制 LoadedRelease inventory
membership。两个 resolver boundary 不能通过默认 bypass 混用。

### 9.1 Keys and indexes

```text
item_hash = sha256(canonical_json_bytes({"item_id": item_id}, pretty=False)).hexdigest()
segment_hash = sha256(
  canonical_json_bytes({"item_id": item_id, "segment_id": segment_id}, pretty=False)
).hexdigest()

features root:
  bundles/<data_version>/item-features/<item_hash[0:2]>/<item_hash>.json
  bundles/<data_version>/segment-proxies/<segment_hash[0:2]>/<segment_hash>.json
```

完整 digest 是 key identity，两位 prefix 只做 fan-out。Processed bundle 包含：

```text
ItemFeatureStoreIndex(schema_version, data_version, entries)
SegmentStoreIndex(schema_version, data_version, catalogs)
```

两个 indexes 按 `item_id` 排序并精确覆盖同一 SourceItem catalog。
SegmentStoreIndex 直接保存 P1-compatible `ItemSegmentCatalog`；其 SegmentMeta 和
SegmentProxyRef identity/order 必须一一对应，已知无 segments 的 item 保存空 catalog。
Indexes 和被它们引用的 records 必须都出现在 release inventory 中。

Store constructor 将 index 转成 immutable `item_id` mapping。之后
`load_refs()`/`load_catalog()` 只按 caller 请求顺序做内存 lookup，不重读 manifests，
也不读取 feature/proxy/media payload。

### 9.2 Resolution, typed loading, and errors

```python
class ResourceResolver(Protocol):
    def read_verified_bytes(self, ref: ResourceRef) -> bytes: ...
    def resolve_verified_path(self, ref: ResourceRef) -> Path: ...
```

`ResourceRef.store` 是 trusted root-registry ID，不是 Store class 名。Filesystem
resolver 只解析 loaded release inventory 内的 ref，并在实际消费时重新验证 safe
contained path、存在/readability、declared version、size 和完整 checksum；第一版不提供
unverified stream 或 persistent digest cache。Path 只在本机 dependency boundary
使用，不进入 JSON records。

ItemFeatureRecordLoader/SegmentProxyRecordLoader 消费 verified bytes，再验证 canonical
JSON、typed schema 和 expected item/segment identity。Unknown query item 保持 P1
`ContractError`；文件定位、membership、size/checksum failure 使用
`ResourceResolutionError`；complete release 的 manifest/index/typed identity 不一致使用
`ArtifactIntegrityError`。Corruption 不得降级为 optional feature、空 catalog 或 skip。

Phase 2 declared errors 统一属于 `PaveRecError` hierarchy：

```text
PaveRecError
├── ContractError
│   ├── ConfigurationError
│   └── DatasetValidationError
├── ResourceResolutionError
├── ComponentExecutionError
├── ArtifactIntegrityError
└── ArtifactPublicationError
```

Dataset/schema/coverage/count 失败属于 contract validation；已发布 graph/typed identity
损坏属于 artifact integrity；staging/publish/report I/O lifecycle 失败属于 publication。

`ComponentDescriptor.version` 表示 Store implementation semantics；run `data_version`
表示固定的 processed release；`ResourceRef.version` 表示该资源自己的版本。生成的
feature/proxy/index 通常使用当前 data version，raw media 可以保留 upstream version。
Resolver 是两个 Store 的共享 infrastructure dependency，不新增 Agent Loop role，也不
修改 Controller。

---

## 10. Preprocessing Config, API, and Lifecycle

P2-07 使用独立 `Phase2PreprocessingConfig` 和
`load_preprocessing_config()`；现有 Phase 1 `Phase1Config/load_config()` 不变。
Preprocessing YAML 放在 `configs/preprocessing/`，继续使用 single-parent relative
`extends`、deterministic recursive mapping merge 和 strict/frozen extra-forbid
validation。CLI/env 不提供 root、component 或 feature overrides。

包含 machine absolute roots 的 local child config 应被 gitignored，但这是 repository
operational policy，不是 runtime Git check。Loader 不依赖 Git repository；它仍要求整个
config chain 留在 project root，并完整验证 root declarations、存在性、access、uniqueness
和 non-overlap。可提交 fixture config 只使用 project-relative roots。

### 10.1 Typed config

```yaml
schema_version: "1"

source:
  manifest_ref:
    store: source
    key: fixture/source_manifest.json
    version: fixture-v1
    checksum: sha256:<64hex>

storage:
  roots:
    source: {path: data/raw/phase2-fixture, access: read_only}
    processed: {path: data/processed, access: write_new}
    features: {path: artifacts/features, access: write_new}

output:
  processed_root_id: processed
  features_root_id: features

codecs:
  source_manifest: canonical-json-v1
  source_records: canonical-jsonl-v1
  behavior_sequences: canonical-jsonl-v1
  feature_records: canonical-json-v1
  manifests_and_indexes: canonical-json-v1
  compression: none

features:
  item_attributes:
    - source_key: category
      output_key: category
      value_type: string
      required: false
  segment_attributes: []

components:
  behavior_processor: canonical
  segment_definition_provider: manifest
  item_feature_extractor: structural
  segment_proxy_extractor: structural

limits:
  max_items: 100
  max_behavior_events: 1000
  max_total_segments: 1000
  max_segments_per_item: 100
```

Source manifest ref 必须带完整 checksum。Config 明确声明 source/output codecs，不能
根据文件扩展名猜测。第一条 codec selectors 只允许上面的 canonical JSON/JSONL 和
`compression=none`；新增 Parquet/compression 需要显式 selector/schema version。

`item_attributes` 从 `SourceItem.metadata` 顶层读取，`segment_attributes` 从
`SegmentDefinition.metadata` 顶层读取。每条 mapping 显式保存 source/output key、
`required` 和以下 value type：

```text
string | integer | number | boolean |
string_list | integer_list | number_list
```

Mappings 按 output key 排序且 source/output keys 唯一。Optional missing/null value
不生成 key；required missing/null 或 type mismatch 使用 `DatasetValidationError`。
第一版不支持 JSONPath、coercion、default value 或 arbitrary object feature。

四个 `limits` 是每份 config 必填的 positive integers，没有写死的全局数据规模。超过
上限时 preprocessing 整体失败，不截断、抽样或跳过记录：

- `max_items`；
- `max_behavior_events`；
- `max_total_segments`；
- `max_segments_per_item`。

它们不限制 clip 时长、不修改 locator bounds，也不切分媒体。只要不同 limits 都允许
同一输入完整执行，输出 bytes 不变，因此 limits、physical root paths 和其他
operational settings 不进入 `DataIdentity`。Component semantics、attribute mappings、
logical output roots、codecs/compression 和 schema versions 进入 identity。

### 10.2 Components and Python API

Content-producing offline roles 的 descriptor order 固定为：

```text
behavior_processor
segment_definition_provider
item_feature_extractor
segment_proxy_extractor
```

它们由显式 selector/constructor mapping 组成 frozen `PreprocessingComponents`。
Resolver、codec、publisher 和 release loader 是 infrastructure；不使用 DI framework、
reflection、async worker pool 或 generic DAG scheduler。Validated source objects 只加载
一次并传给 pure components，components 不自行写 artifacts。

Python/CLI 共享同一高层入口：

```python
result = preprocess_from_config("configs/preprocessing/fixture.yaml")
```

```text
PreprocessingResult
  execution_id
  outcome: created | reused
  data_version
  release_ref: ResourceRef
  execution_report_path: Path
  item_count
  behavior_event_count
  segment_count
  artifact_count
```

只有完整 publish 或 verified reuse 才返回 result；declared failure 抛 typed exception，
不返回 partial/`succeeded=False` result。Exact `release_ref` 可直接作为 identity argument
传给已绑定 validated root registry 的 P2-06 loader，且 ref version 等于 result data
version。Local `Path` 不进入 portable serialization。

`artifact_count` 等于所有 RootBundleManifest 中 generated artifact entries 的总数；包含
behavior、feature/proxy 和 Store-index artifacts，不包含 source_artifacts、root manifests
自身或 final ReleaseManifest。相同 release 的 created/reused result 必须返回相同 count。

### 10.3 Execution and publication

```text
load/merge/validate config
→ validate root graph
→ allocate runs/preprocessing/<execution_id>/
→ resolve/validate source once and enforce count limits
→ build segment indexes/source_artifacts and compute data version
→ full-verify/reuse an existing complete release, or
→ run pure processors/extractors and validate all outputs
→ stage in each root at staging/<data_version>/<execution_id>/
→ write and full-verify root bundles
→ no-overwrite root-local rename to bundles/<data_version>/
→ exclusive publish processed/releases/<data_version>.json last
→ write terminal ExecutionReport and return
```

The invocation that creates the final release returns `created`; an invocation that
finds or loses a race to an identical verified release returns `reused`. A mismatch
fails with `ArtifactIntegrityError`. Concurrent runs rely on exclusive filesystem
create/rename, not a lock service. Complete orphan bundles can be verified and
reused; partial staging cannot.

The staging path is operational and excluded from portable identity. On Windows,
where the historical prefix plus full-SHA artifact keys can exceed the legacy path
limit, the physical staging location is `staging/<128-bit sha256 prefix(root, data
version, execution ID)>`, and trusted absolute storage roots use the Windows
extended-length path form at the filesystem boundary. Published
`bundles/<data_version>/...` keys, full checksums, release bytes and no-overwrite
semantics are unchanged. `ExecutionReport.staging_locations` always records the
actual physical staging location used by the invocation.

第一版没有 dry-run、resume、force、no-reuse、checkpoint recovery、automatic cleanup
或 deletion。Interruption/failure 不发布 release marker；staging remains undiscoverable
and is not reused.

### 10.4 Local execution report

Config/root validation 成功后，runner 独占创建 gitignored
`runs/preprocessing/<execution_id>/`。Execution ID 使用 UTC timestamp 加 8 lowercase
hex；CLI 不允许指定。Config/root validation failure 不创建目录，之后的 declared
failure best-effort 写 failed report，且 report failure 不遮蔽原异常。

`ExecutionReport` 记录 status、created/reused outcome、可空 data version/release ref、
UTC timestamps、config path、configured/resolved roots、component descriptors、
Git commit/dirty、Python/PAVE-Rec/Pydantic/PyYAML/platform versions、已知 counts、
staging locations 和安全 error code/message。它不记录 stack trace、secret、完整
environment freeze 或未使用的 FFmpeg/model versions。

Report 是 local operational JSON，不进入 data identity、portable release 或 golden
comparison。若 release 已完整发布但 success report 写入失败，API 以
`ArtifactPublicationError` 报告；再次运行会验证并 reuse release，再生成新 report，
不会回滚或覆盖 release。

### 10.5 CLI and Phase 1 boundary

```bash
python -m pave_rec.cli.preprocess --config configs/preprocessing/fixture.yaml
```

CLI 只有 `--config`。Success stdout 报告 execution ID、created/reused、data version、
exact release ref 和 report path。Exit codes 为：

- `0`：created 或 verified reused；
- `2`：argparse/config/dataset validation；
- `1`：resource/integrity/publication/component/其他 declared failure；
- `130`：KeyboardInterrupt。

Unexpected programming exceptions 保留 traceback，但不写入 artifacts/report。
P2-07 不修改 Phase 1 config、`run_from_config()`、Mock bootstrap、goldens、Controller、
State、Trace 或 Agent Loop。P2-08 通过同一 validated root registry 和
`PreprocessingResult.release_ref` programmatically 构造 persistent data plane 并执行
Agent smoke test；真实 runtime config selector 留给开始消费真实 Store 的后续阶段。

---

## 11. Testing and Phase Acceptance

P2-08 固定使用 versioned `preprocessing-v1` fixture 验证本模块。Canonical fixture
包含 2 users、`item_a/item_b/item_c`、6 behavior events，并为每个 item 固定
`segment_1/segment_2`；
它同时覆盖一位用户的完整 timestamps、另一位用户的全 null timestamps、合法重复
interaction、range locator、独立 file locator 和带 origin 的 file locator。Media fixture
只是带稳定 checksum 的小型 opaque bytes；baseline tests 不解码媒体。

Version-controlled golden 覆盖 behavior sequences、item/segment records、indexes、root
bundle manifests 和 release manifest 的完整 relative tree，并使用 canonical codec 做
byte-exact comparison。Execution ID、timestamps、absolute roots、config/report/staging
paths、Git/platform metadata 和 created/reused outcome 是 local operational values，只做
typed semantic validation，不进入 golden。

Python API 与 CLI 在独立 fresh synthetic projects 中必须得到相同的 data version、exact
release ref、counts 和 portable artifact bytes。它们的 stdout、ExecutionReport 和
machine-local result fields 不要求逐字节相同。

Acceptance tests 必须证明：

- physical roots、execution metadata 和不触发拒绝的 count-limit changes 不改变
  DataIdentity 或 portable bytes；
- canonical source-manifest fields、referenced source artifact bytes/checksum、attribute
  mappings、content-producing component versions、schema/codec 和 logical recipe changes
  会改变 data version；仅 source-manifest JSON 排版变化不会；
- config/root/source/count/component/publication/report failures 不发布伪完整 release；
- partial staging 不可发现，orphan/reuse/mismatch/corruption 遵守 P2-03/P2-07；
- resolver 和 typed loaders 在已确认的 eager/lazy boundary 拒绝 membership、size、
  checksum、version 和 identity corruption；
- deterministic publisher collision tests 在所有 CI platforms 运行，Ubuntu Python 3.12
  另执行 barrier-controlled two-invocation race；
- exact release 通过 validated root registry 只加载一次，resolver 与两个 filesystem
  Stores 共享同一 `LoadedRelease`；这两个 Stores 替换 in-memory Stores 后仍完成
  `mock-v1` canonical two-action Agent run，并保持 preprocessing-to-trace segment identity；
  smoke run 使用 Phase 2 data version/filesystem Store descriptors，其余 Mock descriptors、
  Controller semantics 和 action budget 不变；
- Phase 1 golden、replay 和全部 regression tests 不改变。

所有 integration/E2E tests 只在 pytest `tmp_path` 下建立 synthetic project 和 distinct
source/processed/features/runs roots，不接触仓库真实 data/artifacts/runs，也不使用网络、
GPU、MLLM、FFmpeg、真实 dataset 或未声明 system tool。Cross-platform path grammar
使用 pure tests；real symlink/junction capability-based，Ubuntu symlink coverage mandatory。

Phase 2 quality gate 是 pytest 全部通过、整个 `pave_rec` package branch coverage 至少
90%、Ruff lint/format，以及 project-wide GitHub Actions 在 Ubuntu Python 3.10/3.12 和
Windows Python 3.12 全部通过。当前 baseline、golden、API/CLI E2E、publication race、
persistent data plane Agent smoke 和本地 quality gates 已实现并通过；同一 candidate
commit 的完整远端 CI matrix 尚未形成 completion evidence，因此路线图仍不能把
Phase 2 标记为 `Completed`。

2026-08-03 的本地 acceptance evidence 为 macOS / Python 3.13：`168 passed`，整个
`pave_rec` package branch coverage `91.62%`，Ruff lint/format passed。该记录只证明
local gates，不替代已确认的 Ubuntu Python 3.10/3.12 与 Windows Python 3.12 CI matrix。

---

## 12. TBD

- final segmentation strategy
- exact proxy feature set
- exact embedding models
- future ASR/audio integration after the structural no-audio baseline
