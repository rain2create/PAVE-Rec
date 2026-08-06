# Phase 4 Discussion — Real Active Perception Baseline

Status: `In Discussion`

本文档用于逐项确认 Phase 4 的研究与工程边界。它继承已经完成的 P1–P3，目标是尽快跑通
第一条真实的正预算 Agent Loop：真实 Recommendation State 产生 Information Need，选择真实视频
片段，按需提取 latent Segment Evidence，再由 Small Candidate-aware Multimodal Reranker 更新整个候选排序。MLLM 文本 Evidence + LLM Reranker 作为后续系统级对比支线。

本文件中的“推荐 baseline”在用户确认前都只是 proposal。只有对应 Gate 的 Decision Record
变为 `Confirmed` 后才授权实现；未确认选择不能因为实现方便被写死。

---

## 1. Phase 4 的定位

### 1.1 本阶段要完成的闭环

```text
P3 Dynamic Memory + SASRec Top-100 prior
                  ↓
         Recommendation State
                  ↓
     Rule-based Information Need
                  ↓
 Heuristic values for unobserved segments
                  ↓
       select one (item, segment)
                  ↓
   frozen deep segment encoder
                  ↓
     versioned latent Evidence ref
                  ↓
 candidate-aware multimodal rerank
                  ↓
          stop or repeat
```

Phase 4 的完成含义是“真实昂贵路径工程 baseline 可运行、可检查、可回放”，不是最终论文方法
已经训练完成，也不是 PAVE-Rec 已经超过 SASRec。

### 1.2 已完成输入

- P1：公共 schema、组件 Protocol、unchanged `AgentController`、action budget、StopPolicy、
  trace/result 和 saved-output replay；
- P2：exact release、root registry、资源 checksum、Item/Segment Store 和 resolver 边界；
- P3：Tsinghua sampled chronological derived dataset、single-seed SASRec engineering checkpoint、
  Dynamic Memory、item semantics、full-catalog evaluation 和 zero-budget Agent run；
- P3 的 exact artifact graph 和当前 `AgentInputBundle` 可作为 P4 集成开发输入；
- P3 的真实 P2 release 当前有 0 个 segment，P4 必须显式建立 media-complete handoff，不能把
  空 catalog 当成已经接入媒体。

### 1.3 本阶段明确不做

- 不训练 supervised Segment Value Model；其 Oracle、gain label、architecture 和 loss 属于 P5；
- 不声称 heuristic Segment Value 就是论文最终 PAVE-Rec；
- 不做最终多数据集、三 seed、完整 ablation 和显著性主表；它们属于 P6；
- 不在 P4 同步复制 MicroLens 主线；第一条真实闭环只使用 Tsinghua；
- 不做 learned Information Need、Memory-aware initial retrieval/fusion、joint training 或 RL；
- 不解决 cold/OOV target；后期冷启动 track 已记录在 Initial Ranker 计划；
- 不把 held-out target、未来 feedback、Oracle gain 或评价标签输入 online Agent；
- 不因接入真实 Deep Encoder/Small Reranker 而改写 P1 Controller 的 selection、budget 或 state transition 顺序。

### 1.4 P4 与 P5/P6 的边界

| 能力 | P4 | P5 | P6 |
| --- | --- | --- | --- |
| Information Need | 第一条 rule-based baseline | 固定后用于造 Oracle state | ablation / tuning |
| Segment selection | 非学习式 heuristic | supervised expected-gain model | 主实验与消融 |
| Perception / Evidence | 冻结 Deep Encoder + latent ref | 固定用于反事实 label generation | encoder 与 MLLM-text 对比 |
| Score Update | Small Candidate-aware Multimodal Reranker | 冻结后定义 actual gain | 正式评价、容量控制与校准 |
| 数据范围 | Tsinghua media smoke + fixed subset | Tsinghua Oracle subset | Tsinghua 主线、MicroLens 第二主线及辅助集 |

---

## 2. 讨论和确认规则

逐项顺序：

```text
P4-00  P3 handoff、范围和训练前置审计
P4-01  Media subset、segment 和资源契约
P4-02  Agent candidate/search-space protocol
P4-03  Rule-based Information Need
P4-04  Heuristic Segment Value
P4-05  Deep Segment Encoder、selected-segment frames 和 artifact contract
P4-06  Latent Evidence、failure 和 public-ref 边界
P4-07  Small Candidate-aware Multimodal Reranker
P4-08  Runtime、budget、failure、cache、cost 和 replay
P4-09  Evaluation、tests 和 Definition of Done
P4-XG-01 跨 Gate 一致性审计
```

任何 Gate 确认时都要记录：决定、理由、未选方案、受影响接口、测试以及 deferred follow-up。
P4-XG-01 通过前不开始整体主体实现；不依赖后续选择的 audit/fixture 可以提前准备，但不能把结果
冒充已确认研究方案。

### 2.1 持续不变量

1. Information Need 在 item/segment selection 前产生，且本身不绑定一个指定 item。
2. 所有可选未观察 segment 在公共 `SegmentValueModel` contract 下得到一一对应输出；Controller
   仍按 `(value desc, item_id, segment_id)` 确定性选择。
3. 只有最终选择的一个 segment 进入一次昂贵 `SegmentPerceiver.observe()`。
4. Deep Encoder 只产生 latent Evidence；MLLM 对比支线也不得绕过 downstream reranker。
5. ScoreUpdater 每轮从固定 SASRec prior + 完整当前 EvidenceState 重算全部候选，不能删除候选或递归累计旧分数。
6. 一次 `observe()` attempt 消耗一个 action；实际模型调用、frames、tokens、latency 另作成本记录。
7. failed perception 不产生 Evidence、不改变 score，但会留下 observation 和 cost/failure record。
8. online Agent 不读取 held-out label、未来 interaction、Oracle gain 或 Teacher after-state。
9. raw media、frames、MLLM payload 和 embedding 不内嵌公共 State/Trace，只通过 reference/sidecar 关联。
10. 真实模型不要求 byte-exact re-execution；saved-output replay 仍不得重新调用 Deep Encoder/MLLM。

---

## 3. P4-00 — P3 Handoff, Scope, and Training Audit

Status: `Confirmed`

### 3.1 目标

确认 P4 从哪些 exact P3 artifacts 开始、哪些是工程输入而不是论文结果，以及正式训练前必须关闭的
数据审计。

### 3.2 已存在的事实

- 当前 P3 checkpoint 使用项目自行构建的 per-user chronological leave-two-out derived split，cutoff、
  train-only vocabulary 和 warm/cold target 已经做了泄漏防护；
- 当前 checkpoint 是为了跑通工程链路的 fixed single-seed baseline，不是正式三 seed 主结果；
- 清华 processed recommendation package 另有 `x_label=0/1/2` 官方 split，但项目尚未取得并完成
  provenance/时序合法性审计；
- P3 的 zero-budget input 是 101-candidate development smoke，不等于 full-catalog Top-100 research handoff；
- P4 不需要等待最终 benchmark 决策才能用当前 P3 artifacts 完成第一条闭环。

### 3.3 已确认 baseline

1. P4 集成开发继续绑定现有 exact P3 derived/SASRec/Memory/semantic/input artifacts，不重新分割数据，
   也不把当前 single-seed checkpoint包装成正式论文结果。
2. 新建 P4 runtime/artifact graph，保留 P3 refs 并增加 media/proxy/model/prompt refs；不原地修改 P3 artifact。
3. P4 第一条真实闭环只使用 Tsinghua；MicroLens、KuaiRec、KuaiRand 和 M³L 不进入本阶段 DoD。
4. P4 使用 rule-based Need + heuristic Segment Value；supervised value、Oracle 和 learned stop 明确留给 P5+。
5. `AgentController` 和 P1 public schemas/Protocols 默认保持不变。新增真实成本通过已有
   `PerceptionResult.metadata`、`Evidence.raw_output_ref` 和 additive run sidecars 表达。

### 3.4 强制保留的 SASRec 正式训练前检查

以下检查是 cross-phase experiment gate，必须在任何“可报告的清华 SASRec 重训/主 benchmark”前完成；
它不阻塞 P4 使用当前工程 checkpoint 跑第一条闭环：

```text
obtain and pin official processed package
    → checksum x_label=0/1/2 files
    → record train/validation/test counts
    → audit user/item overlap and cold coverage
    → map to raw exposures where possible
    → check per-user train < validation < test time monotonicity
    → decide allowed role of official split
```

- 若严格无未来信息：可评估把官方 split 加入 sequential robustness track；
- 若有 temporal inversion：它只用于上游 static MMRec reproduction，PAVE/SASRec 主线继续使用 versioned
  chronological split；
- 无论结论如何，不能把未经审计的官方 8:1:1 split 直接称为 chronological。

### 3.5 已确认范围

