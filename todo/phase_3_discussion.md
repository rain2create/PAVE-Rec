# Phase 3 Discussion — Real Cheap Path: User Memory + SASRec
# Phase 3 真实低成本路径逐项确认

## 1. Phase 3 的定位

Phase 3 的目标是用可训练、可持久化、可独立评估的真实 Cheap Path 替换
Phase 1 的 `MockUserMemory` 和 `MockInitialRanker`：

```text
Phase 2 exact release
  ├── UserBehaviorSequence
  ├── ItemFeatureRecord
  └── immutable item/segment Stores
          │
          ├──→ Dynamic Hybrid User Memory
          └──→ SASRec Initial Ranking
                       │
                       ↓
             Phase 1 Recommendation State
                       ↓
              unchanged AgentController
```

本阶段实现的是第一条真实、低成本推荐先验和用户记忆 baseline，不接入真实 MLLM，
不决定最终 Information Need、Segment Value 或 Score Update 研究方案。

Phase 3 当前整体状态：`In Discussion`。

### 1.1 P1/P2 compatibility rule

Phase 3 必须建立在 Phase 1/2 已确认契约之上，不得因为训练或模型实现方便而静默修改：

- `AgentController` 状态机、budget、stop、trace/replay 和 failure lifecycle；
- `AgentRunRequest`、`UserMemoryView`、`InitialRankingOutput`、`RecommendationState`
  等 Phase 1 公共 schema；
- `UserMemory`、`InitialRanker`、Item/Segment Store 等已确认 Protocol；
- Phase 2 exact-release、immutable `LoadedRelease`、release inventory、root/path safety、
  persistent Store 和 no-latest/no-mtime 规则；
- Phase 1/2 canonical serialization、identity 字段含义和测试隔离语义。

Phase 3 可以增加内部训练 schema、derived-dataset manifest、checkpoint manifest、
Memory State/Store 和新的显式 adapter，但这些对象不能反向污染既有公共 Domain Schema。
如果某个研究目标在上述边界下确实无法表达，必须先把它记录为 blocker；不能在实现中
悄悄扩大 P1/P2 interface。

### 1.2 本阶段明确不做及后续归属

- 真实 MLLM 调用、prompt、Evidence Parser 或感知成本统计：Phase 4 确认第一条
  expensive-path baseline；
- Information Need 的 need vocabulary、打分/选择公式和真实 estimator：P3 只确认
  Memory 输出的 readiness contract，Phase 4 先确认 rule-based baseline，learned
  estimator 留给 Phase 7 optional advanced research；
- 真实候选上的 Segment Value：Phase 4 需要一条非学习式 heuristic/relevance baseline
  支撑真实 MLLM loop，Phase 5 再确认 expected-gain label、Oracle 数据和 supervised model；
- Evidence-to-score update：Phase 4 确认第一条可解释 residual baseline，learned/unified
  reranker 留给 Phase 6 evaluation 后的 Phase 7 optional research；
- 将 Preference Atom 融合进 SASRec：第一条 P3 baseline 明确保持独立，是否融合归入
  Phase 7 optional advanced research；
- 在 online Agent loop 内训练、切分数据、生成 embedding 或批量提取特征；
- RL：只在 Phase 7、且 supervised system 稳定后讨论；
- 把第一条数据集、embedding model、threshold 或 negative sampler 宣布为最终研究方案。

上述“后续归属”只防止研究问题失去落点，不代表相应 baseline、公式或模型已经确认。

### 1.3 CPU/GPU boundary

Phase 2 的 `CPU-only structural feature/proxy baseline` 是第一条验收 baseline 的运行约束，
不是整个仓库禁止 GPU。它只从已验证 metadata、segment definition 和 locator 生成结构化
records，不执行视频解码、神经网络 embedding 或训练，因此 GPU 不提供有效收益。CPU-only
使 Phase 2 golden、Windows/Ubuntu CI、无 GPU 开发机和离线复现保持同一行为。

Phase 3 的 SASRec 训练和 embedding 生成可以支持 GPU，但必须满足：

