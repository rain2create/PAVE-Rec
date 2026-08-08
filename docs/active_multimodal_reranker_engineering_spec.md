# 面向推荐决策的主动多模态感知 Agent
## ≤1B Multimodal Segment Selector 与 Native-frame MLLM Reranker 工程说明

> 文档定位：本文件用于指导项目 V1 的工程实现、数据构造、模型训练与实验验证。
>
> 当前核心决策：
>
> - **主线 Selector**：≤1B 判别式多模态 Segment Selector 使用自己缓存的低清多帧 compact tokens，对全部 eligible segments 直接输出 expected value，不使用独立 CLIP shortlist。
> - **主线 Reranker**：最终选择的 segment 发布 raw-frame Evidence；约 8B native-frame MLLM 通过 candidate scoring head 输出 Top-100 logits，不生成自由文本分数。
> - **训练依赖**：先训练并冻结 MLLM Reranker，再生成 counterfactual gain labels 和训练 Selector；第一版不联合训练。
> - **对比方法**：P4 Chinese-CLIP Query-relevance、CLIP-shortlist + Selector、Small latent/text-only Reranker 和不同模型规模。
> - **核心原则**：Selector 决定“值不值得看”，Perceiver 只发布已选原始帧，MLLM Reranker 决定这些 Evidence 如何改变整个候选排序。
>
> 本文件是对既有 P0–P4 设计的架构补充，不新建第二套公共 schema、Controller 或目录树。公共类型和运行语义仍以 `docs/00_shared_domain_schemas.md`、P1 Protocol 与现有 `src/pave_rec` 为准；本文中的 Tensor、batch 和网络结构只描述组件内部实现。若本文旧 Small-Reranker/Chinese-CLIP-latent 段落与 P4-ARCH-02 冲突，以 P4-ARCH-02 及其后标注的 active amendment 为准。

---

# 1. 项目目标

本项目研究以下问题：

> 在多模态视频推荐中，面对多个候选 Item 和有限的视频感知预算，推荐 Agent 应该主动深入处理哪个 Item 的哪个 Segment，才能以尽可能低的计算成本改善当前推荐排序？

现有多模态推荐通常预先处理所有候选视频：

```text
所有视频
  ↓
固定抽帧 / 全量多模态编码
  ↓
统一 Item Representation
  ↓
推荐排序
```

本项目改为推荐状态驱动的闭环：

```text
用户历史
  ↓
SASRec 初始排序
  ↓
当前 Recommendation State
  ↓
Information Need 提炼当前最值得消除的偏好信息缺口
  ↓
≤1B Multimodal Selector 预测全部未观察 Segment 的决策价值
  ↓
仅发布最高价值 Item-Segment 的原始帧
  ↓
~8B Native-frame MLLM Reranker 更新整个候选集合
  ↓
继续感知 or 停止
```

核心区别不是“有没有视频特征”，而是：

> **视频深层信息不是一次性全部获得，而是由当前推荐决策按需获取。**

---

# 2. 当前最终方法主线

## 2.1 总体架构

```text
┌─────────────────────────────────────────────┐
│ 1. Hybrid User Preference Modeling          │
│ Long-term / Short-term Preference Atoms     │
│ Stable / Emerging / Fading Interests        │
└──────────────────────┬──────────────────────┘
                       ↓
┌─────────────────────────────────────────────┐
│ 2. SASRec Cheap Initial Ranking             │
│ User Sequence Embedding + Base Scores       │
└──────────────────────┬──────────────────────┘
                       ↓
┌─────────────────────────────────────────────┐
│ 3. Recommendation State                     │
│ Ranking / Evidence / Uncertainty / Budget   │
└──────────────────────┬──────────────────────┘
                       ↓
┌─────────────────────────────────────────────┐
│ 4. Information Need                         │
│ Stable / Emerging / Fading Evidence Gap     │
└──────────────────────┬──────────────────────┘
                       ↓
┌─────────────────────────────────────────────┐
│ 5. ≤1B Multimodal Segment Selector          │
│ Input: all eligible compact frame tokens    │
│ Output: Expected Recommendation Gain        │
└──────────────────────┬──────────────────────┘
                       ↓
┌─────────────────────────────────────────────┐
│ 6. On-demand Segment Embedding Extraction   │
│ Selected Segment → CLIP / Video Encoder     │
│ Output: Segment Embedding or Segment Tokens │
└──────────────────────┬──────────────────────┘
                       ↓
        ┌─────────────────────────────────┐
        │ Optional Evidence Adapter       │
        │ Preference-conditioned Fusion   │
        └────────────────┬────────────────┘
                         ↓
┌─────────────────────────────────────────────┐
│ 7. ~8B Native-frame MLLM Candidate Reranker │
│ Native-read only selected raw-frame Evidence│
│ Input Top-100 state, output all logits       │
└──────────────────────┬──────────────────────┘
                       ↓
┌─────────────────────────────────────────────┐
│ 8. State Update + Stop / Continue            │
└─────────────────────────────────────────────┘
```

---

# 3. 最重要的设计边界

## 3.1 每轮只新增一个 Item-Segment 的深层视频信息

假设当前选择了 Item A 的 Segment 2：

```text
A-Segment2
   ↓
Segment Embedding Encoder
（CLIP / Video Encoder / 其他 Embedding 模型）
   ↓
Deep Segment Tokens / Embedding
```

这一轮不会同时深度编码所有候选视频。

但这不意味着 Reranker 只输入 A。

## 3.2 每轮重排必须输入整个候选集合

```text
Item A：Base State + 新 Evidence
Item B：Base State + 当前 Evidence / Empty Evidence
Item C：Base State + 当前 Evidence / Empty Evidence
                         ↓
           Candidate-aware Reranker
                         ↓
                 A、B、C 全部新分数
```

准确表述：

> **深层信息获取是非对称的，但候选重排是集合级、对称的。**

## 3.3 被观察不等于被加分

新 Segment 可能产生：

- 正向证据：对应 Item 升分；
- 负向证据：对应 Item 降分；
- 无关证据：对应 Item 基本不变；
- 区分性证据：改变多个候选的相对概率。

因此分数更新必须是有符号的：

\[
s_i^t=s_i^{base}+\Delta s_i^t,
\qquad \Delta s_i^t\in\mathbb R
\]

禁止使用只能产生非负增量的设计，例如：

```python
new_score = base_score + sigmoid(delta)
```

建议：

```python
delta = beta * torch.tanh(delta_head(candidate_hidden))
new_score = base_score + delta
```

---

# 4. Cheap Proxy 与 Deep Evidence

这是主动感知成立的必要前提。

## 4.1 Cheap Segment Proxy

所有 Segment 都允许提前获得廉价信息：

- 1～2 个低密度关键帧；
- CLIP Image Embedding；
- 标题、字幕、ASR 的轻量文本 Embedding；
- Segment 时间位置；
- 简单运动强度；
- 场景类别；
- 音频类别；
- 低分辨率视觉统计信息。

记为：

\[
z_{i,j}^{cheap}
\]

用途：

- 输入 Segment Value Model；
- 粗略判断 Segment 可能包含什么；
- 不能直接替代深层推荐证据。

## 4.2 Deep Segment Evidence

只有 Segment 被选中后，才进行更昂贵的处理：