1. P4 的近期目标是“第一条真实正预算 Tsinghua 闭环”，不是直接做最终论文实验。
2. P4 先复用当前 P3 工程 checkpoint；官方 split 审计是正式重训硬门，但不阻塞 P4 集成。
3. P4 不训练 supervised Segment Value、不做 MicroLens，只为 P5/P6 建立稳定真实 baseline。
4. P1 Controller/public contract 默认不改；若后续确实无法表达，必须作为显式 blocker 回来讨论。

### 3.6 本 Gate 不决定

媒体规模、Top-L、segment 数、MLLM、prompt、Evidence 字段、更新公式、budget 数值和 P4 DoD；分别由
P4-01—P4-09 确认。

### P4-00 Decision Record

> 2026-08-05 architecture amendment：下方 Decision 3 中的 `explainable residual Score Update` 已由 P4-ARCH-01 的 `Small Candidate-aware Multimodal Reranker` 主线取代；P3 handoff、rule Need、heuristic Value、正式训练前 split audit、Controller/public contract 等其余决定保持有效。

```text
Decision ID: P4-00
Status: Confirmed
Decision:
1. P4 只完成第一条真实正预算 Tsinghua Agent Loop，复用当前 exact P3 chronological derived dataset、
   single-seed SASRec engineering checkpoint、Dynamic Memory、semantics 和 input artifacts；它们继续明确标为
   integration baseline，不冒充 reportable multi-seed paper result。
2. P4 新增独立 exact runtime/artifact graph 和真实 active-path components，不原地修改 P3 artifacts；
   Tsinghua 是本阶段唯一数据主线，MicroLens/KuaiRec/KuaiRand/M³L 均不进入 P4 DoD。
3. P4 使用 rule-based Information Need、non-learned heuristic Segment Value 和 explainable residual Score
   Update。Supervised Segment Value、Oracle/gain labels 属于 P5，完整 benchmark/ablations 属于 P6。
4. P1 AgentController、public schemas/Protocols、budget/state/selection/trace/replay semantics 默认保持不变；
   MLLM raw output 和真实 cost 通过现有 refs/metadata 与 additive run sidecars 表达。
5. 在任何可报告的清华 SASRec 重训或正式 sequential benchmark 前，必须先取得并固定官方 processed
   package，审计 x_label=0/1/2 split 的 checksum/counts、user/item overlap、cold coverage 和逐用户
   train/validation/test 时间单调性。审计未通过前不得称其为 chronological，也不得用于 SASRec next-item、
   Dynamic Memory 或 Agent prefix；存在 temporal inversion 时只允许用于 static MMRec reproduction。
Rationale:
先复用已经完成泄漏防护和 artifact closure 的 P3 工程输入，可以立即推进真实闭环；把官方 split 审计设为
reportable retraining hard gate，则不会为了赶 P4 把一个尚未证明时序合法的上游 8:1:1 split 带进主实验。
Alternatives considered:
等待官方 split 审计后再开始 P4；在 P4 立即重训 SASRec；把未经审计的 x_label split 直接视为 chronological；
同步建设 MicroLens；在 P4 提前训练 Segment Value；为 telemetry 修改 Controller/public schemas。
Affected schemas/interfaces:
现有 public schema/interface/Controller 不变；P4 后续只允许新增 internal config、artifact、adapter 和 sidecar。
Affected docs/tests:
todo/phase_4_discussion.md；todo/initial_ranker_experiment_plan.md；
todo/benchmark_construction_proposal.md；后续 P4 artifact-closure/leakage/runtime regression tests。
Resolved follow-up:
P4 scope、P3 input role、single-dataset lane、P5/P6 ownership、Controller compatibility 和 SASRec 官方 split
训练前硬检查。
Deferred follow-up:
实际取得官方 processed package 后执行 split audit；P4-01 media handoff；P4-02—P4-09 的具体 baseline；
P5 supervised Segment Value；P6 reportable retraining/multi-dataset experiments。
Confirmed by: User
Date: 2026-08-05
```

---

## 3A. P4-ARCH-01 — Active Multimodal Reranker Architecture Amendment

Status: `Confirmed`

本记录只修正 P4-00 中已经过时的 MLLM + hand-written residual 主线，不改写 P0–P3 已完成事实、P1 Controller/public schema、P3 Memory/SASRec 分离、P4-01 segmentation 或尚待逐项确认的 P4-02—P4-09 参数。

### 已确认主线

```text
Dynamic Memory + SASRec Top-100 prior
              ↓
Recommendation State
              ↓
item-agnostic Information Need
              ↓
heuristic Segment Value（P4）/ learned SVM（P5）
              ↓
select one (item, segment)
              ↓
frozen Deep Segment Encoder
              ↓
latent Evidence ref
              ↓
Small Candidate-aware Multimodal Reranker
              ↓
Top-1-centric stop or repeat
```

1. Deep Segment Encoder 实现既有 `SegmentPerceiver`；latent tensor 存外部 artifact，通过 `Evidence.embedding_ref`/aggregated evidence ref 进入既有 `EvidenceState`。
2. Small Reranker 实现既有 `ScoreUpdater`，每轮输入全体 candidates，并从固定 SASRec base scores + 完整当前 EvidenceState 纯函数式重算；不得输入 previous current scores 形成重复累计。
3. Dynamic Memory 不进入 SASRec 粗召回。它通过 Recommendation State 支撑 Information Need 和 Segment Value，并在 reranker 内部作为用户偏好条件直接影响最终排序；BGE semantic vectors 与 SASRec ID embeddings 分别投影后融合。
4. P4 仍用 rule Need + heuristic Value 尽快跑通 loop；P5 先冻结 Encoder/Reranker，再以 `Δ log p(target) - λ cost` 构造 Segment Value labels。
5. 训练 reranker 时平衡 target/non-target、rank 和 evidence count；先按 user/time split，再生成 observation variants。只在训练构造中允许 target injection，validation/test 不注入。
6. V1 loss 使用 listwise rank + no-evidence consistency + mask invariance；shuffled Evidence 是 sanity check，不使用逐样本强制 `L_sens`。
7. 当前 next-item Agent 是 Top-1-centric：Top-1/Top-2 normalized margin 可作为 stop baseline，但阈值只能在 validation 校准；论文仍报告 NDCG@10、MRR、Recall 等标准指标，并增加 HR@1/Top-1 Accuracy。
8. MLLM structured-text Evidence + LLM Reranker 移至 P6 system-level comparison。固定选段用于 representation/reranker 公平比较；若端到端各自选段，必须训练 branch-specific Value Model。
9. All-Segment 是 full-information reference，不保证是上界；同预算 Oracle Segment 才是 selection upper bound。

### P4-01 additive frame amendment

`scene-hybrid-v1` 的 shot detection、merge/split、最多 12 段、3 个 proxy candidates、medoid anchor 与 MLLM native 3-frame recipe 保持不变。Small Reranker 主线只在 segment 被选中后，额外对该段均匀采 8 帧供冻结 Deep Encoder；公平对比报告 native-frame 与 matched-frame 设置及实际 frames/FLOPs。

### P4-ARCH-01 Decision Record

```text
Decision ID: P4-ARCH-01
Status: Confirmed
Decision: 采用冻结 Deep Segment Encoder + latent Evidence ref + Small Candidate-aware Multimodal Reranker 作为 P4/V1 主线；保留 Information Need；MLLM-text + LLM Reranker 降为 P6 system-level comparison。
Rationale: 该结构能让 segment 内容真正参与集合级排序，同时保留主动感知预算、现有 Agent Controller、可插拔 SegmentPerceiver/ScoreUpdater 与后续 Segment Value 反事实标签。
Alternatives considered: MLLM structured Evidence + hand-written residual；MLLM 直接排序；把 Memory 注入 SASRec 初排；递归 current-score update。
Affected schemas/interfaces: 公共 schema/Controller 不变；只增加 internal model/artifact/config implementations。
Affected docs/tests: README、docs/01/02/05/06/10、active reranker spec、roadmap、Phase 4 gate/test matrix。
Deferred follow-up: exact encoder/revision、reranker capacity、thresholds 与 P4-03—P4-09 逐项决定；candidate/search protocol 已由 P4-02 解决。
Confirmed by: User
Date: 2026-08-05
```

---

## 4. P4-01 — Media Subset, Segment, and Resource Contract

Status: `Confirmed`

### 4.1 要解决的问题

- 当前本地 pinned snapshot 只有 `interaction_sampled.csv`、category mapping 和 README；尚未下载 MP4、
  `video_feature_total`、ASR 或 English title。上游 README 声明这些资源存在，但 P4 publication 前仍要对
  实际取得的文件逐项做 identity/coverage/decode audit；
- 当前 P3 release 没有 segment；真实 MP4/clip 如何与 P3 item ID、cutoff 和 checksum 绑定？
- 第一条 smoke 用官方 item `1..100`，之后如何构造 coverage-driven subset？
- 一个视频切几个 segment、时间边界如何定义、媒体缺失如何处理？
- 如何既避免下载 3.2 TB 全量媒体，又不混用两个行为数据快照？
- P2 当前确认的 filesystem baseline 要求一次 Agent run 的 Item Store 和 Segment Store 共享一个
  `LoadedRelease`。P4 不混用 processed release A/B，而是增加一个只补 segment/media 的 derived overlay；
  该窄化 extension 必须精确绑定一个 base P2 release，并保持旧 P2/P3 path 原样可运行。

