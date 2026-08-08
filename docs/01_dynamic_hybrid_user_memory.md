# Module 01 — Dynamic Hybrid User Memory
# 动态混合用户记忆模块

## 1. 模块目标 Purpose

维护一个会随用户行为变化而更新的动态偏好表示，能够区分：

- long-term stable interests
- recent short-term interests
- emerging interests
- fading interests

这个模块 **不是 ranking model**。

它主要回答：

```text
用户当前主要在意什么？
哪些偏好是长期稳定的？
哪些兴趣正在新出现？
哪些旧兴趣正在衰退？
```

Memory 模块内部维护完整 `UserMemoryState`，并向以下模块发布
`UserMemoryView`：

- Recommendation State
- Information Need
- Segment Value Model
- Deep Segment Perception / MLLM comparison branch
- native-frame MLLM Candidate Reranker

---

## 2. 核心表示 Core Representation

不要把用户表示成单一 embedding，而是表示为多个 `PreferenceAtom`。

```python
@dataclass
class PreferenceAtom:
    atom_id: str
    text: str
    embedding: Tensor
    strength: float
    persistence: float
    created_at: int | float
    last_seen_at: int | float
    state: str
    metadata: dict
```

建议支持的 `state`：

```text
stable
emerging
fading
inactive
```

整体用户记忆：

```python
@dataclass
class UserMemoryState:
    long_term_atoms: list[PreferenceAtom]
    short_term_atoms: list[PreferenceAtom]

    global_drift: float | None
    new_interest_drift: float | None
    drop_interest_drift: float | None

    semantic_profile: str | None
```

### Recommendation-facing User Memory View

`UserMemoryState` 是 Memory 模块内部的完整状态。Recommendation State 不直接
内嵌这个对象，而是保存一个紧凑、只读、可 JSON 序列化的 `UserMemoryView`。
公共 View 的权威字段定义见
[`00_shared_domain_schemas.md`](00_shared_domain_schemas.md)；本节只解释它与
Memory 内部状态的关系。

这个 View 至少表达：

```text
long-term and short-term atom summaries
stable match signals
emerging and fading signals
new/drop/global drift
memory version and update time
optional semantic profile
embedding references
Long x Short Similarity Matrix reference
```

单个 atom view 保存 `atom_id`、`text`、`state`、`strength`、`persistence` 和
可选 `embedding_ref`，不保存 Tensor。Matrix 的紧凑派生信号可以表示为：

```python
class PreferenceMatchView:
    long_atom_id: str | None
    short_atom_id: str | None
    similarity: float | None
    classification: PreferenceMatchType
```

`stable` signal 同时关联 long/short atom；`emerging` 可以没有 long atom；
`fading` 可以没有 short atom。两个 atom ID 不能同时为空。

Information Need 消费 stable/emerging/fading、match score 和 drift 等派生信号，
不负责重新提取 atom、重新计算 Matrix 或修改 Memory。未来 learned estimator
如果确实需要完整 Matrix，可以通过 `similarity_matrix_ref` 从 Memory Store
加载。

Phase 4+ 的 native-frame MLLM Reranker 可以在组件内部通过 atom embedding refs 加载 semantic vectors，并与
SASRec user/item hidden、base score 和当前 raw-frame Evidence 分别适配/融合。BGE-M3 semantic space 与
SASRec Item-ID/MLLM hidden space 不兼容，不得直接相加或假设同一坐标系。

一次 Agent run 内使用固定的 `UserMemoryView`。只有新的真实用户行为触发
Memory 更新；对候选 segment 的 perception Evidence 不反向修改用户兴趣。

P1-03 已确认 recommendation-facing synchronous interface：

```python
class UserMemory(Protocol):
    def build_or_update(
        self,
        user_id: str,
        history: tuple[str, ...],
    ) -> UserMemoryView:
        ...
```

权威接口和最小输入权限见
[`00_component_interfaces.md`](00_component_interfaces.md)。

---

## 3. Long-term / Short-term Memory

### Long-term memory

特点：

- update 较慢
- 强调 persistence
- 不应该因为一次偶然点击/观看就明显改变
- 表示相对稳定的长期兴趣

### Short-term memory

特点：

- update 较快
- 基于近期交互构造
- 捕捉 temporary / emerging preference
- 高频刷新

Long-term atom 数量和 Short-term atom 数量不需要相等。

例如：

```text
Long-term:
L1 = suspense / plot twists
L2 = AI / technology
L3 = basketball
L4 = food exploration

Short-term:
S1 = crime suspense
S2 = emotional drama
S3 = AI agents
```