- 8～16 个密集帧；
- VideoMAE / InternVideo 等时序视频编码器；
- 可选音频、字幕联合编码；
- 保留 frame/token-level representation；
- Preference-conditioned Cross Attention。

记为：

\[
H_{i,j}^{deep}\in\mathbb R^{L\times d}
\]

或聚合后的：

\[
e_{i,j}^{deep}\in\mathbb R^d
\]

## 4.3 不允许的信息设计

不建议把所有 Segment 的 Deep Embedding 全部提前输入线上 Reranker，因为这样会削弱主动感知问题：

```text
如果所有深层信息已经获得
→ 为什么还需要 Segment Value Model？
```

训练阶段可以离线预计算 Deep Embedding 以提高实验效率，但评测时必须将其视为按需获取，并统计：

- Deep-encoded Segments 数量；
- Deep-encoded Frames 数量；
- Segment Embedding Encoder FLOPs；
- 推理延迟或 GPU 时间。

---

# 5. 模块一：Hybrid User Preference Modeling

本模块复用现有 `Dynamic Hybrid User Memory`，不是重新从 SASRec embedding 聚类一套用户兴趣。P3 已确认两种 embedding 空间彼此独立：SASRec 使用数据集内可训练的 Item-ID embedding；Memory 使用固定语义编码器产生的 item semantic embedding。二者只在 Recommendation State 及后续主动感知组件中汇合。

## 5.1 输入

```python
user_history = [item_1, item_2, ..., item_t]
```

每个历史行为可包含：

- Item ID；
- 时间戳；
- 点击、观看、完播、点赞、收藏等反馈；
- 可用的 Item 基础文本或多模态特征。

## 5.2 输出

```python
UserState = {
    "sequence_embedding": Tensor[d],
    "preference_atoms": Tensor[M, d],
    "atom_types": ["stable", "emerging", "fading", ...],
    "atom_weights": Tensor[M],
}
```

## 5.3 V1 建议

上面的 `UserState` 只是模型内部 batch 示意。公共输出仍是既有 `UserMemoryView`：包含 long/short summaries、stable/emerging/fading、drift、atom embedding refs 和相似度矩阵 ref。原始 embedding 留在外部向量资源中，不放进公共 State/Trace。

第一版不需要让动态兴趣模块过度复杂。

可采用：

1. 复用 P3 的 item semantic prototype 与 BGE-M3 dense embedding；
2. recent-5 positive observations 形成 Short Memory，累计语义原型形成 Long/Pending Memory；
3. 通过 cosine matching、EMA 与固定状态规则得到 Stable、Emerging、Fading 和 drift；
4. reranker 内部把 Memory semantic embedding 与 SASRec ID embedding 分别投影到共同的 `d_model`，不得直接假定二者同空间。

该模块是支撑模块，不应抢占 Segment Value Model 的核心贡献。

---

# 6. 模块二：SASRec Cheap Initial Ranking

## 6.1 职责

SASRec 只负责：

- 行为序列建模；
- 候选生成或基础候选打分；
- 提供 Base Ranking Prior；
- 提供用户 Sequence Embedding；
- 为 Recommendation State 提供基础分差。

SASRec 不负责读取新获得的视频 Segment Evidence。

当前 baseline 也不读取 Dynamic Memory：粗召回只由行为 ID 序列、SASRec user hidden state 与 Item-ID embedding 完成。Memory-aware recall/fusion 是后续独立消融，不得混入 SASRec-only baseline。

## 6.2 输入

```python
SASRecInput = {
    "user_history_ids": LongTensor[T],
    "candidate_item_ids": LongTensor[K],
}
```

## 6.3 输出

```python
SASRecOutput = {
    "user_sequence_embedding": Tensor[d],
    "candidate_base_embeddings": Tensor[K, d],
    "base_scores": Tensor[K],
}
```

## 6.4 候选集构造

训练时：

- 使用真实下一交互 Item 作为正样本；
- 使用 SASRec Top-K 中未交互 Item 作为 hard negatives；
- 必要时加入部分随机 negatives；
- 保证 Ground Truth 位于候选集合中。

示例：

```text
History: i1 → i2 → i3
Ground Truth: i4
Candidates: [i4, n1, n2, ..., nK-1]
```

上述 target 保证只适用于 reranker **训练样本**，并必须显式标记为 `target-injected training candidates`。validation/test 绝不注入 target：target 不在 SASRec Top-K 时计 retrieval miss，不进入条件 reranking scorer；实验同时报告 conditional reranking 和 end-to-end retrieval 指标。

P4-02 正式 research protocol 固定为 `SASRec recall 100 → Agent/reranker candidates 100 → final output Top-1`。Active search 不设固定 Top-L：对 Top-100 中所有 media/proxy-complete 的未观察 segments（每 item 最多 12 段）批量计算 cheap value，每轮只深度编码全局 argmax 的一段。无媒体 item 仍保留在 reranking pool；整个 state 无 eligible segment 时在感知前停止。

---

# 7. 模块三：Recommendation State 与 Information Need

Recommendation State 表示“当前知道什么、当前排序如何、还剩多少预算”。以下是组件内部 batch 的概念字段，不是新的公共 dataclass：

```python
RecommendationState = {
    "user_state": UserState,
    "candidate_ids": LongTensor[K],
    "base_scores": Tensor[K],
    "current_scores": Tensor[K],
    "current_ranking": LongTensor[K],
    "candidate_margin": Tensor[K],
    "ranking_entropy": float,
    "top1_top2_margin": float,
    "evidence_bank": Dict[item_id, List[Evidence]],
    "observed_segment_mask": BoolTensor[K, S],
    "remaining_budget": int,
}
```

## 7.1 Ranking Uncertainty

跨组件时继续使用既有 `RecommendationState`、`EvidenceState`、`ObservationState` 和 `ResourceRef`；不得把上面的 Tensor、raw frames 或完整 Evidence Bank 内嵌进 JSON/trace。

在每轮 Segment Value 预测之前，既有 `InformationNeedEstimator` 必须先从 Memory、当前竞争格局和 Evidence gap 产生 item-agnostic `InformationNeed`。它用于告诉 Value Model 当前缺哪一类信息，也可作为 preference adapter/reranker 的条件输入；它不能预先绑定某个 item，也不能读取 held-out target。

V1 可先使用：

- Top-1 / Top-2 Margin；
- Candidate Softmax Entropy；
- Ground-truth-free score dispersion；
- 多模型分歧作为后续增强。

## 7.2 停止条件

可组合：

```python
stop = (
    ranking_entropy < entropy_threshold
    or top1_top2_margin > margin_threshold
    or max_segment_value < perception_cost_threshold
    or remaining_budget == 0
)
```

当前是 single-target next-item task，因此 Top-1/Top-2 margin 作为停止 baseline 合理：只要第一名足够稳定，即使 rank10/rank11 仍不确定也可以停止。margin 必须用归一化/校准后的 request-local score，并仅在 validation 选择阈值；同时保留 `max_segment_value < cost`，避免有高预期价值片段时仅凭未校准 raw-logit margin 过早停止。

---

# 8. 模块四：≤1B Recommendation-aware Multimodal Segment Selector

## 8.0 P4-ARCH-02 Active Selector Contract

最终 proposed `SegmentValueModel` 是不超过约 1B 的判别式多模态 Selector。它不依赖独立 CLIP shortlist，
必须为完整 Top-100 内全部 eligible `(item, segment)` 输出一一对应 scalar values。

