# Phase 4 Discussion — Real Active Perception Baseline

Status: `In Discussion`

本文档用于逐项确认 Phase 4 的研究与工程边界。它继承已经完成的 P1–P3，目标是尽快跑通
第一条真实的正预算 Agent Loop：真实 Recommendation State 产生 Information Need，选择真实视频片段，
发布 selected raw-frame Evidence，再由约 8B 的 native-frame MLLM Candidate Reranker 更新整个候选排序。
最终 learned Segment Value 由不超过约 1B 的多模态 Selector 实现；P4 的 Query-relevance 规则只作为 bootstrap。

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
   selected raw-frame publisher
                  ↓
     versioned frame Evidence ref
                  ↓
 native-frame MLLM candidate rerank
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

- 不在 P4 训练最终多模态 Segment Selector；其 counterfactual gain data、architecture 和 loss 属于 P5；
- 不声称 heuristic Segment Value 就是论文最终 PAVE-Rec；
- 不做最终多数据集、三 seed、完整 ablation 和显著性主表；它们属于 P6；
- 不在 P4 同步复制 MicroLens 主线；第一条真实闭环只使用 Tsinghua；
- 不做 learned Information Need、Memory-aware initial retrieval/fusion、Selector/Reranker joint training 或 RL；
- 不解决 cold/OOV target；后期冷启动 track 已记录在 Initial Ranker 计划；
- 不把 held-out target、未来 feedback、Oracle gain 或评价标签输入 online Agent；
- 不因接入 raw-frame Perceiver/native-frame MLLM Reranker 而改写 P1 Controller 的 selection、budget 或 state transition 顺序。

### 1.4 P4 与 P5/P6 的边界

| 能力 | P4 | P5 | P6 |
| --- | --- | --- | --- |
| Information Need | 第一条 rule-based baseline | 固定后用于造 Oracle state | ablation / tuning |
| Segment selection | Query-relevance bootstrap | ≤1B multimodal expected-gain Selector | 主实验、规模/压缩/联合训练消融 |
| Perception / Evidence | selected raw-frame bundle + model-native visual path | 固定用于反事实 label generation | frame/token/cost ablations |
| Score Update | 约 8B native-frame MLLM Candidate Reranker | 冻结后定义 actual gain | 正式评价、容量控制与校准 |
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
P4-05  selected-segment raw frames 和 artifact contract
P4-06  Frame Evidence、failure 和 public-ref 边界
P4-07  Native-frame MLLM Candidate Reranker
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
4. 最终选择的 segment 只发布 canonical raw-frame Evidence；约 8B MLLM Reranker 原生读取这些帧并输出候选分数。
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

1. Deep Segment Encoder 实现既有 `SegmentPerceiver`；latent tensor 存外部 artifact，P4-06 已确认每个 segment
   通过 `Evidence.embedding_ref` 指向 bundle manifest 进入既有 `EvidenceState`，不在此处生成 aggregated ref；
   frame/multi-segment aggregation 由 P4-07 Reranker 负责。
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

## 3B. P4-ARCH-02 — Multimodal Selector + Native-frame MLLM Reranker Amendment

Status: `Confirmed`

本修订根据 2026-08-07 与教授讨论后的研究方向，取代 P4-ARCH-01 的“frozen Chinese-CLIP Deep Encoder +
Small Candidate-aware Multimodal Reranker”主线。P1 Controller、Top-100、Information Need、全局
`SegmentValueModel`/`ScoreUpdater` 接口、action budget 和 failure/replay 原则保持不变。

### 已确认新主线

```text
Dynamic Memory + SASRec Top-100 prior
              ↓
Recommendation State
              ↓
Information Need / Query
              ↓
P4 Query-relevance bootstrap
or P5 ≤1B Multimodal Segment Selector
              ↓
select one (item, segment)
              ↓
canonical selected raw-frame bundle
              ↓
~8B native-frame MLLM Candidate Reranker
              ↓
Top-100 scores and stop-or-repeat
```

1. 最终 proposed Segment Value Model 是不超过约 1B 的判别式多模态 Selector，而不是生成文本的 MLLM。
   它直接覆盖完整 Top-100 内全部 eligible segments，不在 proposed path 前增加独立 CLIP shortlist。
2. Selector 自己拥有轻量 vision tower/tokenizer、query-conditioned local resampler 和 global segment scorer。
   每个 segment 的 3/6/8 等低清多帧先产生可版本化的 content-only compact tokens；在线根据当前 Query/Memory/
   candidate state 把每段压成一个 segment token，再在最多约 1200 个 segment tokens 上一次性输出 scalar values。
3. Selector content tokens 可以跨用户缓存，但必须绑定 exact selector vision checkpoint、frame recipe、resolution、
   processor 和 media checksum。训练中修改 vision tower 后旧 cache 立即失效；冻结发布后重建 canonical cache。
4. P4-04 Chinese-CLIP Query-relevance global argmax 保留为未训练 Selector 前的 bootstrap、baseline 和消融，
   不进入最终 proposed Selector 的前置筛选。Chinese-CLIP proxy artifact 也不等于 Selector-owned token cache。
5. 选中一个 segment 后，Perceiver 发布 canonical raw RGB frame bundle。约 8B（7—9B class，exact model 待
   P4-07 确认）的 MLLM Reranker 使用自己的 native visual processor/vision tower 读取原始帧，不要求把
   Chinese-CLIP `[F,512]` tokens 适配进语言模型。