- device 是显式 config，不通过环境偶然选择；
- CPU 仍支持小 fixture、schema、loader 和 inference contract 测试；
- portable artifact identity 不包含本机 device/path/timestamp；
- 训练重复性、固定 checkpoint 推理重复性和跨平台 byte identity 分开定义；
- GPU-only quality gate 不能替代 project-wide CPU CI；
- Phase 3 不改变 Phase 2 structural baseline 的既有行为和 golden artifacts。

---

## 2. 讨论方式

每次只确认一个 Gate：

1. 先复核依赖的 P1/P2 Decision Records 和 stable docs；
2. 明确本 Gate 决定什么、不决定什么；
3. 列出可行选项、推荐 baseline 和 trade-off；
4. 记录用户确认、显式 Deferred 或 Blocked；
5. 只把已确认内容同步到 stable docs；
6. P3-00—P3-08 全部关闭并通过 P3-XG-01 后才开始主体实现；
7. 实现和 Definition of Done 全部满足后，Phase 3 才能标记 `Completed`。

每条 Decision Record 必须区分：

```text
data version
derived-dataset version
memory version
checkpoint version
component implementation version
schema version
```

这些版本不能共用一个字段或根据文件路径隐式推断。

---

## 3. P3-00 — Phase 1/2 Handoff and Compatibility Audit

Status: `Confirmed`

### 3.1 目标

在讨论模型前，先确认 Phase 2 数据如何进入 Phase 3 的离线训练和在线 adapter，并证明
不需要修改 Phase 1 Controller 或公共组件接口。

### 3.2 已存在的事实

- Phase 2 release inventory 已包含唯一 `behavior-sequences` artifact；
- 该 artifact 的 logical record 是 `UserBehaviorSequence`，内部保留完整
  `SequenceInteraction`；
- `LoadedRelease` 当前 eager 验证 release、manifests、indexes 和 Store coverage，
  但尚未提供专门的 behavior-sequence typed loader/query API；
- Phase 1 `AgentRunRequest.user_history`、`UserMemory.build_or_update()` 和
  `InitialRanker.score()` 只接收按顺序排列的 item-ID tuple；
- P2-01 已确认从 `UserBehaviorSequence.interactions` 确定性投影 item IDs，且不修改
  Phase 1 runtime interface；
- Phase 1 Controller 已经通过依赖注入隔离 User Memory 和 Initial Ranker 实现。

### 3.3 需要确认

1. 是否增加 release-scoped `BehaviorSequenceLoader`，从共享 `LoadedRelease` 的唯一
   artifact 加载 strict typed sequences；
2. loader 是一次性加载全部 user mapping，还是提供受控的按用户读取实现；
3. full interactions 只在离线 derived-dataset/Memory build 中使用，还是 Memory runtime
   implementation 还需要注入只读 sequence repository；
4. item-ID tuple 是否继续作为 Controller-facing 唯一 history projection；
5. runtime 是否对 request history 与 release/memory 中记录的 history version 做一致性检查；
6. missing user、empty/short sequence、unknown item 和 corrupted behavior artifact 的错误分类；
7. User Memory、SASRec checkpoint 和 runtime Stores 是否必须 pin 到同一 source
   `data_version`。

### 3.4 推荐 baseline（待确认）

- 保持 Phase 1 public interface 完全不变；
- 增加 release-scoped typed behavior loader，复用同一个 immutable `LoadedRelease`、
  inventory membership 和 verified resolver；
- 完整 interaction 只进入离线 dataset/memory build，Controller-facing adapter 继续接收
  deterministic item-ID tuple；
- runtime components 通过 manifest 验证自身训练/构建所用 `data_version` 与本次 run
  固定 release 一致；
- 任一 version/coverage 不一致 fail fast，不降级为 Mock、空 memory 或随机 ranking。

### 3.5 本 Gate 不决定

- 具体数据集；
- train/validation/test split；
- SASRec 架构；
- Atom extraction、threshold、EMA 或 decay；
- checkpoint 和 Memory artifact 的最终文件布局。

### 3.6 交付结果

- 唯一的 P2 → P3 behavior handoff contract；
- public runtime interface no-change record；
- data/checkpoint/memory release compatibility matrix；
- missing/corruption/version mismatch failure boundary。

