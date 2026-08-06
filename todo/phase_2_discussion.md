# Phase 2 Discussion Checklist
# Phase 2 逐项讨论清单

## 1. Phase 2 的定位

Phase 2 的目标是建立真实 online Agent 可以消费的离线数据契约、可重复的
preprocessing pipeline、可版本化 artifacts，以及持久化 Item/Segment Stores。

Phase 2 应证明：

- online loop 不执行视频切分或批量特征提取；
- behavior、item、media、segment 和 proxy identities 可以稳定关联；
- 同一来源和 preprocessing config 可以得到可追踪的数据版本；
- `ResourceRef` 可以安全解析到带 checksum 的真实资源；
- persistent Stores 可以替换 Phase 1 的 in-memory Stores，而不改变 Controller；
- Phase 1 的 schemas、Agent loop、trace/replay 和 failure semantics 不回退。

### 已确认的第一条 baseline 边界

Status: `Confirmed`

1. 第一条 Phase 2 baseline 使用通用 source-data contract 和小型 versioned fixture，
   不立即绑定最终研究数据集。
2. 第一条 segment baseline 消费外部明确定义的 canonical segment
   manifest，不预设固定时长或切分策略。同一 contract 同时支持独立媒体文件
   和原媒体时间范围；产生 manifest 的切分方法可替换。
3. 第一条 proxy baseline 是 no-network、CPU-only 的结构化 extractor，不解码媒体，
   不包含 ASR、audio、CLIP/SigLIP 或其他 learned embedding。Phase 2
   先证明 typed record、reference、artifact 和 Store pipeline。
4. Phase 2 允许 dataset/artifact 位于项目目录外，但外部位置只能作为显式声明、
   单独校验的 storage root；root 下的 manifest keys 和 `ResourceRef.key` 仍必须是
   规范化相对路径，不能逃逸 root。

### 本阶段明确不做

- 选择最终 target dataset；
- 训练真实 SASRec；
- 实现 Dynamic Hybrid User Memory 算法；
- 调用真实 MLLM；
- 生成 Oracle expected-gain labels；
- 训练 Segment Value Model 或最终 Score Updater；
- 固化最终 segmentation strategy；
- 固化最终 item/segment feature set 或 embedding model；
- 将 observation-aware filtering 放入静态 Store；
- 改写 Phase 1 已确认的 Controller state machine。

### P2-BASELINE Decision Record

```text
Decision ID: P2-BASELINE
Status: Confirmed
Decision:
1. 使用通用输入契约和小型 versioned fixture，不在第一条 baseline 绑定真实研究数据集。
2. 使用 manifest-driven segment-definition baseline；每个 segment 可指向独立
   media file 或原 media 中的 range，不预设固定时长。
3. 第一条 proxy baseline 仅生成结构化 item/segment records，不解码媒体，
   不使用 ASR/audio 或 learned embedding/model。
4. 允许显式 external storage roots，但所有 root 内资源 key 继续使用安全相对路径。
Rationale:
先固定可复现的数据平面、identity、reference、Store 和 pipeline，再逐步替换数据集、
segment-definition provider 和 feature extractor，避免 Phase 2 提前吸收
Phase 3—5 的研究选择。
Alternatives considered:
立即绑定真实数据集；第一版直接依赖 FFmpeg/CLIP/ASR；继续禁止所有外部数据目录；
在未确定切分方法时强制 fixed-window 或仅支持一种媒体布局。
Affected schemas/interfaces:
Phase 2 source schemas, preprocessing config, SegmentDefinitionProvider, feature
extractors, ResourceResolver, persistent ItemFeatureStore/SegmentStore,
preprocessing manifest.
Affected docs/tests:
todo/phase_2_discussion.md；后续确认后更新 implementation roadmap、docs/09、
configs/data/artifacts READMEs 和 Phase 2 tests。
Deferred follow-up:
最终数据集、具体 manual/fixed/scene/hybrid segmentation producer、
learned proxy embeddings 和 ASR/audio 分别在获得明确实验需求时重新讨论。
Confirmed by: User
Date: 2026-08-02
```

---

## 2. 讨论方式

下面的 Decision Gates 按顺序逐个讨论：

```text
Pending / In Discussion
→ 明确问题与 Phase 1 依赖
→ 比较选项和取舍
→ 用户 Confirm 或 Deferred
→ 更新本文件和受影响的稳定文档
→ 只实现已确认部分
```

已经确认的 baseline 方向不代表字段、文件布局、错误语义和验收标准自动确定。
每个 Gate 只有在 Decision Record 标记为 `Confirmed` 后才可以进入实现。

---

## 3. P2-00 — Phase 1 Handoff and Store Filtering Consistency

Status: `Confirmed`

这是正式设计 Phase 2 前必须先解决的跨阶段一致性 Gate。

### 3.1 原始冲突

`todo/implementation_roadmap.md` 的 Phase 2 交付物包含：

```text
可排除已观察片段的查询接口
```

但 P1-03 已确认的权威 Store contract，以及
`docs/00_component_interfaces.md` 和 `docs/09_offline_preprocessing.md` 都规定：

```text
SegmentStore 只返回完整静态 ItemSegmentCatalog；
Store 不读取 Observation State，也不执行 observed/unobserved 策略过滤；
Controller 从 Recommendation State 确定性投影未观察 segment。
```

如果同时保留两种语义，会出现两个 observation 事实来源，并使 Store 成为 Agent
policy 的一部分。不同 Store 还可能对 failed observation、重试或排序产生不同解释。

### 3.2 已确认的统一方案

保留 Phase 1 的权威契约：

```text
SegmentStore.load_catalog(item_ids)
→ 返回完整、静态、canonical ordered catalog

Recommendation State / Controller projection
→ 结合 ObservationState 排除已经尝试的 segment
```

Phase 2 可以为 offline inspection 提供纯数据查询或索引，但不能让 runtime
`SegmentStore` 接收 Observation State，也不能增加 `exclude_observed` 参数。

### 3.3 已统一的位置

1. `todo/implementation_roadmap.md` Phase 2 交付物已将
   “可排除已观察片段的查询接口”统一为：

   ```text
   可按 item 查询完整静态 catalog 的 persistent Segment Store
   Recommendation State 可基于 ObservationState 确定性投影未观察片段
   ```

2. Phase 2 验收标准已补充：persistent Store 与 in-memory Store 使用相同的
   coverage、ordering 和 missing-resource semantics。
3. `docs/00_component_interfaces.md`、`docs/09_offline_preprocessing.md` 和当前
   Controller 代码保持原有语义；实现时只增加 persistent Store 和 resolver。

### P2-00 Decision Record

```text
Decision ID: P2-00
Status: Confirmed
Decision:
删除路线图中 observation-aware Store 查询的歧义。SegmentStore 始终返回完整静态
catalog；未观察片段只由 Recommendation State/Controller 根据 ObservationState
投影。Phase 2 persistent Store 必须保持 P1-03 contract。
Rationale:
维持单一 observation 事实来源、Store/Agent policy 解耦，以及所有 Store
implementations 的可替换性。
Affected schemas/interfaces:
No schema change. SegmentStore, ItemSegmentCatalog, ObservationState,
RecommendationState projection semantics remain authoritative.
Affected docs/tests:
todo/implementation_roadmap.md；Phase 2 persistent-store and integration tests。
Confirmed by: User
Date: 2026-08-02
```

---

## 4. P2-01 — Source Data and Processed Record Contracts

Status: `Confirmed`

### 已确认边界

- 第一条 baseline 使用小型、versioned、可提交的 fixture。
- source contract 必须与具体推荐数据集解耦。
- raw source data 视为只读；preprocessing 不原地修改源文件。
- dataset-specific raw format 通过显式 adapter 进入通用 source contract；第一条
  baseline 只提供已经符合通用 contract 的 fixture。

### 已确认的 source records

```text
BehaviorEvent
  user_id
  item_id
  interaction_index
  occurred_at_ms: int | null
  interaction_type
  value: float | null
  metadata

SourceItem
  item_id
  metadata

SourceDatasetManifest
  schema_version
  source_dataset_id
  source_dataset_version
  behavior_events_ref
  items_ref
  segment_definitions_ref
  metadata
```

所有 ID 都是 opaque、case-sensitive、非空 string，不自动 trim 或类型转换。
`interaction_index` 是每个 user 从 0 开始连续递增的唯一行为顺序事实；source 和
processed behavior 都按 `(user_id, interaction_index)` canonical ordering。
`occurred_at_ms` 使用真实 Unix epoch milliseconds；同一 user 的 timestamps 必须
全部提供或全部为 `null`，提供时必须非负并随 interaction index 单调不减。缺少真实
timestamp 时保留 `null`，不得生成伪造 epoch time。

`interaction_type` 是非空 dataset-defined string，Phase 2 不固定全局 Enum。
`value` 为 finite float 或显式 `null`，其 dataset-specific 语义记录在 metadata/docs，
但 Phase 2 不把它解释为训练 label。自由 `metadata` 只保存非核心 JSON extension；
所有未知顶层字段禁止。

重复 item/action event 在不同 interaction index 上原样保留，不做隐式 dedup；重复
`(user_id, interaction_index)` 非法。每个 behavior item 必须存在于 item catalog，
但 item catalog 可以包含尚未出现在 behavior 中的 candidate-pool item。

`SourceItem` 只拥有 item identity 和 dataset-specific metadata；媒体布局不再
被强制成“每个 item 一个原视频”。`segment_definitions_ref` 指向 P2-04
定义的 canonical segment records，它们可以引用独立 clip files 或原媒体
ranges。某 item 没有 segment definition 表示它没有可用 segment，是合法的
source data；已声明的 segment resource 缺失或 checksum 失败不能降级为
“无媒体”。title、category、creator 等字段保存在 `metadata`。

`SourceDatasetManifest` 只保存逻辑 `ResourceRef`，不能声明 absolute storage roots。
受信任 config 在 P2-02 声明 root ID 与真实路径；checksum/data-version 公式由 P2-03
确认。

### 已确认的 processed behavior record

```text
SequenceInteraction
  item_id
  interaction_index
  occurred_at_ms: int | null
  interaction_type
  value: float | null
  metadata

UserBehaviorSequence
  user_id
  interactions: tuple[SequenceInteraction, ...]
  metadata
```

`UserBehaviorSequence` 不重复保存独立 `item_ids` list。Phase 3 需要 Phase 1
interface 时，确定性投影 `tuple(event.item_id for event in interactions)`；P2-01
不修改 `AgentRunRequest`、`UserMemory` 或 `InitialRanker` contract。

### Serialization and validation semantics

- 第一条 codec 使用 canonical UTF-8/LF JSON manifest 与 JSONL records；逻辑
  schemas 不绑定 JSONL，后续可以增加 Parquet codec。
- item records 按 `item_id`、behavior records 按 `(user_id, interaction_index)`、
  user-sequence records 按 `user_id` 排序。
- schemas 使用 strict/frozen validation、显式 `null` 和禁止 extra fields。
- 空 behavior、空 item catalog、重复 identities、不连续 index、unknown item、非法
  timestamp/value 和 unresolved declared resource
  都在发布 processed bundle 前失败；不跳过坏行或发布 partial output。
- source schema/parse/coverage failure 使用明确的 `DatasetValidationError`，并报告
  logical filename 和 JSONL line；资源解析失败继续使用 `ResourceResolutionError`。
- Phase 2 不做 train/validation/test split、negative sampling、candidate generation
  或 label construction；这些由 Phase 3 产生独立、versioned derived datasets。

### P2-01 的交付结果

- strict/frozen source and processed schemas；
- canonical JSON/JSONL ordering；
- fixture source manifest；
- invalid/missing/duplicate input semantics；
- Phase 3 可直接消费的 behavior-sequence contract。

### P2-01 Decision Record