6. MLLM Reranker 实现既有 `ScoreUpdater`：输入 Top-100 compact candidate state、SASRec score/rank、Memory、
   acquisition Query 与全部当前 observed frame Evidence；通过 candidate scoring head 一次输出 candidate logits，
   不用自由文本/JSON 生成数字。首个 baseline 保留 SASRec prior，输出 learned bounded residual 或等价的
   prior-preserving logits；每轮从 initial prior + full current EvidenceState 纯重算，不递归累计 previous scores。
7. 约 8B Reranker 先使用 split-safe Observation State data 训练并固定版本；第一版优先 LoRA/QLoRA，full
   fine-tuning 只作后续容量实验。训练覆盖 no-evidence、target/non-target evidence、不同 rank/evidence count、
   multi-item/multi-segment、mask 和 mismatched/shuffled Evidence states。
8. Reranker 冻结后才生成 Selector labels。对 sampled states 和 stratified segment subsets 计算
   `Δ log p(target) - λ cost`，保存 raw gain/cost，再训练 ≤1B Selector 预测 expected recommendation gain。
   Label builder 不要求对每个 state 的约 1200 segments 全部运行一次 8B Reranker；采样规模与 hard-negative
   recipe 必须版本化并报告覆盖。
9. 第一条研究 baseline 不做 Selector/Reranker joint training。原因是 Reranker 未固定时 Selector reward 非平稳，
   反事实 label/cache 持续失效，且 8B teacher call 成本与 credit assignment 难以审计。Alternating refresh、
   distillation、soft selection、bandit/RL 或端到端 joint tuning 延后 P6/P7 作为独立实验。
10. 在线执行顺序是 Selector → Reranker；训练依赖顺序是 Reranker → counterfactual labels → Selector。
    初始 item retriever/ranker 仍是 SASRec；文档必须使用“segment selector”避免与 item retrieval 混淆。

### 对既有 Gate 的修订

- P4-03 Information Need、P4-04 Query-relevance bootstrap、P4-01 segmentation 和 P4-02 Top-100 boundary 保持有效；
- P4-05 的 eight-bin-center/2—8 valid-frame sampling 继续作为 selected-frame baseline，但 pinned Chinese-CLIP
  image tower 不再是最终主 Evidence Encoder，只保留 proxy/bootstrap/small-latent comparator；
- P4-06 的 atomic publication、typed failure、public-ref、privacy 和 replay closure 保持有效，但 canonical Evidence
  entry 改为 raw-frame bundle；selector tokens 和 MLLM-native cache 是独立 versioned derived artifacts；
- P4-07 重新定义为 native-frame MLLM Candidate Reranker model/data/training Gate；
- P5 重新定义为 ≤1B Multimodal Segment Selector data/model/training Gate；
- P6 将 Small latent reranker、CLIP relevance、不同 Selector/Reranker scales 和 optional joint training 作为对比/消融。

### P4-ARCH-02 Decision Record