### P3-00 Decision Record

```text
Decision ID: P3-00
Status: Confirmed
Decision:
1. Phase 3 不修改 AgentRunRequest、UserMemory、InitialRanker、AgentController 或其他
   Phase 1 public runtime contract；Controller-facing history 继续是按顺序排列的 item-ID
   tuple。
2. Phase 3 增加 release-scoped typed BehaviorSequenceLoader。它从共享 immutable
   LoadedRelease 的 inventory 中解析唯一 behavior-sequences artifact，复用 P2 exact-release、
   resolver verification、inventory membership 和 path-safety 语义；它不成为新的 Agent
   component role，也不修改现有 Item/Segment Store。
3. Loader 对外提供 deterministic sequential iteration，供 derived-dataset 和 Memory
   offline builders 消费。不得默认把任意规模数据全部常驻内存，也不得在 online hot path
   中为每个用户重复扫描 JSONL；verified-bytes 与 verified-path streaming 的内部选择在
   P3-01 获得真实数据规模后确定，不改变 logical output/error contract。
4. 完整 SequenceInteraction 只进入离线 derived-dataset、split、Preference Atom 和
   Memory snapshot 构建。进入 Phase 1 runtime boundary 时仍确定性投影 item IDs；online
   Agent 不执行 split、embedding batch build 或完整行为重处理。
5. AgentRunRequest.user_history 可以是已发布序列的合法时间前缀，不要求等于用户完整
   P2 sequence。SASRec adapter 验证 vocabulary/coverage；预构建 Memory snapshot 必须记录
   对应 history prefix/cutoff，并在加载时验证 request projection，禁止使用 prefix 之后的
   interaction 构建当前 Memory。具体 fingerprint/schema 在 P3-06 确认。
6. Derived dataset、SASRec checkpoint、Memory snapshot 和 runtime persistent Stores 必须
   传递并验证同一个 source data_version。Derived/checkpoint 可以通过 manifest refs 形成
   provenance chain，但 bootstrap 必须解析整条链并在进入 Controller 前 fail fast；不能
   自动选 latest/closest、降级 Mock、返回空 Memory 或使用随机 Ranker。
7. Published inventory 缔约/typed record/manifest internal inconsistency 使用
   ArtifactIntegrityError；filesystem membership/path/size/checksum failure 使用
   ResourceResolutionError；用户配置的互不兼容 artifact selection 使用
   ConfigurationError；runtime history/candidate vocabulary violation 使用 ContractError。
   Empty/short history 的 eligibility 留给 P3-02/P3-06，不在 P3-00 当作 corruption。
8. P3 derived dataset、Memory 和 checkpoint 是独立 immutable artifacts，不回写 P2
   behavior bundle，不把 split/negative/label/training policy 放进 P2 release，也不改变
   P2 data-version contents 或 Store semantics。
Rationale:
在保持 P2 行为序列为唯一顺序事实、P2 release immutable 和 P1 Controller interface
稳定的前提下，为真实训练与 Memory 构建增加一条可校验的数据通路；同时允许 evaluation
使用合法历史前缀，并通过 version/provenance/fingerprint 阻止跨 release 混用和未来泄漏。
Alternatives considered:
修改 AgentRunRequest 传完整 SequenceInteraction；Controller 在线查询完整行为；每次 run
重建 Memory；强制 request history 等于完整 sequence；默认 eager-load 全量用户；每次用户
查询重复扫描 JSONL；把 derived split/checkpoint 回写 P2 release；version mismatch 时自动
fallback。
P1/P2 compatibility evidence:
P2-01 已确认从 UserBehaviorSequence 确定性投影 item-ID tuple 且不修改 Phase 1 interfaces；
P2-03/P2-06 已确认 immutable exact release、inventory、resolver 和 version distinctions；
本 Decision 只新增 P3 offline loader/artifacts，不修改既有 Controller、Schema、Store、
publication 或 trace/replay behavior。
Affected schemas/interfaces:
New Phase 3 BehaviorSequenceLoader and future derived/memory/checkpoint internal manifests.
No Phase 1 public schema/interface change and no Phase 2 release/Store schema change.
Affected docs/tests:
todo/phase_3_discussion.md；后续 P3 loader/provenance/prefix/version/error tests；全部 P1/P2
regression/golden/replay/publication/Store tests。
Resolved follow-up:
P2 → P3 behavior handoff、runtime history projection、prefix compatibility、source-version
pinning、failure ownership 和 immutable derived-artifact boundary。
Deferred follow-up:
P3-01 的真实数据规模/adapter；P3-02 split/short-history policy；P3-06 Memory prefix
fingerprint schema；具体 loader I/O optimization。
Confirmed by: User
Date: 2026-08-03
```

