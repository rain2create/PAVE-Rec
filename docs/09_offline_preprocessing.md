# Module 09 — Offline Preprocessing
# 离线数据与特征预处理模块

## 1. 模块目标 Purpose

预先准备 online Agent 所需的 cheap features。

Online loop 不应该重复做高成本 preprocessing。

---

## 2. Behavior Sequence Preprocessing

输出：

```text
user_id
ordered item interaction sequence
timestamps
interaction type
optional labels
```

用于：

- SASRec
- long/short memory construction

---

## 3. Cheap Item Features

可能包括：

```text
item_id
title
caption
category
creator
metadata
text embedding
thumbnail embedding
CF / ID embedding
```

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

## 4. Video Segmentation

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

当前 segmentation strategy 尚未最终确定。

工程上应该支持：

```text
fixed-window segmenter
scene-based segmenter
hybrid segmenter
```

V1 为了工程方便可以先用 fixed-duration segment。

但必须明确：

```text
fixed duration != final research design
```

---

## 5. Cheap Segment Proxy Features

每个 segment 在 MLLM 感知之前就应该已经有 cheap proxy。

可能包括：

```text
keyframe embedding
CLIP/SigLIP visual embedding
ASR text / embedding
motion statistics
scene statistics
duration
relative position
thumbnail similarity
```

Preprocessing implementation 可以在生成阶段使用包含 Tensor/ndarray 的内部
artifact 对象，但写入 Store 后，跨模块只暴露带版本的 `SegmentProxyRef`：

```python
class SegmentProxyArtifact:
    item_id: str
    segment_id: str
    dense_features: Tensor
    sparse_features: dict


class SegmentProxyRef:
    item_id: str
    segment_id: str
    feature_ref: ResourceRef
    metadata: JsonObject
```

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

所有生成特征都要记录：

- source dataset version
- feature-extractor version
- embedding model name
- segmentation config
- preprocessing timestamp/hash

---

## 8. TBD

- final segmentation strategy
- exact proxy feature set
- exact embedding models
- whether ASR/audio is included in V1