---

## 4. Long × Short Similarity Matrix

构造：

```text
M[i, j] = cosine(long_atom_i.embedding, short_atom_j.embedding)
```

例如：

```text
                    Short-term
                S1        S2        S3

Long L1         0.92      0.31      0.08
     L2         0.12      0.16      0.89
     L3         0.07      0.13      0.05
     L4         0.21      0.11      0.04
```

Required API：

```python
def build_similarity_matrix(
    long_atoms: list[PreferenceAtom],
    short_atoms: list[PreferenceAtom],
) -> Tensor:
    # Return shape: [num_long, num_short]
    ...
```

---

## 5. Stable Interests

对于每一个 short-term atom，查看：

```text
max_i M[i, j]
```

如果它和某个 long-term atom 有很强匹配，则说明：

```text
最近兴趣 ≈ 已有长期兴趣
```

因此它应该被判断为 existing interest reinforcement。

例如：

```text
S1 crime suspense
→ L1 suspense / plot twist
similarity = 0.92
```

对应 update 行为：

```text
reinforce L1
optionally update L1 embedding by EMA
update last_seen
increase / maintain strength
```

Baseline embedding update：

```text
e_long_new =
    (1 - eta) * e_long_old
    + eta * e_short
```

`eta` 必须放在 config 中，不能写死。

---

## 6. Emerging Interests

对于某一个 short-term atom，如果：

```text
max_i M[i, j] < emerging_match_threshold
```

说明它在已有 long-term memory 中没有良好对应兴趣。

此时标记：

```text
state = emerging
```

非常重要：

**不能因为一次 emerging interest 出现，就立刻写入 long-term memory。**

应该通过 persistence 机制：

```text
new short interest
      ↓
emerging memory
      ↓
appears repeatedly
      ↓
persistence increases
      ↓
promotion condition satisfied
      ↓
promote to long-term memory
```

Required API：

```python
def detect_emerging(
    similarity_matrix: Tensor,
    short_atoms: list[PreferenceAtom],
    threshold: float,
) -> list[PreferenceAtom]:
    ...
```

Promotion threshold 当前保留为：

```text
TBD / configurable
```

---

## 7. Fading Interests

对于每一个 long-term atom，查看：

```text
max_j M[i, j]
```

如果近期 short-term memory 中没有与它明显匹配的兴趣，说明：

```text
old preference is currently inactive
```

但不能立刻删除。

应该：

```text
decrease strength
increase time_since_seen
possibly mark fading
eventually mark inactive
```

Required API：

```python
def detect_fading(
    similarity_matrix: Tensor,
    long_atoms: list[PreferenceAtom],
    threshold: float,
) -> list[PreferenceAtom]:
    ...
```

---

## 8. Drift Metrics

### New-interest drift

```text
D_new =
Σ_j beta_j * (1 - max_i M[i,j])
```

含义：

- 越大表示近期出现了越多长期记忆中没有的新兴趣
- 可以作为 emerging tendency 的总体指标

### Drop-interest drift

```text
D_drop =
Σ_i alpha_i * (1 - max_j M[i,j])
```

含义：

- 越大表示越多长期兴趣近期没有继续出现
- 可以作为 fading tendency 的总体指标

### Optional global drift

```text
D_global = 1 - cosine(e_long_global, e_short_global)
```

这个只能作为辅助 global signal。

主要解释机制仍然应该是：

```text
Long × Short Atom Similarity Matrix
```

---

## 9. Memory Update Loop

```python
recent_behavior = get_recent_behavior(user)

short_atoms = short_atom_builder.build(recent_behavior)

long_atoms = memory_store.load_long_term_atoms(user)

M = similarity_matrix_builder.build(
    long_atoms,
    short_atoms,
)

stable_matches = detector.find_stable(M)
emerging = detector.find_emerging(M)
fading = detector.find_fading(M)

short_memory.replace(short_atoms)

long_memory.reinforce(stable_matches)
long_memory.accumulate_emerging(emerging)
long_memory.decay(fading)

long_memory.promote_persistent_interests()
long_memory.deactivate_weak_interests()
```

---

## 10. Semantic Profile

可以额外保留一个由 LLM 生成的语义 Profile：

```text
semantic_profile
```

但要明确：

```text
LLM semantic profile != primary online memory update mechanism
```

不要每次 interaction 后都重新生成完整 Profile。