```text
Decision ID: P4-ARCH-02
Status: Confirmed
Decision: 最终 proposed selection 使用无独立 CLIP 前筛的 ≤1B 判别式多模态 Segment Selector；Selector 对全部 eligible segments 的低清多帧 compact tokens 做 query-conditioned compression 和全局 scalar scoring。最终选择的 segment 发布 raw-frame Evidence，约 8B native-frame MLLM Reranker 通过 scoring head 对 Top-100 输出分数。第一版先训练并冻结 Reranker，再生成 counterfactual gain labels 和训练 Selector；不从零联合训练。
Rationale: Selector 的 expected-gain target 必须由有效且固定的 downstream Reranker 定义。Selector-owned compact token path 可以避免把数千 raw images 塞进一个上下文，同时仍让全部 segments 参与 proposed selection；8B MLLM 只读取少量已选 segment 原始帧，从而把多图复杂推理成本限制在每个 action 一次。
Alternatives considered: CLIP shortlist 后再用 Selector；1B MLLM 一次拼接全部 raw frames；继续使用 Chinese-CLIP latent tokens + Small Reranker；把 Chinese-CLIP tokens 通过新 adapter 注入 8B MLLM；生成式 JSON score；从零联合训练 Selector/Reranker。
Affected schemas/interfaces: 复用 `SegmentValueModel`、`SegmentValueInput`、`SegmentValue`、`SegmentPerceiver`、`Evidence`、`EvidenceState`、`ScoreUpdater` 和 Controller 顺序。`segment_proxy_ref` 可指向 Selector-owned compact-token manifest；selected-frame Evidence 使用 external raw-frame bundle ref；model-specific tokens/output 只通过 versioned artifacts/metadata 关联。
Affected docs/tests: README.md；todo/phase_4_discussion.md；todo/implementation_roadmap.md；docs/00_shared_domain_schemas.md；docs/05_segment_value_model.md；docs/07_evidence_score_update.md；docs/10_evaluation_and_training_plan.md；docs/active_multimodal_reranker_engineering_spec.md；后续测试覆盖 full eligible coverage、token-cache identity、query-conditioned compression、raw-frame ref、native-frame MLLM scoring、no-generation output、prior preservation、split-safe observation data、frozen-teacher labels 和 no-joint baseline。
Resolved follow-up: proposed Selector/Reranker roles、无 CLIP 前筛、raw-frame MLLM input、training/inference order 和 first-stage no-joint boundary。
Deferred follow-up: P4-07 exact MLLM family/revision/context/scoring head/LoRA data；P5 exact Selector family/size/token count/frame recipe/label sampling；P6 scale/cost/CLIP-shortlist/joint-training ablations；P7 policy/RL extensions。
Confirmed by: User
Date: 2026-08-07
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
P4-04/P4-05 exact contracts 后续已分别由对应 Decision Record 解决；仍保留 official-100 audit 后的
parameter adjustment，以及 P6 segmentation/proxy/calibration ablations and final scale。
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
1. 正式 research path 使用 full train vocabulary → SASRec Top-100 → Agent State，不注入 held-out target；native-frame MLLM Reranker 每轮重排完整 Top-100，最终 next-item decision 只输出 Top-1。
2. Active search 不设固定 item Top-L：对 Top-100 中所有 eligible 未观察 segments 计算 value；每轮只把全局 argmax 的一个 segment 发布为 raw-frame Evidence。
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
- cheap proxy raw frames/embeddings 按 catalog item/segment + recipe 一次性预计算并跨用户复用，不在每个
  请求中重新抽取；每轮 Query 只重算 concept text embedding 与当前 Top-100 cached refs 的点积；
- `25%/50%/75%` 三帧只作为跑通第一条 P4 pipeline 的工程 baseline，不声明为最终最优采样；frame count、
  sampling positions、medoid/uniform/denser alternatives 明确留给 P6 独立消融，不能静默改变 P4 artifact recipe；
- 只有最终选中的一个 segment 进入 expensive path；P4-04 已确认只使用 selected-Query pure relevance，不再
  加入 rank/novelty；P4-ARCH-02 保留 eight-bin-center/2—8 张有效 raw frames，但已将 pinned Chinese-CLIP
  Deep Encoder 降为 bootstrap/comparator。

### 6.5 Deferred Query/Frame Experiment Matrix

P4 先冻结当前 Memory、concept 和 three-frame recipes 跑通可复现 pipeline；正式 P6 实验分开评估两类会直接
改变 Query 的因素：

- Query-generation / Memory side：short recent window、long recency half-life、max active atoms、inactive threshold、
  persistence saturation、strength/persistence importance、stable/emerging/fading transition、concept df/IDF/cap、
  query template、encoder 和 calibration；
- frame/perception side：proxy source decode resolution、sparse high-resolution vs dense low-resolution、
  3/6/8/12/16 frame count、relative positions、uniform/medoid/scene-aware sampling、invalid-frame replacement、
  frame/segment aggregation、proxy encoder，以及 selected-segment 4/8/16/32 deep frame count/sampling/token aggregation。

Proxy 的目标是提高 selected-segment 命中率，Deep Encoder 的目标是读取已选 segment，二者必须拆开实验。
若仍经 official 224×224 processor，低清 source frame 只直接降低 decode/cache/transfer 成本，不降低每帧
image-tower FLOPs；增加 proxy 帧数时 aggregation 也要共同版本化，避免固定 top-2 引入 multiple-comparisons bias。

实验先固定一侧只改变另一侧，再组合各自最佳候选；每个 variant 必须有独立 config、recipe/version、artifact
identity 和 split-safe rebuild，不能跨 variant 复用不兼容的 Memory/Query/proxy/Evidence artifacts。报告不仅包括
最终 ranking gain 和 cost，也包括 Query fallback rate、candidate-difference/evidence-gap 分布、Query 稳定性及
selected-segment 分布。

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
Deferred follow-up: P6 calibration、df/cap/aggregation/floor、proxy source resolution/frame count/sampling positions、text-only/query-free ablations；P7 learned/multi-need estimator。P4-04/P4-05 后续项已由各自 Decision Record 解决。
Confirmed by: User
Date: 2026-08-06
```

---

## 7. P4-04 — Heuristic Segment Value Baseline

Status: `Confirmed`

### 7.1 定位

P4 的 Segment Value 只是为了在真实候选上选择一段可观察内容：

```text
selected-query cheap visual relevance
```

它不学习 expected recommendation gain，也不能称为最终 Segment Value Model。

### 7.2 已确认 baseline

1. 继承 P4-03 已确认的 exact Chinese-CLIP proxy artifact 和 selected-query `embedding_ref`；P4-04 只为最终
   Query 确定性重算各 eligible segment 的 top-2-of-3 relevance，不换模型/template、重新抽帧或比较 BGE-M3
   与视觉向量。
2. 对 selected Query 的 L2-normalized 512-D text vector `q` 与 eligible segment 的有效 frame vectors
   `f_1..f_m`（`m` 为 2 或 3）计算 raw cosine；降序取最高两个：

```text
c_k = dot(q, f_k)
SegmentValue(item, segment) = mean(top-2(c_1..c_m))
```

3. final `SegmentValue.value` 就是该 raw top-2-of-3 mean，不再加入或乘入 current rank、preference importance、
   candidate difference、evidence gap、ranking uncertainty 或 item-level evidence novelty。前述信号已在 P4-03
   Query/Stop 决策中使用；重复加入会双重计权并削弱 P4-02 的完整 Top-100 纠错空间。
4. eligible segment 必须属于当前 Top-100、media/proxy complete、至少有两张合法 proxy frames、状态为
   `unobserved`，并使用 P4-03 输出的 exact query/model/template/proxy identities。已成功观察的同一 segment
   不得重复进入 input；failed/retry eligibility 由 P4-08 统一决定。
5. P4 baseline 固定 `min_segment_value=null`：只要 budget 尚存且至少有一个 eligible segment，就选择全局
   maximum raw relevance；P4 记录完整 value 分布，不在没有 validation calibration 时设置 cosine threshold。
6. 全部输入在 prediction cutoff 可得；不使用 MLLM Evidence、future label、after ranking 或 actual gain。
7. 输出严格覆盖所有 input `(item, segment)`；metadata 至少记录 query/proxy identities、frame cosines、top-2
   aggregation、eligibility 和 final raw value。相同 final value 使用既有 Controller `(item_id, segment_id)`
   identity tie-break。