---

## 4. P3-01 — Target Dataset and Semantic Input Contract

Status: `In Discussion`

### 4.1 目标

确认第一条真实数据集及其 item/behavior semantics。没有该 Gate，SASRec 的 split、
candidate/negative sampling 和 User Memory 的语义 Atom 都无法被可靠定义。

### 4.2 需要确认

- 第一目标数据集和固定版本；
- 数据许可、下载和本地缓存边界；
- user/item ID 是否在 source adapter 中 pseudonymize；
- 哪些 interaction type/value 计入正反馈序列；
- 同 timestamp、重复 interaction 和删除/无效记录的 adapter 语义；
- item 的 title、category、creator、description、tags 等可用字段；
- 哪些字段明确进入 `ItemFeatureRecord.attributes`，哪些只作 provenance；
- item 缺少文本或 segment 时是否仍可进入 SASRec/Memory；
- 真实数据是否包含视频/segment media，还是 Phase 3 只验证 Cheap Path；
- source adapter 输出如何进入 Phase 2 已确认的 source manifest，而不是建立第二套数据面。

### 4.3 约束

- 仓库内 `preprocessing-v1` 继续只做 portable contract fixture，不能冒充训练数据；
- 真实数据、下载缓存、派生数据和 checkpoints 默认不进入 Git；
- dataset-specific 清洗必须位于显式 adapter/version 边界，不能放入通用 P2 processor；
- P3 不因数据集方便而改变 P2 canonical source/processed schemas。

### 4.4 交付结果

- dataset selection record；
- interaction vocabulary/value mapping；
- item semantic-field inventory；
- source adapter 和 Phase 2 ingestion boundary；
- license/privacy/local-data policy。

---

## 5. P3-02 — Versioned Derived Sequence Dataset

Status: `Pending`

### 5.1 目标

从 immutable Phase 2 behavior sequences 生成独立、versioned、无泄漏的 SASRec
training/evaluation dataset。该 derived dataset 不回写或改写 Phase 2 release。

### 5.2 需要确认

- chronological split 的粒度：leave-one-out、leave-two-out 或时间切分；
- train/validation/test target 的精确定义；
- minimum sequence length 和不足长度用户的处理；
- repeated item 是否保留；
- maximum sequence length 和 prefix truncation 方向；
- item vocabulary、padding/mask/special IDs；
- cold user、cold item 和 OOV semantics；
- training prefix/positive target 生成；
- validation/test candidate set 和 candidate generation source；
- negative sampling 是 materialized artifact 还是按 seed 在线生成；
- sampler seed、coverage、collision 和 positive exclusion；
- split/vocabulary/candidates/labels 的 manifest、checksum 和 provenance。

### 5.3 必须防止的泄漏

- test target 出现在对应 training prefix 之后的信息中；
- 使用未来 interaction 构建当前时刻的 Memory；
- 使用 validation/test label 选择 candidate 或 negative；
- 在全量数据上拟合只应使用 train split 的统计/semantic transformation；
- 因 canonical file ordering 意外替代用户时序事实。

### 5.4 推荐 artifact 边界（待确认）

```text
Phase 2 exact release
        ↓
P3 DerivedDatasetBuilder
        ↓
derived dataset manifest
  ├── source data_version
  ├── split recipe/version
  ├── vocabulary ref
  ├── train/validation/test refs
  ├── optional candidate/negative refs
  └── checksums and counts
```

### 5.5 交付结果

- strict derived-dataset schemas；
- deterministic builder Python API 和薄 CLI；
- split/vocabulary/candidate/negative semantics；
- leakage tests、identity tests 和 small golden fixture。