```text
Decision ID: P2-01
Status: Confirmed
Decision:
1. 通用 source boundary 使用 BehaviorEvent、SourceItem 和 SourceDatasetManifest；
   processed behavior 使用 SequenceInteraction 和 UserBehaviorSequence。
2. interaction_index 是每个 user 从 0 连续递增的唯一顺序事实；timestamp 为真实
   Unix milliseconds 或 null，不能伪造，并在存在时随 index 单调不减。
3. 不自动去重；重复 item/action signal 保留，只禁止重复 event identity。
4. BehaviorEvent 引用的 item 必须存在。SourceItem 不预设单一媒体布局；
   SourceDatasetManifest 显式引用 P2-04 的 segment definitions。无 segment
   的 item 合法，但已声明 segment resource 缺失或校验失败则整体失败。
5. Manifest 只保存逻辑 refs，不声明绝对 storage root。
6. 第一条 codec 使用 canonical JSON/JSONL；strict validation 不执行隐式清洗、
   coercion、bad-row skipping 或 partial publish。
7. Phase 2 保留完整 behavior data，不做 split、negative sampling、candidate
   generation 或 label construction。
8. Phase 3 从 UserBehaviorSequence 确定性投影 item-ID tuple，不修改 Phase 1
   AgentRunRequest/UserMemory/InitialRanker contracts。
Rationale:
保持一个行为顺序事实，保留真实重复信号，并让 item metadata、segment media
layout、dataset-specific adapters、trusted path config 和后续 training policy 各自
拥有单一职责。
Alternatives considered:
timestamp 与 index 同时排序；静默去重；要求所有 history items 必须有媒体；让
manifest 声明绝对 roots；Phase 2 提前创建 split/negative samples；修改 runtime
Agent interfaces 传递完整 event objects。
Affected schemas/interfaces:
BehaviorEvent, SourceItem, SourceDatasetManifest, SequenceInteraction,
UserBehaviorSequence. No Phase 1 runtime interface change.
Affected docs/tests:
docs/09_offline_preprocessing.md；Phase 2 source/processed schema, ordering,
coverage, missing-media, invalid-input and serialization tests。
Resolved follow-up:
P2-02 确认 trusted roots/path safety；P2-03 确认 checksum/data version；P2-04
确认有媒体 item 的 duration/segment semantics。
Deferred follow-up:
真实 dataset adapter、dataset-specific interaction vocabulary/value semantics、
Phase 3 split/negative sampling/candidate generation 和 optional Parquet codec。
Confirmed by: User
Date: 2026-08-02
Amendment: P2-04 讨论期间经用户确认，将媒体布局从单一
SourceItem.media_ref/duration 移到 segment-definition contract；behavior 契约和
Phase 1 runtime interfaces 不变。
```

---

## 5. P2-02 — Storage Roots and Path Safety

Status: `Confirmed`

### 已确认边界

显式 external roots 被允许，但 root 内所有 keys 仍为规范化相对路径。
Phase 1 的 fixture/output project-relative path contract 保持不变；Phase 2 使用
独立的 preprocessing root registry 和 filesystem resolver，不能全局放宽 Phase 1
path validator。

### Typed root registry

第一条 baseline 只允许 typed preprocessing config 声明 roots。CLI 只接收 config
path，不增加 root overrides，也不执行 environment-variable interpolation。真实机器
可以使用 gitignored local config 覆盖 root declarations；可提交 fixture config 使用
项目相对 paths。

```yaml
storage:
  roots:
    source:
      path: data/raw/phase2-fixture
      access: read_only
    media:
      path: D:/datasets/pave/videos
      access: read_only
    processed:
      path: data/processed
      access: write_new
    features:
      path: artifacts/features
      access: write_new
```

Root registry 是可扩展的 `root_id → StorageRootConfig` mapping，不把所有 root IDs
硬编码成固定 Enum；第一条 baseline 使用 `source`、可选 `media`、`processed` 和
`features`。Root ID 使用 portable lowercase identifier，`ResourceRef.store` 必须
匹配一个已声明 root。

每个 root declaration 包含：

```text
path: project-relative or absolute directory
access: read_only | write_new
```

相对 root path 以 project root 为基准解析；绝对 path 只允许出现在这里。所有 root
directories 必须在 preprocessing 启动前存在且是 directory，程序不自动创建可能
拼错的外部 root。

### Access and overlap rules

- `read_only` root 只允许读取，不写入、移动、重命名或删除；
- `write_new` root 只允许在新 bundle/staging directory 内创建资源，不覆盖已有
  bundle；
- 所有 roots 在解析真实路径后必须唯一且两两不重叠：不能相等，也不能互相包含；
- writable root 不能位于 source/media root 内，反向包含同样拒绝；
- 如果 metadata/media 本就在同一目录树，只声明一个 read-only root 并使用不同
  logical keys；
- 默认不执行删除、覆盖或跨 root move；read-only source 可以被读取或复制到显式
  output，但绝不能被 move。

### Filesystem logical-key contract

Filesystem-backed Store 的 logical key 使用 `/` separator 的 canonical relative
POSIX form，例如 `items/item_001.mp4`。Validator 不自动修正 key，并拒绝：

- POSIX absolute、Windows drive/drive-relative、UNC/device path；
- `.`、`..`、空 path segment、反斜杠、NUL/control characters；
- Windows reserved name、component 尾部空格或点；
- 非 canonical Unicode normalization；
- 同一 manifest 中在 case-insensitive filesystem 上会碰撞的 keys。

这些限制只属于 filesystem resolver，不把所有未来 database/object-store
`ResourceRef.key` 全局解释成 filesystem path。

### Containment, symlink, and junction rules

受信任 config 可以显式把 root path 指向 symlink/junction；loader 先解析并记录最终
真实 root。Read key 使用 strict resolution，最终 path 必须仍在真实 root 内。
Root 下任何 child symlink/junction escape 都拒绝；writable root 内不能通过 child
link 写出 root。新 output 解析并校验最近的 existing parent，再在 resolver 已拥有的
new bundle directory 内创建。

该 resolver 防御错误或非可信 manifest/path，不宣称能抵抗拥有同一 filesystem
写权限、可在校验与打开之间并发替换目录的恶意进程；这是 local research pipeline
的明确 threat-model boundary。

### Portable manifest and local execution report

- canonical manifests、records、Agent State/Trace 和 `ResourceRef` 只记录 root ID、
  logical key、version/checksum，不记录机器 absolute path；
- local execution report 可以记录 root ID、configured path、resolved absolute path
  和 access mode；
- local report 不进入 data-version hash，不属于 portable golden artifact，默认
  gitignored；
- 换机器时重建相同 root-ID mapping 即可，不改 manifest identities。

### Failure and test semantics

- 非法或重叠 root declarations 在任何 output 创建前作为 `ConfigurationError`
  失败；
- unknown root、unsafe key、containment/link escape、missing/unreadable declared
  resource 作为 `ResourceResolutionError` 失败；
- tests 在 `tmp_path` 创建 project 外 roots，覆盖 project-relative/absolute roots、
  POSIX/Windows/UNC attacks、overlap、case collision、existing output 和 read-only
  preservation；
- symlink/junction tests 在平台支持时执行，纯 key grammar tests 在所有 OS 执行，
  Windows 与 Linux CI 都必须覆盖 resolver contract。

### P2-02 的交付结果

- typed root/path config；
- reusable safe path resolver；
- cross-platform path tests；
- external-root reproducibility and security rules。

### P2-02 Decision Record

```text
Decision ID: P2-02
Status: Confirmed
Decision:
1. Phase 2 roots 只由 typed preprocessing config 声明；CLI 不提供 root override，
   也不使用 environment interpolation。Root path 可以 project-relative 或 absolute，
   但 absolute path 只能出现在 root declaration。
2. Root registry 使用 portable root IDs 和 read_only/write_new access。所有 roots
   必须预先存在，解析后唯一且互不相等、互不包含。
3. Filesystem ResourceRef keys 使用 canonical relative POSIX grammar；拒绝跨平台
   anchors、dot/empty segments、backslash、reserved/ambiguous names 和 collisions。
4. 显式声明的 root 自身可以解析到 symlink/junction target；root 内 child link
   escape 和 writable-link escape 一律拒绝。
5. Canonical manifest/ResourceRef 不记录机器 absolute paths；local execution report
   可以记录 resolved roots，但不进入 data version、golden artifact 或 Git。
6. Source/media 保持 application-level read-only；outputs 只在新 write_new bundle
   中创建。默认不覆盖、不删除、不跨 root move。
7. Phase 1 project-relative fixture/output contract 不变；Phase 2 新增独立 resolver，
   不全局放宽已有 validator。
Rationale:
在允许大型 dataset/artifact 位于项目外的同时，保持 portable identities、明确读写
边界、跨平台 path grammar 和 containment，避免 manifest 获得自行授权物理路径的
能力，也避免 Phase 2 反向削弱 Phase 1 path safety。
Alternatives considered:
CLI/env root overrides；manifest 内 absolute paths；所有 roots 固定 Enum；允许
source/output overlap；自动创建 roots；静默 normalize keys；完全禁止显式 root
symlink/junction；默认覆盖或清理已有 output。
Affected schemas/interfaces:
Preprocessing StorageRootConfig/root registry, filesystem ResourceResolver and local
execution report. ResourceRef public shape and Phase 1 config interfaces stay unchanged.
Affected docs/tests:
docs/09_offline_preprocessing.md；configs/README.md；Phase 2 config/resolver/path
security tests；Linux/Windows CI。
Resolved follow-up:
P2-01 manifest refs 使用本 Gate 的 root IDs/keys；P2-03 确认 version/checksum；
P2-07 已确认 staging/publish/existing-bundle lifecycle。
Deferred follow-up:
Object-store/database resolvers、CLI root overrides、environment/secret injection、
remote URI/network policy 和 adversarial concurrent filesystem mutation hardening。
Confirmed by: User
Date: 2026-08-02
```

---

## 6. P2-03 — Manifest, Provenance, and Data Versioning

Status: `Confirmed`

### Data identity

`data_version` 表示确定性 preprocessing recipe 的 identity，不是某次 execution ID，
也不是输出 artifact checksum。版本输入使用现有 canonical UTF-8/LF compact JSON
serialization，并包含：

```text
DataIdentity
  identity_schema_version
  canonical validated SourceDatasetManifest
  source_artifacts sorted by ResourceRef identity
  semantic_preprocessing_config
  content-producing component descriptors in fixed role order
  output schema and codec versions
```

`source_artifacts` 使用下文同一 `ArtifactEntry` shape，展开 behavior、items、segment
definitions，以及所有非 null locator media/origin refs。每个 entry 明确记录
`ResourceRef`、artifact/schema kind、精确 `size_bytes` 和可选 `record_count`；entries
按 `(store, key, version, checksum)` canonical ordering，同一逻辑 ref 的冲突声明非法。
每个 source checksum 和 byte size 都在生成版本前完整验证。这样 `ResourceRef` 无需为
Phase 2 修改 public shape，同时 source/generated filesystem resources 都有同一份可执行
的 checksum/size inventory。

Config 中 exact `source.manifest_ref.checksum` 必须在 source ingestion 时验证，但
DataIdentity 保存的是验证后的 canonical `SourceDatasetManifest`，而不是 manifest 文件的
非语义 JSON 排版 bytes。因此仅改变 manifest 的缩进、空白或 object-key 顺序，在
canonical manifest 内容和所有 referenced source artifacts 不变时，不改变
`data_version`；canonical manifest 字段或任一 referenced artifact bytes/checksum 改变时
必须改变版本。

Semantic config 包含 logical input/output root IDs、behavior/segmentation/proxy rules、
schema/codec/compression settings，以及任何会影响输出的 seed。它不包含机器物理 root
paths、config path、staging/output execution directories、run ID、worker/logging
settings、timestamps、Git 或 platform metadata。

```text
identity_digest = sha256(canonical_json_bytes(DataIdentity, pretty=False)).hexdigest()
data_version = "p2-" + identity_digest
```

正式 identity 使用完整 64 lowercase hexadecimal digest；short prefix 只能用于 UI
显示，不能用于 directory、manifest 或 `ResourceRef.version`。输出 checksums 不进入
版本公式，避免循环依赖；如果同一 identity 产生不同 bytes，视为 component version
或确定性 contract 失败。

### Resource checksums

Phase 2 filesystem source/generated resources 必须使用：

```text
sha256:<64 lowercase hexadecimal characters>
```

Checksum 对精确文件 bytes streaming 计算，包括 canonical JSON/JSONL 末尾 LF。
Manifest 同时记录 `size_bytes`，JSONL 等 record artifact 可以记录
`record_count`；size/mtime 不能代替 checksum。公共 `ResourceRef.checksum` 仍保持
optional，避免破坏 Phase 1 和未来 non-filesystem Stores；Phase 2 filesystem
manifest/resolver 施加更严格的 required-checksum contract。