只有在出现较明显的 structural change 时才考虑刷新，例如：

- emerging atom promoted
- important long-term atom becomes inactive
- strong preference-strength shift

---

## 11. First Real Implementation (Phase 3)

P3-05 已确认第一条 Atom/embedding 输入契约。必须先区分两套独立表示：SASRec 从目标数据集的
item-ID sequence 学习 trainable item embeddings 和 sequential hidden state；Dynamic Memory 使用冻结文本
encoder 从 item title/tags/category 生成 semantic embeddings。首版不把后者注入 SASRec，两条支路只在
Recommendation State 和后续 Agent/Segment Value 消费边界汇合。

首版采用 one-item-one-`ItemSemanticPrototype`：

```text
P2 SourceItem
    → canonical title/tags/category semantic text
    → reusable ItemSemanticPrototype + external embedding ResourceRef
    → positive_v1 observation
    → P3-06 user-specific long/short PreferenceAtom
```

prototype 是用户无关的静态语义来源，不包含 long/short side、state、strength 或 persistence。同一 item
的 repeated positives 保留为多个 observations，但复用同一 prototype/embedding；P3-06 才决定 observation
如何形成 long/short atoms，并保证 public atom IDs 在两侧全局唯一。

Tsinghua `tsv-item-semantic-text-v1` 只按 title、tags、Chinese category paths 的固定顺序组合实际存在的
字段，不伪造 description、`unknown` 或生成式摘要。只有 `tsv-positive-v1` 产生正向 preference
observation；negative/passive 首版不生成正向 Atom。tag/category-level atoms、跨 item clustering 和
learned extraction 是后续 ablation。

第一条 embedding recipe 是 `bge-m3-dense-v1`：固定 `BAAI/bge-m3` exact revision
`5617a9f61b028005a4858fdac845db406aefb181`、`FlagEmbedding==1.4.0`、dense CLS、无 instruction、
max 1,024 tokens、1,024 dimensions、FP32 L2 normalization 和 cosine similarity。模型与 embeddings
只能离线准备并以 immutable P3 item-semantic artifact 发布；Tensor 不进入 `UserMemoryView`，只通过
`ResourceRef` 解析。online Agent 不下载模型或批量生成 embeddings。

P3-05 固定 `semantic_profile=None`。P3-06 已确认下面的 cosine matching、threshold、EMA、persistence、
decay、drift 和 artifact persistence baseline；所有 threshold/update coefficient 仍必须配置化和版本化。

### 11.1 P3-06 confirmed Dynamic Memory baseline

P3-06 的主流程固定为：

```text
positive history + P3-05 semantic prototypes
        ↓
recent-5 Short Memory + accumulated Long/Pending Memory
        ↓ cosine matching
Stable 强化 / Emerging 累积晋升 / Fading 衰减
        ↓
Drift（只读摘要，不反向更新）
        ↓
immutable UserMemoryView snapshot
```

Short 是最近 5 个 valid positive semantic observations；Long 是全部 cutoff-safe history 顺序 replay 后形成的
user-specific semantic tracks，两者可以重叠，不是旧/新 history partition。Pending interest 至少跨 2 个不同
source timestamps 得到支持后才晋升 Long。最终 View 最多投影 20 个 active Long Atoms。

每个 observation 先匹配已有 Long，再匹配 Pending，统一 cosine threshold=`0.70`。Long match 对 centroid 做
normalized EMA，`eta=0.20`；每个 Short 只选择一个 best Long，多个 Shorts 可以强化同一个 Long。匹配成功是
stable；Short 无匹配是 emerging；Long 没有近期 Short 支持是 fading；strength `<0.10` 后成为 internal
inactive，不硬删除并允许未来 re-activate。Fading 只表示 recent-5 中没有支持，不等于 dislike。

```text
long_strength    = (1 - exp(-support_count / 3)) * 2 ** (-age_days / 7)
long_persistence = min(distinct_support_times / 5, 1)
short_strength   = 2 ** (-age_index / 2)
```

New-interest drift 汇总近期新兴趣，drop-interest drift 汇总近期缺失的长期兴趣，global drift 汇总 Long/Short
整体语义差异；三者只从最终 matrix/strength 派生为 `[0,1]` signal，不参与当前 Memory 的 matching、promotion、
decay 或 threshold 调整，也不提前决定 Information Need/Segment Value 的公式。