### 4.2 已确认 baseline

1. 先对官方 `1..100` media 做结构/映射/解码 smoke；它只证明媒体路径可用，不作为正式 Agent 数据规模。
2. 再发布独立、immutable、带 checksum 的 `p4-media-subset-v1`：它只补充与 exact P3/P2 item IDs
   对齐的 media 和 segment refs，必须显式引用唯一 base P2 `ReleaseManifest` ref、Item Store index
   ref/checksum 和完整 item-catalog identity；不得复制或替换 behavior/item features/labels。
3. 使用新的 `MediaSubsetSegmentStore` adapter 消费该 artifact。它是 P2 release 的受控 derived extension，
   不是第二个 processed release 或行为/item loader；Store 同时持有已验证 base `LoadedRelease` 和 overlay，
   只允许 base catalog 中的 item。未覆盖的合法 base item 返回 empty catalog；已声明 media/ref 缺失、
   source release 不匹配、未知 item、segment 冲突或 checksum 缺失都 fail closed。Overlay 使用自己的
   inventory-verifying resolver，不得让 P2 resolver 绕过 release membership。
4. 第一版不再预设固定 `K=8` 等分，改为已确认的 `scene-hybrid-v1`：先用 shot-boundary detector 找原始
   镜头切换，再用低频 image-text embedding 相似度、boundary confidence 和时长规则做合并/限长，得到数量
   可变但有上限的 perception segments。固定八等分保留为后续 segmentation ablation，而不是主 baseline。
   segment 共享同一个 checksummed MP4 `media_ref`，只保存 `[start_ms, end_ms)`，不物理复制 clips。
5. media-less candidates 仍留在 ranking，但 segment catalog 为空，因此不能被感知；每个 run/实验必须报告
   candidate/item/segment media coverage。
6. subset 选择只用 prediction-time 可得信息和固定 coverage recipe，不依据 held-out target 是否命中来偷偷
   挑用户或补视频。开发 smoke 若为了确保完整路径选择一个已知可运行 state，必须明确标为 smoke。
7. Media identity 与 segment proxy identity 分开：`p4-media-subset-v1` 固定原始视频和时间范围；后续
   `p4-segment-proxy-*` 单独记录视觉 encoder、frame recipe 和 embedding，并精确引用 media manifest。
   替换 proxy 不改变 media identity，也不能把 BGE-M3 text embedding 与未知/不兼容的 256-D upstream
   visual feature 直接做 cosine。

### 4.3 已确认的 `scene-hybrid-v1`

```text
checksummed MP4
    → pretrained shot-boundary detector
    → raw shots + boundary confidence
    → merge low-confidence / very short / semantically similar adjacent shots
    → split very long shots
    → cap the number of perception segments
    → choose sparse representative frames per final segment
```

第一条推荐配置：

1. Primary detector 使用 pinned pretrained TransNetV2 PyTorch inference；它只做 offline shot boundaries，
   不需要在本数据上训练。PySceneDetect AdaptiveDetector 作为 CPU/debug comparator；专门面向短视频的
   AutoShot 只在 official-100 audit 显示 TransNetV2 明显失效时再比较，不阻塞第一条 loop。
2. 不用 `1 fps/2 fps CLIP similarity < threshold` 单独判定 raw cut：稀疏采样可能漏掉短镜头，运动、字幕或
   相似内容硬切也会使单阈值不稳定。CLIP-like embedding 用作 detector 之后的相邻镜头语义合并、长镜头
   低变化点选择和 representative-frame/proxy 构建。
3. 建议从 `min_segment_duration=1.5s`、`max_segment_duration=8s`、`max_segments_per_item=12` 开始，在
   official-100 上通过 segment-count/duration、over/under-segmentation 和 contact sheet audit 调整；这些
   参数必须进入 recipe/version，不能藏成代码常数。
4. 相邻 raw shots 优先按 boundary confidence 和 representative embedding similarity 合并；超过最大时长的
   shot 在低语义变化点切分。若仍超过 segment 上限，按最低边界置信度/最高相邻相似度确定性合并，并记录
   merge/split reason，不能静默截掉视频尾部。
5. 每个 final segment 先在 `25% / 50% / 75%` 位置取最多三张低成本候选帧，过滤黑帧/严重模糊/切换边缘，
   选与本段其他候选最接近的 medoid 作为 anchor；proxy 可以聚合三帧 embedding，而不是只信物理中点。
6. 真正选中 segment 后，MLLM 默认只消费 `anchor-2s / anchor / anchor+2s` 三帧，时间必须 clamp 在同一
   segment 内并去重；短于 4 秒时改用段内 `25% / 50% / 75%`。不得让 `±2s` 跨进相邻场景。
7. Artifact 保存 detector/model revision、preprocessing、raw boundaries/confidence、merge/split provenance、
   final ranges、anchor/candidate timestamps 和 frame checksums。Detector 扫描媒体是一次性 offline cheap
   preprocessing；Agent budget 仍只统计最终被选择 segment 的 MLLM perception。

现有 `SegmentDefinition`/`ItemSegmentIndex` 已支持每个 item 可变 segment 数、连续 sequence index、range
locator、gap/overlap，因此该方案不需要修改 P1 Controller 或公共 Segment schema。P4 producer 另加无 gap、
无 overlap、完整覆盖和最大数量等 recipe-level constraints。

### 4.4 已确认范围

- 使用 derived media overlay，不因补媒体修改/retrain P3 SASRec；它不是第二个 processed release，必须 exact
  bind base P2 release/item catalog，并通过新 adapter/resolver 的完整 integrity tests；
- `scene-hybrid-v1` 替代固定 `K=8` 成为第一版主 segmentation，固定八等分保留为后续 ablation；
- TransNetV2 primary、PySceneDetect comparator、AutoShot conditional alternative；
- `1.5s / 8s / max 12` 是 official-100 audit 的起始参数，不是未经检查的最终常数；
- 每段使用三张 proxy candidates、medoid anchor 和段内 `anchor±2s` MLLM frames；
- 先做 official `1..100` smoke，再按 prediction-time candidate coverage 构造固定 subset，正式规模由
  P4-02 coverage audit 确认；
- 使用 logical ranges、不提前物理切 clips，并以实际媒体 duration 为边界；
- visual proxy 使用单独 versioned artifact 并绑定 media manifest；
- 原视频、frames、ASR 和 content-derived payload 只作本地研究，不提交 Git 或重新分发。

### P4-01 Decision Record