### Portable manifest schemas

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
  artifacts sorted by (store, key)

ReleaseManifest
  schema_version
  data_version
  identity
  root_bundle_manifest_refs sorted by (store, key)
  status: complete
```

每个 writable root 的 immutable version bundle 带一个 RootBundleManifest；它列出
bundle artifacts，不自包含自己的 checksum。ReleaseManifest 保存各 root manifest
的 `ResourceRef` 和 checksum，并允许从 embedded identity 重新计算 data_version。
ReleaseManifest 本身不自引用 checksum；外部 caller/runtime config 可以通过带
checksum 的 `ResourceRef` 引用它。

一个 loaded release 的授权 resource inventory 是
`DataIdentity.source_artifacts + all RootBundleManifest.artifacts`。前者登记只读 source
resources，后者登记本次 recipe 生成的 resources；P2-06 resolver 只解析这个闭包内的
refs，不能把相同 root 下未被 release 声明的文件当成合法输入。

Portable manifests 不保存 timestamp、Git、absolute roots 或 platform。单独的 typed
local `ExecutionReport` 记录 preprocessing run ID、started/completed times、configured
和 resolved roots、Git commit/dirty、Python/platform、component/runtime details，以及
`created`/`reused` outcome；它不进入 data-version hash、portable bundle 或 golden
artifacts，默认 gitignored。

### Multi-root publish protocol

跨 filesystem roots 不存在整体 atomic rename。第一条 baseline 使用：

```text
validate all source/config/roots
→ compute DataIdentity and data_version
→ create isolated staging directory inside each write_new root
→ write artifacts and RootBundleManifest
→ fully verify bytes/checksums
→ atomic rename each root staging directory to bundles/<data_version>
→ exclusively publish processed/releases/<data_version>.json last
```

只有最后的 ReleaseManifest 存在且完整验证通过，data version 才是 `complete`。
单 root rename 只在自己的 filesystem 内承诺 atomic；文档和实现不得宣称跨 root
transaction。Phase 2 final release 需要 exclusive publish helper，不能直接使用会
覆盖 existing target 的 `os.replace()` helper。

### Existing version, orphan, and partial-output semantics

- 已有 ReleaseManifest 且 identity、root manifests 和全部 resource checksums 完全
  一致：返回 `reused`，不改写 portable artifacts；
- 已有 release 但任何 schema/identity/ref/checksum 不一致：
  `ArtifactIntegrityError`，不覆盖；
- release 不存在但已有完整 immutable root bundle：完整验证一致后可复用，再生成
  缺失 bundles；不能复用散落的 partial files；
- staging 或半写目录永远不视为 published，不参与 Store discovery；
- 默认不删除 staging/orphan，也不提供 `force overwrite`；显式 maintenance/cleanup
  留到确有需要时设计；
- staging/write/rename/exclusive-publish I/O failure 使用
  `ArtifactPublicationError`，不能留下看似 complete 的 release。

Baseline publish/reuse 执行 full verification。大型 dataset 的 verified digest cache
可以以后增加，但 cache 只能优化重新计算，不能用 mtime/size 替代 canonical digest。

### Version fields remain distinct

- `source_dataset_version`：上游 dataset 声明版本；
- `data_version`：Phase 2 recipe identity；
- `schema_version`：record/manifest 结构版本；
- `ComponentDescriptor.version`：实现语义版本；
- `ResourceRef.checksum`：单个 resource 精确 bytes；
- Git commit/dirty：execution provenance，不是 data identity。

### P2-03 的交付结果

- canonical preprocessing manifest；
- deterministic data version；
- per-resource checksum contract；
- atomic publish/idempotency rules；
- provenance verification API。

### P2-03 Decision Record

```text
Decision ID: P2-03
Status: Confirmed
Decision:
1. data_version 使用 canonical DataIdentity 的完整 SHA-256：`p2-<64hex>`；不再
   截断为 16 hex。Identity 包含 validated source manifest、带 checksum/size 的
   source_artifacts、semantic config、content-producing component versions 和
   output schema/codec versions。
2. 机器 absolute roots、run/timestamps、Git/platform 和 operational settings 只进
   local ExecutionReport，不进入 identity 或 portable artifacts。
3. Phase 2 所有 filesystem resources 强制 `sha256:<64hex>` checksum，并记录精确
   byte size；source resources 通过 DataIdentity.source_artifacts 登记，generated
   resources 通过 RootBundleManifest.artifacts 登记；全局 ResourceRef.checksum shape
   仍保持 optional。
4. 每个 writable root 发布 RootBundleManifest；ReleaseManifest 保存完整 identity
   及 root-manifest refs/checksums，并作为唯一 complete marker。
5. 各 root staging/bundle 只承诺同 filesystem atomic rename；跨 root 不宣称事务。
   `processed/releases/<data_version>.json` 最后 exclusive publish。
6. 已有完整版本只有 full verification 一致后才能 reused；任何 mismatch 都以
   ArtifactIntegrityError 失败，绝不覆盖。完整 orphan bundle 可以验证复用，
   partial files/staging 不可复用或被 Store 发现。
7. 默认不自动删除 staging/orphan、不提供 force overwrite；publication I/O failure
   使用 ArtifactPublicationError，不能产生 complete release。
Rationale:
用 recipe identity 在生成前确定目标版本，以 checksums 验证实际 bytes，并以最后
release commit marker 解决 multi-root 不可原子提交的问题；同时把机器 execution
provenance 与 portable data identity 分离。
Alternatives considered:
短 16-hex version；timestamp/Git/absolute path 进入 hash；仅对输出 bytes 定版本；
checksum optional；单 manifest 无 commit marker；宣称跨磁盘 atomic rename；已有
版本直接覆盖；自动清理 partial output；mtime/size 代替 full digest。
Affected schemas/interfaces:
DataIdentity, ArtifactEntry, RootBundleManifest, ReleaseManifest, ExecutionReport,
ArtifactIntegrityError and ArtifactPublicationError. ResourceRef public shape remains.
Affected docs/tests:
docs/09_offline_preprocessing.md；docs/00_shared_domain_schemas.md；data/README.md；
artifacts/README.md；identity/checksum/manifest/reuse/crash-boundary tests。
Resolved follow-up:
P2-01 source refs 和 P2-02 root registry 构成 identity inputs；P2-06 Store/resolver
使用 release manifest；P2-07 实现 staging/exclusive publish lifecycle。
Deferred follow-up:
Large-dataset digest cache、explicit maintenance/cleanup、remote/object-store commit
protocol、signatures/trust policy 和 adversarial durability/fsync hardening。
Confirmed by: User
Date: 2026-08-02
Amendment: P2-06 讨论期间经用户确认，将原 `source_resources` ref list 补全为
ArtifactEntry-shaped `source_artifacts` inventory，使 P2-03 已要求的 source byte size
和 release-scoped resolver membership 可以由 schema 直接验证；data-version 原则和
Phase 1 interfaces 不变。
Amendment: P2-XG-01 经用户确认，exact source-manifest checksum 属于 ingestion
verification；DataIdentity 使用 canonical validated manifest semantics。仅 JSON 排版
变化不产生新 data version，canonical fields 或 referenced source bytes 变化必须产生。
```

---

## 7. P2-04 — Segment Definition Ingestion and Stable Segment Identity

Status: `Confirmed`

### 已确认边界

- Phase 2 不预设 10 秒或任何固定时长，也不自动补齐、截断或重切已定义的
  segments；
- canonical segment manifest 是片段身份、顺序和媒体定位的离线事实来源；
- 同一 contract 支持“一个媒体文件就是一个 segment”和“原媒体中的时间
  range 是一个 segment”两种 locator；
- 独立 clip 可选保存原媒体和原时间范围 provenance，不知道时显式为
  `null`，不伪造时间；
- 真实语义顺序由每个 item 的 `sequence_index` 保存，不依赖原视频时间是否
  可用；
- manual/fixed/scene/hybrid 等未来 producer 都只需生成同一 manifest。

### 已确认方案

- canonical record 必须显式包含 `segment_id`。Provider 保留可用的稳定 source
  ID；source 无 ID 时 adapter 在进入 canonical validation 前确定性生成
  `seg_<sequence_index:06d>`。同 item 内不允许重复 ID。
- `sequence_index` 是每个 item 从 0 开始连续的唯一语义顺序；canonical
  definitions 按 `(item_id, sequence_index)` 排列。
- 全局 contract 允许不同时长、空隙、重叠和同 item 混用 file/range locators。
  需要完整覆盖或禁止重叠时，由具体 producer 的语义 config 额外校验。
- 时间使用 integer milliseconds 和 half-open `[start_ms, end_ms)`。
  `FileLocator.duration_ms` 必须为正；`RangeLocator` 必须满足
  `0 <= start_ms < end_ms`。
- 独立 file 没有原视频坐标是完全合法的；它投影到 P1 时使用该文件自己的
  local interval `[0, duration_ms)`。只有真实存在原视频范围时才填
  `OriginRange`，否则整体为 `null`。
- 第一条 baseline 信任 canonical manifest 中的正时长和边界，resolver 校验
  resource、byte size 和 checksum；不强制 FFmpeg/ffprobe/decoder。未来启用
  `MediaProbe` 后发现不一致必须失败，不静默修改 manifest。只有在存在
  authoritative media duration 或启用 probe 时才声称已校验 physical range
  bounds。
- 无 segment item 合法并产生空 index/catalog。部分 locator/origin、非法时长或
  range、重复 ID/index、缺失 resource 或 checksum mismatch 都使整个
  preprocessing 失败，不发布 partial bundle。
- exact operational safety cap 在 P2-07 config/lifecycle Gate 确认；cap 只能拒绝
  异常输入，不能截断 segments，也不改变成功输出的 identity。

### 推荐 baseline

```text
SegmentDefinition
  item_id
  segment_id
  sequence_index
  locator: FileLocator | RangeLocator
  metadata

FileLocator
  kind: file
  media_ref
  duration_ms
  origin: OriginRange | null

RangeLocator
  kind: range
  media_ref
  start_ms
  end_ms

OriginRange
  original_media_ref
  start_ms
  end_ms
```

P2-04 只加载、校验和版本化 definitions，不复制或重新编码媒体。原视频整体
也可以用一个 `FileLocator` 表示为单 segment。切分方法未定时，不会因为
工程默认而改写客观片段边界。

### 与 Phase 1 的兼容投影

```text
FileLocator
  -> SegmentMeta.media_ref = file media_ref
  -> SegmentMeta.start_ms = 0
  -> SegmentMeta.end_ms = duration_ms

RangeLocator
  -> SegmentMeta.media_ref = source media_ref
  -> SegmentMeta.start_ms = locator.start_ms
  -> SegmentMeta.end_ms = locator.end_ms
```

`SegmentMeta.start_ms/end_ms` 始终相对它自己的 `media_ref`。因此独立
clip 的 `[0, duration_ms)` 是 clip-local 访问范围，不是伪造的原视频
起止时间。`sequence_index` 和可选 origin 保留在 canonical source
`SegmentDefinition`，并由 preprocessing 内部 frozen、per-item `ItemSegmentIndex`
组织；P1 catalog 继续按既有 `(start_ms, end_ms, segment_id)`
canonical ordering 投影，proxy refs 跟随同一顺序。P1 schemas、Store、Controller、
trace/replay 和已有 fixtures 都不修改。

`ItemSegmentIndex` 是 validated source definitions 的非持久化 typed intermediate，供
structural extractors、coverage validation 和 P1 projection 共用。它不作为第三份 segment
事实发布，也不进入 generated-artifact golden tree；原始 locator/origin provenance 由
checksummed canonical SegmentDefinition source artifact 持久化，runtime projection 由
`SegmentStoreIndex` 持久化，proxy 顺序信息由 `SegmentProxyRecord` 持久化。

### Version identity

Canonical segment manifest/checksum、媒体 checksums、schema/codec versions 以及
content-producing provider descriptor/config 进入 P2-03 `DataIdentity`。重切、换文件、
换顺序、改 ID 或改边界都生成新 `data_version`。只负责加载已经 canonical
manifest 的 operational reader settings 仅进入 `ExecutionReport`。

### P2-04 的交付结果

- strict/frozen `SegmentDefinition` 和 discriminated locator schemas；
- replaceable `SegmentDefinitionProvider` protocol 及 manifest-driven baseline；
- canonical per-item `ItemSegmentIndex`；
- stable composite `(item_id, segment_id)` identity；
- 不改 P1 runtime schemas 的 `SegmentMeta` projection；
- identity、ordering、locator、provenance、duration 和 invalid-resource tests。

### P2-04 Decision Record

```text
Decision ID: P2-04
Status: Confirmed
Decision:
1. Phase 2 不默认切分媒体；canonical SegmentDefinition manifest 是片段身份、
   顺序和媒体定位的离线事实来源。