首版只离线生成 immutable exact-prefix snapshot。Bootstrap 用 exact snapshot ref 和 full-exposure cutoff identity
预先绑定 adapter；Online `build_or_update()` 接收 cutoff 前完整、未截断的 `positive_v1` item-ID tuple，只验证
user/history fingerprint/cutoff closure 后只读加载。它不按 tuple 搜索或猜 snapshot；相同 positive tuple 可能对应
不同 full-exposure cutoff。一次 Agent run 内 View 固定；MLLM Evidence、Score Update 和 Re-rank 不更新用户兴趣。
只有新的真实 behavior 才产生下一版 snapshot。`updated_at_ms` 使用 source event time，`semantic_profile=None`。

第一条数值 recipe 是 recent=5、max-long=20、threshold=0.70、promotion-times=2、EMA=0.20、persistence
saturation=5、half-life=7 days、inactive=0.10。它们是可复现 baseline；真实 embedding audit 后只在 validation
做 sensitivity/选择，不读取 test，不自动漂移参数。

### 11.2 Phase 3 evaluation boundary

Memory implementation acceptance 使用 deterministic golden transitions 精确验证 stable/emerging/promotion/
fading/inactive/reactivation、empty axes、same-time/repeat/idempotency、cutoff/leakage、drift boundaries、atomic
persistence/reload 和 public `UserMemoryView` references。真实 Tsinghua build 另报告 semantic/Memory coverage、
long-empty、state/promotion/inactive counts、atom-count、cosine 和 drift distributions；这些 aggregate audit 是
诊断，不是人工 ground truth，也不触发自动 threshold 调整。

在 P3 zero-budget Cheap Path 中尚无 Information Need/Segment Value/Score Updater 消费 Memory，因此加载
Dynamic Memory 前后，同 checkpoint/candidates 的 SASRec ranking 必须完全一致。P3 只证明 cutoff-safe Memory
能稳定进入 Recommendation State 并满足后续 public-view-only consumption，不声称已经提高 NDCG。Memory
next-item gain、interest-state agreement 和最终 benchmark 留到 Phase 6。

P4+ 的预期消费链是：Memory → Recommendation State → Information Need → Multimodal Segment Selector，并在
native-frame MLLM Reranker 中直接影响最终重排。Memory 在一次 Agent run 内仍保持 immutable；新感知
Evidence 不回写 Memory，只有新的真实用户行为才生成下一版 snapshot。首版 SASRec 粗召回继续完全不消费
Memory，Memory-aware initial retrieval/fusion 只作为 Phase 7 独立实验。

### 11.3 First real aggregate audit (2026-08-04)

第一条 Tsinghua validation/test exact-prefix Memory artifact 为
`p3memoryartifact-0c2370bf509742115e03b101e3224c766e6c454e6af6bba8ca24f7d2ce34d3e7`。
对应 immutable audit 为
`p3memoryaudit-89ce25a5d9bb5544772dc6cdfc0eec788e5b14ce29db3f4ae8a1d0c887b58bcf`
（`sha256:11b4a9d555d5d0a22a336ca3d98a83e0575b3d7ee59f864fb8dd1ed292a1f47e`）。

审计覆盖 `8,596` snapshots 和 `164,446` semantic observations，snapshot semantic coverage 为
`1.0`；得到 `4,667` stable、`5,796` fading、`130,407` pending/emerging、`0` inactive tracks，
promotion 数为 `10,463`。Long non-empty snapshot rate 为 `0.549558`，Short empty snapshot 为 `0`；
`29,267` 个 cosine observations 的 mean/p50/p90/p99 分别约为
`0.645856/0.609585/0.842040/0.990675`，global/new/drop drift mean 分别约为
`0.180950/0.640560/0.230850`。

Pending 数量较高是需要在 Phase 6 做 `{0.60, 0.70, 0.80}` threshold sensitivity 的诊断信号，不能据此
读取 test 后自动修改当前 `0.70` baseline，也不能把 aggregate audit 写成兴趣分类 ground truth。

Phase 1 只实现固定查表的 `MockUserMemory`，不实现上述 atom extraction、matching、
EMA、persistence 或 decay baseline。

---

## 12. TBD

下面这些当前不要替我们做研究决定：

- alternative tag/category, clustered, or learned atom extraction
- negative/passive feedback in memory updates
- embedding-model ablations beyond `bge-m3-dense-v1`
- alternative recent/time windows beyond recent-5
- one-to-one/Hungarian matching beyond many-short-to-one-long
- threshold sensitivity beyond the `0.70` baseline
- alternative EMA/persistence/decay formulas
- semantic profile refresh policy