8. deterministic random-perception comparator 延后到 P6 selection ablation，不进入 P4 主实现和 DoD。

### 7.3 已关闭决策

- value 为 selected-query raw top-2-of-3 frame cosine mean，不使用加权组合；
- 不加入 rank prior、importance、candidate difference、evidence gap、uncertainty 或 novelty；
- `min_segment_value=null`，P4 只记录分布，threshold/calibration 延后；
- all-eligible full Top-100 global argmax，每轮只选一个 segment；
- random comparator 延后 P6。

### P4-04 Decision Record

```text
Decision ID: P4-04
Status: Confirmed
Decision: P4 heuristic Segment Value 使用纯 selected-Query relevance。对 P4-03 exact Chinese-CLIP query vector 与每个 eligible unobserved segment 的 2/3 张 proxy frame vectors 计算 raw cosine，value 为最高两帧 cosine 的算术平均；在完整 Top-100 全部 eligible segments 上取全局 argmax。P4 不加入 rank、importance、candidate difference、evidence gap、uncertainty 或 novelty，且 `min_segment_value=null`。
Rationale: P4-03 已用 Memory importance、rank-weighted candidate difference 和 Evidence gap 选择 Query，StopPolicy 负责 request-level uncertainty；P4-04 重复加入这些信号会双重计权、引入任意权重并压制低排名候选。纯 relevance baseline 最小、可解释、可复算，直接回答“哪个未观察 segment 最能回答已选 Query”。
Alternatives considered: relevance+rank+novelty 加法；乘法 gate；只搜索 Top-L；item-first selection；固定 raw-cosine threshold；P4 同步 random comparator；learned expected-gain model。
Affected schemas/interfaces: 复用 `SegmentValueModel`、`SegmentValueInput`、`SegmentValue` 和 Controller global-argmax contract；不修改公共 schema。metadata 固定记录 exact query/proxy identities、frame cosines、aggregation 和 eligibility。
Affected docs/tests: todo/phase_4_discussion.md；docs/04_information_need.md；docs/05_segment_value_model.md；后续测试覆盖 exact-query reuse、top-2-of-3 arithmetic、2-frame boundary、invalid/ineligible exclusion、all-input output coverage、full Top-100 argmax、tie determinism、no duplicate observation、no forbidden extra signals 和 `min_segment_value=null`。
Resolved follow-up: value 形式、rank/novelty 边界、threshold、random comparator phase ownership 和 P4-03/P4-04 信号去重。
Deferred follow-up: P5 supervised expected-gain Segment Value；P6 rank/novelty/threshold/random/query-free selection 以及 proxy frame count/sampling ablations。P4-05 已由其 Decision Record 解决。
Confirmed by: User
Date: 2026-08-06
```

---

## 8. P4-05 — Deep Segment Encoder, Selected Frames, and Artifact Contract

Status: `Confirmed; payload amended by P4-ARCH-02`

P4-ARCH-02 保留 selected-segment eight-bin-center/2—8 valid-frame sampling，但取代 pinned Chinese-CLIP
Deep Encoder 主线：canonical perception output 改为 processor-independent selected raw-frame bundle，供约 8B
MLLM Reranker 使用 native visual processor 读取。下方 Chinese-CLIP token contract 作为历史 P4-05 baseline 和
Small-latent comparator 保留，不再是最终 proposed path。

### 8.0 P4-ARCH-02 active amendment

1. `SegmentPerceiver.observe()` 负责 deterministic decode、invalid-frame filtering 和 raw-frame bundle publication；
   它不在最终 proposed path 内运行 Chinese-CLIP 或替 8B MLLM 做视觉推理。
2. eight-bin-center 目标位置、2—8 张真实有效帧、少于两帧 fail closed、timestamp/frame checksum、segment
   boundaries、mask 和 sampling recipe 继续有效。Exact native resolution/codec 与 4/8/16 frame comparator 由
   P4-07/P6 配置确认，不能静默改变 artifact identity。
3. Canonical selected-frame bundle 是 content-only、user/query independent、可跨 run 复用的受控本地 artifact；
   Selector-owned compact tokens 和 MLLM-native vision tokens 必须作为独立 derived artifacts，分别绑定 exact
   checkpoint/processor，不能覆盖 raw-frame identity。
4. 约 8B MLLM 的 native vision tower、language backbone 和 scoring head 属于 P4-07 `ScoreUpdater`，不是
   `SegmentPerceiver`。Reranker call 的显存、视觉 tokens、文本 tokens、latency 和 cache 均单独计入 P4-08 cost。

### 8.1 要解决的问题

- 租卡环境实际运行哪个模型和版本；
- in-process Transformers、local server 还是 external API；
- selected segment 输入视频、frames 还是 clip；
- 是否使用 ASR/audio；
- prompt 能看到哪些用户/候选信息；
- 解码、timeout、retry 和 determinism 如何记录。

### 8.2 历史 Chinese-CLIP Deep Encoder baseline（由 P4-ARCH-02 superseded）

1. Encoder 固定复用 P4-03 的 `OFA-Sys/chinese-clip-vit-base-patch16` revision
   `36e679e65c2a2fead755ae21162091293ad37834` image tower 和 official 224×224 processor；模型完全 frozen、
   `eval`/inference-only，不训练、不调用 text tower，不引入第二个未经核验的视频模型；
2. 将 selected segment 均分为八个时间 bin，目标 timestamp 为每个 bin 的中心，即段内
   `6.25/18.75/31.25/43.75/56.25/68.75/81.25/93.75%`。按 deterministic nearest-PTS/坏帧替换规则寻找
   RGB frames，去重并过滤黑帧、严重模糊和越界帧；