2. SegmentDefinition 使用 FileLocator | RangeLocator discriminated union。独立
   file 的 OriginRange 可以为 null，不伪造原视频时间。
3. Canonical segment_id 显式存储并在 item 内唯一；sequence_index 从 0 连续。
   无 source ID 时 adapter 默认生成 seg_<sequence_index:06d>。
4. 时间使用 integer milliseconds 和 half-open intervals。FileLocator 映射为
   media-local [0, duration_ms)；RangeLocator 映射为声明的媒体内范围。
5. 全局 contract 允许变长、gap、overlap 和 mixed locator modes；具体 producer
   可根据自身策略施加更强约束。
6. 第一条 baseline 信任 canonical declared duration/bounds 并校验文件/checksum；
   MediaProbe 为未来可替换校验器，不静默修正声明。
7. 空 item segment set 合法；partial/invalid locator or origin、duplicate identity/order、
   missing/corrupt resource 导致整个 preprocessing 失败且不发布 partial bundle。
8. P2 ItemSegmentIndex 保留 sequence/provenance；按兼容规则投影到现有
   SegmentMeta/ItemSegmentCatalog，不修改 Phase 1 runtime schemas 或 Agent Loop。
9. Segment manifest/media checksums、schema/codec 和 content-producing provider descriptor/config
   进入 DataIdentity；P2-07 已确认只使用可配置的 item/event/segment count limits，
   不增加 duration cap。
Rationale:
将“如何切”与“如何稳定消费切分结果”分离，同时支持独立 clip、原视频
range 和未来可替换 producers，并保持 Phase 1 runtime contract 不变。
Alternatives considered:
强制 10 秒 fixed windows；强制所有 clip 提供原视频坐标；仅支持物理 clip 或
仅支持 source ranges；修改 P1 SegmentMeta 增加 sequence/provenance fields；静默修复媒体声明。
Affected schemas/interfaces:
New Phase 2 SegmentDefinition, FileLocator, RangeLocator, OriginRange,
ItemSegmentIndex and SegmentDefinitionProvider. No Phase 1 runtime schema/interface change.
Affected docs/tests:
docs/00_shared_domain_schemas.md, docs/09_offline_preprocessing.md,
todo/implementation_roadmap.md; Phase 2 identity/order/locator/projection/failure tests.
Resolved follow-up:
P2-05 的 proxy 不能要求原视频时间必定存在；P2-07 已确认 operational count limits
不限制 clip duration/bounds。
Deferred follow-up:
具体 manual/fixed/scene/hybrid producer、真实 media probing 与 frame-accurate timebase。
Confirmed by: User
Date: 2026-08-02
Amendment: P2-XG-01 经用户确认，ItemSegmentIndex 明确为 frozen per-item internal
intermediate，不单独发布；canonical SegmentDefinition、SegmentProxyRecord 和
SegmentStoreIndex 分别拥有 source provenance、proxy sequence 和 runtime projection。
```

---

## 8. P2-05 — Item Features and Segment Proxy Baseline

Status: `Confirmed`

### 已确认边界

- 不使用 ASR/audio；
- 不下载或运行 CLIP、SigLIP 或其他 learned model；
- 不把 Tensor/ndarray 写入公共 Domain schemas；
- 每个 SegmentMeta 必须有同 identity、同顺序的 SegmentProxyRef。

### 已确认 records

```text
ItemFeatureRecord
  schema_version
  item_id
  attributes: JsonObject
  segment_count
  payload_refs: tuple[FeaturePayloadRef, ...]
  metadata

SegmentProxyRecord
  schema_version
  item_id
  segment_id
  duration_ms
  sequence_index
  segment_count
  attributes: JsonObject
  payload_refs: tuple[FeaturePayloadRef, ...]
  metadata

FeaturePayloadRef
  name
  resource_ref: ResourceRef
  codec
  dtype: str | null
  shape: tuple[int, ...] | null
  metadata
```

`ItemFeatureRecord` 不包含 item-level `duration_ms`；P2-04 允许 gap、overlap、
mixed locators 和多个独立 clips，所以单一 item duration 不是必然存在的客观
事实。`SegmentProxyRecord.duration_ms` 始终由对应 locator 确定性得到。

`relative_sequence_position` 不持久化；需要时由 `sequence_index` 和
`segment_count` 确定性派生。原视频 `relative_start/center/end` 不是
必填 proxy fields，因为 P2-04 允许 `origin=null`。

`attributes` 只包含 semantic config 明确选择的 source fields；不自动复制整个
`SourceItem.metadata`。缺失的可选 attribute 不生成 key，不写入“unknown”或
空字符串；已存在值与 configured type 不符时以
`DatasetValidationError` 失败。`metadata` 只保存 provenance/debug extensions，
默认不作为模型特征。

### Extractor and coverage semantics

- `StructuralItemFeatureExtractor` 消费 validated SourceItems/ItemSegmentIndexes，并为
  每个 SourceItem 返回一个 ItemFeatureRecord；即使 `attributes={}`，仍有明确
  `segment_count`。
- `StructuralSegmentProxyExtractor` 为每个 segment 返回一个同 identity
  SegmentProxyRecord。无 segment item 产生空 proxy tuple。
- Extractors 是无 I/O 的 typed transformations，不解析 `media_ref`、不解码媒体、不写
  artifacts；publisher/codec 单独负责 canonical serialization、checksum 和 publication。
- 输出 identity/coverage/order 必须精确匹配输入。Extractor 执行或 contract failure
  终止整个 preprocessing，不记录“某 item 失败但继续”，也不发布 partial
  feature bundle。
- P2 baseline 为每个 item 产生 non-null `ItemFeatureRef.feature_ref`。P1 仍允许
  `feature_ref=None` 以兼容其他 Store/config，不修改公共 schema。
- 每个投影后 SegmentMeta 必须有同 identity 的 SegmentProxyRef；最终 proxy refs
  按 P1 ItemSegmentCatalog 的 canonical segment order 排列。

### Artifact and extension semantics

第一条 baseline 对每个 ItemFeatureRecord/SegmentProxyRecord 写一个独立
canonical JSON resource。因此公共 `ResourceRef` 精确指向一个 typed record，无需
JSONL row selector 或 offset index。Opaque item/segment IDs 不直接作为 filesystem
keys；P2-06 已确认 canonical identity JSON 的完整 SHA-256 key、两位 prefix fan-out
和 persistent indexes。

第一条 baseline 的 `payload_refs=()`。未来 dense/text/media-derived payload 保存在
`.npy`、safetensors、Parquet 或其他带版本 codec 中，通过
`FeaturePayloadRef` 引用，不把 Tensor/ndarray 写入 JSON Domain records。真实数据
需要 sharded/indexed codec 时可以增加新 artifact codec/version，不改 P1
`ItemFeatureRef`、`SegmentProxyRef`、Controller 或 State。

Attribute selection、extractor descriptors/config、record schemas 和 artifact codec 进入
P2-03 `DataIdentity`。Workers、logging 等 operational settings 只进入
`ExecutionReport`。

### P2-05 的交付结果

- typed item/proxy artifact records；
- pure/replaceable structural extractor protocols；
- complete proxy coverage；
- per-record canonical JSON artifacts and refs；
- no-network、CPU-only、no-media-decode deterministic fixture baseline。

### P2-05 Decision Record

```text
Decision ID: P2-05
Status: Confirmed
Decision:
1. 第一条 item/proxy baseline 是 no-network、CPU-only 且不解码媒体的结构化
   pipeline；不生成 ASR/audio、visual statistics 或 learned embeddings。
2. ItemFeatureRecord 保存 schema_version、item_id、显式选择的 attributes、
   segment_count、payload_refs 和 metadata；不伪造单一 item duration。
3. SegmentProxyRecord 保存 schema_version、(item_id, segment_id)、duration_ms、
   sequence_index、segment_count、attributes、payload_refs 和 metadata。不重复保存
   可派生 relative position，不要求原视频时间存在。
4. Source metadata 只经 semantic config 显式映射到 attributes；缺失 optional
   values 不伪造 placeholder，configured type mismatch 失败。
5. 每个 SourceItem 产生一个 ItemFeatureRecord，每个 segment 必须有一个同
   identity proxy record/ref；空 segment set 产生空 proxies。
6. Extractors 只执行 typed transformations，publisher 拥有 I/O。非法输出或 execution
   failure 使整个 preprocessing fail-fast，不发布 partial feature bundle。
7. 第一条 codec 为 per-record canonical JSON；opaque IDs 不直接形成 path。P2-06
   已确认完整 identity SHA-256 key、两位 fan-out prefix 和 typed indexes。
8. 第一条 payload_refs 为空；未来外部 dense/sharded artifacts 通过带 codec、
   dtype、shape 的 FeaturePayloadRef 接入，不改 P1 public refs。
9. Attribute mapping、content-producing extractor descriptors/config、record schemas 和 codec
   进入 DataIdentity。P1 runtime components 不增加 offline extractor roles。
Rationale:
先证明可重复、可校验的 feature data plane，同时避免在未确定数据集、媒体
布局和模型时固化视觉/音频依赖。
Alternatives considered:
第一版解码媒体并生成 motion/keyframe statistics；自动把所有 source metadata 当
特征；持久化重复 relative fields；单一 JSONL 加 row-offset index；容忍 partial extraction。
Affected schemas/interfaces:
New Phase 2 ItemFeatureRecord, SegmentProxyRecord, FeaturePayloadRef,
ItemFeatureExtractor and SegmentProxyExtractor. No Phase 1 runtime schema/interface change.
Affected docs/tests:
docs/09_offline_preprocessing.md, artifacts/README.md, configs/README.md;
Phase 2 schema/mapping/coverage/determinism/failure tests.
Resolved follow-up:
P2-06 确认 hashed keys、persistent identity index 和 typed resolution；P2-07 已确认
精确 config/API、mapping 和 codec selectors。
Deferred follow-up:
真实 visual/audio/text proxy extractors、dense codec/sharding 以及最终 feature set/model。
Confirmed by: User
Date: 2026-08-02
```

---

## 9. P2-06 — Persistent Stores and Resource Resolution

Status: `Confirmed`

### 当前已有契约

Phase 1 已有：

- `ItemFeatureStore.load_refs(item_ids)`；
- `SegmentStore.load_catalog(item_ids)`；
- `ResourceRef(store, key, version, checksum)`；
- store coverage、ordering 和 missing-resource semantics；
- `ResourceResolutionError` exception type。

目前缺少真实 persistent Store 和解析 `ResourceRef` 内容的 resolver contract。

### Release pinning and construction

每次 runtime/Agent run 接受一个精确 `ReleaseManifest` `ResourceRef`：它包含 root ID、
`releases/<full-data-version>.json` logical key、完整 `p2-<64hex>` version 和
`sha256:<64hex>` checksum。不支持 `latest` alias、mtime/directory guessing、扫描 orphan
bundle 或隐式选择“当前版本”。

```text
exact release ref
  + trusted validated root registry
  -> ReleaseLoader(root_registry).load(exact_release_ref)
  -> immutable LoadedRelease
       |-- FilesystemItemFeatureStore
       |-- FilesystemSegmentStore
       `-- FilesystemResourceResolver
```

`ReleaseLoader` 每个 runtime construction 只加载一次。它验证 release checksum、
`status=complete`、embedded DataIdentity/data_version、root-manifest refs/checksums、
required indexes、resource graph 和 source-item coverage，并返回共享的 immutable
`LoadedRelease`。两个 Stores 和 resolver 必须使用同一个 object；同一次 Agent run
不能让 item features 来自 release A，而 segment catalogs/proxies 来自 release B。
不同 Agent runs 仍可分别固定不同 releases。

这个限制只针对 processed release snapshot，不禁止 P2-04 的 file/range locator 混合，
也不要求 raw media 的 upstream `ResourceRef.version` 等于生成 artifacts 的
`data_version`。