它不是常见的 single-video keyframe selector：后者只在一个视频内部找最显著/最相关的 frame 或 clip；本任务
同时面对多个候选视频、每个视频多个 segments，并根据用户 Memory、Information Need、SASRec competition 和
已有 Evidence 做跨 item 全局选择。Selector 因此采用 frame → segment → item context → cross-item global scoring
的层级结构，输出目标仍是一个 `(item, segment)`，不是一张 frame。

```text
per-segment low-resolution frames（3/6/8/...）
    → Selector-owned vision tower/tokenizer
    → cacheable compact frame tokens
    → Query/Memory-conditioned local resampler
    → one segment token per segment
    → within-item segment context + item rank/score token
    → cross-item global set/listwise scorer over all segments
    → expected recommendation gain values
```

工程上不能把最多约 1200 segments 的数千 raw images 拼成一个全局 MLLM context。Local visual encoding/
compression 在 segment 内批处理；global scorer 目标只看到约 1200 个 segment-level tokens。Content tokens
绑定 exact frame recipe/resolution/vision checkpoint/processor，可跨用户复用；Query-conditioned representations/
values 不可跨用户复用。Vision tower 更新后必须重建 cache。

Selector 输入包括 Information Need/Query、Memory、SASRec score/rank、item/segment metadata、observation state 和
compact visual tokens。它通过 scalar head 输出数值，不生成文字。100M/300M/500M/1B、tokens/frame、
tokens/segment、frame count、vision freeze/unfreeze 和 CLIP-shortlist comparator 均作为 versioned experiments。

P4-04 Chinese-CLIP Query-relevance 只用于 Selector 训练前 bootstrap 和 baseline，不是 proposed path 的前筛。

训练依赖固定为：先训练并冻结 native-frame MLLM Reranker，再用其 before/after utility 构造
`Δ log p(target) - λ cost` labels，最后训练 Selector。第一版不传播 Reranker gradient、不联合训练；
alternating/distillation/joint/RL 延后 P6/P7。

## 8.H Historical expected-gain abstraction

## 8.1 职责

Value Model 在尚未深度观察 Segment 前预测：

> 深入编码该 Segment，预计能给当前推荐决策带来多大边际收益？

它不是预测：

- 该 Segment 是否语义相关；
- 该 Item 是否是正样本；
- 该 Item 应该加多少分。

它预测的是：

\[
\hat V_{i,j}=V_\theta(S_t,z_{i,j}^{cheap})
\]

## 8.2 输入

```python
SegmentValueInput = {
    "user_embedding": Tensor[d],
    "preference_atoms": Tensor[M, d],
    "candidate_state": Tensor[K, d_c],
    "ranking_state": Tensor[d_r],
    "evidence_state": Tensor[d_e],
    "cheap_segment_proxy": Tensor[d_p],
    "segment_metadata": Tensor[d_m],
    "remaining_budget": int,
}
```

## 8.3 输出

```python
SegmentValueOutput = {
    "segment_value": float,
}
```

可选扩展输出：

```python
{
    "expected_gain": float,
    "expected_uncertainty_reduction": float,
    "estimated_cost": float,
}
```

## 8.4 Value Label

Value Model 的 label 不能直接来自用户点击。

应先训练并冻结 Reranker，然后做观察前后反事实展开：

\[
y_{i,j}^{value}
=
U(R_{t+1})-U(R_t)-\lambda C_{i,j}
\]

其中：

```text
R_t：当前 Evidence State 下的排序
R_t+1：加入该 Segment Deep Evidence 后的排序
U：NDCG、MRR、目标 Item log-probability 等推荐效用
C：Segment 编码成本
```

推荐第一版标签：

\[
y_{i,j}^{value}
=
\log p_{t+1}(i^*)-\log p_t(i^*)-\lambda C_{i,j}
\]

同时可做 Pairwise Value Ranking：

```text
同一 Recommendation State 下
哪个 Segment 带来的真实收益更高
→ Value Model 应输出更高分
```

---

# 9. 模块五：On-demand Selected Raw-frame Evidence Publisher

## 9.0 P4-ARCH-02 Active Frame Contract

最终主线的 `SegmentPerceiver` 不负责运行 Chinese-CLIP 或 8B MLLM。它只对已选择 segment 做 deterministic
decode，并发布 processor-independent raw-frame Evidence：

```text
selected segment
    → eight-bin-center target timestamps
    → nearest-PTS / invalid-frame filtering
    → retain 2—8 real RGB frames + mask
    → atomic content-addressed frame bundle
    → Evidence.raw_output_ref
```

Frame manifest 绑定 media/segment identity、timestamps、frame checksums、codec/color space、sampling recipe、
payload sizes 和 SHA-256。少于两张有效帧 fail closed。Raw-frame bundle 是 content-only，可跨用户复用；
Selector compact tokens、Chinese-CLIP comparator tokens 和 MLLM-native vision caches 是分别绑定 checkpoint/
processor 的 derived artifacts。`Evidence.embedding_ref` 仅在存在这些 exact derived tokens 时使用。

约 8B MLLM Reranker 在 `ScoreUpdater` 内使用 native processor 读取 frame bundle。它只看已观察 segments，
不看 Top-100 全部视频。Exact 4/8/16/32 frame count、resolution、native image/video API 和 multiple-Evidence
packing 由 P4-07/P6 配置与实验确认。

## 9.H Historical Segment Embedding Extractor / Small-latent Comparator

## 9.1 模块定位

这个模块不是额外的“推理 Agent”，也不是必须生成文本的 MLLM。

它的职责只有一个：

> **把被选中的原始视频帧转换成可以输入 Multimodal Reranker 的 Segment Embedding 或 Segment Tokens。**

因此，“Encoder”在这里本质上就是视频 Embedding 提取模型。

可以使用：

- CLIP Image Encoder：逐帧提取 Embedding，再进行 Temporal Pooling；
- VideoMAE、InternVideo 等 Video Encoder：直接输出时空视频表示；
- 其他预训练视觉/视频 Embedding 模型；
- 可选地使用 MLLM 的 Vision Tower，但不运行语言模型解码器。

主线不要求生成式 MLLM。

## 9.2 V1 建议的两种 Embedding 提取方案

### 方案 A：CLIP Frame Embedding

```text
Selected Segment
→ 均匀抽取 8～16 帧
→ CLIP Image Encoder
→ Frame Embeddings [F, d]
→ Mean / Attention / Temporal Transformer
→ Segment Embedding [d] 或 Segment Tokens [L, d]
```

优点：

- 实现简单；
- 容易离线缓存；
- 计算成本低；
- 适合作为 V1 首先跑通的版本。

缺点：

- 对动作、前后状态变化和复杂时序语义建模较弱。

### 方案 B：预训练 Video Encoder

```text
Selected Segment
→ 8～16 Frames
→ VideoMAE / InternVideo / 其他 Video Encoder
→ Spatiotemporal Tokens [L, d]
→ 直接送入 Reranker 或先聚合为 Segment Embedding
```

优点：

- 能建模帧间运动和时序变化；
- 通常比逐帧 CLIP 表达更强。

缺点：

- 计算与存储成本更高；
- 工程复杂度更高。