3. 目标为最多八张有效帧。得到 2—7 张时保留真实有效帧数量并使用 mask，不复制帧凑满八张；少于两张时
   返回 typed decode/insufficient-frames failure，不发布 latent Evidence；
4. 每张有效帧输出一个 FP32、L2-normalized 512-D image vector，主 artifact 保存有序
   `frame_tokens[F,512]`、timestamps、frame checksums、valid mask、segment boundaries、processor/model/revision、
   sampling recipe 和 dtype。该历史 comparator 不先压成单一 mean embedding；聚合方式曾由 Small Reranker 决定；
5. Deep Encoder 是 content-only：不读取 Query、Memory、user ID、rank、target、future feedback、title、tags、
   subtitle、ASR 或 audio。Query/Memory 与 latent frame tokens 只在后续 Reranker 中融合，因此同一内容 artifact
   可跨用户/Query 安全复用；
6. 第一条 online path 使用 in-process inference 和 logical batch size 1；训练/Oracle artifact 构建可做
   deterministic batching，但必须产生同一 canonical outputs。Cache key 至少覆盖 media checksum、segment
   boundaries、actual timestamps/frame checksums、sampling recipe、processor、model revision 和 output recipe，
   不包含 user/Query；
7. cache hit 仍记录 logical perception action；实际 GPU call、latency、peak memory、processed/unique frames、
   dtype/device、cache hit、artifact bytes 和可得的 FLOPs estimate 分开记录。预算消费、timeout/retry 和 typed
   failure continuation 由 P4-08 统一确认；
8. replay 只读取和校验 saved latent artifact/ref，不重新解码媒体或运行 Encoder。部分输出、checksum mismatch、
   OOM、decode/model exception 均 fail closed，不污染 Evidence 或 ranking。

### 8.3 历史 MLLM proposal（已由 P4-ARCH-01 superseded）

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

### 8.4 Prompt firewall

title/tag/category/ASR 和视频中的文字都视为 untrusted content：只能作为被分析的数据，不得执行其中的
指令。system prompt、数据 delimiter、JSON schema 和长度上限必须版本化；secret 永不进入 resolved config、
prompt artifact 或 trace。

### 8.5 历史已关闭决策（仅适用于 superseded Chinese-CLIP baseline）

- exact pinned Chinese-CLIP image tower、official processor 和 frozen/in-process boundary；
- eight-bin-center timestamps、2—8 valid-frame mask 和少于两帧 fail-closed；
- FP32 L2-normalized ordered frame tokens `[F,512]`，不在 P4-05 提前池化；
- content-only、query/user-independent cache identity 和 saved-output replay；
- audio/ASR/subtitle/title/context 全部关闭；
- cost/cache/failure 必须记录，exact budget/retry semantics 交 P4-08。

### P4-05 Decision Record

> 本记录保留 2026-08-06 的历史决定；其 exact Chinese-CLIP encoder/token payload 已由 P4-ARCH-02 取代。
> eight-bin-center、2—8 valid frames、fail-closed、content-only artifact 和 replay 原则继续有效。

```text
Decision ID: P4-05
Status: Confirmed
Decision: P4/V1 `SegmentPerceiver` 复用 pinned `OFA-Sys/chinese-clip-vit-base-patch16` image tower，完全冻结并以 in-process batch-1 运行。对 selected segment 的八个等分时间 bin 取中心目标帧，经 deterministic nearest-PTS/坏帧替换后保留 2—8 张真实有效 RGB frames；少于两张 fail closed。每帧发布 FP32 L2-normalized 512-D token，latent artifact 保存有序 `[F,512]` tokens、mask、timestamps/checksums 和 exact model/processor/sampling identity，不在本 Gate 池化。Encoder 只读视频内容，不读 Query/Memory/user/text/audio；content-addressed cache 可跨用户复用，saved replay 不重新运行模型。
Rationale: P4 的目标是先建立可复现的真实 positive-budget pipeline。复用已核验的 Chinese-CLIP image tower 可避免再引入未固定的视频模型，同时8个有序完整 frame tokens 比三帧 proxy 的单一 relevance scalar 提供明显更丰富的 latent Evidence。content-only boundary 保持缓存、安全和 Reranker 职责清晰，variable valid-frame mask 避免短片段靠复制帧制造虚假信息。
Alternatives considered: X-CLIP/VideoMAE/InternVideo 等原生视频编码器；同三帧 proxy 直接复用；单一 pooled segment embedding；固定复制/补帧到8；16/32帧；Query-conditioned encoder；audio/ASR/subtitle/title fusion；external API/server。
Affected schemas/interfaces: 实现既有 `SegmentPerceiver`；latent tensor 存外部 versioned artifact，P4-06 已确认由 per-segment `Evidence.embedding_ref` 指向 bundle manifest，P4 baseline 不生成 aggregate ref。公共 State/Trace 不内嵌 Tensor/raw frames；新增 internal frame resolver、encoder adapter、artifact publisher/cache 和 cost sidecar。
Affected docs/tests: todo/phase_4_discussion.md；docs/active_multimodal_reranker_engineering_spec.md；todo/implementation_roadmap.md；后续测试覆盖 exact revision/processor、bin-center timestamps、nearest-PTS/invalid filtering、2/7/8-frame masks、少于2帧失败、FP32/L2/token ordering、content-only inputs、cache identity/corruption、batch equivalence、replay no-model-call 和 cost metadata。
Resolved follow-up: exact encoder/revision、uniform-8 timestamp recipe、short-segment fallback、token-vs-pool、text/audio boundary、batch/cache/replay 和 cost fields。
Deferred follow-up: P4-07 token aggregation/Reranker；P4-08 timeout/retry/action accounting；P6 proxy low-resolution dense-frame、4/8/16/32 deep-frame、sampling/aggregation、native video encoder 和 Query-conditioned/audio ablations。P4-06 latent Evidence public-ref/failure publication 已由其 Decision Record 解决。
Confirmed by: User
Date: 2026-08-06
```

