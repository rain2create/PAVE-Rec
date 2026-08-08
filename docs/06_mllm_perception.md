# Module 06 — MLLM Text-Evidence Comparison Branch
# MLLM 文本证据对比支线

> Architecture amendment (2026-08-07): P4-ARCH-02 主线由 `SegmentPerceiver` 发布 selected raw-frame Evidence，
> 再由约 8B native-frame MLLM `ScoreUpdater` 通过 scoring head 直接输出 Top-100 logits。本文保留的
> structured-text Evidence + generative/token-ranking LLM 路径只属于 Phase 6 representation/explanation comparator；
> 它不是主线 Reranker 的实现方式。公共 Protocol、failure、artifact 和安全边界仍可复用。

## 1. 模块目标 Purpose

只有在 Agent 已经选出高价值 segment 后，对比支线才调用昂贵 MLLM。

MLLM 的职责是：

```text
raw multimodal content
→ structured recommendation evidence
```

---

## 2. 输入 Input

```text
selected item
selected segment
information need
user preference state
already observed evidence
dense frames / clip frames
ASR / audio text if available
```

---

## 3. 输出 Output

公共 Evidence 以
[`00_shared_domain_schemas.md`](00_shared_domain_schemas.md) 为准：

```python
class Evidence:
    evidence_id: str
    item_id: str
    segment_id: str
    attributes: JsonObject
    text_summary: str | None
    confidence: float | None
    source: str
    raw_output_ref: ResourceRef | None
    embedding_ref: ResourceRef | None
    metadata: JsonObject
```

原始 response、完整 API payload 和 embedding 不直接内嵌 Evidence，只通过
带版本的 reference 关联。

例如：

```json
{
  "evidence_id": "ev_B_03_001",
  "item_id": "B",
  "segment_id": "B_03",
  "attributes": {
    "plot_twist": "strong",
    "pace": "fast",
    "emotional_intensity": "moderate"
  },
  "text_summary": null,
  "confidence": 0.88,
  "source": "example_mllm",
  "raw_output_ref": null,
  "embedding_ref": null,
  "metadata": {}
}
```

---

## 4. Design Principle

优先采用：

```text
MLLM → evidence
Ranker → recommendation score
```

而不是：

```text
MLLM → final recommendation score
```

这样 perception 和 recommendation decision 是分开的，更容易训练、分析和做 ablation。

---

## 5. Interface

```python
class SegmentPerceiver(Protocol):
    def observe(
        self,
        request: PerceptionRequest,
    ) -> PerceptionResult:
        ...
```

`PerceptionRequest` 只包含已选 `SegmentMeta`、Information Need、
UserMemoryView 和当前 item Evidence。成功返回 Evidence；可预期失败返回 typed
failed result，不伪造空 Evidence。权威字段和错误契约见
[`00_component_interfaces.md`](00_component_interfaces.md)。

Implement：

```text
MockPerceiver
MLLMPerceiver
```

---

## 6. Prompting

MLLM prompt 应围绕当前 `Information Need`。

Conceptual format：

```text
User relevant preference:
{preference}

Current missing information:
{information_need}

Inspect this segment and extract recommendation-relevant evidence.

Return structured JSON.
```

Structured-text 对比支线先生成文本 Evidence，再由独立 LLM 对候选集合排序。Phase 4 主线则直接使用
native-frame MLLM scoring head，不经过本文的文本 Evidence schema；Phase 1 mock runtime 仍不依赖真实模型。

---

## 7. Evidence Parser

Parsing logic 单独隔离：

```python
class EvidenceParser:
    def parse(self, raw_mllm_output: str) -> Evidence:
        ...
```

需要考虑：

- schema validation
- retry / repair if malformed
- confidence normalization
- raw response logging

---

## 8. Cost Logging

本节是路线图 Phase 6 接入 MLLM 对比支线后的要求。Phase 1 的 Mock Perceiver 不增加
frame/token/latency/cost placeholder 字段，也不把这些字段塞入
`PerceptionResult`、State 或 Trace。

必须记录：

```text
number of frames
segment duration
input tokens
output tokens
latency
model name
```

因为整个研究的核心动机之一就是：

```text
limited multimodal perception budget
```

---

## 9. TBD

- exact MLLM
- frame sampling inside a selected segment
- whether ASR/audio is used
- structured attribute vocabulary
- whether free-form text evidence is retained