```text
Decision ID: P4-01
Status: Confirmed
Decision:
1. 保留现有 exact P2/P3 artifacts 和旧 filesystem data plane；P4 新增 immutable `p4-media-subset-v1`
   derived overlay、inventory-verifying media resolver 和 `MediaSubsetSegmentStore`。Overlay 精确绑定一个 base
   P2 release、Item Store index/catalog identity，只补 media/segments；不得引入第二套 behavior/items/labels。
2. P4 runtime 继续从 base `LoadedRelease` 读取 Item Store，并由同时验证 base release 与 overlay 的新 Segment
   Store 返回 catalogs。合法但 media-less 的 base item 返回 empty catalog；未知 item、cross-release、missing/
   corrupt declared resource、identity/coverage/checksum mismatch 全部 fail closed。旧 P2/P3 selectors、Stores、
   resolver、goldens 和 zero-budget runtime 不改变。
3. 先对官方 item 1..100 做下载/ID/codec/duration/scene/contact-sheet smoke，再按 prediction-time SASRec
   candidate coverage 构造固定、带版本 subset；不能根据 held-out target 偷选或补媒体。正式 subset 规模由
   P4-02 coverage audit 确认。
4. 第一条主 segmentation 固定为 `scene-hybrid-v1`：pinned TransNetV2 PyTorch inference 产生 raw shot
   boundaries；CLIP-like semantic similarity、boundary confidence 和 duration rules 再做 merge/split/cap。
   PySceneDetect AdaptiveDetector 是 CPU/debug comparator；AutoShot 仅在 official-100 audit 显示 primary 明显
   不适配短视频时评估。固定 K=8 等分降为 segmentation ablation。
5. Official-100 起始参数为 min 1.5s、max 8s、每 item 最多 12 segments；audit 后的任何调整都必须产生新
   recipe/version。Final segments 使用完整、无 gap/overlap 的 half-open logical ranges，共享 checksummed
   MP4，不物理切 clips；实际媒体 duration 是边界事实，CSV duration 只作差异 audit。
6. 每段在 25%/50%/75% 取至多三张候选，过滤黑帧/严重模糊/边界帧，以 embedding medoid 选 anchor；
   selected segment 的 MLLM input 首版为段内去重/clamp 的 anchor-2s、anchor、anchor+2s，短段改用段内
   25%/50%/75%。Detector 全视频扫描属于一次性 offline preprocessing，不消费 Agent action budget。
7. Media manifest 与 `p4-segment-proxy-*` identity 分开但 exact-linked；proxy 记录 encoder/frame recipe/
   embedding provenance。BGE-M3 text embedding 不与未知/不兼容的 upstream 256-D visual features 直接比较。
8. 原视频、frames、ASR、raw/derived media 与 content-derived payload 只用于本地学术研究，不提交 Git、
   不重新分发；公开前必须另做许可/隐私/版权复核。
Rationale:
Scene-aware variable segments 比固定时间八等分更接近真实内容变化；shot detector 负责不漏快速切镜，低频
semantic similarity 负责把镜头整理成适合推荐感知的单位，稀疏 anchor frames 控制 MLLM 成本。Derived overlay
使媒体覆盖可以独立扩展而不重训 ID-only SASRec，同时通过 exact base binding 防止跨数据集/跨 release 混用。
Alternatives considered:
固定 K=8 等分；1/2 fps CLIP threshold 单独切场；只取物理中点；每段传整段密集 frames；AutoShot 直接作为
首个强依赖；每次加媒体重建整个 P2/P3；无 manifest 的本地路径；允许两个独立 processed releases 混用。
Affected schemas/interfaces:
P1 public schemas、AgentController、SegmentStore Protocol、P2 LoadedRelease/Filesystem Stores 和 P3 artifacts
不变。新增 P4 internal media manifest/publisher/resolver/SegmentStore/proxy artifact/config selectors；stable
P2 data-plane 文档增加 exact derived-overlay exception，不放宽任意 cross-release mixing。
Affected docs/tests:
todo/phase_4_discussion.md；todo/benchmark_construction_proposal.md；docs/09_offline_preprocessing.md；
data/README.md；todo/phase_2_discussion.md；后续 media identity/publication/range/coverage/resolver/store、scene
producer、frame recipe、P2/P3 regression 和 overlay corruption/cross-release tests。
Resolved follow-up:
media handoff architecture、P2 compatibility amendment、scene segmentation、sparse frame recipe、two-stage subset、
missing-media semantics、artifact/version/privacy boundary。
Deferred follow-up:
P4-02 已解决 candidate/search protocol；P4-03 已确认 exact semantic proxy encoder/frames 和 Need contract；
P4-04 仍待 Segment Value 组合/threshold；P4-05 exact Deep Encoder/frame preprocessing；official-100 audit 后的
parameter adjustment；P6 segmentation/proxy/calibration ablations and final scale。
Confirmed by: User
Date: 2026-08-05
```

---

## 5. P4-02 — Candidate Pool and Active Search Space

Status: `Confirmed`

### 5.1 要解决的问题

P3 的 full-catalog Top-100 是 item-level recall handoff，不表示 Deep Encoder 要看 100 个视频。P4 必须明确：

- Recommendation State 保留哪些 candidates；
- heuristic Segment Value 实际优先搜索前多少 item；
- media 不完整、OOV、seen item 和 target miss 如何处理；
- smoke candidate 与正式 research candidate 如何区分。

### 5.2 已确认 baseline

1. research path 保留 `full train vocabulary → SASRec Top-100 → Agent State`，不注入 held-out target。
2. State 内保留完整 Top-100 prior；首版 heuristic 对全部 Top-100 中 media-complete、具有 cheap proxy 的未观察 segments 计算 value，不设置固定 Top-L item gate。
3. 每个 item 继承 P4-01 的最多 12 段，最坏每轮约 1,200 次可批量化 cheap value calculations；Deep Encoder 仍只处理全局 argmax 的一段。Top-5/10/20/100 active-search cap 留作 P6 效率消融。
4. Candidate OOV 继续 fail closed；cold target 在 retrieval coverage 记 miss，不能映射 UNK 或注入 vocabulary。
5. 官方 `1..100` smoke 使用独立命名的 media-complete development input；不得与 Top-100 research handoff
   或论文结果混表。
6. 若一个 state 没有任何 eligible segment，应该在 Perceiver 前停止，不以 random media item 补齐。

### 5.3 兼容性注意

现有 Controller 要求 Value 覆盖投影出的全部未观察 segments。第一版不改变 State/Store/Controller seam：存在 segment/proxy 的未观察内容全部进入 cheap value batch；media/proxy 不完整的 item 保留在 Top-100 ranking 中，但没有 eligible segment，并记录明确原因。若整个 state 没有 eligible segment，则在 Perceiver 前以 `no_eligible_segment` 停止。

### P4-02 Decision Record

```text
Decision ID: P4-02
Status: Confirmed
Decision:
1. 正式 research path 使用 full train vocabulary → SASRec Top-100 → Agent State，不注入 held-out target；Small Reranker 每轮重排完整 Top-100，最终 next-item decision 只输出 Top-1。
2. Active search 不设固定 Top-L：对 Top-100 中所有 media-complete、proxy-complete 的未观察 segments 批量计算 cheap value；每轮只把全局 argmax 的一个 segment 送入 Deep Encoder。
3. 每个 item 最多 12 个 segments，与 P4-01 `scene-hybrid-v1` 一致；最多约 1,200 个 cheap value calculations 不等于 1,200 次深度编码。
4. media/proxy-ineligible item 不从排名删除，只是没有可观察 segment；整个 state 无 eligible segment 时在感知前以 `no_eligible_segment` 停止，不随机补齐。
5. warm target 未进入 Top-100 或 cold target 均计 retrieval miss；validation/test 不注入 target。训练 reranker 时允许显式命名的 target-injected training candidates，并分别报告 conditional reranking 与 end-to-end metrics。
6. Candidate OOV、seen-item filtering、repeated-target exception 和 train-only vocabulary 继续沿用 P3 fail-closed 契约。
7. 官方 item 1..100 media smoke 与真实 per-user Top-100 research input 使用不同 config/artifact/result namespace，不混表。
Rationale:
Top-100 是候选纠错空间而不是最终展示数量。保留完整 pool 可让 Memory/Need/Segment Evidence 把当前低排名但正确的 item 提升为 Top-1；cheap value 可批量计算，而昂贵 Deep Encoder 每轮仍只调用一次。提前裁成 Top-10 会把 Recall@10 变成不可恢复的 Agent ceiling，并削弱 emerging-interest 场景。
Alternatives considered:
只召回/重排 Top-1；只重排 Top-10；State 保留 Top-100 但 active search 固定 Top-L=10；从 State 中删除无媒体 item；target miss 时注入 held-out target；随机媒体补齐。
Affected schemas/interfaces:
现有 AgentController、RecommendationState、SegmentValueModel、SegmentPerceiver、ScoreUpdater 和 Store contracts 不变；只需 P4 eligibility/config/metadata 与 typed stop implementation。
Affected docs/tests:
todo/phase_4_discussion.md；active reranker spec；后续 tests 覆盖 Top-100 preservation、full cheap-value coverage、single expensive action、12-segment cap、no-eligible stop、target miss/OOV 和 smoke/research namespace separation。
Resolved follow-up:
Recall/rerank/output 数量、active-search 范围、segment cap、media-ineligible、target miss、cold/OOV 与 smoke/research 边界。
Deferred follow-up:
P6 对 Top-5/10/20/100 active-search cap 做成本-效果消融；正式 SASRec 重训后报告 Recall@K ceiling；P4-03 Information Need。
Confirmed by: User
Date: 2026-08-06
```

---

## 6. P4-03 — Rule-Based Information Need Baseline

Status: `Confirmed`

### 6.1 要解决的问题

Information Need 必须说明“当前排序为了做出更好决策最缺哪类信息”，但不能先写成“去看 item A”。
需要确认第一版 need vocabulary、Memory 信号、evidence gap、空 Memory 和 tie-break。

### 6.2 已确认 baseline

> 2026-08-06 candidate-aware amendment：原先只按 `importance * evidence_gap` 选择 Memory atom，
> 第一轮所有 gap 都为 `1`，会退化为“复述最强兴趣”，不能回答当前 Top-100 到底卡在哪个区分问题上。
> 本 amendment 保留显式、item-agnostic Query 和既有 Memory/evidence 规则，但增加由当前候选 cheap
> visual proxies 计算的 `candidate_difference`，并以它决定哪个兴趣概念成为本轮 Information Need。
> 用户随后确认按本节建议收紧 vocabulary、raw-cosine、聚合、coverage、floor、fallback 和跨轮语义；
> P4-03 现已恢复为 `Confirmed`。Per-query calibration 明确不进入 P4 baseline，只作为 P6 对照实验。

第一版保留一个显式、item-agnostic Query。Query 的候选概念从 public `UserMemoryView` 的
stable/emerging/fading preference atoms 确定性派生，不调用 LLM 生成自由文本；当前 Top-100 的 proxy
差异只负责决定哪个概念胜出，不把 Query 预先绑定到某个 item：