---

## 9. P4-06 — Latent Evidence, Failure, and Public-Ref Boundary

Status: `Confirmed; artifact payload amended by P4-ARCH-02`

主线 Evidence 现在使用 external selected raw-frame bundle；公共 State/Trace 仍只保存 refs/紧凑 metadata，不内嵌
frames、Tensor 或模型输出。下方 structured-text vocabulary/parser 与 Chinese-CLIP latent bundle 均作为历史
proposal/comparator 保留。

### 9.0 P4-ARCH-02 active Evidence contract

1. 每个成功观察的 segment 原子发布一个 content-addressed raw-frame bundle：manifest 闭包绑定 2—8 张 canonical
   RGB frame payloads、timestamps、frame checksums、valid mask、media/segment identity、sampling recipe、codec/
   color-space identity、payload sizes 和 SHA-256。Partial bundle 不得获得公共 ref。
2. P4 baseline 复用现有 schema：`Evidence.raw_output_ref` 指向 selected-frame bundle manifest；
   `Evidence.embedding_ref` 仅在存在 exact model-specific derived visual-token manifest 时使用，否则为 null。
   `text_summary` 与 `confidence` 仍为 null。Evidence event metadata 记录 acquisition Need/step，但 raw-frame content
   artifact 不包含 user/Query，可跨用户安全复用。
3. Selector-owned compact tokens、Chinese-CLIP comparator tokens 和 8B MLLM-native visual caches 是三个不同的
   derived artifact families；任何 ref 都必须绑定 source frame bundle checksum、model checkpoint、processor、
   dtype/shape/token recipe。用户/Query-dependent MLLM scores/output 不能跨用户缓存。
4. P4-06 不生成 item-level aggregate embedding。每次成功按 action order 追加 per-segment Evidence；
   `evidence_embedding_ref=null`。P4-07 MLLM Reranker 解析当前全部 frame Evidence 并直接输出 candidate scores。
5. Atomic publication、typed failure、failed-no-Evidence/no-score-update、secret/path sanitization、受限 artifact 不入 Git
   和 saved replay 不重跑 decode/MLLM 的原则保持有效。Replay 缺失或损坏 frame/model-output artifact 时 fail closed。

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

### 9.3 历史 Chinese-CLIP latent Evidence baseline（由 P4-ARCH-02 superseded）

1. 每个成功观察的 segment 发布一个 content-addressed latent bundle。Canonical entry point 为
   `manifest.json`，payload 为 `frame_tokens.npy`；NPY 只允许非 object tensor 并以 `allow_pickle=False` 加载。
   `frame_tokens` 必须是 finite FP32 `[F,512]`，`2 <= F <= 8`，各行满足已确认 L2 normalization contract。
2. Manifest 至少保存 schema/recipe version、item/segment identity、media checksum、segment boundaries、实际
   timestamps/frame checksums、valid-slot mask、tensor shape/dtype、model/revision、processor、sampling/output recipe，
   以及 payload `ResourceRef`、SHA-256 和 size。Manifest 与 payload 均先写临时文件、校验后原子发布；partial
   bundle 不得获得公共 ref。
3. 成功的 `Evidence.embedding_ref` 指向该 bundle manifest，而不是把 Tensor 内嵌到 State/Trace；`source` 固定为
   versioned latent perceiver identity。`attributes` 只保存 `evidence_kind=latent_frame_tokens`、schema version、
   frame count 和 token dim 等紧凑 typed facts；`metadata` 关联 acquisition step、Information Need ID/concept、
   supporting atom IDs、query/template identities 与 artifact/model recipe。content artifact 本身仍不含 user/Query。
4. Latent baseline 不生成文本或校准概率，因此 `text_summary=null`、`confidence=null`、`raw_output_ref=null`。
   `evidence_id` 由 run ID、action step、item/segment identity 和 manifest checksum 确定性派生；同一 cached content
   在不同 run 中仍形成各自的 Evidence event，但共享同一 content artifact ref。
5. P4-06 不做 frame pooling 或多 segment 聚合。每次成功只把 per-segment Evidence 按 action order 追加到对应
   `ItemEvidenceState.evidence`；`aggregated_attributes` 只维护 evidence/segment/frame-count inventory，
   `evidence_embedding_ref=null`。P4-07 从全部 per-segment refs 加载 tokens，并负责 learned frame/segment aggregation。
6. 只有 bundle 发布、checksum/schema/identity 校验全部成功后才返回 `ObservationStatus.SUCCEEDED`。失败统一返回
   `FAILED`、`evidence=null` 和稳定 failure code，至少区分 `decode_failed`、`insufficient_valid_frames`、
   `encoder_timeout`、`encoder_oom`、`encoder_failed`、`artifact_write_failed`、`artifact_missing`、
   `artifact_corrupt` 和 `cache_mismatch`；failure reason 必须清洗 secret 与绝对路径。
7. failed perception 只更新 `ObservationState` 和 cost/failure sidecar：不产生 Evidence、不调用 ScoreUpdater、排名
   保持不变。一次 attempt 的 action 消耗、retry eligibility 和底层 call accounting 继续由 P4-08 确认。