历史 P4-05 曾确认 pinned `OFA-Sys/chinese-clip-vit-base-patch16` latent-token baseline；P4-ARCH-02 已将其
从最终主线降为 Query/proxy/bootstrap 与 Small-latent comparator。最终 MLLM Reranker 原生读取 raw frames。

## 9.3 输入

```python
SegmentEmbeddingInput = {
    "frames": Tensor[F, 3, H, W],
    "audio": Optional[Tensor],
    "subtitle_tokens": Optional[Tensor],
}
```

V1 对 selected segment 目标采样八帧视觉输入。

这里的历史 token baseline 在 segment 被选中之后，将该 segment 均分为八个时间 bin，并取各 bin 中心
`6.25/18.75/31.25/43.75/56.25/68.75/81.25/93.75%`。经 deterministic nearest-PTS、去重和无效帧过滤后，
保留 2—8 张真实有效帧及 mask，不复制补满；少于两张时 typed failure。每帧由 frozen Chinese-CLIP image
tower 输出 FP32、L2-normalized 512-D token，artifact 主输出为有序 `[F,512]` frame tokens，不在本阶段提前池化。
该 recipe 不改变 scene detection、最多 12 段、25/50/75 proxy baseline 和 medoid anchor 契约；proxy 的
低清多帧/其他密集采样以及 Deep Encoder 的 4/8/16/32 帧均留作独立实验。MLLM 文本对比支线公平比较时另报
matched-frame 设置、实际 frames 和 FLOPs。

## 9.4 输出

研究接口可以比较两种输出形式，但 P4/V1 已确认使用多个 ordered frame tokens，不提前池化。

### 单个 Segment Embedding

该形式只作为后续 pooling baseline，不是 P4/V1 主线。

```python
SegmentEmbeddingOutput = {
    "segment_embedding": Tensor[d],
}
```

适合：

- V1 简化实现；
- 直接拼接或投影后输入 Reranker；
- 降低显存和计算成本。

### 多个 Segment Tokens

```python
SegmentEmbeddingOutput = {
    "segment_tokens": Tensor[L, d],
    "pooled_segment_embedding": Tensor[d],
}
```

适合：

- 保留局部视觉和时序信息；
- 在 Reranker 内部进行 Cross-Attention；
- 使用可选 Evidence Adapter。

历史 Chinese-CLIP comparator 的 exact 输出是 finite FP32 `frame_tokens[F,512]`（`2 <= F <= 8`，row-wise
L2 normalized）与八个目标 slot 的 valid mask；它不是 ARCH-02 final Reranker 的主输入。

历史 latent comparator 将 tokens 发布为独立 derived bundle，并通过 `Evidence.embedding_ref` 引用。ARCH-02
主 Evidence 则通过 `Evidence.raw_output_ref` 指向 selected raw-frame manifest；公共 State/Trace 均不内嵌 payload。

P4-06 只按 action order 保存 per-segment Evidence，不生成 item-level aggregate ref；P4-07 MLLM 直接读取
action-ordered raw-frame refs。所有 raw/token bundles 都必须原子发布并校验 closure；partial/missing/corrupt/
cache mismatch 均 fail closed，不产生 Evidence、不改变排名。

## 9.5 冻结策略

V1 建议：

- 冻结 CLIP / Video Encoder；
- 将提取出的 Segment Embedding 直接输入 Reranker；
- 只训练投影层、Evidence Aggregator 和 Candidate-aware Reranker；
- 训练稳定后，再考虑对 Encoder 后几层做 Partial Fine-tuning 或 LoRA。

---

# 10. 可选模块：Preference-conditioned Evidence Adapter

## 10.1 是否必须

**不是必须。**

主线默认可以直接采用：

```text
Segment Embedding / Tokens
        ↓
Small Candidate-aware Multimodal Reranker
```

也就是说，被选 Segment 的 Embedding 可以直接作为对应 Item 的新增多模态信息输入 Reranker。

Evidence Adapter 只是一个可选增强，用于在进入候选级重排之前，先让用户 Preference Atoms 从 Segment Tokens 中抽取用户相关信息。

## 10.2 两种工程实现

### 实现 A：直接 Embedding 输入 Reranker（V1 默认）

```text
Segment Embedding
+ User Embedding
+ Item Base Embedding
+ SASRec Score
        ↓
Candidate-aware Multimodal Reranker
```

Reranker 内部可以通过：

- 拼接 + MLP；
- Gated Fusion；
- User-Segment Cross-Attention；
- Candidate Transformer；

自行学习用户与视频 Embedding 的交互。

优点：

- 模块少；
- 工程简单；
- 便于先验证主动 Segment 选择是否有效。

### 实现 B：增加 Preference-conditioned Evidence Adapter（增强方案）

```text
Preference Atoms
        ↓ Query
Segment Tokens
        ↓ Key / Value
Cross-Attention
        ↓
Personalized Evidence
        ↓
Candidate-aware Reranker
```

形式为：

\[
E_{i,j}
=
\operatorname{CrossAttention}
(Q=P_u,K=H_{i,j}^{deep},V=H_{i,j}^{deep})
\]

输出示例：

```python
Evidence = {
    "item_id": int,
    "segment_id": int,
    "preference_conditioned_tokens": Tensor[M, d],
    "pooled_evidence": Tensor[d],
}
```

优点：

- 用户条件化更明确；
- 能保留“不同 Preference Atom 关注不同视觉内容”的解释；
- 可能更适合复杂多兴趣建模。

缺点：

- 模块更多；
- 训练和消融更复杂；
- 与 Reranker 内部 Cross-Attention 可能功能重复。

## 10.3 推荐决策

建议工程上同时保留配置开关：

```yaml
reranker:
  evidence_mode: direct_embedding  # direct_embedding | preference_adapter
```

默认：

```text
direct_embedding
```

后续通过消融实验比较：

```text
Direct Segment Embedding
vs
Preference-conditioned Evidence Adapter
```

## 10.4 Evidence Bank

无论是否使用 Adapter，都需要为每个 Item 保存当前已观察的 Segment 表示：

```python
EvidenceBank = {
    item_A: [z_A_1, z_A_2],
    item_B: [z_B_1],
    item_C: [],
}
```

其中 `z` 可以是：

- 原始 Segment Embedding；
- Segment Tokens；
- Preference-conditioned Evidence。

多轮表示可通过 Mean Pooling、Attention Pooling 或 Evidence Transformer 聚合。

---

# 11. 模块六：Native-frame MLLM Candidate Reranker

这是 P4-ARCH-02 的最终重排主模型。

## 11.0 Active 7—9B MLLM Contract

```text
SASRec user/prior + Dynamic Memory
+ Top-100 compact candidates
+ action-ordered selected raw-frame Evidence
+ acquisition Query/step
    → native-frame 7—9B MLLM
    → candidate marker hidden states
    → shared scalar scoring head
    → Top-100 numeric logits
```

约束：只观看已观察 segments；不观看全部候选视频；不生成 JSON/自然语言数字；输出覆盖全部候选；训练时
随机 candidate serialization 并提供显式 identity/rank；每轮从 initial SASRec prior + full current EvidenceState
纯函数式重算。第一版优先 LoRA/QLoRA，listwise CE + no-evidence prior consistency + mask/mismatch objectives。
Exact model/revision/context/native frame packing/scoring head 由 P4-07 确认。

## 11.H Historical Small Candidate Transformer Comparator