```text
User Memory preference atoms
        ↓
deterministic tag/category need concepts（最多 32 个）
        ↓
Chinese-CLIP text query × every proxy-complete segment's three frames
        ↓
rank-weighted candidate difference
        ↓
importance × candidate difference × evidence gap
        ↓
highest-scoring item-agnostic InformationNeed / Query
        ↓
P4-04 reuses the selected Query's segment relevance to choose one segment
```

首版 need types：

- `confirm_stable_preference`：领先候选缺少对稳定兴趣的区分证据；
- `probe_emerging_preference`：新兴趣 drift 高，需要检查候选是否覆盖该兴趣；
- `check_fading_preference`：旧兴趣正在衰减，不应继续仅凭历史先验加分；
- `general_candidate_relevance`：没有可用 atom 时的显式低信息 fallback。

具体规则：

1. estimator 只读 `RecommendationState` 及其 exact-pinned semantic/proxy refs，不修改 Memory、candidate、
   Evidence 或 proxy artifacts；artifact resolver 只能解析 State 已绑定的 identity，不能选择 `latest`；
2. 单 atom importance 定义为 `strength * (0.5 + 0.5 * persistence)`，让 persistence 温和增强重复出现的兴趣，
   但不把一次新出现的 emerging interest 直接乘没；
3. emerging need 使用 short atom importance，fading need 使用 long atom importance；stable match 分别计算 long/short
   importance 后取算术平均，并同时引用两个 atom IDs；
4. `need-concept-vocab-v1` 从这些 preference sources 所引用的 exact medoid/source prototypes 中，只提取
   canonical `tags` 和完整 `category_paths_cn`；首版不把 title 当作 Need，不做 LLM 改写或近义词合并。
   概念 key 为 `(concept_type, normalized_text)`，使用 Unicode NFC + strip + exact dedup；tag 必须在 P3-02
   train-only item vocabulary 至少覆盖 5 个不同 items，完整 category path 不设 minimum-df floor。只用该
   train-only vocabulary 的静态 P2 item metadata 计算 document frequency，并产生
   `idf(q)=log((N+1)/(df(q)+1))/log(N+1)`，概念初始 importance 为所有 supporting preference sources 的
   `source_importance * idf(q)` 最大值，同时保留全部 supporting atom IDs。按 importance desc、concept type、
   normalized UTF-8 text、atom IDs 确定性排序，只让前 32 个概念进入 visual comparison；`min_tag_df=5`、
   `max_concepts=32`、P3 derived/train-vocabulary checksum、P2 static item-feature version 和 IDF recipe 均进入
   immutable IDF artifact identity。Validation/test runtime 只读该 frozen artifact，不按当前 candidates、held-out
   target、未来 behavior 或 test inventory 重算；P6 再做 8/16/32 与 df floor sensitivity；
5. proxy encoder 固定为 `OFA-Sys/chinese-clip-vit-base-patch16` revision
   `36e679e65c2a2fead755ae21162091293ad37834`。`need-query-template-zh-v1` 固定为 tag
   `这段视频是否主要展示了「{concept}」相关内容？`、category
   `这段视频是否属于「{concept}」相关内容？`，fallback 使用
   `这段视频是否包含有助于区分当前候选的核心内容？`。模板只插入已规范化 concept，经同一
   Chinese-CLIP text encoder 得到 L2-normalized 512-D query vector；不得把 BGE-M3 Memory vector 与
   Chinese-CLIP image vector 做 cosine。P4 baseline 直接使用 raw normalized cosine，不做 per-query
   P90/P99、z-score、null-state 或其他校准；必须记录 per-query frame/segment/candidate/Difference 分布，
   calibration 作为 P6 显式对照实验；
6. 每个 final segment 使用 P4-01 已确认的段内 `25% / 50% / 75%` 三张 proxy candidates。frame artifact
   使用 pinned model 的 official processor（224×224 input），保存实际 timestamps/checksums 和同 revision
   image encoder 产生的 FP32、L2-normalized 512-D vectors。目标帧无效时，令
   `delta=min(250ms, 0.1*segment_duration)`，按 `0,-delta,+delta,-2delta,+2delta` 的固定 offset 顺序在段内寻找
   最近 PTS frame，并去重；少于两张
   有效、去重且通过黑帧/严重模糊/边界过滤的帧时，该 segment 为 `proxy_ineligible`，不能以零向量或零分
   冒充。对 concept `q`、segment `s`，三帧分别做 cosine，`segment_relevance(s,q)` 为最高两帧的算术平均；
7. 对当前 candidate `i`，将该 item 全部 proxy-complete segments 的 relevance 降序排列；至少两个 segment 时
   `candidate_support(i,q)` 取最高两个 segment relevance 的算术平均，只有一个时取该值。它不取单一 max，
   以降低 segment 数量不同带来的 multiple-comparisons advantage。已观察 segment 的 static proxy 仍可描述
   候选内容差异；是否已经取得 Deep Evidence
   只由后述 `evidence_gap` 表达，避免同时从 support 集合删除该 segment 而重复惩罚。没有任何 proxy-complete
   segment 的 item 保留在 Top-100 ranking，但不参与 `candidate_difference`；
8. 令 `E` 为当前 Top-100 中至少有一个 proxy-complete segment 的 candidates；先在完整 Top-100 上归一化
   `u_i=(1/current_rank_i)/sum_j(1/current_rank_j)`，并计算 `proxy_rank_mass=sum_{i in E}u_i`。只有
   `|E|>=2` 且 `proxy_rank_mass>=0.50` 时才允许 candidate-aware comparison；否则输出 typed fallback，缺媒体
   candidates 不得以 support `0` 参加。Comparison 内再归一化
   `w_i=(1/current_rank_i)/sum_{j in E}(1/current_rank_j)`，并定义：

   ```text
   candidate_difference(q)
   = sum_{i<j} w_i*w_j*abs(candidate_support(i,q)-candidate_support(j,q))
     / sum_{i<j} w_i*w_j
   ```

   因此全部可计算 Top-100 candidates 都参与，但高排名竞争者贡献更大；100 个候选最多 4,950 个 pair，
   不设 Top-L 截断。只有 `candidate_difference(q)>=0.10` 的 concept 才进入最终 Need 排序；若全部 concepts
   都低于该 floor，则输出 `general_candidate_relevance` fallback。`minimum_candidate_difference=0.10` 进入
   recipe identity，P6 报告 sensitivity；
9. 对 preference concept `q` 和当前 candidate `i`，若该 item 已有至少一个成功、且 acquisition metadata 引用 `q`
   的 Deep Evidence，则 `coverage(i,q)=1`，否则为 `0`。成功要求 observation status/evidence ref 均合法，且
   acquisition metadata 的 exact `concept_id`、query-template version 和 supporting atom IDs 与本 need 一致；
   failed/empty perception 永远是 `0`。使用上一步完整 Top-100 evidence weight `u_i`，则
   `evidence_gap(q)=sum_i u_i * (1-coverage(i,q))`。因此第一轮未观察任何帧时所有 gap 都为 `1`；每次 rerank
   后按新的完整 Top-100 ranks 重算，低排名 item 获得 Evidence 后若升到前列，其 coverage 会自动获得更高权重；
10. 对通过 `0.10` floor 的 concepts，
   `need_score(q)=concept_importance(q) * candidate_difference(q) * evidence_gap(q)`；每轮只输出最高分的
   一个 need，精确 tie 按 normalized need type、concept type/text、atom IDs 确定性打破；
11. 输出中 `preference_importance=concept_importance`、`contrastiveness=candidate_difference`、
   `evidence_gap=evidence_gap`，`embedding_ref` 指向 exact selected-query Chinese-CLIP text vector。
   `metadata` 只保存最多 32 个 concept 的 aggregate diagnostics 和最终 Query 的最多 100 个 per-candidate
   supports，以及 need score、query template/version、proxy model/artifact identity、eligible candidate count、
   proxy rank mass 和 fallback reason；不保存 per-frame/per-segment tensors 或 raw frames。candidate IDs 只用于
   诊断，不进入 item-agnostic concept/description；
12. `top1_top2_margin` 只作为是否继续感知的 request-level uncertainty/stop signal，不重复乘入所有 query 的
   相对排序；raw SASRec logit 不解释为概率；
13. 无可用 atom/concept、`|E|<2`、`proxy_rank_mass<0.50`、全部 difference `<0.10` 或无法生成合法 query
   vector 时输出 `general_candidate_relevance` fallback：`relevant_preference_atom_ids=()`，importance/gap/
   contrastiveness 均为 `None`，使用固定 fallback query embedding，并在 metadata 写唯一 typed reason；是否继续
   仍由 budget、eligibility 和 stop policy 决定；
14. 每轮复用 immutable static proxy supports，但按新的 current ranks 重算 comparison/evidence weights 和
   `evidence_gap`。已观察 segment 继续参与候选内容 support，却从 P4-04 action eligibility 中排除；同一 concept
   可以在仍有未观察相关 segments 且 gap 未关闭时再次胜出，但同一 segment 不得重复观察。若没有 eligible
   unobserved segment，由既有 typed stop 结束；