P4-01 amendment（2026-08-05）：P2 baseline 和既有实现/测试继续保持上述单一
`LoadedRelease` 规则。Phase 4 可显式选择一个新的 `MediaSubsetSegmentStore`，其输入是
一个 exact base `LoadedRelease` 加一个只含 media/segments/proxies、并精确绑定该 release
和 item-catalog identity 的 immutable derived overlay。它不是 processed segment release B，
不得包含/替换 behavior、items 或 labels，也不得复用 P2 resolver 绕过 release inventory。
未覆盖但属于 base catalog 的 item 返回 empty catalog；已声明资源缺失/损坏、unknown item、
cross-release/catalog mismatch 或 segment/proxy coverage drift 均 fail closed。旧 selector、
Filesystem Stores、resolver、goldens 和 P1—P3 runtime 不自动启用 overlay、语义不变。

Exact `release_ref` 是唯一的 portable release-identity handoff，但不是自包含的物理
locator。Root ID 到本机 path 的映射只能由受信任 config 提供，不能进入 ref 或 portable
manifest。Preprocessing source ingestion 在 release 尚不存在时使用同一 path-safety core
和 validated root registry 校验 exact source refs；runtime resolver 额外强制 loaded-release
inventory membership。二者不能混成一个默认放行的 resolver mode。

### Deterministic keys and persistent indexes

Opaque IDs 先做 canonical identity JSON，再使用完整 SHA-256，不直接进入路径：

```text
item_hash = sha256(canonical_json_bytes({"item_id": item_id}, pretty=False)).hexdigest()
segment_hash = sha256(
  canonical_json_bytes({"item_id": item_id, "segment_id": segment_id}, pretty=False)
).hexdigest()

features root:
  bundles/<data_version>/item-features/<item_hash[0:2]>/<item_hash>.json
  bundles/<data_version>/segment-proxies/<segment_hash[0:2]>/<segment_hash>.json
```

完整 64-hex digest 是 identity key；两位 prefix 只做 directory fan-out，不参与
identity。Processed root 发布两个 typed indexes：

```text
ItemFeatureStoreIndex
  schema_version
  data_version
  entries: tuple[ItemFeatureRef, ...]

SegmentStoreIndex
  schema_version
  data_version
  catalogs: tuple[ItemSegmentCatalog, ...]
```

两个 indexes 都按 `item_id` 排序，并且必须精确覆盖同一份 SourceItem catalog。
`SegmentStoreIndex` 直接复用 P1 `ItemSegmentCatalog` 的 canonical segment/proxy coverage
与 ordering；空 segment item 保存显式空 catalog。Index refs 和 index 内引用的每个
resource 都必须属于 loaded release 的 source/generated resource inventory；indexes
自身也是带 schema/checksum/size 的 RootBundleManifest artifacts。

Store 构造时将 index 变成 immutable `item_id -> entry/catalog` mapping。之后
`load_refs()`/`load_catalog()` 只进行内存 lookup，按 caller 的 item 请求顺序返回，
不重复读取 manifest，也不读取 feature/proxy/media payload。

### Resolver and typed loaders

第一条 baseline 分开文件安全解析与 Domain decoding：

```python
class ResourceResolver(Protocol):
    def read_verified_bytes(self, ref: ResourceRef) -> bytes: ...
    def resolve_verified_path(self, ref: ResourceRef) -> Path: ...
```

`FilesystemResourceResolver` 使用 P2-02 trusted root registry；
`ResourceRef.store` 就是 registry root ID（例如 `source`、`media`、`processed`、
`features`），不是 Store implementation class 名，也不能由 manifest 重定义。Resolver
验证 release membership、canonical/contained key、required version/checksum、存在性、
readability、`size_bytes` 和完整 SHA-256。`Path` 只用于本机 dependency boundary，永不
序列化；第一条 baseline 不增加未校验 stream API。

`ItemFeatureRecordLoader`、`SegmentProxyRecordLoader` 等 typed loader 消费 verified
bytes，负责 canonical JSON/schema 和 expected item/segment identity。这样 resolver
不需要知道每一种 feature schema，Store 也不承担媒体 I/O。

### Verification timing and failures

- eager construction：验证 release/root manifests、DataIdentity/data_version、两个
  indexes、resource declarations、coverage 和 index-level ordering；
- lazy resolution：实际消费某个 feature/proxy/media 时重新执行 containment、size、
  full checksum 和 typed identity validation；baseline 不依赖 mtime，也不持久化 digest
  cache；
- unknown query item 使用 P1 `ContractError`；已知无 segments 返回空 catalog；
- `ItemFeatureRef(feature_ref=None)` 继续是合法 P1 optional 语义，虽然 P2-05 baseline
  正常会为每个 item 生成 non-null ref；
- ref 不属于 release、unknown root、unsafe key、missing/unreadable file、required
  version/checksum/size 不匹配使用 `ResourceResolutionError`；
- complete release 的 manifest/index/schema/coverage 不一致，或 checksum 正确但 typed
  record identity 与 index 不一致，使用 `ArtifactIntegrityError`；
- corruption 永远不能降级成 `None`、空 catalog 或跳过单个 record。

### Version identities

- `ComponentDescriptor.version` 是实现语义，例如
  `filesystem-item-feature-store-v1`；
- Agent run `data_version` 是本次固定的 Phase 2 release；
- `ResourceRef.version` 是该 resource 自己的数据/source version。Generated
  features/proxies/indexes 通常使用当前 `data_version`，raw media 可以保留 upstream
  version，因此不要求所有 refs 的 version 字符串完全相同；
- persistent Stores 替换现有 Item Feature Store/Segment Store component roles；resolver
  是它们共享的基础设施 dependency，不新增 Agent Loop role，也不修改 Controller。

### P2-06 的交付结果

- persistent Store implementations；
- immutable release loader、typed persistent indexes；
- ResourceResolver protocol/implementation 和 typed record loaders；
- corruption, traversal, coverage and ordering tests；
- in-memory/persistent contract parity tests。

### P2-06 Decision Record

```text
Decision ID: P2-06
Status: Confirmed
Decision:
1. 每次 runtime construction 由带完整 version/checksum 的 exact ReleaseManifest ref
   固定一个 release；ReleaseLoader 只加载一次，两个 persistent Stores 与 resolver
   共享同一 immutable LoadedRelease，禁止同一次 Agent run 混用 processed releases。
2. Item/segment opaque identity 使用 canonical JSON 的完整 SHA-256 filesystem key，
   两位 prefix 只用于 fan-out；不把原始 ID 直接写入路径。
3. Processed root 保存按 item_id 排序、覆盖同一 SourceItem catalog 的
   ItemFeatureStoreIndex 与 SegmentStoreIndex；后者复用 P1 catalog/proxy ordering。
4. ResourceRef.store 等于 trusted root ID。FilesystemResourceResolver 只解析 loaded
   release inventory 内的 refs，并提供 verified bytes/path；typed loaders 单独验证
   schema 和 expected record identity，不提供 unverified stream baseline。
5. Release/manifests/indexes/coverage 在构造时 eager 验证；payload 在实际解析时验证
   containment、size、完整 SHA-256 和 typed identity。Store query 本身只查内存 index。
6. Unknown query item 保持 P1 ContractError；已知空 segment catalog 和 optional
   feature_ref=None 保持合法；资源定位/bytes 问题用 ResourceResolutionError，已发布
   release 的结构/identity 不一致用 ArtifactIntegrityError，不能静默降级。
7. ComponentDescriptor.version、run data_version 与每个 ResourceRef.version 保持不同
   语义；只禁止同一 run 混用 processed release snapshot，不要求 upstream raw refs
   使用当前 data_version。
8. P2-03 DataIdentity source inventory 使用 ArtifactEntry-shaped source_artifacts；它与
   RootBundleManifest generated artifacts 合并成 release-scoped resolver registry。
Rationale:
将发布发现、文件安全、typed decoding 和 Store lookup 分层；完整验证集中在构造与
实际资源解析边界，Agent Loop 热路径只做内存查询，并保持 Phase 1 interfaces 不变。
Alternatives considered:
latest/目录扫描；每次 query 重载 manifests；Store 直接 decode 所有 payload；原始 ID
作路径；截断 hash；resolver 返回未校验 stream；启动时读取全部媒体；把 corruption
当 optional missing；允许 item/segment Stores 各选版本。
Affected schemas/interfaces:
New LoadedRelease, ReleaseLoader, ItemFeatureStoreIndex, SegmentStoreIndex,
ResourceResolver, FilesystemResourceResolver and typed record loaders. Existing
ResourceRef, ItemFeatureStore, SegmentStore and Agent Loop interfaces remain.
Affected docs/tests:
docs/09_offline_preprocessing.md, artifacts/README.md, configs/README.md,
data/README.md; release pinning/hash-key/index/membership/lazy-verification/error/parity tests.
Resolved follow-up:
P2-03 source checksum/size inventory completed；P2-05 per-record hashed layout fixed；
P2-07 已确认 exact config/API construction and publication lifecycle。
Deferred follow-up:
Remote/object-store/database resolver、SQLite index、persistent digest cache、auto reload、
unverified streaming 和 large-scale sharded feature codec。
Confirmed by: User
Date: 2026-08-02
Amendment: P2-XG-01 经用户确认，ReleaseLoader 必须由 trusted validated root registry
构造；release_ref 只承担 portable identity handoff。Pre-release source resolution 与
runtime release-scoped resolution 共享 path-safety core，但后者额外要求 release
inventory membership。
```

---

## 10. P2-07 — Preprocessing API, Config, CLI, and Lifecycle

Status: `Confirmed`

### 已确认子项：Operational count limits

第一条 baseline 使用四个由每份 preprocessing config 显式填写的正整数安全上限：

```text
max_items
max_behavior_events
max_total_segments
max_segments_per_item
```

这些字段没有写死的全局数据规模默认值。可提交 fixture config 使用适合小型 fixture
的值；以后真实数据 config 可以按实际规模调大，无需修改代码。它们只负责在输入规模
明显超出本次执行预期时 fail-fast，不能截断、抽样、跳过或只处理前 N 条记录；超过
任一上限时使用 `DatasetValidationError` 终止，并且不创建 staging 或发布 partial
artifacts。

这些 limits 不限制 clip duration，不修改 `[start_ms, end_ms)`，不切分、合并或重排
segments，也不要求原视频坐标存在。它们属于只决定“允许执行还是拒绝执行”的
operational safety config；只要两组 limits 都允许同一输入完整执行，调整 limits 不会
改变输出 bytes，因此不进入 `DataIdentity` 或 `data_version`。

Confirmed by: User
Date: 2026-08-03

### Independent typed preprocessing config

Phase 2 使用独立的 `Phase2PreprocessingConfig` 和
`load_preprocessing_config()`，不扩展或放宽现有 `Phase1Config/load_config()`。
配置放在 `configs/preprocessing/`，第一条 baseline 使用 `base.yaml` 和
`fixture.yaml`。需要绑定真实机器 absolute roots 时，可以用明确 gitignored 的 local
child config 覆盖 root declarations。

“local child config 应被 gitignored”是 repository/operational policy，不是 runtime
schema validation：loader 不调用 Git，也不要求 synthetic project 是 Git repository。
Runtime 仍严格验证 config chain 留在 project root 内，以及 root 类型、存在性、访问
模式、唯一性和 non-overlap。可提交 fixture config 只使用 portable project-relative
roots；用户负责确保包含机器 absolute paths 的 local child 不进入版本控制。

Preprocessing config 复用 P1 已验证的 deterministic loading contract：只允许一个
相对声明文件的 `extends`，mapping 递归合并，scalar/list 整体替换，按 resolved path
检测循环，整个 chain 留在同一 project root；PyYAML 只 parse，strict/frozen Pydantic
models 负责 validation/extra-forbid。继续禁止多父合并、CLI `key=value` overrides、
environment interpolation、动态 class import、plugin discovery 和 secret injection。

第一条完整 shape 为：

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

`source.manifest_ref` 必须是带完整 checksum 的 exact filesystem ref。Output root IDs
必须引用不同的 `write_new` roots；所有 source/media refs 必须引用已声明的
`read_only` root。Config 显式声明 codecs，不能从扩展名猜测 JSONL/JSON/未来 Parquet。
第一版所有 codec selector 都是上述 single allowed literal，compression 固定 `none`；
未来增加 codec 使用新 selector/schema version。

### Attribute mapping contract