## 11.1 核心职责

- 读取用户行为先验；
- 读取全体候选基础状态；
- 读取当前部分候选已获得的 Segment Embedding / Tokens；
- 在候选集合内进行相对比较；
- 同时输出所有候选的新 logits。

## 11.2 单个候选输入

对候选 Item \(i\)：

\[
x_i^t=
[
 h_u^{seq};
 h_i^{base};
 s_i^{base};
 \bar e_i^t;
 m_i^t;
 n_i^t;
 r_i^t
]
\]

包括：

- 用户 Sequence Embedding；
- Item Base Embedding；
- SASRec Base Score；
- 当前聚合的 Segment Embedding / Evidence；
- 是否已观察；
- 已观察 Segment 数量；
- 当前排名与分差信息。

## 11.3 Empty Evidence

未观察候选不能直接使用全零且无区分的输入。

建议使用：

- 可学习的 `NO_EVIDENCE` Embedding；
- 独立 observed mask；
- evidence count；
- 训练中加入 mask invariance 约束。

```python
if len(evidence_bank[item_id]) == 0:
    evidence_repr = no_evidence_embedding
```

## 11.4 Candidate-aware Listwise Interaction

```python
candidate_tokens = build_candidate_tokens(...)
contextualized = candidate_transformer(candidate_tokens)
delta_scores = delta_head(contextualized)
final_scores = base_scores + beta * tanh(delta_scores)
```

Candidate Transformer 的 Self-Attention 允许：

- A 的负向证据降低 A；
- A 降低后 B 的相对概率上升；
- 同一证据根据其他候选状态产生不同作用。

## 11.5 输出

```python
RerankerOutput = {
    "candidate_logits": Tensor[K],
    "candidate_probs": Tensor[K],
    "candidate_delta_scores": Tensor[K],
    "new_ranking": LongTensor[K],
}
```

---

# 12. Native-frame MLLM Reranker 的 Label

## 12.1 主 Label

Reranker 的主 label 直接来自真实用户下一次交互 Item。

```text
History: [i1, i2, i3]
Ground Truth Next Item: B
Candidates: [A, B, C, D]
Target Index: 1
```

标签：

```python
target_index = candidates.index(ground_truth_item)
```

## 12.2 Listwise Loss

\[
\mathcal L_{rank}
=
-\log
\frac{\exp(s_{i^*})}
{\sum_{i\in\mathcal C}\exp(s_i)}
\]

实现：

```python
loss_rank = F.cross_entropy(candidate_logits, target_index)
```

## 12.3 Segment 本身没有直接正负 Label

禁止：

```text
Ground Truth Item 的所有 Segment = 正 Segment
Negative Item 的所有 Segment = 负 Segment
```

原因：

- 正 Item 中可能存在无关 Segment；
- 负 Item 中可能存在与用户偏好高度匹配但仍不足以改变最终行为的 Segment；
- Segment 的作用需要通过候选排序变化体现。

---

# 13. Reranker 训练数据构造

这是整个主线最需要注意的部分。

## 13.1 同一个候选集合构造多个 Observation State

必须先按 user/time 完成 train/validation/test 划分，再在各 split 内生成 observation variants 与 cache。来自同一个基础 `(history, target, candidates)` case 的 No-Evidence、positive、negative、multi-item 和 shuffled variants 不得跨 split。

同一个训练实例保持：

- User History 相同；
- Candidate Set 相同；
- Ground Truth Item 相同；

只改变：

- 哪些 Item 被观察；
- 每个 Item 观察了哪个 Segment；
- 当前 Evidence Bank 的内容。

## 13.2 推荐的 Observation State 类型

### State A：No Evidence

```text
A: empty
B: empty
C: empty
D: empty
Label: B
```

### State B：Observe Positive Item

```text
A: empty
B: Segment 3 Raw-frame Evidence
C: empty
D: empty
Label: B
```

### State C：Observe Hard Negative

```text
A: Segment 2 Raw-frame Evidence
B: empty
C: empty
D: empty
Label: B
```

### State D：Observe Random Negative

```text
A: empty
B: empty
C: Segment 1 Raw-frame Evidence
D: empty
Label: B
```

### State E：Observe Multiple Candidates

```text
A: Segment 2
B: Segment 3
C: empty
D: Segment 1
Label: B
```

### State F：Observe Irrelevant Segment

```text
B: Logo / Intro Segment
Label: B
```

### State G：Shuffled Evidence

将某个 Item 的 Evidence 替换为其他 Item 的 raw-frame bundle/Query pair，用于对抗训练和 sanity check。

## 13.3 初始采样比例建议

```text
25% No Evidence
25% Positive Item Observed
25% Hard Negative Observed
25% Multi-item / Random Observation
```

后续再细分：

- 高排名负样本；
- 中排名负样本；
- 低排名负样本；
- 有关 Segment；
- 无关 Segment；
- 单 Segment；
- 多 Segment。

## 13.4 训练样本伪代码

```python
def build_reranker_samples(
    user_history,
    target_item,
    sasrec,
    segment_store,
):
    candidates = sasrec.topk(user_history, k=K)

    # 仅训练集允许 target injection；validation/test 不调用本 builder 的注入分支。
    if target_item not in candidates:
        candidates[-1] = target_item

    base_scores = sasrec.score(user_history, candidates)
    target_index = candidates.index(target_item)

    observation_states = [
        sample_no_evidence_state(candidates),
        sample_positive_item_state(target_item, segment_store),
        sample_hard_negative_state(
            candidates,
            target_item,
            base_scores,
            segment_store,
        ),
        sample_random_negative_state(
            candidates,
            target_item,
            segment_store,
        ),
        sample_multi_item_state(candidates, segment_store),
    ]

    return [
        {
            "user_history": user_history,
            "candidates": candidates,
            "base_scores": base_scores,
            "observation_state": state,
            "target_index": target_index,
        }
        for state in observation_states
    ]
```

---

# 14. Selection Bias 与 Observation Bias

## 14.1 风险

如果训练中几乎总是观察 Ground Truth Item，模型会学到：

```text
observed = 1
→ 该 Item 更可能是正样本
→ 自动加分
```

这不是使用了 Segment 内容，而是泄漏了 Selector 的选择结果。

## 14.2 必须遵守的数据平衡

训练时平衡：

1. 正样本与负样本被观察概率；
2. 不同当前排名的 Item 被观察概率；
3. 相关与无关 Segment；
4. 单 Item 与多 Item Observation；
5. 不同 Evidence 数量；
6. 正向、负向、无效 Evidence 情况。

这里的 non-target 只表示该样本的真实 next item 不是它，不代表用户明确 dislike 该视频。Observation sampler 还必须平衡候选 rank、evidence count 与 target/non-target 的被观察概率，避免模型把 selector identity 当标签。

MLLM candidate scoring head 不得依赖候选序列化位置偷学 SASRec rank：训练时随机化 candidate entries 的物理
顺序，同时提供显式 identity/rank feature；验证时增加 permutation-consistency 测试。

## 14.3 必做 Sanity Checks