15. learned/multi-need/query-free estimator 留作 P6/P7 ablation；P4/P5 第一条主线保留显式 Query，以分离
   “确认什么”和“去哪里看”。

### 6.3 已关闭决策

- concept 使用 Memory tags + full category paths；tag minimum train-vocabulary df=5、train-only static-metadata IDF、
  exact dedup、排除 title、max 32；同一 atom 的 tags 不按数量平分 importance；
- query 使用 `need-query-template-zh-v1` 固定模板；P4 使用 raw normalized cosine，calibration 延后 P6；
- exact Chinese-CLIP revision、official processor、25/50/75 帧、确定性坏帧替换、FP32 L2 vectors 和少于两帧
  fail-closed；
- segment relevance 为 top-2-of-3 frame mean，candidate support 为 top-2 segment mean；
- Top-100 proxy-complete comparison、reciprocal-rank pairwise difference、proxy rank mass 0.50 和 difference
  floor 0.10；
- successful query-tagged binary Evidence coverage、failed=0、逐轮 rank/gap 重算和 static proxy reuse；
- compact public output、selected query embedding ref、typed fallback 以及 P4-03/P4-04 recomputation boundary。

### 6.4 与 P4-04/P4-05 的已确认边界

- Information Need 不选择 item 或 segment；多个视频符合同一 Query 时，由 P4-04 对完整 Top-100 全部 eligible
  segments 做全局比较并只选一个；
- P4-03 为最多 32 个 concepts 临时计算 aggregate scores，只发布最终 Query embedding 和 compact diagnostics。
  P4-04 使用该 exact query embedding 与既有 segment proxy refs 确定性重算最终 Query 的 per-segment relevance；
  允许重复这一次廉价点积以保持公共 schema 简洁，但不得换 query/model/template、重新抽帧或使用不同空间；
- cheap proxy frames/embeddings 按 catalog item/segment 预计算并跨用户复用，不在每个请求中重新抽取；
- 只有最终选中的一个 segment 进入 expensive path，按 P4-ARCH-01 的方向额外均匀抽取八帧供冻结 Deep
  Segment Encoder；P4-04 仍需确认如何把已选 Query 的 relevance 与 rank/novelty 合成 Segment Value，P4-05
  仍需确认 selected-segment uniform-8 decode/preprocess 和 exact Deep Encoder contract。

### P4-03 Decision Record

```text
Decision ID: P4-03
Status: Confirmed
Decision: 2026-08-06 candidate-aware amendment 取代原 `importance * evidence_gap` 选择式。Need concepts 固定来自 Memory source prototypes 的 tags 和完整 category paths，排除 title/LLM/近义词合并；tag min-df=5，只用 P3 train-only item vocabulary 的静态 metadata 计算 normalized IDF，冻结到 exact derived/vocabulary/item-feature identity 后取 top-32，同一 atom 的 tags 不按数量平分 importance。`need-query-template-zh-v1` 经 pinned Chinese-CLIP text encoder 产生 512-D query vector，与每段 25%/50%/75% 的 FP32 L2 frame vectors 做 raw cosine；P4 不做 per-query calibration。Segment relevance 取 top-2 frame mean，candidate support 取 top-2 segment mean。Top-100 proxy-complete candidates 在 proxy rank mass>=0.50 且至少两个时，以 reciprocal-current-rank 加权两两绝对差得到 candidate difference；只保留 difference>=0.10 的 concepts。最终按 `concept_importance * candidate_difference * evidence_gap` 输出一个 item-agnostic Query；successful same-concept Deep Evidence 使用 binary coverage，失败为 0。P4-04 以 exact selected query embedding 重算该 Query 的 segment relevance，再选择具体 item/segment。
Rationale: 原式第一轮所有 evidence gap 都为 1，会退化为复述最强 Memory 兴趣。Candidate-aware contrast 使 Need 回答“当前候选在哪个用户在意的维度上最不同”，同时保持 Query 与 item selection 分离。Top-2 aggregation 降低单帧和 segment-count 偶然极值，rank weighting 防止 tail 数量淹没领先候选，coverage mass/floor/fallback 防止缺媒体或微小数值噪声伪装成可行动差异。Raw-cosine baseline 简单可审计，校准留给有真实分布证据后的 P6 对照。
Alternatives considered: 继续使用 `importance * evidence_gap`；title/LLM/近义词生成 concepts；只比较候选文本 BGE；直接比较 BGE-M3 与 visual vectors；per-query P90/P99/null calibration 进入 P4；只看 Top-1/Top-2 或固定 Top-L；100 candidates 等权；缺媒体记 0；candidate single max；无 contrast floor；先选 item 再生成 Query；query-free learned policy 或 joint Segment Value。
Affected schemas/interfaces: 复用 `InformationNeed`、`RecommendationState`、`SegmentProxyRef` 和 metadata；`contrastiveness` 承载 candidate difference，`embedding_ref` 指向 selected Chinese-CLIP query vector，Evidence acquisition metadata 关联 concept/query-template/supporting atom IDs。新增 internal versioned concept resolver、query encoder/proxy artifact 和 compact diagnostics；不修改 P1 Controller 顺序，不在公共 State 内嵌 Tensor/raw frames/全量 per-segment scores。
Affected docs/tests: todo/phase_4_discussion.md；docs/04_information_need.md；README.md；后续测试覆盖 train-only vocabulary/metadata/checksum IDF closure、禁止 validation/test/target/future inventory 重算、min-df/IDF/top-32/no-tag-count-normalization/template、exact model/processor/vector space、25/50/75 replacement/invalid-frame fail-closed、top-2 frame/segment aggregation、proxy rank mass、Top-100 reciprocal-rank pairwise difference、0.10 floor、binary successful coverage、initial gap=1、rerank recomputation、typed fallback、compact metadata、P4-04 exact-query recomputation、item-agnostic output 和无 future-feedback leakage。
Resolved follow-up: candidate-aware Need、concept source/filter/cap、train-only IDF/no tag-count normalization、query templates、raw cosine/no P4 calibration、proxy frame contract、segment/candidate aggregation、Top-100 missingness/rank weighting、contrast floor、Evidence coverage、round-to-round semantics、fallback、public field mapping 和 P4-03/P4-04 boundary。
Deferred follow-up: P4-04 Segment Value 组合式与 min value；P4-05 selected-segment uniform-8/Deep Encoder；P6 calibration、df/cap/aggregation/floor/text-only/query-free ablations；P7 learned/multi-need estimator。
Confirmed by: User
Date: 2026-08-06
```

---

## 7. P4-04 — Heuristic Segment Value Baseline

Status: `Pending`

### 7.1 定位

P4 的 Segment Value 只是为了在真实候选上选择一段可观察内容：

```text
cheap relevance / uncertainty / rank / coverage heuristic
```

它不学习 expected recommendation gain，也不能称为最终 Segment Value Model。

### 7.2 推荐 baseline（待确认）

1. 继承 P4-03 已确认的 exact Chinese-CLIP proxy artifact 和 selected-query `embedding_ref`；P4-04 只为最终
   Query 确定性重算各 eligible segment 的 top-2-of-3 relevance，不换模型/template、重新抽帧或比较 BGE-M3
   与视觉向量。
2. Proxy model/revision、official processor、frame eligibility 和 vector contract 不再是本 Gate 的研究变量；
   本 Gate 只负责 Segment Value 组合、eligibility、threshold 和 trace。
3. value 由透明的配置权重组合：

```text
selected-query segment relevance
+ current-rank priority
+ optional evidence novelty
```

   `preference importance` 和 `candidate difference` 已在 P4-03 选择 Query 时使用，P4-04 不重复乘入；
   request-level ranking uncertainty 只进入 StopPolicy，不作为所有 segments 共有的相对排序常数。

4. 全部输入在 prediction cutoff 可得；不使用 MLLM Evidence、future label、after ranking 或 actual gain。
5. media/proxy eligibility、各分项和 final value 写入 `SegmentValue.metadata`，便于 trace 和 ablation。
6. 输出严格覆盖所有 input `(item, segment)`；相同 final value 仍由 Controller identity tie-break。
7. 提供 deterministic random-perception comparator 只作后续 ablation/sanity，不替代主 heuristic。

### 7.3 需要确认

- value 的加法/乘法形式和首版权重；
- rank prior 在完整 Top-100 cheap search 中是否过强；
- `min_segment_value` 的可解释范围；
- optional evidence novelty 的 exact 定义；
- random comparator 是否 P4 同步实现或留到 P6。

### P4-04 Decision Record

```text
Decision ID: P4-04
Status: Pending
Decision: TBD
Rationale: TBD
Alternatives considered: TBD
Affected schemas/interfaces: TBD
Affected docs/tests: TBD
Deferred follow-up: TBD
Confirmed by: TBD
Date: TBD
```

---