---

## 6. P3-03 — SASRec Architecture and Training Baseline

Status: `Pending`

### 6.1 目标

确认第一条标准 SASRec baseline，使其可单独训练、验证、保存和替换，而不把 User Memory
或多模态昂贵路径融合进模型。

### 6.2 需要确认

- framework/dependency 和最低支持版本；
- item/position embedding、block 数、hidden size、attention heads；
- activation、dropout、normalization 和 weight initialization；
- max sequence length；
- loss：sampled binary loss、cross-entropy 或其他标准 baseline；
- negative sampling strategy 和数量；
- optimizer、learning rate、weight decay、batch size、epochs；
- validation metric、early stopping 和 best-checkpoint rule；
- gradient clipping、mixed precision；
- explicit device (`cpu`/`cuda`/`mps`) 和 unavailable-device failure；
- global/per-worker seed、data-loader ordering 和 determinism policy；
- 训练中断、resume 和 partial checkpoint semantics。

### 6.3 第一条 baseline 边界

- 只消费 sequence item IDs 和 derived-dataset vocabulary；
- 不消费 Preference Atom、MLLM Evidence 或 Segment Proxy；
- model tensor 不进入公共 Domain Schema；
- training loop 不进入 `AgentController`、runner 或 online Store；
- 超参数全部由 strict typed config 决定，不在代码中形成隐藏研究默认值。

### 6.4 CPU/GPU 验收边界

- 小 fixture training/inference 必须可在 CPU 执行；
- 真实训练可以显式选择 GPU/MPS；
- CI 不要求训练真实数据或下载 pretrained assets；
- 固定 checkpoint 的 CPU inference contract 必须可测试；
- 不预先承诺不同 device/backend 训练产生 byte-identical weights。

### 6.5 交付结果

- typed SASRec train config；
- reusable model/trainer Python APIs；
- thin train/evaluate CLI；
- metrics/history；
- deterministic small-fixture tests。

---

## 7. P3-04 — Checkpoint, Candidate Scoring, and Score Semantics

Status: `Pending`

### 7.1 目标

确认训练结果如何成为可验证的 `InitialRanker` implementation，以及 SASRec score 如何
安全进入 Phase 1 ranking/uncertainty contract。

### 7.2 Checkpoint 需要确认

- checkpoint manifest 字段；
- model weights、model config、vocabulary、derived dataset 和 source data refs；
- best/last checkpoint 的区别；
- checksum、checkpoint ID 和 schema version；
- save atomicity、existing target、resume 和 corruption behavior；
- `map_location`、dtype 和 device-independent loading；
- incompatible config/vocabulary/data version fail-fast 语义。

### 7.3 Candidate scoring 需要确认

- caller 仍显式提供 `candidate_ids`，还是另建独立 candidate provider；
- history item 是否可以出现在 candidates；
- unknown candidate/OOV 行为；
- batch scoring、canonical output coverage 和 deterministic tie-break；
- `user_sequence_feature_ref` 是否发布，以及由哪个 artifact store 持有；
- raw logits、dot product、sigmoid 或其他 score representation。

### 7.4 与 Phase 1 StopPolicy 的关键边界

Phase 1 `ThresholdStopPolicy` 使用 top1/top2 raw-score margin。Mock 的 `0.10` threshold
不能默认解释为 SASRec confidence。P3 必须在以下方向中显式确认一个：

1. 定义并验证 score calibration/normalization；
2. 为 P3 real-cheap-path config 将 certainty threshold 设为 `null`；
3. 保留 raw ranking score，但只在后续专门研究校准后启用 certainty stop。

不得直接复用 Mock threshold 并宣称真实排名已经“足够确定”。

### 7.5 交付结果

- checkpoint and loader contract；
- `SASRecInitialRanker` adapter；
- score/rank/tie/OOV semantics；
- checkpoint reload and inference equivalence tests；
- StopPolicy compatibility record。

---

## 8. P3-05 — Preference Atom and Embedding Baseline

Status: `Pending`

### 8.1 目标