| 设置 | 输入 | 预期结果 |
|---|---|---|
| Real Evidence | 真实 selected raw frames + acquisition Query | 最好 |
| Zero Evidence | observed mask 但无合法 frame ref | 接近 No Evidence / fail closed |
| Shuffled Evidence | Frames/Query 错配给其他 Item | 显著下降 |
| Selector ID Only | 只告诉哪个 Item 被选 | 接近 Base |
| Random Segment | 随机片段 | 弱于 Value Selection |
| Random Item | 随机候选 | 弱于 Value Selection |

若 `Selector ID Only` 仍能带来明显提升，说明存在观察偏置。

---

# 15. Reranker 辅助损失

第一版先跑通 Listwise CE，再逐步增加辅助约束。

## 15.1 No-evidence Consistency

没有成功 raw-frame Evidence 时，Reranker 应接近 SASRec：

\[
\mathcal L_{base}
=
D_{KL}
(p_{SASRec}\parallel p_{reranker}^{no-evidence})
\]

## 15.2 Mask Invariance

仅改变 observed mask，但不提供有效内容，输出不应明显变化：

\[
\mathcal L_{mask}
=
\|p^{zero-evidence}-p^{no-evidence}\|_2^2
\]

## 15.3 Evidence Sensitivity Sanity Check

Shuffled Evidence 只作为数据级 sanity check，不作为 V1 的逐样本强制 loss。真实的 non-target segment 可能正确提高该 non-target 候选并降低 target 概率；next-item 的 non-target 不等于负反馈，因此不能要求每条 real evidence 都比 shuffle 提高 `p(target)`。

## 15.4 Pairwise Hard-negative Loss

\[
\mathcal L_{pair}
=-\sum_{j\in\mathcal N_{hard}}
\log\sigma(s_{i^*}-s_j)
\]

## 15.5 总损失

\[
\mathcal L_{reranker}
=
\mathcal L_{rank}
+\lambda_1\mathcal L_{base}
+\lambda_2\mathcal L_{mask}
+\lambda_3\mathcal L_{pair}
\]

V1 推荐：

```text
Phase 1：L_rank
Phase 2：L_rank + λ1 L_base
Phase 3：加入 L_mask；L_pair 仅在验证确有增益后启用
```

---

# 16. 主线训练顺序

## Stage 0：数据准备

- 切分用户行为序列；
- 构造 next-item Ground Truth；
- 切分视频 Segment；
- 为所有 Segment 预计算 Cheap Proxy；
- 训练阶段可缓存 Deep Video Embedding。

## Stage 1：训练 SASRec

输入：

```text
User History → Next Item
```

输出：

- User Sequence Embedding；
- Base Candidate Scores；
- Top-K Candidate Set。

训练完成后先冻结。

## Stage 2：准备 Deep Segment Features

对训练数据中的 Segment 离线提取：

```text
8～16 Frames
→ Frozen CLIP / Video Embedding Encoder
→ Segment Embedding or Segment Tokens
```

缓存用于 Reranker 训练。

注意：缓存只是训练工程优化，评测时仍需按需计入感知成本。

## Stage 3：训练 Small Multimodal Reranker（Adapter 可选）

输入：

```text
User State
+ Candidate Base States
+ SASRec Scores
+ Random Partial Segment Embedding State
```

Label：

```text
Ground Truth Next Item Index
```

损失：

```text
Listwise CE + Optional Consistency Losses
```

## Stage 4：冻结 Native-frame MLLM Reranker，构造 Selector Labels

```python
ranking_before = reranker(state)
ranking_after = frozen_mllm_reranker(state.add(selected_raw_frame_evidence))
value_label = utility(ranking_after) - utility(ranking_before) - cost
```

## Stage 5：训练 ≤1B Multimodal Segment Selector

输入：

```text
Recommendation State + Information Need + all eligible compact visual tokens
```

Label：

```text
观察该 Segment 后的真实推荐收益
```

## Stage 6：在线 Agent Rollout

用当前 Value Model 顺序选择 Segment，验证：

- 推荐效果；
- 感知成本；
- 平均感知轮数；
- 不同预算下的性能曲线。

## Stage 7：可选交替/联合训练（非第一版）

```text
Selector 采样新轨迹
→ 可选更新 Reranker
→ 重新计算 Value Label
→ 更新 Selector
```

第一版不做该 Stage，也不建议直接上 RL。

---

# 17. 主线 Agent Loop

P4-ARCH-02 active flow：

```text
build state and Information Need
→ load Selector-owned compact visual refs for every eligible segment
→ ≤1B Selector batch-scores all segments（no external CLIP shortlist）
→ select global argmax
→ publish canonical selected raw-frame Evidence
→ ~8B native-frame MLLM scoring head reranks Top-100
→ rebuild state and stop-or-repeat
```

每轮 MLLM 都从固定 `base_scores + 完整当前 raw-frame evidence_bank` 纯函数式重算。下面的 Python 代码保留为
P4-ARCH-01 historical Small-latent pseudocode，不再是 active implementation recipe。

```python
def active_multimodal_recommendation(
    user_history,
    candidate_items,
    budget,
):
    # 1. User State + SASRec Prior
    user_state = preference_model(user_history)

    sasrec_output = sasrec(
        user_history=user_history,
        candidates=candidate_items,
    )

    base_scores = sasrec_output.base_scores
    current_scores = base_scores.clone()

    evidence_bank = {
        item_id: []
        for item_id in candidate_items
    }

    observed_mask = initialize_segment_mask(candidate_items)

    # 2. Active Perception Loop
    for step in range(budget):
        recommendation_state = build_recommendation_state(
            user_state=user_state,
            candidates=candidate_items,
            base_scores=base_scores,
            current_scores=current_scores,
            evidence_bank=evidence_bank,
            observed_mask=observed_mask,
            remaining_budget=budget - step,
        )

        if ranking_is_confident(recommendation_state):
            break

        information_need = information_need_estimator.estimate(
            recommendation_state
        )

        # Value Model only sees Cheap Proxy
        values = {}
        for item_id, segment_id in unobserved_segments(observed_mask):
            values[(item_id, segment_id)] = segment_value_model(
                recommendation_state=recommendation_state,
                information_need=information_need,
                cheap_segment_proxy=load_cheap_proxy(
                    item_id,
                    segment_id,
                ),
            )

        selected_item, selected_segment = argmax(values)

        if values[(selected_item, selected_segment)] < COST_THRESHOLD:
            break

        # Only selected Segment is deeply encoded
        frames = load_segment_frames(
            selected_item,
            selected_segment,
        )

        segment_repr = segment_embedding_encoder(frames)

        # V1 默认：Embedding 直接输入 Reranker。
        # 可选增强：先经过 preference-conditioned adapter。
        if config.evidence_mode == "preference_adapter":
            segment_repr = evidence_adapter(
                preference_atoms=user_state.preference_atoms,
                segment_tokens=segment_repr,
            )

        evidence_bank[selected_item].append(segment_repr)
        observed_mask[selected_item, selected_segment] = True

        # Rerank all candidates together
        rerank_output = multimodal_reranker(
            user_state=user_state,
            information_need=information_need,
            candidates=candidate_items,
            base_scores=base_scores,
            evidence_bank=evidence_bank,
        )

        current_scores = rerank_output.candidate_logits

    return sort_candidates(current_scores), evidence_bank
```

每一轮 reranker 都是从固定 `base_scores + 完整当前 evidence_bank` 纯函数式重算；`current_scores` 只用于构造下一轮 Recommendation State 与停止判断，绝不再次作为可累加 prior 输入 reranker，否则旧 Evidence 会被重复计算。