## 8. P4-05 — Deep Segment Encoder, Selected Frames, and Artifact Contract

Status: `Pending`

当前主线已由 P4-ARCH-01 锁定为 frozen Deep Segment Encoder。P4-05 只待确认 exact encoder/revision、8-frame decode/preprocess、batch/cache 和 cost profile；MLLM/prompt 细节移至 P6 对比支线。

### 8.1 要解决的问题

- 租卡环境实际运行哪个模型和版本；
- in-process Transformers、local server 还是 external API；
- selected segment 输入视频、frames 还是 clip；
- 是否使用 ASR/audio；
- prompt 能看到哪些用户/候选信息；
- 解码、timeout、retry 和 determinism 如何记录。

### 8.2 历史 MLLM proposal（已由 P4-ARCH-01 superseded）

1. 保持同步 `SegmentPerceiver` adapter；并发/service runtime 不在第一条闭环修改 Controller。
2. 模型选择时只核验官方 model card/代码与固定 revision，要求 multi-image/video 能力、结构化输出能力、
   可离线部署、租卡显存可承载和明确许可。具体模型不在总览阶段凭记忆锁死。
3. 第一版把 selected segment 解析为固定数量的均匀 frames，而不是依赖不同模型不一致的原生 video API；
   暂建议每段 8 帧，固定分辨率/颜色空间/时间戳规则并记录实际 processed frames。
4. 首版关闭 ASR/audio，只使用视觉 frames + 安全清洗后的最小 title/category/tag context；后续作独立 ablation。
5. prompt 只包含：固定 system contract、当前 normalized Information Need、相关 preference atom 摘要、
   当前 item 已有 Evidence、选中 segment 的允许 metadata 和 frames。
6. prompt 不包含 user ID、held-out target、future feedback、Oracle label、其他候选的答案或绝对本机路径。
7. 解码使用固定 generation config；若底层仍不完全确定，必须记录环境并以 saved output 复现，不承诺
   byte-exact model re-execution。

### 8.3 Prompt firewall

title/tag/category/ASR 和视频中的文字都视为 untrusted content：只能作为被分析的数据，不得执行其中的
指令。system prompt、数据 delimiter、JSON schema 和长度上限必须版本化；secret 永不进入 resolved config、
prompt artifact 或 trace。

### 8.4 当前仍需确认

- exact frozen image/video encoder 与 revision、许可、显存 profile；
- selected segment 内 uniform-8 frame 的 resolution、normalization 和 short-segment fallback；
- single embedding vs frame/video tokens；
- cache key、checksum、batch size、timeout 与 typed failure；
- frames、FLOPs、latency、显存和 cache hit 的记录方式。

### P4-05 Decision Record

```text
Decision ID: P4-05
Status: Pending
Decision: TBD
Rationale: TBD
Alternatives considered: TBD
Affected schemas/interfaces: TBD
Affected docs/tests: TBD
Deferred follow-up: TBD
Confirmed by: TBD
Date: TBD
```

---

## 9. P4-06 — Latent Evidence, Failure, and Public-Ref Boundary

Status: `Pending`

主线 Evidence 使用外部 latent artifact + existing `Evidence.embedding_ref`；公共 State/Trace 不内嵌 Tensor。下方 structured-text vocabulary/parser 作为历史 MLLM proposal 保留，仅归 P6 对比支线。

### 9.1 历史 MLLM Evidence vocabulary（P6 对比支线）

第一版 MLLM JSON 不输出 recommendation score，只描述选中片段对当前 need 的证据：

```text
evidence_schema_version
need_concept
preference_atom_ids
alignment: supports | contradicts | unclear
strength: 0 | 1 | 2 | 3
confidence: [0, 1]
grounded_cues: bounded list of short observations
summary: bounded optional text
```

公共 `Evidence.attributes` 保存规范化后的 typed payload；`Evidence.confidence` 保存已验证数值；原始模型响应
写入 content-addressed raw artifact 并由 `raw_output_ref` 关联。

### 9.2 历史 MLLM Parser 策略（P6 对比支线）

1. strict JSON/schema validation；identity、enum、range、长度和 JSON compatibility 全部 fail closed；
2. 允许本地确定性清理，例如去掉单层 Markdown code fence，但不猜缺失业务字段；
3. 第一版不使用第二次 LLM “repair” 来掩盖坏输出；parse failure 返回 typed failed perception，消耗 action、
   不产生 Evidence、不改 ranking；
4. timeout/model refusal/unsafe output/parse error/resource error 使用不同 failure codes；
5. raw response 即使失败也进入受控 sidecar，便于诊断，但不进入公开仓库或论文补充材料；
6. model self-confidence 只作为未经校准的 heuristic signal，不能描述成真实概率。

### 9.3 当前仍需确认

- latent artifact schema、dtype/shape、encoder/preprocess revision 与 checksum；
- per-segment `embedding_ref` 到 aggregated `evidence_embedding_ref` 的确定性规则；
- missing/corrupt/cache mismatch/encode timeout 的 typed failures；
- failed perception 不产生 Evidence、不改变 score，但 action/cost 仍按 P1 规则记录；
- public ref、sidecar、隐私、许可和 replay closure。

### P4-06 Decision Record

```text
Decision ID: P4-06
Status: Pending
Decision: TBD
Rationale: TBD
Alternatives considered: TBD
Affected schemas/interfaces: TBD
Affected docs/tests: TBD
Deferred follow-up: TBD
Confirmed by: TBD
Date: TBD
```

---

## 10. P4-07 — Small Candidate-aware Multimodal Reranker

Status: `Pending`

P4-ARCH-01 已确认 learned Small Reranker 是主线 `ScoreUpdater`。P4-07 仍待确认 exact network capacity、feature projection、training config 和 validation-only calibration。

### 10.1 要解决的问题

SASRec 输出是 request-local uncalibrated raw logit；Evidence alignment 是离散/归一化信号。必须确认如何在
不破坏 prior、不重复累计旧证据的前提下产生可解释 delta。

### 10.2 历史 residual proposal（已由 P4-ARCH-01 superseded）

1. 每次从 `initial_ranking + 全部当前 EvidenceState` 重新计算，不在 previous score 上重复叠加同一 Evidence。
2. 每个 Evidence 转为有符号 signal：

```text
supports    → positive
contradicts → negative
unclear     → zero
weighted by strength × confidence × preference importance
```

3. 同 item 多段 Evidence 使用有界、确定性的 weighted aggregation；conflicting Evidence 可以抵消，结果 clamp
   到 `[-1, 1]`，并在 aggregated attributes 中保存 support/contradict/unclear counts。
4. 只更新已有有效 Evidence 的 item；未观察 item 的 `delta=0`，保留原 SASRec raw prior。
5. 将 signal 映射到 raw-logit residual 时使用当前 candidate score distribution 的 robust scale 和可配置
   `lambda`：

```text
new_score_i = initial_raw_score_i + lambda * state_score_scale * aggregate_signal_i
```

6. `state_score_scale`、lambda、每项 signal/delta 和 clamp 必须写 metadata；不得把 raw logit 解释为概率。
7. 第一版不跨 item 联动更新，不训练 unified reranker。Score output 继续精确覆盖全部 candidates 并稳定 rerank。
8. P4 初期关闭 raw-margin certainty stop；只有 validation-only calibration 后才能给 real score 设阈值。

### 10.3 当前推荐 baseline 与待确认项

- 输入：SASRec user hidden、candidate ID/base embedding、base score/rank、Memory atoms、Information Need、observed mask 与每个 item 的 current latent Evidence；各 embedding space 独立投影到共同 `d_model`；
- candidate-aware listwise transformer 每轮输出全体 logits，candidate serialization 随机化并显式提供 rank feature；
- 每轮固定从 initial SASRec base scores + full current EvidenceState 重算，不输入 previous current scores；
- training observation states 平衡 target/non-target、rank 和 evidence count；No-Evidence 是必要容量控制；
- V1 loss 为 listwise CE + no-evidence consistency + mask invariance；shuffled Evidence 只作 sanity check；
- exact K/d_model/layers/heads、evidence aggregator、Memory adapter、optimizer 和 validation-only stop calibration 仍待确认。

### P4-07 Decision Record

```text
Decision ID: P4-07
Status: Pending
Decision: TBD
Rationale: TBD
Alternatives considered: TBD
Affected schemas/interfaces: TBD
Affected docs/tests: TBD
Deferred follow-up: TBD
Confirmed by: TBD
Date: TBD
```

---

## 11. P4-08 — Runtime, Budget, Failure, Cache, Cost, and Replay

Status: `Pending`

### 11.1 Runtime 推荐 baseline（待确认）