确认第一条可解释的 Preference Atom 来源。该 Gate 只定义 atom/embedding 构建，不决定
stable/emerging/fading 的状态转移。

### 8.2 需要确认

- atom 由单 item、显式 metadata field、聚合/聚类还是其他 rule 构建；
- atom text 的 canonical construction；
- long/short 输入各使用哪些 interaction type/value；
- embedding model、model revision、pooling、normalization 和 dimension；
- model/download/cache/license boundary；
- CPU/GPU batch embedding config；
- 缺失文本、空文本、非目标语言和重复文本语义；
- atom ID、embedding artifact、builder recipe 和 provenance；
- embedding 是 Phase 2 feature extension、P3 derived artifact 还是 Memory-owned artifact；
- 是否在第一版生成 semantic profile。

### 8.3 约束

- 不能只凭 item ID 伪造有语义的 atom text；
- embedding Tensor 不进入 `UserMemoryView`，只通过 `ResourceRef` 暴露；
- `metadata` 不默认成为模型特征；
- pretrained model revision 必须固定，不能运行时自动漂移到 latest；
- online Agent 不下载模型或批量生成 embeddings。

### 8.4 交付结果

- internal `PreferenceAtom` schema；
- AtomBuilder/EmbeddingProvider interfaces；
- versioned embedding artifacts；
- empty/missing/duplicate/multilingual behavior；
- CPU fixture and optional accelerated execution tests。

---

## 9. P3-06 — Dynamic Hybrid Memory Update and Persistence

Status: `Pending`

### 9.1 目标

在已确认 Atom/Embedding 基础上定义 Long × Short matching、stable/emerging/fading、
drift、持久化和 reload baseline，并投影为既有 `UserMemoryView`。

### 9.2 需要确认

- long-term 和 short-term window/selection；
- one-to-one、many-to-one 或 independent-max matching；
- cosine matrix 空轴语义；
- stable/emerging/fading thresholds；
- strength、persistence 的精确定义和 `[0, 1]` 映射；
- EMA coefficient；
- emerging accumulation 和 promotion rule；
- fading decay、inactive 和是否删除；
- repeated interactions、same timestamp 和 no-new-event idempotency；
- new/drop/global drift normalization；
- semantic profile 是否 Deferred；
- `updated_at_ms` 使用 source event time 还是 execution time；
- Memory State、matrix、embeddings、UserMemoryView snapshot 的 artifact layout；
- per-user update atomicity、concurrent update、existing version 和 corruption behavior。

### 9.3 Public view compatibility

真实 Memory 必须投影到已经确认的：

```text
UserMemoryView
  long_term_atoms
  short_term_atoms
  preference_matches
  drift fields
  optional semantic_profile
  optional similarity_matrix_ref
  memory_version
  updated_at_ms
  metadata
```

不得把完整 Tensor、训练对象、Store path 或 mutable internal State 塞进公共 View。

### 9.4 Information Need readiness

P3 不实现真实 `InformationNeedEstimator`，但必须确认真实 Memory 对 Phase 4 是可消费的：

- 每个可用于推荐推理的 atom 有稳定 ID、规范化 text、state、strength 和 persistence；
- stable/emerging/fading match 引用有效 atom IDs，similarity 的缺失和边界语义唯一；
- new/drop/global drift 的定义、范围和缺失语义明确；
- embedding/matrix 只通过可验证 `ResourceRef` 暴露；
- 一次 run 内 View 固定，need estimator 不反向修改 Memory；
- Phase 4 可以只读取 `RecommendationState.user_memory`，不依赖 Memory internal State、
  physical path 或训练对象；
- readiness tests 只验证信号完整性和引用一致性，不伪装成已确认的 need vocabulary、
  evidence-gap 公式或真实 estimator 效果。

Phase 4 必须在 MLLM prompt/perception 之前建立单独 Gate，确认第一条真实 rule-based
Information Need baseline。

### 9.5 Runtime mode 需要确认

- 推荐 baseline：离线 build/update 并在 online run 中只读加载固定 Memory snapshot；
- alternative：runtime `build_or_update()` 在注入的 Memory Store 上同步更新；
- 两种模式都必须保持一次 Agent run 内 `UserMemoryView` 固定，perception Evidence 不反向
  更新用户兴趣。