---

# 18. Historical Structured-text MLLM/LLM Comparator

该支线用于验证：

> 将视频 Segment 转成结构化文本 Evidence，是否比 ARCH-02 native raw-frame MLLM scoring 更有效或更可解释？

它是对比方法，不是 ARCH-02 主线。

## 18.1 支线架构

```text
SASRec Initial Ranking
        ↓
Segment Value Model 选择 Item-Segment
        ↓
MLLM Perceiver 生成结构化文本 Evidence
        ↓
LLM Reranker 读取：
User Profile + Candidate Info + SASRec Prior + Evidence
        ↓
候选选择概率 / 排序
```

## 18.2 MLLM Evidence 输入

```python
MLLMInput = {
    "selected_segment_frames": Tensor[F, 3, H, W],
    "user_preference_summary": str,
    "current_information_need": Optional[str],
}
```

## 18.3 MLLM Evidence 输出

建议结构化，而不是普通 Caption：

```json
{
  "matched_preferences": [
    {
      "preference": "lightweight running equipment",
      "evidence": "The segment shows a lightweight foam sole",
      "polarity": "positive",
      "confidence": 0.91
    }
  ],
  "negative_evidence": [],
  "new_attributes": [
    {
      "attribute": "heel support",
      "value": "strong",
      "confidence": 0.83
    }
  ],
  "summary": "The segment provides positive evidence for lightweight running usage."
}
```

## 18.4 LLM Reranker 输入

```text
[User Preference State]
Stable / Emerging / Fading interests

[Candidate Prior Ranking]
A: SASRec score ...
B: SASRec score ...
C: SASRec score ...

[Observed Evidence]
A: ...
B: none
C: ...

[Task]
Select or rank the candidate most likely to be interacted with next.
```

## 18.5 LLM Reranker 输出

不建议自由生成任意浮点数。

建议：

- 为候选绑定 `<A> <B> <C>` Token；
- 读取候选 Token 的生成概率；
- 或输出固定格式排列。

```python
candidate_probs = softmax([
    logit_token_A,
    logit_token_B,
    logit_token_C,
])
```

## 18.6 LLM Reranker 训练 Label

与 Small Reranker 一样：

```text
Label = Ground Truth Next Item
```

SFT：

\[
\mathcal L_{LLM}
=-\log P(i^*\mid context)
\]

可选后续：

- GRPO 做候选选择；
- Reward = 是否选中真实下一 Item；
- 不建议第一版同时对 Selector 和 LLM 做 RL。

---

# 19. ARCH-02 主线与容量/表征对比

## 19.1 必须统一

- 相同用户历史；
- 相同候选集；
- 相同 SASRec Base Scores；
- 做 evidence/reranker 表征公平比较时使用相同选中 Segment；
- 相同感知预算；
- 相同 Ground Truth；
- 相同 Segment 切分。

不能把由某个 downstream Reranker gain labels 训练出的同一个 Selector 自动称为其他分支的公平 selector。
端到端对比若让各分支自行选段，应分别用各自冻结 Reranker 生成 labels 并训练 branch-specific Selector；
固定相同 segments 的实验用于单独比较 evidence/reranker representation。

## 19.2 主要区别

| 维度 | Native-frame ~8B MLLM | Small latent Reranker | Structured-text LLM |
|---|---|---|---|
| Segment 表示 | selected raw frames / native vision tokens | Chinese-CLIP/video tokens | MLLM text Evidence |
| 排序器 | MLLM + scalar scoring head | 小型 Candidate Transformer | LLM/token ranking |
| 数值输出 | direct tensor logits | direct tensor logits | token probability / structured output |
| 高层语义推理 | 强 | 中等 | 强 |
| 推理成本 | 高 | 低 | 高 |
| 主线定位 | 是 | 容量/成本对比 | 表征/解释对比 |

## 19.3 推荐对比设置

```text
A. SASRec Only
B. Query-relevance Segment + Native-frame MLLM
C. CLIP-shortlist + learned Selector + Native-frame MLLM
D. All-eligible ≤1B Selector + Native-frame MLLM   ← 主方法
E. Same selected segments + Small latent Reranker  ← 容量/成本对比
F. Same selected segments + Structured-text LLM   ← 表征/解释对比
G. All-Segment reference where feasible
H. Oracle Segment under same budget                ← Selection upper bound
```

---

# 20. 核心实验与指标

## 20.1 推荐效果

- HR@1 / HR@3 / HR@5；
- NDCG@K；
- MRR；
- Recall@K；
- 目标 Item 的平均概率；
- Top-1 Accuracy。

## 20.2 感知成本

- Average Perceived Segments；
- Selector low-resolution frames / compact tokens / FLOPs；
- Selected raw frames；
- MLLM visual/text tokens and calls；
- Average Latency；
- GPU Memory；
- Performance-Cost Curve。

## 20.3 Agent 指标

- Segment selection hit rate；
- Value prediction correlation；
- Regret against Oracle Segment；
- Average stopping step；
- Budget utilization；
- Ranking uncertainty reduction。

## 20.4 Reranker 消融

- Candidate-marker listwise head vs independent/chunked scoring；
- Native image vs video API and multiple-Evidence packing；
- 3B/8B/larger scale、LoRA/QLoRA/full tune；
- Remove SASRec Prior；
- Remove Base Consistency；
- Remove observation balancing；
- MLLM Reranker with No Evidence；
- Small latent/text-only Reranker（容量控制）；
- Zero / Shuffled Evidence；
- Positive-only observation training。

---

# 21. 推荐代码目录

以下目录仅表示职责映射，不授权创建第二个 `project/` 根。实际实现必须落在现有 `src/pave_rec`、`configs`、
`tests` 与既有 CLI 中：raw-frame publisher 实现 `SegmentPerceiver`，frame manifest 通过
`Evidence.raw_output_ref` 引用，model-specific tokens 可选使用 `embedding_ref`；≤1B Selector 实现
`SegmentValueModel`，native-frame MLLM Reranker 实现 `ScoreUpdater`，循环继续由 `AgentController` 驱动。

```text
project/
├── configs/
│   ├── sasrec.yaml
│   ├── preference_model.yaml
│   ├── segment_value_model.yaml
│   ├── segment_embedding_encoder.yaml
│   ├── multimodal_reranker.yaml
│   └── llm_reranker.yaml
│
├── data/
│   ├── sequence_builder.py
│   ├── candidate_builder.py
│   ├── segment_splitter.py
│   ├── cheap_proxy_builder.py
│   ├── deep_feature_cache.py
│   └── observation_state_sampler.py
│
├── models/
│   ├── sasrec.py
│   ├── preference_model.py
│   ├── recommendation_state_encoder.py
│   ├── segment_value_model.py
│   ├── segment_embedding_encoder.py
│   ├── evidence_adapter.py          # optional
│   ├── evidence_aggregator.py
│   ├── candidate_aware_reranker.py
│   └── llm_reranker.py
│
├── agents/
│   ├── active_perception_agent.py
│   ├── stop_policy.py
│   └── rollout.py
│
├── training/
│   ├── train_sasrec.py
│   ├── train_reranker.py
│   ├── build_value_labels.py
│   ├── train_value_model.py
│   └── train_llm_reranker.py
│
├── evaluation/
│   ├── ranking_metrics.py
│   ├── cost_metrics.py
│   ├── value_metrics.py
│   ├── bias_sanity_checks.py
│   └── compare_rerankers.py
│
└── scripts/
    ├── preprocess.sh
    ├── train_mainline.sh
    ├── train_llm_baseline.sh
    └── evaluate_all.sh
```