- 新增 strict `phase4-runtime` config 和 exact artifact graph；P3 zero-budget config 继续原样可运行；
- 真实 component selector 显式选择 rule Need、heuristic Value、Deep Segment Encoder Perceiver、Evidence/Observation Updater、Small Reranker ScoreUpdater 和 StopPolicy；禁止 unavailable/mock silent fallback；
- 第一条 canonical real smoke 建议 `max_perception_actions=2`，证明更新后重新估计 need/value 并再次决策；
- `ranking_margin_threshold=null`；`min_segment_value` 只在 P4-04 value 范围锁定后设置；
- model/media/prompt preflight 在正式 action 前完成，资源缺失不能消耗感知 budget；
- Controller 内部 action accounting、failed result 和 component exception semantics 保持 P1 不变。

### 11.2 一次 action 与模型调用

```text
one SegmentPerceiver.observe() attempt = one Agent action
```

它内部可能包含 frame decode、cache lookup 和一次 deep encoding。若将来允许 retry，多次底层调用
仍属于同一 action，但必须完整报告 call count/tokens/latency，不能只报 action 数掩盖成本。

### 11.3 Additive run artifacts

保留原三个 canonical 文件并增加 P4 sidecars：

```text
runs/phase4/<run_id>/
├── resolved_config.json
├── trace.jsonl
├── result.json
├── perception_events.jsonl
├── perception_manifest.json
└── perception/<call_id>/
    ├── request_manifest.json
    ├── frame_manifest.json
    └── raw_response.*
```

每次 attempt/call 至少记录：segment duration、requested/processed frame count、input/output tokens、latency、
model/revision、prompt version、generation config、cache hit、status/failure code 和 raw-output checksum。

`PerceptionResult.metadata` 只放轻量 reference/cost summary；大型 payload 留在 sidecar。saved-output replay 继续只验证 State/Trace chain，不读取媒体、不调用 Deep Encoder；另建 P4 artifact validator 检查 sidecar/ref/checksum/cost closure。

### 11.4 Cache 推荐边界（待确认）

- cache key 覆盖 model revision、prompt/schema、generation config、frame checksums、Information Need、相关
  Memory/Evidence context；不能只按 segment ID 跨用户复用 personalized output；
- cache hit 和 fresh inference 分开报告 incurred cost 与 logical perception cost；
- 正式 latency/cost 测量使用明确 cold/warm cache protocol，不能混在一个均值里；
- cache corruption/checksum mismatch fail closed。

### P4-08 Decision Record

```text
Decision ID: P4-08
Status: Pending
Decision: TBD
Rationale: TBD
Alternatives considered: TBD
Affected schemas/interfaces: TBD
Affected docs/tests: TBD
Deferred follow-up: TBD
Confirmed by: TBD
Date: TBD
```

---

## 12. P4-09 — Evaluation, Test Matrix, and Definition of Done

Status: `Pending`

### 12.1 P4 评价定位

P4 只做 integration/diagnostic evaluation，不用少量 media smoke 宣称论文效果。最低需要比较：

```text
B=0: P3 SASRec prior
B>0: frozen Deep Encoder + heuristic selection + Small Reranker
```

每个 run 同时报告 ranking transition 和成本：before/after ranks、selected segments、Evidence、delta、stop reason、
actions、model calls、frames、tokens、latency、failures 和 media coverage。若小诊断集有 held-out target，可以报告
明确标为 non-reportable diagnostic 的 conditional metric，但不能替代 P6 正式 benchmark。

### 12.2 自动化测试建议

Unit：

- media artifact identity/coverage/range/checksum；
- media/proxy eligibility、Top-100 full cheap-Value coverage 和 single deep action；
- Need vocabulary/formula/tie/empty-memory；
- proxy loading、value components 和 deterministic ordering；
- frame timestamp/sampling/cache key；
- deep encoder preprocessing、latent ref schema/checksum/cache/failure codes；
- Evidence aggregation、no-double-counting、no-evidence consistency、mask/permutation invariance；
- balanced observation sampler、train-only target injection、split-before-variants；
- cost records、secret/path sanitization 和 sidecar integrity。

Integration/E2E：

- tiny local media + deterministic fake Deep Encoder/Small Reranker 完成两 action loop；
- one successful + one encode/ref-failed perception；
- no eligible media、timeout、ref corruption、cache hit/miss；
- P3 zero-budget runtime/replay 完整回归；
- P4 saved-output replay 不加载模型/媒体；
- API/CLI equivalence、Windows long-path 和 no-overwrite run publication。

CI 必须 offline、CPU-only、使用 tiny fixture/fake backend，不下载真实模型、不调用网络/GPU/MLLM。真实 GPU
模型 smoke 是独立 reproducible acceptance lifecycle，不进入每个 PR 的 required matrix。

### 12.3 推荐 Definition of Done（待确认）

1. P4-00—P4-09 与 P4-XG-01 全部 Confirmed；
2. exact Tsinghua media subset、proxy/model/prompt refs 和 P3 graph closure 可验证；
3. 至少一个真实 Deep Encoder + Small Reranker positive-budget run 成功产生合法 latent Evidence ref、reranking 和明确 stop；
4. 只有选择的 segment 触发 deep encoding，failed output 不污染 Evidence/score；
5. raw/cost sidecars 和 public trace/result 可关联、可校验、无 secret/绝对路径；
6. saved-output replay 不调用模型；同一 saved Evidence 可从固定 SASRec base 独立重算 Score Update；
7. P1–P3 全部回归，本阶段 package branch coverage 继续至少 90%，Ruff clean；
8. GitHub Actions Ubuntu Python 3.10/3.12、Windows Python 3.12 required jobs 全绿；
9. 真实 run 的 model/media/prompt/config/environment/cost summary 记录在 docs，但不提交受限 raw data；
10. 文档明确 P4 是工程 baseline，supervised Segment Value/Oracle/P6 paper results 尚未完成。

### P4-09 Decision Record

```text
Decision ID: P4-09
Status: Pending
Decision: TBD
Rationale: TBD
Alternatives considered: TBD
Affected schemas/interfaces: TBD
Affected docs/tests: TBD
Deferred follow-up: TBD
Confirmed by: TBD
Date: TBD
```

---

## 13. P4-XG-01 — Cross-Gate Consistency Review

Status: `Pending`

实现授权前至少检查：

| Invariant | 必须证明 |
| --- | --- |
| P3 artifact closure | P4 每个输入都绑定 exact P2/P3 refs，没有 latest/mtime/path guess |
| media ownership | exact overlay 绑定唯一 base P2 release/catalog，只补媒体/segments/proxies，不复制或篡改 behavior/labels，也不放宽 P2 resolver membership |
| temporal leakage | Need/Value/Prompt/Updater 都不读 cutoff 后 feedback 或 target |
| candidate semantics | Top-100 recall/rerank、all-eligible cheap search、Top-1 output、official-100 smoke 和 101 dev pool 名称/用途不混淆 |
| selection order | Need 不绑定 item；Value 覆盖全部 input；Controller 选择规则不变 |
| cost boundary | Agent actions 与底层 model calls 都记录，不能靠 retry 隐藏成本 |
| evidence boundary | selected frames → Deep Encoder → latent artifact/ref → EvidenceState；公共 State 无 Tensor |
| score boundary | raw SASRec scale 不当概率；fixed base + full Evidence 纯重算；旧 Evidence 不重复累计 |
| failure boundary | parse/timeout/ref/contract/component failures 的状态和 budget accounting 唯一 |
| replay boundary | P4 sidecar additive；saved replay 不调用模型或读取大型资源 |
| experiment boundary | P4 smoke/diagnostic 不冒充 P6 主结果；官方 split 未审计不进入正式训练 |
| privacy/license | 不发布受限媒体、ASR、raw response、user rows 或 content-derived payload |

### P4-XG-01 Decision Record

```text
Decision ID: P4-XG-01
Status: Pending
Decision: TBD
Rationale: TBD
Alternatives considered: TBD
Affected schemas/interfaces: TBD
Affected docs/tests: TBD
Deferred follow-up: TBD
Confirmed by: TBD
Date: TBD
```

---

## 14. 当前确认进度

| Gate | Topic | Status |
| --- | --- | --- |
| P4-00 | P3 handoff、范围、官方 split 训练前审计 | Confirmed |
| P4-01 | media subset、segments、resource contract | Confirmed |
| P4-02 | Top-100 recall/rerank、all-eligible cheap search、Top-1 output | Confirmed |
| P4-03 | candidate-aware rule-based Information Need | Confirmed |
| P4-04 | heuristic Segment Value | Pending |
| P4-ARCH-01 | Deep Encoder + Small Reranker architecture amendment | Confirmed |
| P4-05 | Deep Encoder、selected frames、artifact | Pending |
| P4-06 | latent Evidence/failure/public refs | Pending |
| P4-07 | Small Candidate-aware Multimodal Reranker | Pending |
| P4-08 | runtime/budget/cache/cost/replay | Pending |
| P4-09 | evaluation/tests/DoD | Pending |
| P4-XG-01 | cross-gate audit and implementation authorization | Pending |

下一项：确认 P4-04 Heuristic Segment Value Baseline。

---

## 15. Decision Record Template

```text
Decision ID: P4-XX
Status: Confirmed | Deferred | Blocked
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
