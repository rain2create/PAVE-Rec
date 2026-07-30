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

最终生成的 `UserMemoryState` 会被以下模块使用：

- Recommendation State
- Information Need
- Segment Value Model
- MLLM Perception

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

## 11. V1 Implementation

V1 可以先使用：

- text descriptions for atoms
- one embedding model
- cosine similarity
- configurable thresholds
- EMA update
- simple persistence count
- simple decay

所有 threshold 和 update coefficient 都必须配置化。

---

## 12. TBD

下面这些当前不要替我们做研究决定：

- how preference atoms are extracted / clustered
- exact time window defining short-term behavior
- one-to-one vs many-to-one matching policy
- stable/emerging/fading thresholds
- EMA coefficient
- persistence scoring
- decay function
- semantic profile refresh policy