```text
AttributeMapping
  source_key
  output_key
  value_type:
    string | integer | number | boolean |
    string_list | integer_list | number_list
  required
```

Item rules 读取 `SourceItem.metadata` 顶层 key，segment rules 读取对应
`SegmentDefinition.metadata` 顶层 key；第一版不实现 nested JSONPath、coercion、默认值
或 arbitrary JSON object feature。Rules 必须按 `output_key` canonical ordering，且
source/output keys 各自唯一。Missing/null optional value 省略 output key；missing/null
required value 或实际类型不匹配使用 `DatasetValidationError`。Boolean 不视为 integer，
number/list elements 必须 finite。

Component selectors/config、attribute mappings、logical output root IDs、codec/compression
和 output schema versions 进入 `DataIdentity`。Physical roots、config path、count limits、
execution ID/report、timestamps、Git/platform 和其他 operational fields 不进入。

### Components and fixed pipeline

第一条 baseline 只有四个 content-producing、可替换的 offline roles，并按以下固定顺序
保存 descriptors：

```text
behavior_processor
segment_definition_provider
item_feature_extractor
segment_proxy_extractor
```

显式 constructor mapping 构造一个 frozen `PreprocessingComponents`，不使用 DI
framework、reflection 或 service locator。Resolver、codec、publisher 和 release loader
是 pipeline infrastructure，不新增 Agent component role；codec/schema versions 已单独
进入 identity，publisher 的 staging mechanics 是 operational behavior。

固定执行流程为：

```text
load/merge/validate config
→ validate root graph
→ allocate local execution identity/directory
→ resolve and validate source manifest/records once
→ enforce count limits without truncation
→ build canonical segment indexes and source_artifacts inventory
→ collect component descriptors and compute DataIdentity/data_version
→ verify-and-reuse a complete existing release when present
→ otherwise build behavior sequences/item features/segment proxies/store indexes
→ validate complete identity/coverage/order
→ serialize and publish through the filesystem publisher
→ write terminal local ExecutionReport
→ return PreprocessingResult
```

第一条实现单进程、同步、固定步骤，不引入 worker pool、async、generic DAG scheduler
或 resume checkpoint。Validated source records/indexes 只加载一次并作为 immutable typed
objects 传给 pure components；components 不重复打开 source files，也不自行写 artifacts。

### Python API and result

统一高层入口为：

```python
result = preprocess_from_config("configs/preprocessing/fixture.yaml")
```

它完成 config/source/root validation、execution identity、显式 component bootstrap、
identity/version、reuse 或 publication、ExecutionReport 和最终结果。CLI 只能调用这一
入口，不能复制 pipeline。内部保留接收 typed request/components 的 coordinator 以便
unit tests 和 future composition，但它不是第二条行为路径。

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

API 只在完整成功或 verified reuse 后返回，不使用 `succeeded=False` 或 partial result。
`release_ref` 是 P2-06 可直接消费的 exact release ref，且其 version 必须等于返回的
data_version。`Path` 只属于本地 return object，不进入 portable serialization。Declared
failure 抛现有 typed exception；不返回大批 records 或机器 artifact paths。

`artifact_count` 固定为所有 `RootBundleManifest.artifacts` entries 的总数。它包含本次
release 的 generated behavior、feature/proxy 和 Store-index artifacts，不包含
`DataIdentity.source_artifacts`、RootBundleManifest 自身或最终 ReleaseManifest；因此同一
release 的 `created` 和 `reused` result 返回相同计数。

### Publication, reuse, and concurrency

P2-03 的 publish contract 在本 Gate 固定为以下 mechanics：

```text
root-local staging/<data_version>/<execution_id>/；Windows physical staging 可将
`(root_id, data_version, execution_id)` 映射为一个 opaque 128-bit SHA-256 prefix token，以避免 legacy
path-length failure；该 operational 映射不改变 published keys/data identity
→ canonical artifacts and root manifest
→ full verification
→ no-overwrite atomic rename to bundles/<data_version>/
→ exclusive publish processed/releases/<data_version>.json last
```

- final ReleaseManifest 由本次 invocation 成功 exclusive-create：`outcome=created`；
- invocation 发现或并发输给一个已存在且完整验证一致的 release：`outcome=reused`；
- release mismatch 使用 `ArtifactIntegrityError`，绝不覆盖；
- 完整 orphan bundles 可以 full verification 后复用；partial staging 永远不复用；
- 两个并发 invocation 不需要 lock service；rename/exclusive-create loser 验证 winner
  bytes，一致则 reused，不一致则失败；
- 不实现 public dry-run、resume、`--force`、`--no-reuse`、自动 cleanup 或 deletion；
- interruption/failure 不发布 complete marker，已创建 staging 按 P2-03 保留并保持不可
  discovery；后续运行使用新 execution ID，不把旧 staging 当 checkpoint。

### Local ExecutionReport

Config/root graph 验证成功后，在 project-local、gitignored
`runs/preprocessing/<execution_id>/` 独占创建 execution directory。自动 execution ID
沿用 `YYYYMMDDTHHMMSSZ-<8 lowercase hex>` 形状；CLI 不允许覆盖它。Config/root
validation failure 不创建目录；之后的 declared failure best-effort 写 terminal failed
report，并且 report failure 不能遮蔽原始异常。

```text
ExecutionReport
  schema_version
  execution_id
  status: succeeded | failed
  outcome: created | reused | null
  data_version: str | null
  release_ref: ResourceRef | null
  started_at_utc
  completed_at_utc
  config_path
  configured_and_resolved_roots
  component_descriptors
  git_commit / git_dirty
  Python/PAVE-Rec/Pydantic/PyYAML/platform versions
  item/behavior/segment/artifact counts when known
  staging_locations
  error_code/message: safe values | null
```

Report 是 local operational record：允许本机 absolute paths/timestamps，但不进入
DataIdentity、portable release 或 golden comparison。它不保存 secret、stack trace、
整份 environment/pip freeze，也不记录没有实际使用的 FFmpeg/model version。Git 和
tool metadata best-effort；无法获得时显式 null。

成功 release 发布后若 terminal success report 无法写入，API 使用
`ArtifactPublicationError` 失败并明确 release 已经 complete；重试会 full-verify/reuse
该 release 并重新产生 execution report，不能回滚或覆盖已发布版本。

### CLI and failure codes

第一条唯一 CLI 为：

```bash
python -m pave_rec.cli.preprocess --config configs/preprocessing/fixture.yaml
```

只提供 required `--config`；不提供 execution ID、roots、components、features、dry-run、
resume、reuse 或 force flags，也不增加 console script。成功 stdout 固定报告
`execution_id`、`outcome`、`data_version`、exact release ref 和 execution-report path。
Declared failure 只向 stderr 输出简洁诊断：

- `0`：created 或 verified reused；
- `2`：argparse、`ConfigurationError` 或 `DatasetValidationError`；
- `1`：`ResourceResolutionError`、`ArtifactIntegrityError`、
  `ArtifactPublicationError`、component/其他 declared PaveRec failure；
- `130`：`KeyboardInterrupt`。

Unexpected programming exception 不被广泛吞掉，保留 Python traceback，但 traceback
不能写入 portable artifacts 或 ExecutionReport。

### Runtime handoff and Phase 1 compatibility

`PreprocessingResult.release_ref` 是本 Gate 与 P2-06 runtime data plane 的唯一 portable
release-identity handoff。Caller 还必须向 ReleaseLoader 提供受信任的 validated root
registry；ref 本身不携带 physical paths。P2-08 使用同一 synthetic preprocessing config
解析出的 registry 和 exact ref 构造 LoadedRelease/resolver/persistent Stores，并与其余
Mock components 做 Agent smoke run。P2-07 不给 `Phase1Config` 增加 filesystem selector
或 external roots，不修改 `run_from_config()`、现有 Mock bootstrap、golden artifacts、
Controller、State、Trace 或 Agent Loop。真实 runtime experiment config 何时选择某个
release，留给开始消费真实 Store 的后续阶段。

### P2-07 的交付结果

- strict preprocessing config；
- explicit offline component bootstrap、shared Library API and thin CLI；
- deterministic lifecycle and exit codes；
- verified reuse、no-overwrite/partial-output/concurrency rules；
- local success/failure ExecutionReport；
- reproducible fixture invocation。

### P2-07 Decision Record

```text
Decision ID: P2-07
Status: Confirmed
Decision:
1. Phase 2 使用独立 Phase2PreprocessingConfig/load_preprocessing_config 和
   configs/preprocessing/{base,fixture}.yaml；复用 P1 single-parent merge/strict
   validation 规则，但不修改或放宽 Phase1Config/load_config。
2. Config 明确保存 exact source manifest ref、typed root registry、logical output root
   IDs、source/output codec selectors、attribute mappings、四个 component selectors
   和四个 required positive count limits；不通过扩展名猜 codec。
3. AttributeMapping 只读取 item/segment metadata 顶层 key，显式声明 output key、
   primitive/homogeneous-list type 和 required；不做 JSONPath、coercion 或默认值。
4. max_items、max_behavior_events、max_total_segments、max_segments_per_item 由每份
   config 自行设置。超限 fail-fast 且不截断；它们不限制 duration/bounds，也不进入
   data identity。
5. Content-producing roles 固定为 behavior_processor、segment_definition_provider、
   item_feature_extractor、segment_proxy_extractor；显式 bootstrap、固定 descriptor
   order、单进程同步 pipeline。Resolver/codec/publisher 是 infrastructure。
6. 高层 preprocess_from_config(path) 是 Python/CLI 共享入口；成功返回只包含
   execution/outcome/version/exact release ref/report path/counts 的
   PreprocessingResult，失败抛 typed exception，不返回 partial result。
7. Lifecycle 在 config/root/source/count validation 和 identity computation 后才创建
   root-local staging；write/full-verify/root-local rename 后最后 exclusive publish
   ReleaseManifest。Complete existing release 默认 full-verify/reuse。
8. 第一版不提供 dry-run、resume、force、no-reuse、automatic cleanup/deletion 或
   checkpoint recovery；partial staging 不可 discovery/reuse。并发依赖 exclusive
   filesystem operations，loser 验证 winner 后 reused 或 integrity-fail。
9. Config/root 验证后使用 runs/preprocessing/<execution_id>/ 保存 local typed
   ExecutionReport；它记录 created/reused/failed、roots、Git/tool metadata、counts、
   staging 和安全错误，不进入 data version/portable release/golden artifacts。
10. CLI 只有 python -m pave_rec.cli.preprocess --config <path>；exit 0=created/reused，
    2=CLI/config/dataset validation，1=resource/integrity/publication/component declared
    failure，130=interrupt；unexpected programming errors 保留 traceback。
11. PreprocessingResult.release_ref 是 P2-06 的 exact handoff。P2-07 不修改 Phase 1
    config/runner/bootstrap/golden/Controller/Agent Loop；P2-08 programmatically 完成
    persistent Store Agent smoke integration。
Rationale:
把 semantic recipe、机器 storage、pure transformations、safe publication 和 local
execution provenance 分层，同时让 Python 与 CLI 只有一条 lifecycle，并保持第一版
同步、无网络、无 destructive recovery，控制实现复杂度。
Alternatives considered:
复用并扩张 Phase1Config；从扩展名猜 codec；CLI roots/feature overrides；动态 component
imports；unlimited/截断式输入；worker DAG；CLI 自己组装 pipeline；dry-run/resume/force；
覆盖或清理 partial output；latest release；把 absolute roots/timestamps/tool versions
写入 data identity；为 P2 修改现有 run_from_config。
Affected schemas/interfaces:
Phase2PreprocessingConfig, AttributeMapping, PreprocessingComponents,
PreprocessingResult, ExecutionReport, preprocessing bootstrap/coordinator/publisher and
CLI. Phase 1 public config/runtime interfaces remain unchanged.
Affected docs/tests:
docs/09_offline_preprocessing.md, configs/README.md, runs/README.md,
todo/implementation_roadmap.md; Phase 2 config/API/lifecycle/report/CLI tests.
Resolved follow-up:
P2-02 root config/path rules、P2-03 identity/publication、P2-04 operational count cap、
P2-05 mapping/codec config 和 P2-06 exact release handoff 已完成 wiring 决策；P2-08
确认完整 acceptance matrix。
Deferred follow-up:
Parallel workers、progress/structured logging contract、dry-run/resume/force/cleanup、
CLI overrides、console script、nested attribute paths、compression/Parquet selectors
以及真实 runtime experiment config selector。
Confirmed by: User
Date: 2026-08-03
Amendment: P2-XG-01 经用户确认，gitignore 是 operational policy 而非 runtime dependency；
artifact_count 等于 generated RootBundle artifact entries 总数；release_ref 是 portable
identity handoff，加载时必须另行提供 trusted validated root registry。
```