8. public State/Trace/Result 只保存 ResourceRef 与紧凑 JSON metadata，不保存 raw frames、token values、受限媒体、
   secret 或绝对路径。latent/cost/failure artifacts 使用声明的受控 root，默认不提交公开仓库。Saved replay 只解析
   manifest/payload refs 并校验 closure，不重新解码或运行 Encoder；missing/corrupt/mismatch 必须 fail closed。

### P4-06 Decision Record

> 本记录保留 2026-08-06 的历史 latent-token payload；P4-ARCH-02 已将主 entry 改为
> `Evidence.raw_output_ref -> selected raw-frame bundle`，并把 `embedding_ref` 改为可选 model-specific derived ref。

```text
Decision ID: P4-06
Status: Confirmed
Decision: P4 latent Evidence 采用 per-segment content-addressed bundle：canonical manifest 绑定一个 finite FP32 `[F,512]`（2—8帧）`frame_tokens.npy` payload、mask/timestamps/frame checksums、exact encoder/processor/sampling identities 与 checksum closure。成功 Evidence 的 `embedding_ref` 指向 manifest，文本、confidence 和 `raw_output_ref` 均为空；Evidence event 记录 acquisition Need/step，但 content artifact 保持 user/query independent。P4-06 不池化 frames、不聚合同 item 多 segments，`evidence_embedding_ref=null`，全部 learned aggregation 交 P4-07。只有 artifact 原子发布并完整校验后才产生 Evidence；失败只产生 typed failed observation/cost record，排名不变。公共 State/Trace 只保存 refs/紧凑 metadata，saved replay 只校验并加载 saved artifact，不重新运行 Encoder。
Rationale: 保留 ordered frame tokens 可避免在 Reranker 之前不可逆丢失时间与局部视觉信息，也使 P4-07 可以统一学习 frame/segment aggregation。将 content artifact 与 run-specific Evidence event 分离，可跨用户/Query 复用缓存，同时保留本轮 Information Need provenance。manifest-first checksum closure、atomic publication 和 fail-closed replay 防止 partial/corrupt tensor 静默污染 EvidenceState 与排名。
Alternatives considered: 在 P4-06 对 frames 求 mean/max；同 item 多 segment 预先平均为 `evidence_embedding_ref`；Tensor/raw frames 内嵌公共 State；裸 tensor ref 不绑定 manifest；把 latent token 伪装成文本 summary/confidence；partial tokens 作为成功 Evidence；replay 时缺 artifact 自动重跑 Encoder。
Affected schemas/interfaces: 复用现有 `Evidence`、`ItemEvidenceState`、`EvidenceState`、`PerceptionResult`、`ObservationState` 和 `ResourceRef`，不修改公共 schema shape。新增 internal latent bundle manifest/publisher/loader、production Evidence/Observation updater 规则和 failure-code vocabulary；`Evidence.embedding_ref` 指向 manifest，`ItemEvidenceState.evidence_embedding_ref` 在 P4 baseline 保持 null。
Affected docs/tests: todo/phase_4_discussion.md；docs/00_shared_domain_schemas.md；docs/active_multimodal_reranker_engineering_spec.md；todo/implementation_roadmap.md；后续测试覆盖 NPY no-pickle、2/7/8-frame shape/dtype/finite/L2、manifest/payload checksum closure、atomic/no-partial publication、deterministic evidence ID、Need provenance、cache reuse/event separation、append order、no pooling/aggregate ref null、typed failures、failed no-Evidence/no-score-update、path/secret sanitization 和 replay no-model-call。
Resolved follow-up: latent bundle schema、public `embedding_ref`、run event/content identity separation、no-aggregation boundary、null text/confidence/raw-output fields、typed failures、atomic publication、privacy/public sidecar 和 saved replay closure。
Deferred follow-up: P4-07 exact learned frame/segment aggregator；P4-08 retry、budget、timeout 和 physical-call accounting；P6 alternate storage format、pooling baselines、precomputed aggregate refs 与 privacy/license release study。
Confirmed by: User
Date: 2026-08-06
```

---

## 10. P4-07 — Native-frame MLLM Candidate Reranker

Status: `Pending`

P4-ARCH-02 已确认约 8B native-frame MLLM Reranker 是主线 `ScoreUpdater`。本 Gate 仍待确认 exact model/
revision、native frame/context contract、candidate scoring head、LoRA/QLoRA recipe、Observation State dataset、
loss/calibration 和租卡资源画像。

### 10.1 要解决的问题

必须让一个约 8B MLLM 在只读取已观察 raw-frame Evidence 的前提下，对完整 Top-100 输出稳定可训练的数值
scores。它不能观看全部候选视频、生成自由文本数字、读取 target/future feedback，也不能破坏 SASRec prior、
依赖 candidate serialization 顺序或重复累计旧 Evidence。

### 10.2 历史 residual/Small-Reranker proposals（已由 P4-ARCH-02 superseded）

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

1. Model family 只从支持离线部署、native multi-image/video、hidden-state/scoring-head fine-tuning、明确许可和
   租卡显存可承载的 7—9B class MLLM 中选择；exact model card、revision、processor、context limit、license、
   flash-attention/quantization compatibility 必须实测后再锁定，不能凭模型名猜测。
2. Reranker 只读取 EvidenceState 中已成功观察 segments 的 canonical raw frames；未观察候选只提供 compact
   item text/category/tag、SASRec item/base features、score/rank 和 mask。禁止为了 rerank 把 Top-100 全部视频帧
   输入 MLLM，否则主动感知成本边界失效。
3. 输入包含 SASRec user hidden/history projection、Dynamic Memory compact atoms、Top-100 compact candidates、
   每个 observed Evidence 的 acquisition Query/step 和 native frames。所有用户/候选文本均按 untrusted data
   delimiter 处理；不包含 target、future feedback、Oracle gain 或绝对路径。
