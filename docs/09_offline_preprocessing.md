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
class ItemFeatureStore:
    def load(self, item_ids: list[str]) -> dict:
        ...
```

---

## 4. Video Segmentation

输出：

```python
@dataclass
class SegmentMeta:
    item_id: str
    segment_id: str
    start_time: float
    end_time: float
    media_path: str
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

Schema：

```python
@dataclass
class SegmentProxy:
    item_id: str
    segment_id: str
    dense_features: Tensor
    sparse_features: dict
    metadata: dict
```

---

## 6. Segment Store

```python
class SegmentStore:
    def load_by_item(self, item_id: str):
        ...

    def get_unobserved_segments(
        self,
        candidate_ids: list[str],
        evidence_state,
    ):
        ...
```

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