---

## 11. P2-08 — Integration, Tests, and Phase Acceptance

Status: `Confirmed`

P2-08 不再选择数据集、segmentation、feature 或模型研究方案。它固定 Phase 2
implementation 必须如何证明 P2-00—P2-07 的 schema、identity、filesystem lifecycle、
Store handoff 和 Phase 1 compatibility，避免只用 happy-path smoke test 宣布完成。

### Canonical preprocessing fixture

第一条 versioned fixture 固定为 `preprocessing-v1`，位于
`tests/fixtures/preprocessing/v1/`，并具有以下最小可观察行为：

- 2 个 users、3 个 source items、6 个 behavior events；
- item IDs 使用 `item_a`、`item_b`、`item_c`，每个 item 的 segment IDs 固定为
  `segment_1`、`segment_2`，以便 persistent Stores 可以替换
  `mock-v1` 的 in-memory Stores；
- 一位用户的 events 全部使用单调不减的真实 timestamps，另一位全部显式为 `None`；
- 至少一位用户重复交互同一 item，但 `(user_id, interaction_index)` 始终唯一且
  index 从 0 连续；
- 每个 item 两个 segments，共 6 个，并同时覆盖 `RangeLocator`、
  `FileLocator(origin=None)` 和带 `OriginRange` 的 `FileLocator`；
- source media 使用带固定 bytes/checksum 的小型 opaque fixture files，不要求是可解码
  视频，也不调用 FFmpeg/ffprobe；
- canonical happy path 保持完整有效；empty catalog、unknown item、非法时间、重复
  identity、缺失 resource 和 count-limit overflow 由独立 variants/fault tests 覆盖。

Fixture source bytes、source manifest 和 config 纳入版本控制。Fixture 的有意语义变化
创建新版本，不静默改写 `preprocessing-v1`。

### Unit tests

- preprocessing config inheritance/merge/cycle、strict validation、selectors、attribute
  mappings、root roles 和 required positive count limits；
- source/processed schema validation；
- behavior ordering and duplicate semantics；
- root graph、containment、portable POSIX key grammar、cross-platform anchors、Unicode 和
  case-collision rules；
- canonical serialization、manifest/version/checksum generation 和 identity sensitivity；
- segment-definition identity/order, file/range locators and provenance；
- item/proxy record mapping、coverage、ordering 和 payload-ref validation；
- release/index eager validation 与 payload-resolution lazy verification timing；
- resolver membership、containment、size/version/checksum/typed-identity failures；
- persistent Store coverage、caller-order projection、unknown-item failures 和 immutable
  lookup behavior；
- `PreprocessingResult`、`ExecutionReport`、CLI exit-code/output-channel semantics；
- publication helper 的 no-overwrite、exclusive-create、collision 和 loser verification。

### Integration tests

- source fixture → preprocessing bundle；
- root bundles → manifest graph/full verification；
- manifest → persistent Item/Segment Stores；
- persistent Store output → RecommendationStateBuilder；
- persistent Stores 与 in-memory Stores contract parity；
- exact `release_ref` → one shared `LoadedRelease` → resolver/two Stores；
- created、verified reuse、verified orphan-bundle reuse 和 collision/integrity outcomes；
- config/root/source/component/publisher/report fault boundaries；
- Python API 和 CLI 通过同一个 `preprocess_from_config()` lifecycle。

### End-to-end tests

- Python API 与 CLI 分别在 fresh synthetic projects 中产生相同的 stable result fields、
  exact release ref 和 byte-exact portable artifact tree；
- same source/semantic config 在不同 physical roots/executions 中产生相同 data version 和
  canonical artifacts；
- existing version verify-and-reuse；
- partial/collision/path failure 不发布伪完整 bundle；
- 使用 persistent Stores 替换两个 in-memory Stores，并与其余 `mock-v1` components
  完成 canonical two-action Agent smoke run；
- Phase 1 golden、trace/replay 和 CI tests 全部继续通过。

### Golden and equivalence boundary

Version-controlled golden 覆盖两个 generated roots 中的全部 portable artifacts：

```text
behavior sequences
item feature records
segment proxy records
ItemFeatureStoreIndex
SegmentStoreIndex
RootBundleManifests
ReleaseManifest
```

这些 artifacts 使用各自确认的 canonical UTF-8/LF codec，并做 relative-tree 和
byte-exact comparison。以下 machine-local/operational values 不进入 golden comparison：

```text
execution ID
timestamps
configured/resolved absolute roots
config and report paths
staging paths
Git/Python/platform metadata
created vs reused outcome
```

`ExecutionReport` 只做 typed schema、status/outcome、safe error、root/provenance 和
lifecycle semantic assertions。API 与 CLI equivalence 比较 data version、release ref、
counts 和 portable bytes；不要求 stdout、ExecutionReport 或完整
`PreprocessingResult` 的机器相关字段逐字节相同。

### Data-identity acceptance matrix

当输入仍完整通过 limits 时，下列 operational changes 不得改变 data version 或 portable
artifact bytes：

- physical root paths；
- config file path、execution ID 和 timestamps；
- Git/Python/platform metadata；
- 调高但不触发拒绝的 count limits。

下列 semantic changes 必须改变 data version：

- canonical source manifest fields 或其 referenced source artifact bytes/checksum；仅
  source-manifest JSON 排版变化不属于 semantic change；
- attribute mappings；
- content-producing component descriptor/version；
- output schema/codec/compression version；
- logical output root IDs 或其他进入 `DataIdentity` 的 recipe fields。

同一 DataIdentity 如果产生不同 generated bytes，属于 determinism/integrity failure，
不得作为另一个合法 release 发布或复用。

### Failure and publication matrix

- config/root validation failure 不创建 execution directory、staging 或 release；
- source/schema/coverage/count failure 在已经分配 execution 后 best-effort 写 failed
  report，但不创建 staging 或 complete release；
- processor/extractor/output-validation failure 不发布 bundles/release；
- staging write、full verification、root-local rename 或 final exclusive-publish failure
  不得留下可发现的 complete release；
- partial staging 永不 discovery/reuse；完整 orphan bundles 只有 full verification 后可
  reuse；
- existing release/root bundle mismatch 或 corruption 使用 `ArtifactIntegrityError`，不
  overwrite、skip 或降级；
- release/index/record/payload membership、size、checksum 或 typed identity corruption
  必须在 P2-06 确认的 eager/lazy boundary 被发现，不能变成 optional feature 或空 catalog；
- success release 已发布但 terminal ExecutionReport 写失败时，API 抛
  `ArtifactPublicationError`，release 保留；下一次 invocation full-verify 后 reused。

Fault injection 覆盖每个已确认的 semantic boundary，但不要求穷举每个内部 filesystem
call site 的所有 `OSError`。

### Concurrency acceptance

所有 CI platforms 使用确定性 fault injection 验证 rename/exclusive-create collision、
winner verification 和 loser `reused`/integrity-failure semantics。Ubuntu Python 3.12
额外执行一个使用 synchronization barrier 的真实双 invocation race；测试不能依赖
arbitrary `sleep` 或时序运气。相同 identity 的成功 race 必须恰好得到一个 `created`
和一个 `reused`，且两者引用同一 complete release。Windows 不强制真实 race E2E，
但必须覆盖相同 publisher collision/reuse logic。

### Persistent-Store Agent smoke

E2E 先运行 canonical preprocessing，再使用同一 validated root registry 和返回的 exact
`release_ref` 构造一次 immutable `LoadedRelease`；`FilesystemItemFeatureStore`、
`FilesystemSegmentStore` 和 resolver 共享该对象。只替换 Phase 1 的 item/segment
in-memory Stores，其余 Mock components、Controller state machine 和 action budget 不变。
Smoke result 的 `data_version` 使用本次 Phase 2 release，两个 Store descriptors 使用
filesystem implementations；其余 Mock descriptors 保持不变。

Smoke run 必须仍然：

```text
select item_b.segment_1
→ item_b overtakes item_a
→ select item_a.segment_2
→ stop with budget_exhausted
```

测试断言 processed index、Store output、Recommendation State、Perception、Evidence 和
trace 使用同一个 `(item_id, segment_id)` identity，两个 Stores 不混用 release。这个
smoke test 做完整 semantic assertions，但不新增第二套 Agent byte-exact trace golden；
现有 Phase 1 golden/replay 继续独立精确回归。

### Test isolation and platform semantics

- 所有 integration/E2E 写入只发生在 pytest `tmp_path` 下；synthetic project、source、
  processed、features 和 runs roots 都在临时目录中建立；
- external roots 使用 tmp parent 下 distinct sibling directories 模拟，不接触真实外部
  dataset，也不写入或清理仓库 `data/`、`artifacts/`、`runs/`；
- POSIX/Windows/UNC anchors、reserved/control segments、Unicode normalization 和
  case-collision grammar 使用 platform-independent tests；
- real symlink/junction escape 在运行平台允许安全创建时执行，不支持时显式 skip；
  Ubuntu CI 必须实际覆盖 symlink escape；
- 所有 tests offline、CPU-only，不使用网络、GPU、真实 MLLM、FFmpeg/ffprobe、真实
  dataset 或未声明 system tool；
- Phase 2 不要求 performance/load benchmark。

### Quality gates and CI

- pytest 全部通过；整个 `pave_rec` package 的 branch coverage 至少 90%；
- Ruff lint 和 format check 通过；Phase 2 不新增 mypy、Hypothesis、pytest-xdist 或其他
  quality/test tool；
- 使用一套 project-wide GitHub Actions workflow 运行 Phase 1 + Phase 2 全部 tests，
  matrix 继续覆盖 Ubuntu Python 3.10/3.12 和 Windows Python 3.12；
- 所有 jobs 必须在同一 candidate commit 上通过；不增加 macOS 或额外 Python matrix。

### Phase 2 Definition of Done

- P2-00—P2-08 Decision Records 全部 Confirmed 或明确 Deferred；
- P2-XG-01 已完成并确认；
- stable docs 与实现一致；
- preprocessing fixture 可以 offline、CPU-only、无网络重复生成；
- generated manifest、records 和 checksums 可验证；
- filesystem Stores 可查询并满足 Phase 1 Store contract；
- segment identity 从 preprocessing 到 State/trace 保持一致；
- canonical portable artifacts 可以 byte-exact 复现，machine-local report 通过 semantic
  validation；
- created/reused、failure、corruption、collision 和 concurrency acceptance matrix 通过；
- Phase 1 全部 tests/goldens/replay 不回退；
- pytest、package branch coverage >= 90%、Ruff 和 project-wide GitHub Actions matrix
  全部通过；
- completion record 保存 candidate commit、日期和完整 matrix 通过证据；路线图只在该
  commit 的远端 CI 通过后标记 Phase 2 `Completed`。

### P2-08 的交付结果

- Phase 2 unit/integration/e2e matrix；
- versioned golden preprocessing artifacts；
- CI acceptance evidence；
- Phase 2 completion record。

### P2-08 Decision Record