### 9.6 交付结果

- internal Memory State schemas/interfaces；
- matching/update/persistence baseline；
- deterministic projection to `UserMemoryView`；
- Information Need readiness contract and tests；
- version and atomic reload semantics；
- stable/emerging/fading/drift fixture suite。

---

## 10. P3-07 — Config, Bootstrap, Runtime Integration, and CLI

Status: `Pending`

### 10.1 目标

将真实 Memory 和 SASRec 通过显式 config/bootstrap 接入既有 Controller，同时保持
训练、Memory build、evaluation 和 online Agent run 的 lifecycle 分离。

### 10.2 需要确认

- P3 configs 是否扩展 Phase 1 runtime config，derived/training config 是否保持独立；
- component selector 的固定映射和 descriptor version；
- root registry、exact release ref、derived dataset ref、memory ref、checkpoint ref；
- secret-free resolved config 和 project-relative portable fields；
- train/build/evaluate/run Python APIs；
- 对应 thin CLI 的名称、参数和 exit codes；
- run directory 是否继续只保存 P1 已确认的三项 artifact；
- checkpoint/memory refs 如何进入 resolved config/result metadata，而不改变 trace schema；
- bootstrap construction failure 与 Controller component failure 的既有边界；
- Mock、real-memory-only、real-ranker-only、full-real-cheap selector combinations。

### 10.3 推荐集成 smoke（待确认）

```text
exact Phase 2 release
+ fixed real Memory snapshot
+ fixed SASRec checkpoint
+ persistent Item/Segment Stores
+ max_perception_actions = 0
→ unchanged AgentController
→ initial ranking
→ budget_exhausted
→ valid trace/result/replay
```

选择 zero-budget 是为了验证真实 Cheap Path 和 Controller 的兼容性，同时不调用
`mock-v1` signature-bound Information Need/Perceiver，也不假装 Phase 4 已经完成。

### 10.4 交付结果

- strict configs and selector mapping；
- shared Python APIs and thin CLIs；
- exact artifact pinning；
- real-cheap zero-budget Agent integration；
- existing Phase 1/2 runner/replay regression no-change evidence。

---

## 11. P3-08 — Evaluation, Test Matrix, and Definition of Done

Status: `Pending`

### 11.1 SASRec evaluation

需要确认：

- HR@K、NDCG@K、MRR、Recall@K 的 exact definitions；
- sampled-candidate 与 full-catalog evaluation；
- K values；
- seen-item filtering；
- candidate/negative seed；
- baseline comparator；
- fixture contract threshold 与真实数据 research result 分离。

### 11.2 Memory evaluation

至少需要覆盖：

- stable reinforcement；
- unseen short atom → emerging；
- repeated emerging → promotion；
- unmatched long atom → fading/inactive；
- empty long/short side；
- repeat execution idempotency；
- persistence/reload equivalence；
- drift boundary values；
- public `UserMemoryView` reference integrity。

真实 benchmark 和最终 memory metric 若仍未确认，可以 `Deferred`，但不能用单一 fixture
的通过代替研究效果结论。

### 11.3 Unit tests

- behavior loader and projection；
- derived split/vocabulary/prefix/negative semantics；
- leakage and OOV rules；
- SASRec masking, causal behavior, loss and score coverage；
- checkpoint/config/version validation；
- Atom/embedding identity and missing-input semantics；
- similarity/matching/update/drift boundaries；
- Information Need readiness and public-view-only consumption；
- Memory atomic persistence/reload；
- device selection and unavailable-device failure；
- score scale/StopPolicy compatibility。

### 11.4 Integration/E2E tests

- P2 exact release → derived dataset；
- small fixture train → checkpoint → reload → candidate scores；
- behavior/item semantics → Memory build → reload → `UserMemoryView`；
- real Memory View → Information Need readiness contract validation；
- API/CLI semantic equivalence；
- real Cheap Path zero-budget Agent run；
- trace/result saved-output replay；
- corrupted/mismatched release, dataset, checkpoint and memory failures；
- Phase 1 and Phase 2 complete regression suites。