---

# 22. 关键数据结构建议

本节 dataclass 只表示训练器内部 batch/view，不是新的公共 schema。公共 State/Trace 必须保持 JSON-compatible，只携带标量、ID、metadata 和 `ResourceRef`；raw Tensor、frames、latent token 只能存在于组件内部或外部 artifact store。

## 22.1 CandidateState

```python
@dataclass
class CandidateState:
    item_id: int
    base_embedding: torch.Tensor
    base_score: float
    current_score: float
    current_rank: int
    evidence_list: list[torch.Tensor]
    observed_segment_ids: list[int]
```

## 22.2 ObservationState

```python
@dataclass
class ObservationState:
    evidence_bank: dict[int, list[torch.Tensor]]
    observed_mask: torch.Tensor
    step: int
    remaining_budget: int
```

## 22.3 RerankerTrainingExample

```python
@dataclass
class RerankerTrainingExample:
    user_history: torch.Tensor
    candidate_ids: torch.Tensor
    base_scores: torch.Tensor
    observation_state: ObservationState
    target_index: int
```

## 22.4 SegmentValueTrainingExample

```python
@dataclass
class SegmentValueTrainingExample:
    recommendation_state: dict
    item_id: int
    segment_id: int
    cheap_proxy: torch.Tensor
    value_label: float
```

---

# 23. V1 实现优先级

## Implementation Tier A：必须先完成

1. 用户序列与候选构造；
2. SASRec Base Ranker；
3. Segment 切分与 selected raw-frame bundle；
4. Native-frame MLLM input/candidate serialization；
5. Observation State Sampler；
6. 7—9B MLLM + candidate scoring head；
7. LoRA/QLoRA listwise next-item 训练并冻结；
8. Zero / Shuffled Evidence sanity check。

## Implementation Tier B：形成完整主线

1. Frozen-MLLM counterfactual Segment Value Label 构造；
2. Selector-owned compact visual token cache；
3. ≤1B Multimodal Segment Selector；
4. Agent Loop；
5. Stop Policy；
6. Performance-Cost Curve。

## Implementation Tier C：容量与表征对比

1. Small latent/text-only Reranker；
2. Chinese-CLIP relevance 与 CLIP-shortlist + Selector；
3. 3B/8B/larger MLLM scale；
4. 成本、语义能力和可解释性分析。

## Implementation Tier D：增强项

- MLLM Teacher Distillation；
- Full-information Oracle Reranker；
- Selector 与 Reranker label-refresh/交替/联合训练；
- RL Segment Policy；
- 高不确定状态下 MLLM fallback。

---

# 24. 关键风险清单

## 风险 1：Observed Item 自动升分

症状：

- Zero Evidence 也能提升；
- Selector ID Only 有明显效果。

处理：

- 平衡正负候选观察；
- Candidate-aware Listwise 训练；
- Mask Invariance；
- Shuffled Evidence 测试。

## 风险 2：Selector compact tokens 已包含近似完整视频信息

症状：

- Selector 读取过密/过高清 tokens 后本身接近 full-video reasoning；
- 8B MLLM selected-frame Evidence 带来的增益很小。

处理：

- 联合消融 Selector frame resolution/count/tokens-per-segment；
- MLLM 使用更丰富但只属于 selected segment 的 raw frames；
- 分别报告 Selector 与 Reranker 成本，维持两级感知边界。

## 风险 3：Reranker 完全忽略视频 Evidence

症状：

- Real Evidence 与 Shuffled Evidence 结果接近；
- 只靠 SASRec Prior 就能达到相同效果。

处理：

- 增加 hard candidates；
- 提高多模态能区分的候选比例；
- balanced observation training 与 No-Evidence capacity control；
- Real/Zero/Shuffled Evidence 作为数据级 sanity checks；
- 构造行为相近但视频内容不同的候选。

## 风险 4：Segment Value 学成 Query Relevance

症状：

- 选择高度相关 Segment，但不能改善排序；
- 与简单 cosine relevance 接近。

处理：

- Label 必须来自观察前后排序收益；
- 加入 Candidate Competition State；
- 与 Relevance Selector 做强对比。

## 风险 5：主线收益只来自 8B 参数量或训练算力

处理：

- 统一候选、selected segments 和 frame budget；
- 报告参数量、训练 GPU-hours、visual/text tokens、显存和 latency；
- 比较 Small latent、3B/8B 与 text-only MLLM；
- 分离 Selector 改进、视觉 Evidence 改进和 Reranker scale 改进。

---

# 25. 最终方法表述

主线可概括为：

> 首先由 SASRec 基于用户行为历史生成 Top-100 先验，Dynamic Memory 与 Information Need 表达当前偏好缺口；
> 随后，≤1B 多模态 Segment Selector 使用自己缓存的低清多帧 compact tokens，对全部 eligible segments 预测
> expected recommendation gain，而不依赖独立 CLIP shortlist。系统只为最高价值 segment 发布 canonical 原始帧，
> 约 8B native-frame MLLM 通过 candidate scoring head 读取当前全部已观察 Evidence，并对 Top-100 输出数值
> logits。该过程持续迭代，直至 Top-1 足够稳定、剩余 segment 价值低于成本或预算耗尽。

一句话版本：

> **SASRec 提供行为先验，Memory + Query 定义信息缺口，≤1B 多模态 Selector 决定看什么，8B native-frame
> MLLM 只看已选原始帧并重算 Top-100。**

训练顺序可概括为：

> **先训练并冻结 Reranker，再用它生成 counterfactual gain labels 和训练 Selector；第一版不联合训练。**

---

# 26. 当前明确结论

1. **主线使用 ≤1B Multimodal Segment Selector + 约 8B native-frame MLLM Candidate Reranker。**
2. Proposed Selector 不使用独立 CLIP shortlist，并对全部 eligible segments 输出 value。
3. 每轮只为一个被选 Item-Segment 发布 raw-frame Evidence，但 Reranker 输入全体候选 compact state。
4. Reranker 的主 label 是 Ground Truth Next Item，不需要 Segment 人工标签。
5. 同一 Ground Truth 必须构造多种正负均衡的 Observation State；被观察不代表加分。
6. Selector label 来自冻结 Reranker 后的观察前后推荐收益差，训练时分开保存 gain 与 cost。
7. 在线顺序是 Selector → Reranker；训练依赖顺序是 Reranker → labels → Selector。
8. 第一版不联合训练；alternating/distillation/joint/RL 属于 P6/P7。
9. MLLM 通过 scoring head 输出 tensors，不生成自由文本/JSON scores。
10. Small latent/text-only Reranker、Chinese-CLIP relevance 和 CLIP-shortlist + Selector 是主要对比。
11. SASRec 粗召回不消费 Dynamic Memory；Memory 在 Information Need、Selector 和 MLLM Reranker 中使用。
12. validation/test 不注入 target；conditional reranking 与 end-to-end retrieval 必须明确区分。
13. All-Segment 是 full-information reference，同预算 Oracle Segment 才是 selection upper bound。