4. 输出使用 candidate marker hidden states + shared scalar scoring head，一次返回与 Top-100 一一对应的 logits；
   不通过 autoregressive JSON/自然语言生成分数。Candidate order 在训练中随机化，并显式提供 original rank/
   candidate identity；测试 permutation consistency 和 stable identity tie-break。
5. 首个 prior-preserving score contract 建议为 `final_i = base_i + alpha * tanh(delta_i)` 或数学等价的 bounded
   residual head；exact alpha/normalization 只在 validation 校准。每轮从 initial SASRec base + full current
   EvidenceState 重算，不输入 previous current scores。
6. 先按 user/time split，再在 train 内构造 Observation State variants：no-evidence、target evidence、不同 rank
   non-target evidence、multi-item/multi-segment、不同 evidence count、hard negative、mismatched/shuffled frames/
   queries。Validation/test 不 target-inject，并同时报告 conditional Top-100 reranking 与 end-to-end retrieval。
7. 第一版优先 parameter-efficient tuning：冻结或部分冻结 native vision tower，以 LoRA/QLoRA 调整 projector/
   language blocks/scoring head；full fine-tuning、vision unfreeze 和 3B/8B/更大 scale 属于 P6 cost/capacity ablation。
8. Primary loss 为 Top-100 listwise next-item CE；同时加入 no-evidence prior consistency、mask invariance 和
   evidence-query mismatch/shuffle contrastive objective。Loss weights、candidate packing/chunking、max observed
   frames/context、optimizer、batch/gradient accumulation 和 early stopping 仍需 P4-07 确认。
9. Reranker 必须先取得相对 SASRec/no-evidence/Small-latent baselines 的有效且稳定 validation 表现并冻结 exact
   checkpoint；之后 P5 才使用它生成 Segment Selector counterfactual labels。P4/P5 baseline 不联合训练。

### 10.4 下一轮需要逐项确认

- exact 7—9B MLLM shortlist、许可、语言/视频能力与租卡 GPU profile；
- raw-frame count/resolution/native image-vs-video API、多个已观察 segments 如何打包；
- Top-100 candidate serialization/context budget 和 candidate-marker scoring head；
- Observation State dataset size、variant proportions、hard negatives 和 target-injection firewall；
- LoRA/QLoRA modules、quantization、loss weights、validation metrics 和 checkpoint selection；
- MLLM score artifact、cost/replay 与 StopPolicy calibration。

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
- 真实 component selector 显式选择 rule Need、Query-relevance bootstrap Value、raw-frame Perceiver、
  Evidence/Observation Updater、native-frame MLLM ScoreUpdater 和 StopPolicy；禁止 unavailable/mock silent fallback；
- 第一条 canonical real smoke 建议 `max_perception_actions=2`，证明更新后重新估计 need/value 并再次决策；
- `ranking_margin_threshold=null`；`min_segment_value` 只在 P4-04 value 范围锁定后设置；
- model/media/prompt preflight 在正式 action 前完成，资源缺失不能消耗感知 budget；
- Controller 内部 action accounting、failed result 和 component exception semantics 保持 P1 不变。

### 11.2 一次 action 与模型调用

```text
one selected-segment observe + successful MLLM rerank step = one Agent action
```

一次成功 action 包含 raw-frame bundle resolve/publish，以及随后一次约 8B MLLM ScoreUpdater forward；failed
Perceiver 不调用 Reranker。若将来允许 retry，多次 decode/model calls 仍属于同一 logical action，但必须完整
报告 selector、frame、MLLM call count/tokens/FLOPs/latency，不能只报 action 数掩盖成本。

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
    ├── reranker_request_manifest.json
    └── candidate_scores.json
```

每次 attempt/call 至少记录：segment duration、requested/processed frame count、selector tokens/FLOPs、MLLM visual/
text tokens、latency、peak memory、model/revision、processor/context/scoring-head versions、quantization/LoRA identity、
cache hit、status/failure code 和 score-output checksum。

`PerceptionResult.metadata` 只放轻量 reference/cost summary；大型 payload 留在 sidecar。saved-output replay 继续只验证 State/Trace chain，不读取媒体、不调用 Deep Encoder；另建 P4 artifact validator 检查 sidecar/ref/checksum/cost closure。

### 11.4 Cache 推荐边界（待确认）

- raw-frame bundle 和 frozen Selector content tokens 可按 content/model identity 跨用户复用；MLLM candidate scores
  的 cache key 必须覆盖 model/scoring-head revision、frame checksums、Top-100 serialization、SASRec prior、
  Information Need、Memory/Evidence context，不能只按 segment ID 跨用户复用 personalized output；
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
| P4-04 | pure Query-relevance Segment Value | Confirmed |
| P4-ARCH-01 | Deep Encoder + Small Reranker architecture amendment | Superseded by P4-ARCH-02 |
| P4-ARCH-02 | ≤1B Selector + native-frame ~8B MLLM Reranker | Confirmed |
| P4-05 | eight-bin selected raw frames；Chinese-CLIP payload superseded | Confirmed, amended |
| P4-06 | raw-frame Evidence、typed failure、public refs | Confirmed, amended |
| P4-07 | native-frame MLLM Candidate Reranker | Pending |
| P4-08 | runtime/budget/cache/cost/replay | Pending |
| P4-09 | evaluation/tests/DoD | Pending |
| P4-XG-01 | cross-gate audit and implementation authorization | Pending |

下一项：确认 P4-07 exact native-frame MLLM model、scoring head 和 Observation State training data。

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