### 11.5 Quality gates 待确认

- pytest 全部通过；
- `pave_rec` branch coverage threshold；
- Ruff lint/format；
- supported Python/platform matrix；
- CPU-only CI fixture；
- optional GPU smoke 是否只在有稳定 runner 时加入；
- tests 不下载真实数据/pretrained models，不访问网络，不写仓库 `data/`、`artifacts/`
  或 `runs/`；
- real dataset experiment 是独立 reproducible command，不成为普通 PR CI 前置条件。

### 11.6 Phase 3 Definition of Done 待确认

- P3-00—P3-08 与 P3-XG-01 全部 Confirmed；
- stable docs 与 implementation 一致；
- versioned derived dataset 可以从 exact P2 release 重建；
- SASRec 可以单独训练、评估、保存、加载和 score candidates；
- Dynamic Memory 可以单独构建、更新、持久化、加载和投影 View；
- Controller 无修改完成 real-cheap zero-budget run；
- existing P1/P2 golden、replay、publication 和 persistent Store tests 无回退；
- local quality gates 和同一 candidate commit 的 remote CI 全部通过；
- 已知研究限制和 Deferred 项明确记录。

---

## 12. P3-XG-01 — Cross-Gate Consistency Review

Status: `Pending`

P3-00—P3-08 字段和语义确认后、实现前统一检查：

- P3 没有修改或绕过 P1 Controller/public schemas/component interfaces；
- P3 没有修改 P2 release、Store、resolver、path safety 或 publication semantics；
- behavior sequence 是单一顺序事实，derived dataset 不回写 source release；
- source/derived/memory/checkpoint/component/schema versions 没有混用；
- split、Memory 和 evaluation 不读取未来信息；
- SASRec candidate scores 精确覆盖 caller candidates，tie/OOV 语义唯一；
- real score margin 没有套用未校准 Mock threshold；
- User Memory 与 SASRec 保持独立，只在 Recommendation State 汇合；
- P3 Memory View 满足 Phase 4 Information Need readiness，但没有提前写死 need vocabulary、
  estimator formula 或 learned policy；
- Tensor/physical path/execution-local fields 没有进入公共 portable schemas；
- CPU/GPU device 是 operational config，不改变 semantic identity；
- online Agent 不执行训练、embedding batch build 或数据切分；
- Phase 4/5/7 研究问题有明确归属但仍保持 Deferred；
- test fixtures、真实数据实验和 CI 的边界清楚且无仓库污染。

P3-XG-01 Confirmed 只表示允许开始实现，不表示 Phase 3 Completed。

---

## 13. Phase 3 Discussion Order

按以下顺序推进，一次只处理一个 Gate：

1. `P3-00 Phase 1/2 Handoff and Compatibility Audit`
2. `P3-01 Target Dataset and Semantic Input Contract`
3. `P3-02 Versioned Derived Sequence Dataset`
4. `P3-03 SASRec Architecture and Training Baseline`
5. `P3-04 Checkpoint, Candidate Scoring, and Score Semantics`
6. `P3-05 Preference Atom and Embedding Baseline`
7. `P3-06 Dynamic Hybrid Memory Update and Persistence`
8. `P3-07 Config, Bootstrap, Runtime Integration, and CLI`
9. `P3-08 Evaluation, Test Matrix, and Definition of Done`
10. `P3-XG-01 Cross-Gate Consistency Review`

依赖关系：

```text
P3-00 → P3-01 → P3-02 → P3-03 → P3-04
                  │
                  └────→ P3-05 → P3-06

P3-04 + P3-06 → P3-07 → P3-08 → P3-XG-01 → implementation
```

---

## 14. Decision Record Template

每个 Gate 确认后追加：

```text
Decision ID: P3-XX
Status: Confirmed | Deferred | Blocked
Decision:
Rationale:
Alternatives considered:
P1/P2 compatibility evidence:
Affected schemas/interfaces:
Affected docs/tests:
Resolved follow-up:
Deferred follow-up:
Confirmed by:
Date:
```

在 Decision Record 明确确认前，正文中的“推荐 baseline”只代表讨论建议，不代表已经
授权实现或已成为研究结论。