```text
Decision ID: P2-08
Status: Confirmed
Decision:
1. Phase 2 使用 unit、integration 和 end-to-end 三层测试；每条 P2-00—P2-07 已确认
   contract 至少在最靠近 ownership 的层级有明确断言，不能只依赖 happy-path E2E。
2. Canonical preprocessing-v1 固定使用 2 users、3 items、6 behavior events 和 6
   segments；item IDs 为 item_a/item_b/item_c，每个 item 的 segment IDs 为
   segment_1/segment_2；覆盖 timestamp/all-null sequence、valid repeated interaction、file/range
   locators、nullable/present origin 和 opaque checksummed media bytes。Invalid/empty
   cases 使用独立 variants。
3. Source fixture/config 和完整 expected portable artifact tree 纳入版本控制；behavior
   sequences、feature/proxy records、indexes、root manifests 和 release manifest 做
   canonical relative-tree/byte-exact comparison。ExecutionReport 和 machine-local
   values 只做 semantic validation。
4. API/CLI equivalence 定义为：在独立 fresh synthetic projects 中产生相同 stable
   result fields、exact release ref、data version、counts 和 portable bytes；不要求
   execution ID、timestamps、paths、outcome、report 或 stdout byte-equivalent。
5. Tests 固定 positive/negative DataIdentity matrix：physical roots/execution metadata/
   non-binding limits 和 source-manifest-only JSON 排版不改变 version/bytes；canonical
   source fields、referenced source bytes、mapping、component、schema/codec 和 logical
   recipe changes 必须改变 version。同 identity 不同 bytes 是 integrity failure。
6. Failure matrix 覆盖 config/root/source/count、processor/extractor/output validation、
   staging/write/verify/rename/final publish、existing mismatch/corruption、resolver/typed
   loader 和 terminal report boundaries；partial output 永不伪装 complete，默认不覆盖。
7. 所有 platforms 以 deterministic fault injection 覆盖 publisher collision semantics；
   Ubuntu Python 3.12 另做 barrier-controlled real two-invocation race，不用 sleep。成功
   race 恰好一个 created、一个 reused，并共享 exact release。
8. Persistent-Store smoke 使用 validated root registry 和 PreprocessingResult.release_ref
   加载一次 LoadedRelease，让 resolver/two Stores 共享它，只替换 mock-v1 的两个
   in-memory Stores，完成原两步 Agent behavior 并验证 preprocessing-to-trace segment
   identity；run data_version 使用 Phase 2 release，Store descriptors 使用 filesystem
   implementations。此 smoke 不新增重复的 Agent byte golden。
9. Integration/E2E 只在 pytest tmp_path synthetic roots 写入；path grammar 跨平台纯测，
   real symlink/junction capability-based，Ubuntu symlink mandatory。测试不接触真实 repo
   data/artifacts/runs、网络、GPU、MLLM、FFmpeg、真实 dataset 或外部 system tool。
10. Quality gate 固定为 pytest 全部通过、整个 pave_rec branch coverage 至少 90%、Ruff
    lint/format；不新增 mypy/Hypothesis/xdist。Project-wide CI matrix 延续 Ubuntu
    Python 3.10/3.12 和 Windows Python 3.12，所有 jobs 必须通过。
11. P2-08 Confirmed 只关闭测试与验收设计 Gate，不代表 Phase 2 Completed。只有
    P2-XG-01、implementation、stable-doc consistency、全部 local gates 和同一 candidate
    commit 的远端 CI matrix 通过后，才记录 evidence 并更新路线图为 Completed。
Rationale:
Phase 2 的主要风险不是模型效果，而是 data identity、portable bytes、path containment、
multi-root publication、corruption/reuse 和 runtime release mixing。固定小型 golden、
positive/negative identity matrix、完整 lifecycle fault tests、受控 race 和 persistent-Store
Agent handoff，可以在不引入真实媒体/模型的前提下证明数据平面可靠且不破坏 Phase 1。
Alternatives considered:
只做一个 preprocessing happy path；把 machine-local report 加入 byte golden；要求 API/
CLI 全部输出逐字节相同；只测 version stability 不测 sensitivity；跳过 publication faults；
使用 sleep-based race；所有平台强制真实 concurrency；只构造 State 不跑 Agent；提高到
95%/per-file coverage；增加 macOS、mypy、Hypothesis、xdist、真实视频或性能测试。
Affected schemas/interfaces:
Phase2PreprocessingConfig, source/processed/feature/manifest/index schemas,
PreprocessingComponents, publisher, ReleaseLoader/LoadedRelease, ResourceResolver,
filesystem Stores, PreprocessingResult, ExecutionReport, preprocessing CLI and Phase 1 Store
handoff. No new research-model schema is introduced.
Affected docs/tests:
docs/09_offline_preprocessing.md；todo/implementation_roadmap.md；tests/README.md；
Phase 2 unit/integration/e2e fixtures and goldens；project-wide GitHub Actions workflow；
coverage/Ruff gates；Phase 1 regression suite。
Resolved follow-up:
P2-00 Store filtering、P2-01 source contracts、P2-02 path safety、P2-03 identity/publish、
P2-04 segment identity、P2-05 feature records、P2-06 persistent Stores 和 P2-07 lifecycle
现在都有明确 acceptance evidence requirements。
Deferred follow-up:
真实 dataset/media/FFmpeg/model integration、performance/load benchmarks、macOS/additional
Python matrix、mypy/property-based testing、remote/object-store concurrency 和大型 digest
cache tests 在对应实现需求出现时重新讨论。
Confirmed by: User
Date: 2026-08-03
```

---

## 12. P2-XG-01 — Cross-Gate Consistency Review

Status: `Confirmed`

P2-00—P2-08 字段和语义确认后，在实现前统一检查：

- source IDs、processed IDs、`ResourceRef` 和 Store outputs 的 identity 一致；
- `data_version`、manifest version、component version 和 schema version 不混用；
- storage roots/path safety 与 ResourceResolver 使用同一规则；
- SegmentMeta 与 SegmentProxyRef 一一覆盖且顺序一致；
- persistent Store 不读取 Observation State；
- pipeline lifecycle 不会把 partial artifacts 当成完整数据版本；
- Phase 2 config 不破坏 Phase 1 config/replay contract；
- tests 不依赖外部数据、网络、GPU 或未声明系统工具；
- Phase 3/4/5 的真实模型研究选择仍保持 Deferred。

### Cross-Gate Review Conclusion

P2-00—P2-08 的主体契约一致，以下实现前歧义已统一：

- exact `release_ref` 是 portable release identity，不是自包含物理 locator；
  `ReleaseLoader` 同时需要 trusted validated root registry；
- source manifest exact checksum 在 ingestion 时验证，但 DataIdentity 使用 canonical
  validated manifest semantics；仅排版变化不改变 data version；
- `ItemSegmentIndex` 是非持久化 frozen typed intermediate，不复制 source/runtime
  segment facts；
- `PreprocessingResult.artifact_count` 等于 generated RootBundle artifact-entry 总数；
- local config 的 gitignore 是 operational policy，不是 runtime Git dependency；
- preprocessing source resolver 与 runtime release-scoped resolver 共用 path-safety core，
  runtime 额外验证 release inventory membership；
- Phase 2 declared errors 统一进入 PaveRecError hierarchy，portable identity hashing 使用
  现有 compact canonical UTF-8/LF JSON，portable metadata 不含 execution-local values；
- `preprocessing-v1` 的 IDs、persistent-Store smoke data version/descriptors 和 canonical
  ordering 已与 Phase 1 Mock contracts 对齐。

本 Gate 完成后，Phase 2 design gates 全部关闭，可以正式开始 implementation；Phase 2
仍只有在实现、stable-doc consistency、local quality gates 和同一 candidate commit 的
完整远端 CI matrix 全部通过后才能标记 `Completed`。

### P2-XG-01 Decision Record

```text
Decision ID: P2-XG-01
Status: Confirmed
Decision:
1. P2-00—P2-08 的 source/item/segment identities、version fields、root/path rules、
   Store contracts、publication lifecycle、Phase 1 boundary 和 test isolation 无冲突。
2. release_ref 只承担 portable release identity handoff；ReleaseLoader 必须由 trusted
   validated root registry 构造，portable refs/manifests 不保存 physical paths。
3. source.manifest_ref checksum 在 ingestion 时精确验证；DataIdentity 保存 canonical
   validated SourceDatasetManifest。仅 JSON 排版变化不改变 version，canonical fields 或
   referenced artifact bytes/checksums 变化必须改变。
4. ItemSegmentIndex 是 frozen per-item internal intermediate，不单独发布。Canonical
   SegmentDefinition、SegmentProxyRecord 和 SegmentStoreIndex 分别保存 source provenance、
   proxy sequence 和 runtime projection。
5. PreprocessingResult.artifact_count 等于所有 RootBundleManifest.artifacts entries 总数，
   排除 source_artifacts、root manifests 自身和 final release manifest。
6. Machine-local config 应 gitignored，但这是 operational policy；runtime 不调用 Git，
   继续严格验证 project-contained config chain 和完整 root graph。
7. Pre-release source resolution 与 runtime release-scoped resolution 共享 filesystem
   path-safety core；runtime resolver 额外强制 LoadedRelease inventory membership。
8. Phase 2 errors 全部属于 PaveRecError hierarchy；DatasetValidationError 属于 contract
   validation，ArtifactIntegrityError/ArtifactPublicationError 保持独立 declared failures。
9. DataIdentity 和 opaque ID hashes 使用现有 compact canonical UTF-8/LF JSON；portable
   outputs 禁止 execution ID/timestamp/absolute path 等 non-deterministic metadata，所有
   identity/ref/manifest collections 使用已确认 canonical ordering。
10. preprocessing-v1 固定 item_a/item_b/item_c 和每项 segment_1/segment_2。Persistent
    Store smoke 使用 Phase 2 run data_version/filesystem Store descriptors，其余 Mock
    components、Controller semantics 和 budget 不变。
11. P2-XG-01 Confirmed 关闭设计 Gate 并允许开始 implementation，但不表示 Phase 2
    Completed；completion 仍受 P2-08 Definition of Done 约束。
Rationale:
消除 portable identity 与 machine locator、semantic source identity 与文件排版、内部
segment indexing 与持久化事实、以及 result count 与 manifest graph 之间的歧义，使
implementation 可以从唯一 contract 推导行为，同时不扩大 Phase 2 的研究范围。
Alternatives considered:
让 release_ref 保存 absolute path；让 manifest 排版 checksum 改变 data version；发布
第三份 ItemSegmentIndex；让 artifact_count 包含 source/manifests；运行时依赖 Git 检查
ignore；pre-release source resolver 默认绕过 path safety；修改 Phase 1 schemas/loop。
Affected schemas/interfaces:
DataIdentity/source manifest ingestion, ItemSegmentIndex, PreprocessingResult,
ReleaseLoader/LoadedRelease, trusted root registry, source/runtime resolvers, Phase 2 error
hierarchy, preprocessing fixture and persistent-Store Agent smoke. No Phase 1 public schema
or Controller change.
Affected docs/tests:
README.md；docs/00_shared_domain_schemas.md；docs/00_component_interfaces.md；
docs/09_offline_preprocessing.md；configs/README.md；data/README.md；artifacts/README.md；
tests/README.md；
todo/implementation_roadmap.md；todo/phase_2_discussion.md；Phase 2 identity/config/resolver/
manifest/result/smoke tests。
Resolved follow-up:
P2-00—P2-08 cross-gate consistency、release location binding、source-manifest formatting
identity、ItemSegmentIndex persistence、artifact-count semantics、local-config VCS policy、
resolver modes、error hierarchy 和 smoke version/descriptor semantics。
Deferred follow-up:
真实 dataset/segmentation/features/models、remote/object-store locator binding、signed
manifests、persistent digest cache、cleanup/maintenance 和真实 runtime experiment config。
Confirmed by: User
Date: 2026-08-03
```

---

## 13. Phase 2 Discussion Order

按以下顺序推进，一次只处理一个 Gate：

1. `P2-00 Phase 1 Handoff and Store Filtering Consistency`
2. `P2-01 Source Data and Processed Record Contracts`
3. `P2-02 Storage Roots and Path Safety`
4. `P2-03 Manifest, Provenance, and Data Versioning`
5. `P2-04 Segment Definition Ingestion and Stable Segment Identity`
6. `P2-05 Item Features and Segment Proxy Baseline`
7. `P2-06 Persistent Stores and Resource Resolution`
8. `P2-07 Preprocessing API, Config, CLI, and Lifecycle`
9. `P2-08 Integration, Tests, and Phase Acceptance`
10. `P2-XG-01 Cross-Gate Consistency Review`

某个 Gate 可以显式 `Deferred`，但必须记录：

- 为什么现在不决定；
- 哪个 interface/config 隔离它；
- baseline 使用什么确定性语义；
- 在哪个后续 Phase 或触发条件下重新讨论。

---

## 14. Decision Record Template

每次确认后，在对应 Gate 下追加：

```text
Decision ID:
Status: Confirmed | Deferred
Decision:
Rationale:
Alternatives considered:
Affected schemas/interfaces:
Affected docs/tests:
Resolved follow-up:
Deferred follow-up:
Confirmed by:
Date:
```

只有 `Confirmed` 的内容可以被当作 Phase 2 实现要求。
