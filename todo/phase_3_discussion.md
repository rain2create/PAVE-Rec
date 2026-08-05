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

Phase 3 当前整体状态：`Local Implementation Complete / Remote CI Pending`（P3-00—P3-08 与
P3-XG-01 已确认，全部真实 lifecycle 和本地 Definition of Done gates 已通过；同一 candidate commit 的
required remote CI 尚未执行，因此仍不是 `Completed`）。

### 1.1 Implementation progress（2026-08-04）

Phase 3 implementation 已完成并保持 P1/P2 public contract 不变：

- Windows filesystem boundary 支持 extended-length paths，physical staging 使用 deterministic 128-bit
  operational token；portable full-SHA identities、final bundle keys 和 path safety 未改变；
- 新增六类 P3 lifecycle 共用的 strict/frozen config inheritance + typed RootRegistry loader foundation；
- 新增 exact/self-verifying `AgentInputBundle`，固定 complete positive-history projection、独立 cutoff identity、
  exact derived/candidate refs 和到既有 `AgentRunRequest` 的唯一投影；
- 新增首条 strict `phase3-runtime` config，固化 artifact/SASRec/persistent/unavailable selector graph、exact refs、
  explicit device、read-only input roots、write-new runs root、raw-margin null 和 zero-budget constraint；
- 新增六个 role-specific Phase 4/5 unavailable guards，误调用统一 fail closed 为
  `ComponentExecutionError`；
- 已实现并真实运行 Tsinghua adapter、derived sequences、pinned BGE-M3 semantics、SASRec training/checkpoint、
  Dynamic Memory/audit、MostPop/SASRec full-catalog evaluation、101-candidate zero-budget Agent 和 replay；
- exact real artifacts、真实 aggregate metrics 和运行引用已同步到 stable docs。

当前本地验收：完整 suite `275 passed, 2 skipped`；branch coverage `90.03%`；Ruff clean；Windows
short-basetemp 全套通过并关闭原 285 字符临时发布路径问题。剩余 gate 仅为同一 candidate commit 的 required
remote CI；未通过远端前不得标记 `Completed`。

首条真实 artifact/run closure：

| Lifecycle | Exact version / run | Manifest or payload checksum |
|---|---|---|
| P2 source release | `p2-eb8680c692ae42a2dadbd8ac2f6cbaccfdf390581b974893072eb5d10d0fd1d2` | `sha256:2f3ca5d53c81b9cec08067bd852e9a523499e8ce2e53df89385cbceadd1e2ada` |
| P3-02 derived | `p3derived-0965ee788706f1f190728cfeaa1f7fbaa6747941997ef068a49d9950b61083b2` | `sha256:8963a04e151162ada68c874095bf4f99d7b859c9ec3bd422b0cfcf47e81dd3f0` |
| P3-03/04 SASRec best | `p3ckpt-ba0ad86774b3c6b7b601d61258ce60b1c06c1ca15d89a32e2e0169e7f3eec5d7` | `sha256:83ad9a644dca1a48354d78e728a991af1252f18b8158d7088817ae142572820e` |
| P3-05 semantics | `p3semantic-5a1288d6d6a76d757649a22a90d44909b3bc1da25aff5113188f92e17203d92d` | `sha256:0bb9f612bb922952b7b6472e12d696de3d0b0857e7696b3d4807247703e84268` |
| P3-06 Memory | `p3memoryartifact-0c2370bf509742115e03b101e3224c766e6c454e6af6bba8ca24f7d2ce34d3e7` | `sha256:c1bb6fdb86f4ac1fc5f147df0f765caf80743e56e3d3147daf832d7515316f97` |
| P3-06 audit | `p3memoryaudit-89ce25a5d9bb5544772dc6cdfc0eec788e5b14ce29db3f4ae8a1d0c887b58bcf` | `sha256:11b4a9d555d5d0a22a336ca3d98a83e0575b3d7ee59f864fb8dd1ed292a1f47e` |
| P3-07 Agent input | `p3input-fdf2733f0b4aa678cc426c9014b77ac68b55d1e62a2073e59932381aa8a487f0` | `sha256:e2fd6cb94a956a707e7ea6be24bb8c73dd1afd125627bceb4ac7db1b81aef5f7` |
| P3-07 run | `runs/phase3/20260804T141855Z-40d12921` | saved-output replay passed |

MostPop/SASRec 的 exact P3-08 evaluation refs 和真实 metric table 记录在
`docs/10_evaluation_and_training_plan.md`；Memory audit 解释记录在
`docs/01_dynamic_hybrid_user_memory.md`。

### 1.2 P1/P2 compatibility rule

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

### 1.3 本阶段明确不做及后续归属

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

### 1.4 CPU/GPU boundary

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
   P2 sequence。经 P3-02/P3-XG-01 最终消歧，真实 P3 runtime tuple 固定为 exact cutoff 前完整、
   未截断的 `positive_v1` item-ID projection；SASRec adapter 再做 OOV filtering/recent-50。完整曝光
   prefix 由独立 cutoff identity 锚定，不塞进公共 tuple。预构建 Memory adapter 绑定 exact snapshot，
   并验证 user、positive projection fingerprint 和 full-exposure cutoff closure；不得只凭 tuple 猜 snapshot，
   也不得使用 cutoff 后 interaction。
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

Status: `Confirmed`

### 4.1 目标

确认第一条真实数据集及其 item/behavior semantics。没有该 Gate，SASRec 的 split、
candidate/negative sampling 和 User Memory 的语义 Atom 都无法被可靠定义。

### 4.2 已核验的上游事实（2026-08-04）

权威来源是 [Tsinghua FIB Lab ShortVideo repository](https://github.com/tsinghua-fib-lab/ShortVideo_dataset)
及其链接的 [official authenticated server](https://fi.ee.tsinghua.edu.cn/datasets/short-video-dataset/)；
本次核验时上游 `main` 为 `6bd97f13a620f429745b24a17897457a75054052`。论文描述的是
10,000 users、153,561 videos、1,019,568 interactions，但上游 README 明确把当前服务器内容称为
`sampled dataset`；因此论文全量统计不能冒充当前可下载 release 的统计。

本地只读审计冻结了以下首批 source snapshot：

| Source artifact | Verified bytes / identity |
| --- | --- |
| `interaction_sampled.csv` | 159,920,078 bytes；SHA-256 `96cadb70829e853b8d7797bc566928eceeb670f19a8a0b92dbfa58b32372bf87`；server last-modified `2026-01-29T12:17:35Z` |
| server `README.md` | 5,382 bytes；SHA-256 `89d133788031f991ed4112bfb8fb5416514fd992e0418eccc8a9003dad4b91a7` |
| `categories_cn_en.csv` | 31,506 bytes；SHA-256 `39fcfbf0d42873facd25cbca3996e9e5d44a287d02c5530145bcf0ccd5d7d922` |

`interaction_sampled.csv` 的实际审计结果是：

```text
794,053 CSV logical rows
    → 129,483 unique (user_id, pid, exposed_time) exposure events
    → 6,654 users
    → 31,496 items
    → 93,616 proposed positive events
```

该表不是“一行一个 interaction”。同一次 exposure 会被多个 `tag_name`、多个层级/分支的
category 和完全重复行展开：122,967 个 exposure 有多行，单个 exposure 最多 675 行，组内有
104,519 个完全重复 expansion rows。所有 expansion 都连续出现；不同 timestamp 的重复 user-item
exposure 确实存在并应保留。同一 exposure 组内另有 9 个 expansion rows 的冗余 `p_date/p_hour`
与组内其他行冲突，但观看时间和反馈 flags 一致，所以 `exposed_time` 必须是唯一时序事实。

当前文件相对上游 README 还有 schema drift：实际存在未文档化的 `click`，不存在物理
`effective_view`；README 将 `effective_view` 定义为 `watch_time > 3 seconds`，所以只能显式派生，
不能伪称读取了 source column。部分 title 是合法 CSV quoted multiline/untrusted text，且 10 个 item
存在 title 不一致；不能把任意一行 title 静默当作 item 真值或直接拼进 prompt。

恢复后的第二次 strict audit 进一步确认：header/record arity、identity、boolean 和 numeric 字段均为 0 个
非法 row；exposure 组内真正的 feedback 冲突为 0，item 内 `author_id`/`duration` 冲突也都是 0。
但是 22,973 个 exposure 的 `p_date/p_hour` 与按 `Asia/Shanghai` 解释的 Unix timestamp 不一致；
37,666 个 exposure 的 `watch_time > duration`；20,578 个 item 有多个 `author_fans_count` 值。
这证明冗余 calendar fields 和 fans count 不能充当 immutable truth，watch time 也不能被 adapter 静默
clamp。冻结的 820-entry category mapping 覆盖全部 31,496 items，所有 item 至少有 tag 和 category；
按下面 `text-v1` 规则有 31,485 个 item 的 title 可用，其余只失去 optional title，不失去 item/behavior。

服务器还提供 `raw_file`、每个视频 `8 × 256` 的 `video_feature_total`、中英文 ASR 和英文标题。
官方 bootstrap sample 为 item `1..100` 的视频/特征/文本；它在当前行为表中只有 279 个 exposure、
242 users、150 个 proposed positives，足够做 media/MLLM integration smoke test，不足以作为
supervised Segment Value 训练集。

### 4.3 推荐的 dataset/version 决策

1. 第一条实现主线固定为 **Tsinghua ShortVideo official public sampled release**，不是论文中的
   full 1,019,568-interaction release。它可以承担第一条 SASRec、Dynamic Memory 和受控 Agent Loop；
   报告必须显示 `sampled` 和实际 counts。
2. 首条 upstream snapshot ID 为 `tsinghua-shortvideo-sampled-20260129-snapshot-v1`，其定义是 4.2 表中
   三个 source artifacts 的 exact paths、sizes 和 SHA-256 集合，不是只使用 behavior hash。
   P2 `data_version` 还必须覆盖 source manifest、`TsinghuaSourceAdapter` recipe/version 和全部实际引用的
   source bytes。禁止使用 `latest`、下载时间或目录名冒充任何一种 version。
3. 将来若作者提供 full interaction，必须创建新的 source snapshot/data version 并重新生成 split、
   checkpoint、Memory 和 evaluation artifacts；不能原地替换 sampled bytes。
4. Dropbox tiny 或官方 `1..100` media 只作开发/smoke，不作为正式训练 release。

### 4.4 Exposure adapter 和 interaction vocabulary

source adapter 必须先把 CSV 的 attribute expansion 聚合回 exposure，再生成 P2 canonical records：

```text
exposure key = (user_id, pid, exposed_time)
event order  = per-user sort(exposed_time, first_source_logical_row_ordinal)
occurred_at_ms = exposed_time * 1000
interaction_type = "short_video_exposure"
value = watch_time_seconds
```

- source user/video IDs 已经由上游 hashing；adapter 不做不可追溯的二次随机 hash，只映射为
  namespaced opaque strings，例如 `tsv:user:<source_user_id>` 和 `tsv:item:<source_pid>`。该确定性
  namespace 本身就是 mapping，不再生成一份额外 portable user-ID mapping table；用户人口属性不得参与 ID。
- 同 exposure 组内 `watch_time/cvm_like/click/comment/follow/collect/forward/hate` 必须一致；
  不一致则 adapter fail，不做多数表决。`p_date/p_hour` 只作 source audit，不进入 canonical event metadata。
- `tag_name` 和 category tuples 做去重、canonical sort 后并入 item 多值属性；attribute expansion rows
  不生成多次行为。不同 timestamp 的重复曝光完整保留。相同 timestamp 的不同 item 以首次 source
  logical-row ordinal 稳定打破平局，然后为每个 user 生成从 0 连续的 `interaction_index`。
- `BehaviorEvent.metadata` 保留 typed `like/click/comment/follow/collect/forward/hate`，并记录
  `effective_view = (watch_time > 3)` 的 derived recipe/version。`click` 因上游未定义只保留，不作为首版 label。
- `watch_time` 原值必须保留；`watch_time > duration` 合法且不得被 adapter clamp。completion/watch ratio
  如需截断、分桶或解释重播，只能由后续显式、versioned derived recipe 决定。
- source 没有 deletion/tombstone 字段，adapter 不推断“已删除”。空 identity、非法 timestamp/value/bool、
  critical item 冲突或 expansion 组内 feedback 冲突使整次 build fail；不得 skip bad rows 后发布 partial release。
- P2 保存全部 canonical exposures；P3 derived sequence 才应用首版 positive vocabulary；该 recipe 的稳定
  ID 是 `tsv-positive-v1`：

```text
positive_v1 = not hate and (
    watch_time > 3
    or like or comment or follow or collect or forward
)
explicit_negative_v1 = hate
passive_nonpositive_v1 = not positive_v1 and not hate
```

白话理解：`positive_v1` 只是一个带版本号的确定性筛选规则，不是模型或预测分数。它从“所有真实曝光”中
选出首版 SASRec 认为足够像正向兴趣的事件；`v1` 防止以后修改阈值/行为组合后把两套 derived data 混用：

```text
watch_time=10s, no action, hate=false  → positive_v1（有效观看）
watch_time=2s,  like=true, hate=false  → positive_v1（明确正反馈）
watch_time=2s,  only click=true         → passive_nonpositive_v1（click 未被上游定义）
watch_time=2s,  no action, hate=false  → passive_nonpositive_v1（短观看，不等于明确 dislike）
watch_time=20s, hate=true               → explicit_negative_v1（hate 优先）
```

`passive_nonpositive_v1` 不得写成用户明确 dislike；它是否进入辅助 loss/negative sampling 由 P3-02/P3-03
决定。graded relevance、completion ratio、Oracle gain 和 RL reward 不在 P3-01 提前锁死。

### 4.5 Item semantic-field inventory

source adapter 每个 `pid` 只产生一个 `SourceItem`。字段边界如下：

| Field | First baseline use | Policy |
| --- | --- | --- |
| Chinese title；optional English title ref | `title_cn: string`；English text 保持 ref，启用时另建 versioned extractor | `text-v1`：strict UTF-8 → Unicode NFC → outer-whitespace strip；必须非空、单行、无 C0/C1 controls、最多 512 Unicode code points，且同 item 唯一；否则不输出 `title_cn` 并记录 reason code，不猜一条“正确 title” |
| tags | `tags: string_list` | 每个值应用 Unicode NFC + strip；必须非空、单行、无 C0/C1 controls、最多 128 code points；去重后按 UTF-8 bytes canonical sort；任一非法值使该 item 的 tags attribute 缺失并 audit |
| category CN/EN hierarchy | `category_paths_cn/category_paths_en: string_list` | 由 category tuples 和冻结 mapping 构造显式 level path，按 `(level, root_id, parent_id, category_id)` 排序；raw numeric IDs 只留 provenance，不使用相互错位的 parallel raw-ID arrays |
| `author_id`、`author_fans_count` | provenance only | author ID 是 opaque identity、fans 可能随时间变化；首版不作为语义 Atom 或 SASRec side feature |
| `duration` | source/segment provenance only | 不写 P2 item-level feature duration；segment timing 仍以 P2 locator/segment definition 为准 |
| description | unavailable | 当前 source 没有独立 description；不得用 title、tag 或 ASR 冒充 source description |
| ASR、English title、visual `.npy`、MP4 | explicit resource/payload refs | 不把大文本/bytes 内联进 item attributes；缺失 coverage 显式报告 |
| gender、age、phone price、city/community | excluded | 首版不进入 SourceItem、Memory、SASRec、prompt 或 checkpoint features；只允许 non-identifying aggregate source audit |

critical identity、author 或 duration 冲突使 adapter fail；optional text 冲突采用“缺失 + audit”而非发布
partial/corrupt record。Invalid raw text 不复制进 portable item provenance，只保留 local source locator、
checksum 和 reason code。所有 title/tag/ASR 都是 untrusted data；后续进入 MLLM 前必须经过既有 Prompt
Firewall 边界，不能解释其中的指令。

### 4.6 Missing data、media 和 P2 ingestion boundary

- 只要 canonical exposure 的 ID/timestamp/behavior 合法，缺少 optional text 的 item 仍可进入 SASRec；
  Memory 只使用实际存在的 attributes，不生成 `unknown`/空字符串 placeholder。
- 没有 segment/media 的 item 仍生成 P2 合法 empty segment catalog，但不进入需要真实感知的 candidate
  subset；每次实验必须报告 behavior/text/media/segment coverage。已在 manifest 声明的 media/ref 缺失、
  checksum 不符或 segment coverage 不完整则 fail fast。
- P3 Cheap Path 先用全 sampled behavior/semantic metadata。官方 `1..100` media 只跑第一条 Agent Loop smoke；
  P4 按 P3 split/candidate coverage 生成独立、固定、带 checksum 的 media-subset manifest，再扩展 Oracle/
  Segment Value 数据，不要求先下载 3.2 TB 全量视频。
- 唯一数据通路保持：

```text
read-only official snapshot
    → versioned TsinghuaSourceAdapter
    → P2 SourceDatasetManifest + behavior/items/segment-definition refs
    → existing P2 processor/publisher
    → immutable exact release
    → P3 derived dataset / Memory / SASRec
```

真实 snapshot、缓存、derived data、media、embeddings、Oracle、checkpoints 和 runs 都留在 Git 忽略的
local/external roots。仓库只提交 adapter code、schema/config、portable fixture、checksum/count manifest 和
不含用户级数据的 audit summary；不得建立绕过 P2 manifest/release 的第二套 loader 数据面。

### 4.7 License/privacy 决策和外部前置条件

上游公开了下载入口并在论文中邀请研究使用；论文说明参与者知情同意、user IDs 已匿名化，并说明视频来自
公开平台。但截至本次核验，官方 repository 和 server README 没有给出一份明确的数据 LICENSE/usage terms，
论文中的 `ImageNet license` 描述也不足以替代逐项许可条款。

因此首版工程政策固定为：

- 只做本地学术研究和内部实验；不在 Git、artifact release 或论文补充材料中重新分发 row-level behavior、
  user attributes、raw/derived video、ASR、titles、visual features 或其他 content-derived payload；
- 不使用用户人口属性训练模型；日志、trace 和示例不得暴露 source user rows；
- 可以公开 adapter/config/schema、内容 hashes、aggregate counts 和不含源内容的实验方法；
- 在任何数据/媒体/embedding/checkpoint 对外发布前，必须取得/存档作者的明确许可条款并完成隐私/版权复核。

该外部前置条件不阻塞本地 P3 Cheap Path 和 Agent Loop 实现，但阻塞 source/derived-content 的公开分发。

### 4.8 本 Gate 明确 deferred

- chronological split、minimum sequence length、candidate/negative sampling：P3-02；
- SASRec architecture/loss 和 passive-nonpositive 的训练用法：P3-03；
- Atom extraction/decay/threshold：P3-04/P3-05；
- media subset 的正式规模、Teacher、prompt 和 MLLM：P4 discussion；
- graded relevance、Oracle gain 和 supervised Segment Value labels：P5 discussion；
- full 1,019,568-interaction source 的获取：作者提供时作为新 snapshot 评估，不阻塞当前 sampled lane。

### P3-01 Decision Record

```text
Decision ID: P3-01
Status: Confirmed
Decision:
1. 第一实现主线使用 Tsinghua ShortVideo official public sampled release；以三份 source artifacts 的
   exact path/size/SHA-256 manifest 固定 upstream snapshot，并由 P2 对 source bytes + adapter recipe 计算
   data_version；不得称为论文 full release。
2. source adapter 以 (user_id, pid, exposed_time) 聚合 attribute-expanded rows，每次曝光只生成一个
   short_video_exposure；Unix timestamp 是唯一时序事实，distinct-time repeats 保留。
3. P2 保存全部曝光；P3 positive_v1 使用 not hate 且（watch_time > 3 或任一 documented explicit
   positive action）。hate 是 explicit negative；其余短观看是 passive nonpositive；undocumented click
   只保留为 metadata。watch_time 原值保留，即使大于 duration 也不得在 adapter clamp。
4. hashed source IDs 只做 deterministic namespace；user demographics 完全排除首版模型和 artifacts。
5. title/tags/category paths 按 explicit text-v1 normalization 构成首版 semantic attributes；source 没有
   description，不得合成冒充；author/fans/duration 只作 provenance；ASR、visual features 和 media 通过
   refs 管理。Optional semantic 缺失不阻止 SASRec，但 coverage 必须报告。
6. P3 使用 sampled behavior/metadata 跑全量 Cheap Path；官方 1..100 media 只跑 Agent smoke；P4 再冻结
   coverage-driven media subset。全量 3.2 TB media 不是启动前置条件。
7. adapter 输出必须进入既有 P2 source manifest/exact-release pipeline；真实/派生数据不进 Git。
8. 在明确 data license 缺失时只允许本地学术研究、不重新分发 source/content-derived artifacts；取得作者
   明确条款是公开发布前置条件，但不阻塞本地实现和实验。
Rationale:
该决策使用实际可下载、已哈希和已审计的数据，而不是论文统计或 latest 路径；它修复 attribute expansion
造成的伪重复交互，保留多反馈与负反馈用于后续研究，同时以最小媒体子集尽快跑通 Agent Loop。
Alternatives considered:
把 794,053 CSV rows 当 interactions；把公开 sampled 冒充论文 full；只保留 like/comment；把 click 当已定义
positive；丢弃全部 short views；再次随机 hash IDs；把人口属性输入模型；下载全部 3.2 TB 后才实现；绕过 P2
直接训练；在无明确 license 时重新分发数据或媒体。
Affected schemas/interfaces:
New versioned Tsinghua source adapter/config/audit artifacts only. No Phase 1 public interface or Phase 2 canonical
schema/Store/release semantic change.
Affected docs/tests:
todo/phase_3_discussion.md；todo/benchmark_construction_proposal.md；后续 adapter aggregation/schema-drift/
ordering/repeat/conflict/missing/privacy/version/coverage tests。
Resolved follow-up:
first dataset、source snapshot identity、exposure aggregation、interaction vocabulary、item semantic inventory、
ID/privacy、text normalization、missing/deletion policy、media bootstrap、P2 ingestion 和 local-data boundary。
Deferred follow-up:
P3-02 split/candidate/negative；P3-03 loss；P3-04/P3-05 Memory；P4 media/MLLM；P5 Oracle/Segment Value；
author-provided full release 和 explicit redistribution license。
Confirmed by: User
Date: 2026-08-04
```

---

## 5. P3-02 — Versioned Derived Sequence Dataset

Status: `Confirmed`

### 5.1 目标

从 immutable Phase 2 behavior sequences 生成独立、versioned、无泄漏的 SASRec
training/evaluation dataset。该 derived dataset 不回写或改写 Phase 2 release。

### 5.2 已审计的序列事实

按 P3-01 `positive_v1` 聚合后共有 93,616 positive events 和 35,867 passive/negative events；数据只覆盖
6.922 天。positive sequence 长度中位数为 8，P95 为 49，最大为 286。主要方案对比如下：

| Split/eligibility | Users | Train events | Next-event samples | Val/Test cold target |
| --- | ---: | ---: | ---: | ---: |
| per-user leave-two-out, min=3 | 5,221 | 81,413 | 76,192 | 13.12% / 13.37% |
| per-user leave-two-out, min=4 | 4,714 | 80,906 | 76,192 | 13.53% / 13.68% |
| per-user leave-two-out, min=5 | 4,298 | 80,074 | 75,776 | 13.89% / 14.10% |

`min=3` 中有 507 users 只有一个 train event，不能贡献 next-event training sample；`min=4` 虽多保留
416 users，但每个新增 user 只有两个 train positives。`min=5` 保证至少三个 train positives，更适合同时
支持 SASRec 和 Dynamic Memory，且只比 `min=4` 少 416 training samples。

若采用 global temporal 80/10/10，只有 1,633 users 同时具有 train/validation/test，validation/test cold
events 分别达到 2,184/2,445（约 23%/26%）。在仅约七天且用户活跃时间不齐的数据上，它不适合作为首版
主 split；后续可以作为 time-drift robustness experiment。

positive sequence 中只有 62 个 repeated user-item pairs（66 个额外重复事件）；validation/test repeat targets
分别只有 5/2。相同 timestamp 的正反馈组有 7,558 个，但 P3-01/P2 已通过 `interaction_index` 固定唯一顺序。

### 5.3 Split、target 和完整 exposure cutoff

首版固定 `user-chronological-leave-two-out-v1`：

```text
eligibility: positive_v1 count >= 5

positive train sequence = positive events [0 : n-2]
validation target        = positive event  [n-2]
test target              = positive event  [n-1]

validation SASRec history = positive train sequence
test SASRec history       = positive train sequence + observed validation target
```

Test history 包含 validation event 是合法时序事实：它在 test target 之前已经发生。训练、调参和 checkpoint
选择仍不能读 test target/label。

每个 validation/test target 还必须保存它在 P2 **完整曝光序列**中的 source `interaction_index`，并定义：

```text
history_end_interaction_index_exclusive = target.interaction_index
full exposure prefix = all source interactions whose interaction_index < target.interaction_index
```

因此后续 Memory 可以读取 cutoff 前的 positive/passive/negative events，但不能看到 target 或 target 之后的
任何曝光。Split 和 prefix 一律使用 P2 canonical `interaction_index`；不得重新按 item ID/file order 排序。

不足五个 positives 的用户仍完整保留在 P2 release，只是不进入首版 P3 benchmark；runtime 对 empty/short
history 的行为由 P3-06 确认，不能把 benchmark eligibility 误写成公共接口错误。

### 5.4 Full history 与 SASRec view

Derived split artifact 保存完整、未截断的合法 history。第一条 SASRec input projection 单独固定为：

```text
view recipe: sasrec-recent-50-v1
max_history_length: 50
truncation: left truncate; retain the most recent 50 positives
```

P95 positive sequence 约为 49，因此该 view 覆盖绝大多数用户。截断只发生在 SASRec sample projection；
Dynamic Memory 仍消费 target cutoff 前的完整曝光前缀，derived artifact 不物理删除早期事件。

训练 logical samples 由每个 train sequence 的所有合法 next-positive prefixes 构成；每个 sample 保存稳定
`sample_id`、user、target、prefix cutoff 和 source identities。具体 tensor packing/batching 留给 P3-03，不能
改变这些 logical samples。

### 5.5 Vocabulary、special IDs 和 cold semantics

Vocabulary 只从 eligible users 的 **train positive events** 构建，按 canonical item ID UTF-8 bytes 排序：

```text
PAD = 0
train item IDs = 1..N
MASK = not defined for the first SASRec baseline
rankable UNK = not allowed
```

首版 `min=5` 得到 26,625 个 train-vocabulary items。Validation 有 597/4,298 cold targets，test 有
606/4,298 cold targets。Cold target 保留原 canonical item ID 和 `in_train_vocabulary=false`，不得把不同
items 合并成同一个可排名 `UNK`，也不得利用 validation/test 目标提前扩展 train embeddings。

评估同时报告：

1. **all-target retrieval coverage**：全部 4,298 targets 均进入分母；cold target 对 ID-only SASRec 是
   unretrieved/miss，真实反映 candidate-generation ceiling；
2. **warm-target conditional ranking**：只对 target 属于 train vocabulary 的固定 subset 计算 NDCG/HR/MRR，
   衡量 SASRec 在可学习 item 上的排序质量。

两组 counts/subset identities 必须 materialize/checksum，所有方法使用同一 subset；不得只报告 warm metrics
而隐藏约 14% cold coverage，也不得用随机未训练 item embedding 污染指标。

### 5.6 Repeats、candidate 和 evaluation negatives

- repeated positives 按 source event 保留，不做 user-level dedup；
- 正式 primary ranking domain 是完整 26,625-item train vocabulary，不做 target injection、不使用 sampled
  negatives；对应 cutoff 前已经出现的 positive items 被 mask，但若 ground-truth target 本身是 repeat，
  target 必须作为唯一例外保留；
- candidate masking 首版只使用 cutoff 前 positives。Passive/nonpositive 是否抑制候选属于 P3-03/后续
  ablation，不能在 split builder 中形成隐藏 policy；
- cold target 不进入 scorer domain，在 all-target coverage 中自然计 miss；warm target 自动存在于完整
  train vocabulary，不需要注入。

另生成独立、明确标为 development-only 的 sampled candidate artifact：

```text
1 labeled warm positive + 100 unique train-vocabulary negatives
eval_negative_seed = 20260804
```

它只用于 CPU smoke/CI/快速调试，不作为论文主结果。Negative 排除 target 和 cutoff 前 positive history；
不得查看 target 之后的 positives 来“清洗” negatives。候选不足、duplicate、target collision 或 coverage
不完整使 builder fail。该 dev artifact materialize、canonical sort、保存 recipe/seed/checksum。

训练 loss、每个 positive 的 negative 数量和 uniform/popularity/hard sampler 由 P3-03 确认；P3-02 只锁定
训练 sampler 只能使用 train vocabulary/train labels，其 seed/config 必须进入 checkpoint provenance，不能用
validation/test positives 清洗训练 negatives。

### 5.7 必须防止的泄漏

- vocabulary、item frequency、normalization/fitted statistics 和训练 sampler 只能从 train partition 构建；
- validation history 只能到 validation target exclusive；test history 只能到 test target exclusive；
- Memory prefix 使用完整 exposure cutoff，不能只在 positive sequence 截断后误纳入未来 passive events；
- validation/test target 不得用于训练 negative exclusion、hard-negative mining 或 train candidate selection；
- test target/metric 不得参与 hyperparameter、early stopping 或 checkpoint selection；
- derived builder 不得因 source file ordering 替代 P2 `interaction_index`；
- version/coverage/collision failure 不得 fallback 到随机 split、全量 vocabulary、sampled candidates 或 partial
  dataset。

### 5.8 Artifact 边界

```text
Phase 2 exact release
        ↓
P3 DerivedDatasetBuilder
        ↓
derived dataset manifest
  ├── source data_version
  ├── positive recipe: tsv-positive-v1
  ├── split recipe: user-chronological-leave-two-out-v1
  ├── eligibility: min-positive-5
  ├── full-exposure target/cutoff refs
  ├── full train/validation/test positive-sequence refs
  ├── train-only vocabulary ref
  ├── SASRec view: sasrec-recent-50-v1
  ├── full warm candidate policy
  ├── warm/cold evaluation subset refs
  ├── optional development sampled-candidate ref
  └── schema/codec/builder versions, seeds, counts and checksums
```

首版 codec 使用 canonical UTF-8/LF JSON manifest 和 canonical JSONL records，不压缩；真实 derived bytes
继续留在 Git 忽略的 local/external root。Artifact 是独立 immutable release，不回写 P2 source/processed
bundle。任何影响 logical output 的 recipe/version/seed 都进入 identity；absolute paths、device、execution
timestamp、worker count 和 invocation ID 不进入 portable identity。

### 5.9 本 Gate deferred

- SASRec architecture/loss/training negative strategy/optimizer：P3-03；
- positive/passive/negative events 如何进入 Preference Atoms：P3-04/P3-05；
- runtime empty/short history 与 prefix fingerprint：P3-06；
- global temporal robustness、cold-item semantic model 和 sampled/full evaluation expansion：P6 evaluation；
- Oracle/Segment Value 的 future-observed candidate protocol：P5 及 benchmark proposal Track C。

### 5.10 交付结果

- strict derived-dataset schemas；
- deterministic builder Python API 和薄 CLI；
- split/vocabulary/candidate/negative semantics；
- leakage tests、identity tests 和 small golden fixture。

### P3-02 Decision Record

```text
Decision ID: P3-02
Status: Confirmed
Decision:
1. 从 P3-01 positive_v1 events 构建 user-chronological-leave-two-out-v1；只纳入至少五个 positives
   的用户。最后一个 positive 是 test，倒数第二个是 validation，其余为 train。
2. Validation SASRec history 是 train positives；test history 是 train positives + observed validation。
   每个 target 另保存 P2 full-exposure interaction_index-exclusive cutoff，供无未来泄漏的 Memory prefix 使用。
3. Derived artifact 保存完整 history；首版 SASRec view 是 left-truncated recent 50 positives；Memory 不随之
   截断。Repeated events 保留，顺序只读 P2 interaction_index。
4. Vocabulary 只从 eligible train positives 构建；PAD=0，无 MASK 和 rankable UNK。Cold target 保留 identity
   但不扩展 train vocabulary。
5. 同时报 all-target retrieval coverage（cold 为 miss）和 fixed warm-target conditional ranking，subset
   identities/counts materialize；不能隐藏 cold coverage 或给 cold item 随机 embedding。
6. Primary evaluation 排完整 train vocabulary，不注入 target、不 sampled；mask prefix positives，但 repeated
   target 作为例外保留。Passive candidate suppression 不在 split builder 暗中启用。
7. Development-only artifact 使用 1 warm positive + 100 unique warm negatives，seed=20260804；只排除 target
   和 cutoff 前 positive history，不查看未来 positives；不得作为论文主结果。
8. Training negative loss/count/distribution deferred to P3-03，但只能消费 train vocabulary/labels，禁止使用
   validation/test positives，全部 sampler config/seed 进入 checkpoint provenance。
9. Derived manifest/version 固定 source data_version、positive/split/eligibility/view/vocabulary/candidate recipes、
   full-exposure cutoffs、warm/cold subsets、seeds、counts、checksums 和 builder/schema/codec versions；artifact
   immutable 且不回写 P2。
Rationale:
该数据只有约七天；global temporal split 会把完整三段用户压到 1,633 并显著增加 cold events。Per-user
leave-two-out + min=5 保留 4,298 users、80,074 train events 和 75,776 training samples，同时给每个用户
至少三个 train positives。Recent-50 覆盖约 P95，但完整 artifact/Memory prefix 不丢长期行为。双报告将
ID-only scorer 的约 14% cold ceiling 与 warm ranking quality 分开，避免隐藏检索失败或污染排名指标。
Alternatives considered:
random 8:1:1；global temporal primary split；min=3/4；leave-one-out；物理截断 derived histories；去重 repeated
items；用全量数据建 vocabulary；把 cold items 合并为 UNK 或随机扩 embedding；只报 warm metrics；以 sampled
negatives 作为主结果；target injection；用完整未来序列排除 negatives；让 SASRec 截断同时截断 Memory。
Affected schemas/interfaces:
New P3 derived manifest/sequence/target-cutoff/vocabulary/evaluation-subset/development-candidate schemas and builder/
loader interfaces. No Phase 1 public interface or Phase 2 release/schema/Store semantic change.
Affected docs/tests:
todo/phase_3_discussion.md；后续 deterministic split/order/cutoff/repeat/truncation/vocabulary/OOV/cold-subset/
candidate/negative/leakage/version/checksum/identity/golden tests；全部 P1/P2 regressions。
Resolved follow-up:
split、eligibility、targets、full-exposure cutoffs、complete-vs-recent history、repeats、vocabulary/special IDs、
cold semantics、primary/dev candidates、evaluation negative seed 和 immutable derived artifact boundary。
Deferred follow-up:
P3-03 model/loss/training sampler；P3-04/P3-05 Memory semantics；P3-06 runtime short-history/fingerprint；P5
Oracle/Segment Value；P6 global-time/cold-item/evaluation robustness。
Confirmed by: User
Date: 2026-08-04
```

---

## 6. P3-03 — Pluggable Initial Ranker and SASRec Training Baseline

Status: `Confirmed`

### 6.1 目标

确认可插拔 Initial Ranker 的共同边界和第一条标准 SASRec baseline，使 SASRec 可单独训练、
验证、保存和替换，同时不把 User Memory、多模态昂贵路径或 Agent lifecycle 融入模型。详细的
后续 backbone 实验计划见
[`initial_ranker_experiment_plan.md`](initial_ranker_experiment_plan.md)。

### 6.2 Plugin architecture

- Phase 1 已确认的 `InitialRanker.score(user_id, sequence, candidate_ids)` 是公共推理接口，
  `AgentController` 不依赖具体模型；
- P3-02 derived dataset、split/vocabulary/candidate identity 和 evaluator 跨 ranker 共享；
- training view、network、loss、sampler、model-only special IDs、trainer state 和 weights 属于具体
  ranker；
- 使用显式、版本化 registry 和 strict discriminated config，不接受 arbitrary import string、文件名
  猜测类型或 incompatible checkpoint fallback；
- 不建立包含所有未来模型字段的巨大通用 Trainer Protocol；共享数据/评测/checkpoint provenance
  边界，具体 trainer 可以 model-specific；
- Phase 3 当前只实现 SASRec。BERT4Rec 是 Agent Loop 完成后的第二个插件，GRU4Rec/更强模型是后期
  robustness，不阻塞第一条真实闭环。

### 6.3 SASRec 必须按数据集训练

SASRec 的 item embeddings 绑定 train-only item vocabulary，不存在可直接用于任意 ID space 的通用
pretrained checkpoint。Tsinghua、MicroLens-100K 和其他数据集共享代码/config/算法/评测协议，但
分别训练 dataset-specific checkpoint；MicroLens-50K development checkpoint 也不能冒充 100K 正式
checkpoint。

只有 source release、positive/split/view/vocabulary recipe、ID mapping、model config 和 checkpoint
provenance 全部兼容时才允许加载或 resume。禁止跨数据集复用 ID embeddings、resize 后强行加载或
把 upstream checkpoint 当成本项目结果。

### 6.4 第一条 `sasrec-pytorch-v1` recipe

| Field | Confirmed value |
| --- | --- |
| framework | optional training extra `torch>=2.8,<3`；run manifest 记录精确 Torch/CUDA version；core install/普通 CI 不强制安装 Torch |
| input | P3-02 item-ID prefix only；不读取 Memory、metadata、MLLM Evidence 或 Segment Proxy |
| max length | 50，recent left truncation；不物理截断完整 derived history/Memory history |
| model | learned tied item embedding + learned position embedding；hidden=64；blocks=2；heads=2；FFN=256 |
| block details | GELU；pre-LN + final LN；dropout=0.2；Normal(0, 0.02) init；PAD=0 row 固定为零 |
| loss | sampled positive/negative binary loss；每个 P3-02 sample 的最后预测位置计算一次 |
| negative | 每个 positive 一个 uniform train-vocabulary negative；排除该用户全部 train positives |
| optimizer | Adam；lr=1e-3；betas=(0.9, 0.98)；eps=1e-8；weight_decay=0；无 scheduler |
| batch/epochs | batch=128；最多 200 epochs；每 epoch validation |
| stability | global-norm clip=5.0；第一版 FP32/AMP off |
| selection | P3-02 primary full-catalog warm-target validation NDCG@10；patience=10；metric tie 取更早 epoch |
| checkpoints | `best` 用于 evaluation/inference；`last` 只用于显式 resume |

Sampler 只能读取 train vocabulary/train labels，不得用 validation/test positives 清洗 negatives，也不把
passive/nonpositive events 暗中转成 negatives。首版确定性键为
`(training_seed, epoch, sample_id, negative_index)`，使 sampler 不依赖 DataLoader worker 完成顺序；
config/seed 必须进入 provenance。

后期允许显式增加 `sampled-BCE vs full-softmax-CE` loss sensitivity，但不阻塞 Phase 3，也不能在不改变
recipe identity 的情况下替换第一条 baseline。

### 6.5 Training runtime and determinism

- first real run 显式使用租赁 NVIDIA GPU 的 `cuda` device；不使用 `auto`，unavailable device fail；
- CPU small-fixture train/reload/inference 必须通过，普通 CI 不训练真实数据或下载 assets；
- 首个 Agent Loop 使用一个固定 training seed；最终 multi-seed 数量和 equal tuning budget 留给 evaluation
  Gate，不把单 seed smoke 当论文结果；
- fixed seed、epoch permutation 和 negative sampler 可复现；不同 device/backend 不承诺 byte-identical
  weights；
- existing output 不覆盖；resume 必须显式指定并从完成的 `last` epoch 恢复 model/optimizer/early-stop/RNG
  state。Checkpoint manifest、atomicity 和 corruption 的精确规则由 P3-04 锁定。

### 6.6 Backbone experiment and Segment Value boundary

- Ranker-only 后期比较 MostPop、GRU4Rec、SASRec、BERT4Rec；同数据集共享 split/candidates/metrics 和
  调参预算，但分别训练；
- Full PAVE backbone robustness 先只比较 SASRec 与 BERT4Rec 各自的 Cheap Path/Full PAVE 配对；
- 完整 `Dynamic Memory/Random/Relevance-only/Full Perception/PAVE/Oracle` 消融默认只在 SASRec 上跑，
  不构造全部 ranker × 全部消融的笛卡尔积；
- 不同 ranker raw logits 不可直接解释为相同 confidence。P3-04 锁定 score/calibration，P5 的 Segment
  Value 优先消费 rank、percentile、request-local normalized score/margin 和 ranker identity；
- 最佳性能实验按 `dataset × ranker` 独立训练 Segment Value checkpoint；冻结 SASRec Segment Value 后
  零样本换 BERT4Rec 只作为可选 portability stress test。

### 6.7 CPU/GPU 验收边界

- 小 fixture training/inference 必须可在 CPU 执行；
- 真实训练使用显式 GPU config；
- CI 不要求训练真实数据或下载 pretrained assets；
- 固定 checkpoint 的 CPU inference contract 必须可测试；
- 不预先承诺不同 device/backend 训练产生 byte-identical weights。

### 6.8 交付结果

- strict typed plugin/model/train configs 和显式 registry boundary；
- reusable SASRec model/trainer Python APIs；
- thin train/evaluate CLI；
- metrics/history 和 best/last handoff；
- deterministic sampler 与 small-fixture tests；
- 后续 BERT4Rec plugin 不修改 Controller/public `InitialRanker` signature 的 extension seam。

### P3-03 Decision Record

```text
Decision ID: P3-03
Status: Confirmed
Decision:
1. Initial ranking 是可插拔平台；公共 InitialRanker/derived/evaluator 边界与 model-specific training
   view/trainer/checkpoint 分离，不构造包含所有模型字段的统一 Trainer。
2. Phase 3 只实现 sasrec-pytorch-v1；完整 Agent Loop 后增加 BERT4Rec，GRU4Rec/更强模型后置。
3. SASRec 必须按 dataset/split/vocabulary 独立训练；Tsinghua、MicroLens-50K development 和
   MicroLens-100K checkpoint 不共享 ID embeddings/weights。
4. sasrec-pytorch-v1 使用 maxlen=50、hidden=64、2 blocks、2 heads、FFN=256、GELU、pre/final LN、
   dropout=0.2、Normal(0,0.02) 和 tied item embeddings。
5. 首版使用 sampled binary loss，每 positive 一个 uniform train-vocabulary negative；只排除 user train
   positives，禁止读取 validation/test labels 或把 passive events 暗中用作 negatives。
6. 使用 Adam(lr=1e-3, betas=(0.9,0.98), weight_decay=0)、batch=128、max 200 epochs、FP32、
   grad clip=5；按 full-catalog warm validation NDCG@10、patience=10 选最早并列 best。
7. Torch 是 optional training dependency；真实训练显式 cuda，普通 CI 保持 torch-free，CPU fixture/reload/
   inference 必须通过；exact environment、seeds 和 sampler recipe 进入 provenance。
8. 完整 method ablation 默认只跑 SASRec；backbone robustness 先跑 SASRec/BERT4Rec 的 Cheap/Full 配对。
   Segment Value 最佳性能按 dataset/ranker 独立训练，冻结跨 ranker 迁移另作可选压力测试。
Rationale:
现有 InitialRanker 依赖注入已提供正确 inference seam。现在只实现 SASRec 能最快打通真实 Agent Loop，
同时显式 registry、共同数据/评测契约和 model-specific trainer 足以支持后续 BERT4Rec。Dataset-specific
训练是 ID embedding 模型的必要条件；使用 rank/normalized signals 可避免后续 Segment Value 被某个
ranker 的 raw-logit 尺度绑死。
Alternatives considered:
把系统写死 SASRec；现在同时实现多模型；直接依赖 RecBole runtime；建立巨大通用 Trainer；跨数据集
复用 checkpoint；使用 upstream weights；首版 full-softmax CE；把 passive events 当 negatives；所有
ranker × 所有消融全量组合；对所有 ranker 共用一个未经适配的 Segment Value checkpoint。
Affected schemas/interfaces:
Existing public InitialRanker signature remains unchanged. New P3 strict model/train configs, explicit registry seam,
training-view/trainer/checkpoint artifacts; P3-04 defines exact adapter/score/checkpoint semantics.
Affected docs/tests:
todo/phase_3_discussion.md；todo/initial_ranker_experiment_plan.md；
todo/benchmark_construction_proposal.md；docs/02_sasrec_initial_ranking.md；后续 model/mask/loss/sampler/
determinism/train/resume/plugin/evaluator fixtures and all P1/P2 regressions.
Resolved follow-up:
plugin boundary、first model、dataset-specific training、SASRec architecture/loss/negative/optimizer/runtime、
backbone experiment scope 和 Segment Value cross-ranker boundary。
Deferred follow-up:
P3-04 exact checkpoint/score/calibration/OOV semantics；P3-07 runtime bootstrap；BERT4Rec/GRU4Rec implementation；
evaluation Gate 的 tuning budget/multi-seed count；P5 final Segment Value features/training。
Confirmed by: User
Date: 2026-08-04
```

---

## 7. P3-04 — Checkpoint, Candidate Scoring, and Score Semantics

Status: `Confirmed`

### 7.1 目标

确认训练结果如何成为可验证的 `InitialRanker` implementation，以及 SASRec score 如何
安全进入 Phase 1 ranking/uncertainty contract，同时诚实暴露 ID-only 模型的 cold-item 边界。

### 7.2 Checkpoint bundle and identity

第一版 checkpoint 是 immutable、checksummed bundle，不是一个可任意覆盖的 `.pt` 文件：

```text
checkpoint bundle
  checkpoint_manifest.json
  model_state.pt
  optimizer_state.pt   # last/resume only
  trainer_state.pt     # last/resume only: epoch/RNG/sampler/early-stop
```

Manifest 至少固定：schema/status/checkpoint kind；ranker descriptor；model/training recipe 和完整 strict
config；source release、P3 derived manifest、split/view/vocabulary refs；vocabulary count/checksum/special IDs；
training seed、epoch/global step；validation protocol/metrics/selection rule；各 payload 的 format/checksum/size；
Python/Torch/CUDA/Git/device 等 execution provenance。Portable refs 不保存 absolute path，机器 path、运行
timestamp 和 device 不作为 semantic recipe identity。

只保存 tensor/state dictionaries，不 pickle 完整 Python model 或动态类。第一版 inference weights format 是
`pytorch-state-dict-v1`、stored dtype 是 FP32。Identity 先包含 weights/required state 的精确 checksums，再用
canonical JSON 计算：

```text
checkpoint_id = "p3ckpt-" + sha256(canonical CheckpointIdentity).hexdigest()
```

完整 64-hex ID 用于 directory/ref identity；短前缀只可 UI 显示。`ComponentDescriptor.version` 仍表示
adapter 实现语义版本，不与 checkpoint ID 混用。

### 7.3 Best/last, publication, and loading

| Kind | Purpose | Required state |
| --- | --- | --- |
| `best` | validation 选出的 evaluation/Agent inference checkpoint | model weights + manifest/metrics |
| `last` | 从最后完整 epoch 显式 resume | model + optimizer + trainer/RNG/sampler/early-stop state |

`best` 只由 P3-03 warm validation NDCG@10 选择，metric tie 取更早 epoch；test 不参与。Reported test 和
Agent runtime 固定 exact best manifest `ResourceRef`，不使用 `last`、`latest` alias、mtime 或 directory scan。

写入在 checkpoint root 内 isolated staging 完成，写完 payload/manifest、计算并验证全部 checksums 后原子
publish immutable bundle。已有 exact ID 全部一致可返回 reused；任何 schema/identity/checksum mismatch
使用 `ArtifactIntegrityError`，不覆盖。Partial staging 不可发现、不自动删除、不自动 fallback。

Loader 在构造 Agent components 时验证 exact manifest ref、closed inventory、data/vocabulary/model config、
embedding shape 和 checksums；使用 CPU `map_location` 和 `weights_only=True` 加载 state dict，验证后再移动
到显式 device，`eval()` + inference mode。Missing/corrupt/incompatible checkpoint 在 Agent 启动前失败；
不降级 Mock、随机 ranker、旧 checkpoint 或另一个 device/dtype。运行中的数值/设备 failure 才属于
`initial_ranker` component failure。

### 7.4 Candidate scoring semantics

- 保持 public `InitialRanker.score(user_id, sequence, candidate_ids)` 不变；caller 明确提供 candidate pool，
  candidate generation/provider 留在 Controller 之外；
- `candidate_ids` 非空、唯一且全部属于 exact train vocabulary；scorer 精确返回全部 IDs，不增加、删除、
  自动过滤或只返回 top-K；
- history item 可以作为 candidate。Seen-item filtering 属于 evaluator/Candidate Provider；P3-02 primary
  evaluation 继续过滤 cutoff 前 positives，但 repeated target 例外；
- candidate OOV/PAD/special ID 是 contract failure。Cold target 在进入 scorer 前由 evaluation subset 识别，
  在 all-target retrieval coverage 中计 miss，不注入 target、不分配随机 embedding、不映射 UNK；
- history OOV 先记录并丢弃，再从剩余 known events 取 recent 50，repeated known events 保留。Metadata 记录
  input/OOV-dropped/used counts；过滤后无 known history 显式失败，P3-06 决定 cold-user fallback；
- sequence feature 每个 request 只计算一次，candidate embeddings 可按 operational batch/chunk size 打分；
  chunk size 不改变 semantic identity 或输出 coverage；
- 输出按 `(-score, item_id)` 排序，rank 从 1 连续；不先 round score 制造 tie。所有 score 必须 finite。

### 7.5 Score representation and metadata

第一版 public `score` 使用未经校准的 raw dot-product logit：

```text
score(user, item) = sequence_representation · item_embedding
```

不应用 sigmoid、candidate-set softmax、min-max 或把 raw logit 命名为 confidence。Softmax 会使同一 item 的
数值随 candidate pool 改变；单调 sigmoid 虽不改 rank，却会任意改变 margin/Updater scale。

`InitialRankingOutput.metadata` 第一版固定发布 ranker type/version、checkpoint ID、
`score_representation=raw_dot_product_logit`、`score_calibrated=false` 和 history counts；不放 tensor、absolute
path 或 mutable runtime object。`user_sequence_feature_ref=null`，不为每次请求持久化 hidden state。若 P5
确需 sequence embedding，另建版本化 feature artifact/Store contract。

### 7.6 StopPolicy compatibility

P3 real-cheap config 固定：

```yaml
stop:
  ranking_margin_threshold: null
```

`RecommendationState` 仍保存 raw top1-top2 margin 供 trace/诊断，但 `ThresholdStopPolicy` 不据此产生
`ranking_sufficiently_certain`。Mock 的 `0.10` threshold 只属于 mock-v1。只有后续使用 validation labels
完成明确 calibration，并根据 ranking gain/perception cost 验证 threshold 后，真实 ranker 才可启用
certainty stop；SASRec/BERT4Rec raw margin 不跨模型直接比较。

### 7.7 Cold-start evaluation boundary

第一版不是完全忽略 cold start，而是测量缺口、不声称已经解决：validation cold targets 为
`597/4,298 (13.89%)`，test cold targets 为 `606/4,298 (14.10%)`。Primary report 同时给 all-target
retrieval coverage（cold 为无法服务/miss）和 warm-target conditional ranking；纯 ID SASRec 不对 cold
target 生成伪 score。

真正的 cold-item recovery 留作 Phase 6 后期实验：以 prediction cutoff 前可获得的 title/category/video
内容为 cold item 建 representation/candidate retrieval，对比 ID-only SASRec、content-only 和 hybrid/PAVE，
报告 cold-only Recall/NDCG、overall coverage、warm quality trade-off 和额外成本。若数据没有可靠 item
availability/first-seen 时间，只能称为 held-out-item generalization，不能冒充 temporal cold-start。

### 7.8 交付结果和测试

- checkpoint manifest/bundle/loader/publisher contract；
- `SASRecInitialRanker` adapter；
- exact coverage、history/candidate OOV、score/rank/tie/metadata semantics；
- save/reload score tolerance 和 exact fixture ranking equivalence；candidate chunk invariance；
- missing/extra/duplicate/OOV、checksum/config/vocabulary/shape/corruption failures；
- StopPolicy compatibility record。

### P3-04 Decision Record

```text
Decision ID: P3-04
Status: Confirmed
Decision:
1. Checkpoint 是 immutable checksummed bundle；manifest 固定 model/training/data/split/view/vocabulary/
   validation/artifact/environment provenance，checkpoint ID 使用含 payload checksums 的 canonical identity
   完整 SHA-256。
2. 只保存 state dictionaries，不 pickle 完整 model。Loader 先 CPU weights-only load/validate，再移到显式
   device；任何 missing/corrupt/incompatible dependency 在 Agent construction 前 fail，无 fallback。
3. best 只由 warm validation NDCG@10 选择并用于 test/Agent；last 保存完整 resume state 且只能显式 resume。
   不支持 latest scan、silent overwrite 或 partial discovery。
4. Caller 继续显式提供 candidates；scorer 精确覆盖全部 IDs，不内建 Candidate Provider、seen filtering 或
   top-K truncation。Tie-break 固定 (-score,item_id)。
5. Candidate OOV/PAD/special ID fail。Cold targets 不进入 warm scorer，在 all-target coverage 计 miss；history
   OOV drop-and-record 后再 recent-50，全部 OOV 时 fail，cold-user fallback deferred P3-06。
6. Public score 是 finite raw dot-product logit，不 sigmoid/softmax/min-max；metadata 标记 uncalibrated 和 exact
   checkpoint/history counts；首版不发布 sequence feature ref。
7. Real-cheap ranking_margin_threshold=null；raw margin 只诊断。真实 certainty stop 必须等 validation-based
   calibration/gain-cost 研究，不能复用 Mock 0.10 或跨 ranker raw margin。
8. 当前报告 cold coverage/miss 与 warm conditional ranking；Phase 6 可增加 content-only/hybrid/PAVE
   cold-item recovery。无可靠上线时间时只称 held-out-item generalization。
Rationale:
沿用现有 caller-candidate 和 exact-coverage contract 可保持 Controller/Stores 不变；immutable exact checkpoint
防止数据、词表和权重漂移；raw dot product 保留 candidate-set-independent ranking semantics，而关闭未校准
certainty 防止把模型尺度误当概率。显式报告 cold coverage 比随机/UNK embedding 更诚实，也为后续内容模型
留下独立可验证的 cold-start track。
Alternatives considered:
单文件可覆盖 checkpoint；pickle 完整 model；自动 latest/best fallback；last 直接报 test；ranker 内生成或截断
candidates；自动过滤 seen items；candidate OOV 随机/UNK/零分；history OOV 随机 embedding；sigmoid/softmax
public score；持久化每请求 hidden state；直接沿用 Mock margin threshold；完全隐藏 cold targets。
Affected schemas/interfaces:
Existing AgentRunRequest, InitialRanker, InitialRankingOutput, RecommendationState and StopPolicy public shapes remain
unchanged. New internal checkpoint manifest/identity/bundle, loader/publisher, strict adapter config and metadata key
contracts. P3-07 supplies exact refs/root bindings.
Affected docs/tests:
todo/phase_3_discussion.md；todo/initial_ranker_experiment_plan.md；
todo/benchmark_construction_proposal.md；docs/02_sasrec_initial_ranking.md；后续 checkpoint/loader/publication/
coverage/OOV/scoring/chunk/reload/StopPolicy fixtures and all P1/P2 regressions.
Resolved follow-up:
checkpoint contents/identity/best-last/publish/load、candidate ownership/coverage/seen/OOV、score/metadata/feature-ref、
certainty threshold 和 current-vs-later cold-start boundary。
Deferred follow-up:
P3-06 empty/all-OOV user fallback；P3-07 root/config/bootstrap；P5 sequence/normalized ranker features；P6
calibration/threshold/cold-item recovery；candidate-provider implementation。
Confirmed by: User
Date: 2026-08-04
```

---

## 8. P3-05 — Preference Atom and Embedding Baseline

Status: `Confirmed`

### 8.1 目标

确认第一条可解释的 Preference Atom 语义来源和 embedding contract。该 Gate 只定义 item semantic
prototype、positive observation 和离线 embedding artifact，不决定 long/short window、strength、persistence
或 stable/emerging/fading 状态转移；后者全部由 P3-06 确认。

### 8.2 SASRec embedding 与 Atom embedding 的边界

Phase 3 存在两套用途不同、不得混用的 embedding：

```text
item ID sequence
    → dataset-specific trainable SASRec item embeddings
    → sequential hidden state
    → initial ranking scores

title + tags + category paths
    → frozen multilingual text encoder
    → item semantic embedding
    → Dynamic Memory long × short semantic matching
```

SASRec embedding 从 P3-02 train-only vocabulary 和行为顺序中训练，绑定数据集和 checkpoint；它不自动
理解 title/tag/category。P3-05 embedding 从 canonical item text 离线生成，不替代 SASRec item embedding，
也不在第一条 baseline 中作为 SASRec side feature。两条支路只在 Recommendation State 和后续 Agent/
Segment Value 消费边界汇合。未来若 Segment Value 使用依赖本 embedding 的特征，embedding recipe/version
变化必须生成新 artifact，并重新训练相应的 downstream model。

### 8.3 ItemSemanticPrototype 与 PreferenceAtom

第一条 baseline 使用 **one item → one semantic prototype**，不把每个 tag/category 拆成独立 Atom，
也不做跨 item 聚类：

```text
P2 SourceItem
    → ItemSemanticPrototype（item 级、用户无关、可复用）
    → positive_v1 interaction observation（用户/时间相关）
    → P3-06 long/short PreferenceAtom（状态/强度/持久性相关）
```

`ItemSemanticPrototype` 不是已经完成状态更新的用户 Atom。它至少保存：

```text
schema_version
prototype_id
item_id
semantic_text
semantic_text_sha256
included_fields
embedding_ref
provenance
```

P3-06 才根据 user、history prefix、memory side 和事件时间创建真正的 internal/public Memory Atom；
`PreferenceAtomView.atom_id` 必须继续满足 long/short 两侧全局唯一。同一个 prototype 可以被多个用户、
多次 observation 和 long/short 两侧复用；复用 embedding 不等于复用 public atom ID。

首版 item-level 粒度使语义来源、事件归属和 replay 均可追踪。tag/category-level Atom、跨 item
semantic clustering、learned atom extraction 和 atom merge/split 是后续显式 ablation，不进入当前 Agent
Loop 前置路径。

### 8.4 Canonical semantic text

Tsinghua 首版 recipe ID 固定为 `tsv-item-semantic-text-v1`，只消费 P3-01 已验证的 `title_cn`、`tags`
和 `category_paths_cn`。字段顺序固定为 title、tags、categories；只输出实际存在的字段，使用 Unicode NFC、
LF 分行且无尾随 LF。tag 和 category path 继承 P3-01 的 dedup/canonical ordering，多个值用 `；`，
category path 内层级用 ` > `：

```text
标题：为什么嫖娼是违法的
标签：主播说新闻；正能量；违法
分类：新闻 > 社会
```

该内容称为 `semantic_text`，不是 source description；当前 source 没有 description，禁止用 title、tag、
ASR 或生成文本冒充。`category_paths_en`、English title ref、ASR、author、fans、duration 和 demographics
不进入该首版文本。其他数据集使用自己的 versioned semantic-text adapter，但可以共享同一 embedding
provider contract。

所有 source text 仍视为 untrusted data。P3 文本编码不执行其中的指令；未来若把任何文本送入 MLLM，
仍须经过既有 Prompt Firewall。

### 8.5 Interaction input semantics

- semantic artifact 对 P2 exact release 中所有具备有效语义字段的 items 构建 prototype；当前 Tsinghua
  31,496 个 items 全部至少有 tags/category，因此预计 semantic coverage 为 31,496/31,496；
- 只有 P3-01 `tsv-positive-v1` event 产生用户 preference observation；`explicit_negative_v1` 和
  `passive_nonpositive_v1` 首版都不生成正向 Atom；
- repeated positive events 继续作为多个 observation 保留，但引用同一个 item prototype/embedding；重复次数、
  recency 和 timestamp 如何影响 strength/persistence 由 P3-06 决定；
- Memory builder 只能读取当前 request/history cutoff 以前的 observations。提前构建全 item 静态文本
  embedding 不授权读取 future behavior，也不扩展 SASRec train vocabulary；
- negative inhibition、passive weighting 和 multi-feedback strength 属于后续 Memory ablation，不能静默混入 v1。

### 8.6 `bge-m3-dense-v1` embedding contract

第一条真实 provider 固定为：

| Field | Confirmed value |
| --- | --- |
| model | `BAAI/bge-m3` |
| model revision | `5617a9f61b028005a4858fdac845db406aefb181` |
| inference package | `FlagEmbedding==1.4.0`，放在 optional embedding extra，普通 core/CI 不强制安装 |
| model mode | frozen/eval；dense output only，不启用 sparse 或 ColBERT output |
| instruction | none；semantic texts 使用同一 symmetric encoding path |
| pooling | BGE-M3 official dense CLS pooling，由 pinned provider 实现 |
| max input | 1,024 tokens；tokenize-first，确定性 right truncation，记录原 token count 和 `was_truncated` |
| output | dimension 1,024；finite、non-zero FP32 vector |
| normalization | explicit L2 normalization；norm 必须通过 tolerance validation |
| similarity | cosine；归一化后允许以 inner product 实现 |

模型 snapshot 必须以 exact 40-hex revision 下载并记录实际文件 inventory、sizes 和 SHA-256；config/manifest
不得接受 `main`、`latest` 或只写 model name。真实 builder 默认使用本地 snapshot 和 `local_files_only`，
缺文件、revision/checksum 不一致或输出 shape/norm 非法时 fail closed。

`BAAI/bge-m3` 和 FlagEmbedding code 是 MIT licensed，但这不改变 P3-01 对 source/content-derived payload
的限制：Tsinghua semantic text、embeddings 和依赖它们的 checkpoints 在取得明确数据许可前只允许本地
学术研究，不得进入 Git 或公开 artifact release。

### 8.7 Execution boundary

- model fetch 是独立、显式的离线准备操作；online Agent、Memory loader 和普通 tests 均禁止联网或下载；
- 真实全量 artifact 推荐在租用 CUDA GPU 上以 FP32、no-grad/eval 构建；初始 operational default 为
  GPU batch 32、CPU batch 8，允许按显存修改 batch/worker/device；
- device、batch size、worker count、absolute cache path 和 execution timestamp 不进入 semantic recipe identity；
  已发布 artifact 的 exact payload checksum 才是 downstream 消费事实，禁止不同输出覆盖已有 release；
- CPU CI 使用小型 `FixtureEmbeddingProvider` 和已知 canonical text/vector 验证 schema、batch ordering、
  normalization、refs 和 loader；fixture provider 不得注册进真实研究 config，也不得从 item ID 伪造语义。

### 8.8 Missing、multilingual 和 duplicate semantics

- optional title 缺失时只使用实际 tags/category；不写空字段、`unknown` 或生成式 placeholder；
- 若未来 item 的 title/tags/category 全部缺失或 canonical text 为空，则不生成 prototype/embedding，记录
  `missing_semantics`；该 item 仍可进入 ID-only SASRec，但不能伪装成可用的 semantic Memory observation；
- 非中文或混合语言的合法 Unicode 文本原样交给 multilingual BGE-M3，不自动翻译、不猜 language；
- 不同 item 即使 canonical text 完全相同也保持不同 `prototype_id` 和 item identity。Builder 可以按
  `semantic_text_sha256` 去重 embedding 计算/存储，但 resolver 必须能把每个 item 解析回相同的 verified vector；
- 同 item 的 text/provenance 冲突继承 P3-01 的缺失/fail policy，不在 P3-05 重新投票或挑一行。

### 8.9 Artifact ownership、identity 和 layout

Embedding 归属于独立的 immutable **P3 item-semantic derived artifact**：它不回写 Phase 2 release，
也不是 per-user Memory-owned duplicate。推荐逻辑布局为：

```text
item-semantic artifact
  ├── manifest.json
  ├── semantic_items.jsonl
  ├── embedding_index.jsonl
  └── embeddings-00000.safetensors ...
```

records 按 canonical `item_id` 排序；shard/index ordering 固定。`ResourceRef` 以 store + prototype/text key +
artifact version + checksum 定位外部向量，Tensor 不进入 `PreferenceAtomView`、`UserMemoryView`、trace 或
portable JSON schema。`prototype_id` 至少 hash dataset namespace、canonical item ID、semantic-text recipe ID
和 semantic-text hash；artifact identity/manifest 还必须覆盖 exact P2 release ref、builder/schema/codec、
model snapshot revision/checksums、provider version、tokenization/pooling/normalization/dimension/dtype、record
inventory 和 payload checksums。

真实文本、vectors 和 user observations 留在 Git 忽略的 local/external artifact root。仓库只提交 code、
schema/config、无 source content 的 aggregate audit 和 portable synthetic fixture。

### 8.10 Semantic profile

第一版固定 `UserMemoryView.semantic_profile=None`。首版 Atom 自身已提供可解释文本；现在增加 LLM summary
会引入 hallucination、prompt/version/cost 和 refresh policy，却不是打通 Dynamic Memory 所必需。可选 deterministic
或 LLM semantic profile 在真实 Memory/Information Need baseline 稳定后另开 Gate，不得阻塞 P3。

### 8.11 交付结果和 tests

- strict `ItemSemanticPrototype`、semantic artifact manifest/index schemas；
- `SemanticTextBuilder`、`EmbeddingProvider`、artifact publisher/loader/resolver interfaces；
- exact model snapshot/cache bootstrap 和 local-only execution config；
- positive observation resolver，供 P3-06 构建 user-specific Memory；
- canonical text golden、missing/empty/conflict/multilingual/duplicate/repeat/cutoff tests；
- model revision/checksum、dimension/finite/norm、batch order、shard/index/ref、immutability/corruption tests；
- CPU fixture tests、optional real BGE/GPU integration test 和全部 P1/P2/P3 regression tests。

### P3-05 Decision Record

```text
Decision ID: P3-05
Status: Confirmed
Decision:
1. 首版使用 one-item-one-ItemSemanticPrototype；它是用户无关的静态语义原型，不等于 P3-06 生成的
   long/short PreferenceAtom。tag/category atoms、跨 item 聚类和 learned extraction 后置为 ablation。
2. Tsinghua `tsv-item-semantic-text-v1` 只以固定模板组合实际存在的 title_cn、tags 和
   category_paths_cn，不伪造 description；当前 31,496 items 均可由 tags/category 获得语义文本。
3. 只由 `tsv-positive-v1` 产生 preference observations；negative/passive 不生成正向 Atom。Repeated positives
   保留多个 observation、复用同一 prototype/embedding；long/short 分配和强度更新留给 P3-06。
4. Atom text embedding 固定为 BAAI/bge-m3 revision
   5617a9f61b028005a4858fdac845db406aefb181 + FlagEmbedding 1.4.0；dense CLS、无 instruction、
   max 1,024 tokens、1,024 dimensions、FP32 L2 normalization 和 cosine similarity。
5. 模型只通过显式 offline fetch 获取 exact snapshot/checksums；真实构建可用 GPU，CPU 提供 fixture contract，
   online Agent/loader/tests 不联网、不下载、不批量生成 embeddings。
6. Embeddings 是独立 immutable P3 item-semantic artifact，不回写 P2、也不按用户复制；Tensor 只通过
   ResourceRef 解析。artifact identity 固定 source/recipe/model/provider/vector/inventory/checksum provenance。
7. 缺失全部语义时不生成假 Atom；多语言原样编码；重复文本不合并 item identity但可复用 verified vector。
   第一版 semantic_profile=None。
8. SASRec 的 trainable ID embedding/hidden state 与本 Gate 的 frozen text embedding 保持独立；首版不把
   semantic embedding 注入 SASRec。依赖该 recipe 的后续 Segment Value 特征/模型必须随版本变化重建/重训。
Rationale:
item-level semantic prototype 能利用当前真实 title/tag/category coverage，以最少额外研究变量快速打通
Dynamic Memory，同时保留 item/事件 provenance 和重复行为。冻结的 multilingual text encoder 让不同 item
可以按内容语义匹配，而不混淆 SASRec 从行为序列学习的 dataset-specific ID representation。独立 artifact
避免 P2 schema 漂移和 per-user 重复，并为后续 Atom 粒度、embedding 模型及 Segment Value ablation 留下边界。
Alternatives considered:
每个 tag/category 一个 Atom；先做跨 item clustering/LLM extraction；用 SASRec hidden state 代替语义向量；
把 BGE embedding 注入首版 SASRec；为每次 interaction 重复编码；由 negative/passive 生成正向 Atom；使用
main/latest 模型；运行时下载；缺失文本填 unknown/生成 description；混合中英字段或自动翻译；第一版生成
LLM semantic profile；将 embeddings 回写 P2 或复制进每个 UserMemoryView。
P1/P2 compatibility evidence:
既有 PreferenceAtomView/UserMemoryView 已通过 ResourceRef 将 tensor 留在公共 schema 外，且要求 long/short
atom IDs 唯一；本决策保留这些契约。所有语义字段来自 P3-01 审计后的 P2 exact release，Memory 只解析
history cutoff 前 observations，不回写 SourceItem、behavior sequence、segment/store 或 release semantics。
Affected schemas/interfaces:
New internal ItemSemanticPrototype/semantic manifest/index records, SemanticTextBuilder, EmbeddingProvider,
publisher/loader/resolver and positive-observation resolver. No Phase 1 public schema, InitialRanker/SASRec checkpoint,
Phase 2 canonical schema/Store/release semantic change.
Affected docs/tests:
todo/phase_3_discussion.md；docs/01_dynamic_hybrid_user_memory.md；后续 semantic text/prototype/provider/model
snapshot/artifact/ref/missing/duplicate/multilingual/repeat/cutoff/immutability tests 和全部 P1/P2/P3 regressions。
Resolved follow-up:
首版 Atom source/granularity、canonical text、interaction eligibility、BGE model/revision/pooling/normalization/
dimension、download/cache/license、device/batch boundary、missing/multilingual/duplicate semantics、prototype/ref/
artifact ownership/identity/layout、SASRec separation 和 semantic-profile deferral。
Deferred follow-up:
P3-06 long/short selection、atom IDs、strength/persistence、matching/state/drift/update/persistence；后续 tag/category/
clustered/learned atoms、negative inhibition/passive weighting、embedding-model ablation；Phase 4 Information Need；
Phase 5 Segment Value features/models；P6 cold-semantic evaluation；future semantic-profile Gate。
Confirmed by: User
Date: 2026-08-04
```

---

## 9. P3-06 — Dynamic Hybrid Memory Update and Persistence

Status: `Confirmed`

### 9.1 目标

在已确认 Atom/Embedding 基础上定义 Long × Short matching、stable/emerging/fading、
drift、持久化和 reload baseline，并投影为既有 `UserMemoryView`。

### 9.2 一页主流程

```text
cutoff 前 positive_v1 history + P3-05 semantic prototypes
        ↓ chronological replay
recent-5 Short Memory + accumulated Long/Pending Memory
        ↓ cosine matching
Stable：强化 Long
Emerging：进入 Pending；跨两个不同时间点再次出现后晋升 Long
Fading：近期无匹配，按 source time 衰减；过弱则 Inactive
        ↓
Drift（只读派生摘要，不反向修改 Memory）
        ↓
immutable UserMemoryView snapshot
```

一次 Agent run 内 snapshot 固定。Information Need、Segment Value、MLLM Evidence 和 Score Update 都不能
反向修改 Memory；只有新的真实用户行为触发下一次离线 replay/build。

### 9.3 数据审计与双时间尺度决策

P3-02 的 4,298 个 eligible users 在 validation cutoff 最少只有 3 个 observed positives。如果把 long/short
定义为互斥切片，`recent-3` 会使 375 个用户 long 轴为空，`recent-5` 会使 964 个用户 long 轴为空。
同时实际 audit 显示：validation prefix 只有 51/4,298 users 出现 exact-item positive repeat，full prefix 也
只有 58/4,298，repeated-event fraction 约 0.074%。因此不能用“旧 items = long”或“同一个 item 重复”作为
长期兴趣的唯一来源。

首版固定为重叠的双时间尺度：

- Short Memory 是 cutoff 前最近 5 个具有有效 semantic prototype 的 `positive_v1` observations；event 不去重，
  按 P2 `interaction_index` 保序；
- Long Memory 是从 cutoff 前全部有效 positive observations 顺序 replay 后形成的 user-specific semantic
  tracks，不等于 `history minus recent-5`；
- Pending tracks 保存尚未达到 persistence 的 emerging interests；它们不是公开 long atoms；
- 最终 View 最多投影 20 个 active long atoms。Long 按 strength desc、persistence desc、last_seen desc、
  atom_id asc 排序；Short 按 interaction_index desc、atom_id asc 排序；
- Memory 可使用已观察且具有语义 prototype 的 cold/OOV item；这不扩展 SASRec vocabulary，也不允许读取
  cutoff 后 behavior。SASRec 与 Memory 的可用 item 边界分别记录。

当前 source 只覆盖约七天，因此本数据集中的 `long-term` 只表示 sampled observation period 内的 persistent
interest，不得外推为数月/数年的用户偏好；长周期结论需要后续其他数据集验证。

### 9.4 `dynamic-hybrid-memory-v1` sequential update

对每个 observation 按以下固定顺序处理：

1. 解析 P3-05 prototype/embedding，并把 event atom 加入 recent-5 Short queue；
2. 在全部 long tracks（包括 internal inactive tracks）中选择 cosine 最高者；tie 使用 `atom_id` 升序；
3. 若 best-long similarity `>= 0.70`，将 observation 分配给该 track：support count 增加、更新 last_seen、
   inactive 允许 re-activate，并执行 normalized EMA；
4. 否则在 pending tracks 中以同样 tie rule 查找 best match。若 similarity `>= 0.70`，累积该 pending；
   否则以当前 observation 创建新 pending；
5. pending 只有在拥有至少 2 个 distinct source timestamps 后才晋升 long。Same-timestamp events 仍保留并按
   interaction_index replay，可计入 support/centroid，但不增加 temporal persistence 或 promotion count；
6. observation 只能分配到一个 best long/pending track；long 优先于 pending，避免同一兴趣重复建 track。

该过程是单用户、chronological memory tracking，不是把全体 items 预先做 global clustering。每个 source item
仍保持 P3-05 独立 `ItemSemanticPrototype`；long atom 是由某个 prototype seed、被该用户后续相似 observations
强化的 user-specific track。

Long/pending centroid 使用：

```text
e_new = L2_normalize((1 - eta) * e_old + eta * e_observation)
eta = 0.20
```

公开 atom text 不由 LLM 生成；从该 track 的真实 support prototypes 中选择与最终 centroid cosine 最高的
medoid semantic text，tie 按 earliest interaction_index、prototype_id。Long atom ID 由 memory recipe、user
namespace 和 seed observation identity 确定，后续强化不改变 ID；Short atom ID 由 recipe、user、side 和
exact event identity 确定，因此 long/short 两侧始终唯一。

### 9.5 Strength、persistence 和状态

设 long track 的全部 assigned observations 数为 `support_count`，distinct source timestamps 数为
`distinct_support_times`，snapshot source reference time 与 `last_seen` 的差为 `age_days`：

```text
long_support_score = 1 - exp(-support_count / 3)
long_recency_score = 2 ** (-age_days / 7)
long_strength      = clip(long_support_score * long_recency_score, 0, 1)
long_persistence   = min(distinct_support_times / 5, 1)
```

Short atom 中 newest 的 `age_index=0`：

```text
short_strength    = 2 ** (-age_index / 2)
short_persistence = min(assigned_track_distinct_support_times / 5, 1)
```

因此 recent-5 short strengths 从 newest 到 oldest 为约 `1.00, 0.71, 0.50, 0.35, 0.25`。第一次出现的
emerging atom persistence 为 `0.20`；两个不同时间点支持后为 `0.40` 并允许 promotion。所有 public
strength/persistence 必须 finite 且在 `[0, 1]`。

Snapshot 最终从 strength `>= 0.10` 的 long tracks 中选 top-20；其余 strength `< 0.10` 标记 internal
`inactive`。Inactive 不硬删除、不进入默认 View/matrix，但保留在 immutable internal State，未来 matching
成功后可 re-activate。Fading 不等于 dislike，只表示当前 recent-5 没有支持；不因一次 absence 删除。

### 9.6 Long × Short matching 和 classifications

对 projected long atoms 和 recent short atoms 构建 FP32 matrix：

```text
M[i, j] = cosine(long_i, short_j)
shape = [num_projected_long, num_short]
match_threshold = 0.70
```

首版使用 deterministic many-short-to-one-long：每个 short atom 选择唯一 best long；多个 shorts 可以选择同一
long，不使用 Hungarian/one-to-one global assignment。

- best similarity `>= 0.70`：输出一个同时引用 long/short 的 `stable` match，short state=`stable`；被至少一个
  short 选择的 long state=`stable`；
- best similarity `< 0.70`：输出 long ID 为 `None` 的 `emerging` match，short state=`emerging`；
- 没有被任何 stable short 选择的 projected long 输出 short ID 为 `None` 的 `fading` match，long state=`fading`；
- emerging/fading 在对侧非空时保存 best cosine 作为 diagnostic similarity；对侧为空时 similarity=`None`。

Matrix 两侧都非空时 `similarity_matrix_ref` 必须解析到 exact matrix；任何一侧为空时 ref=`None`，规则为：

| Long axis | Short axis | Match/state semantics | Drift semantics |
| --- | --- | --- | --- |
| empty | empty | no matches | all drift fields `None` |
| empty | non-empty | all shorts emerging，similarity `None` | new=1；drop/global=`None` |
| non-empty | empty | all longs fading，similarity `None` | drop=1；new/global=`None` |
| non-empty | non-empty | normal threshold matching | calculate all three |

### 9.7 Drift 是只读派生信号

Drift 在最终 Long/Short/matrix 确定后计算，不参与 matching、threshold、promotion、EMA、decay、删除、SASRec
scoring 或当前 snapshot 的再次更新。Phase 4/5 可以消费它，但 P3 不提前定义 Information Need/Segment Value
的使用公式。

令 `clip_sim(x)=clip(x,0,1)`；short weights `beta` 由 short strengths 归一化，long weights `alpha` 由 long
strengths 归一化：

```text
D_new  = sum_j beta_j  * (1 - clip_sim(max_i M[i,j]))
D_drop = sum_i alpha_i * (1 - clip_sim(max_j M[i,j]))

e_long_global  = L2_normalize(sum_i alpha_i * e_long_i)
e_short_global = L2_normalize(sum_j beta_j  * e_short_j)
D_global       = 1 - clip_sim(cosine(e_long_global, e_short_global))
```

三个有值的 drift 均在 `[0,1]`。`new` 高表示近期出现较多旧 Memory 无法解释的兴趣；`drop` 高表示较多
long interests 最近没有支持；`global` 只表示整体语义方向差异。它们是 summary，不是新的事实来源。

### 9.8 Runtime、prefix 和 public view

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

首版 runtime 固定为 **offline build/publish + online exact read-only load**。Memory builder 从 P3-02/P3-05 exact
artifacts 为 validation/test target cutoffs 和显式请求的 run prefix 生成 snapshot；可选 full-history snapshot
使用独立 inventory/identity。Bootstrap 已用 exact Memory snapshot ref + `AgentInputBundle.cutoff_identity` 绑定
当前 adapter；已有同步 `UserMemory.build_or_update(user_id, history)` 中的 `history` 固定为 cutoff 前完整、未截断
`positive_v1` item-ID projection，只执行：

```text
bound exact snapshot + cutoff identity
    + user_id + exact positive_v1 history projection
    → validate projection SHA-256
    → validate user/cutoff/artifact closure
    → return immutable UserMemoryView
```

它不在线 replay、写 Store、按 history scan snapshot inventory 或从 latest/tuple 猜测结果。Tuple 不是 snapshot
selector，因为相同 positive projection 可能对应不同 full-exposure cutoff；exact bundle/ref 才是 selector。History
中 repeated IDs 保留；history/prefix/cutoff mismatch、未知 user/snapshot 或 checksum/ref corruption fail closed。
无 semantic observations 时 Memory 可返回合法 empty View，但这不为 SASRec 增加 cold-user/popularity fallback；
当前 Initial Ranker 的 empty/all-OOV 限制保持不变。

`created_at_ms`/`last_seen_at_ms` 使用 source event time；`UserMemoryView.updated_at_ms` 使用本 snapshot 消费的
最后一个 source event time，无 event 时为 `None`。Execution/build time 只留 manifest provenance，不进入
portable view semantics。`semantic_profile` 继续固定为 `None`。

### 9.9 Information Need readiness

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

### 9.10 Artifact、identity 和 atomic reload

推荐逻辑布局：

```text
memory artifact
  ├── manifest.json
  ├── memory_states.jsonl
  ├── memory_views.jsonl
  ├── snapshot_index.jsonl
  ├── memory_embedding_index.jsonl
  ├── memory_embeddings-00000.safetensors ...
  ├── similarity_matrix_index.jsonl
  └── similarity_matrices-00000.safetensors ...
```

Internal State 保存 pending/active/inactive tracks、support event refs 和 centroid refs；View 只保存紧凑 atoms、
matches、drifts 和 ResourceRefs。Short atom embeddings 可直接引用 P3-05 artifact；long centroids 和 matrices
属于 Memory artifact。`memory_version` 唯一绑定 memory artifact、user、cutoff/prefix fingerprint 和 snapshot
record checksum；metadata 至少记录 source/P3-derived/semantic artifact IDs、recipe ID、prefix hash、observed/
semantic/long/short/pending/inactive counts 和 cutoff identity，不把 metadata 当默认模型特征。

Artifact identity 覆盖 exact P2 release、P3-02 derived ref、P3-05 semantic ref、全部 threshold/window/EMA/
strength/persistence/drift/ordering/codec/schema recipes、snapshot inventory 和 payload checksums；absolute path、
worker/device、execution time 不进入 semantic recipe identity。

Publication 复用 P2/P3 已确认的 staging → validate closed inventory/checksums/refs → atomic publish 语义。相同 exact
identity/content 可返回 reused；同 identity 的 schema/content mismatch 使用 `ArtifactIntegrityError`，不覆盖。
Concurrent builders 只允许一个完成原子发布，其他 builder 验证并复用；partial staging 不可发现，不自动删除，
loader 不 fallback 到 previous/latest，也不在 online path 自动重算。Same exact prefix/config 的 no-new-event build
必须得到 byte-identical logical records/refs；snapshot load 不产生新 version。

真实 user State/View/embedding/matrix artifacts 留在 Git 忽略的 local/external root，只提交 schema/code、aggregate
audit 和 synthetic fixtures。

### 9.11 交付结果和 tests

- internal Memory State schemas/interfaces；
- sequential matching/pending/promotion/EMA/strength/persistence/fading/inactive baseline；
- deterministic projection to `UserMemoryView`；
- exact prefix snapshot builder/publisher/loader and ResourceRef resolvers；
- Information Need readiness contract and tests；
- version/identity/atomic publication/reload semantics；
- ordering/tie/repeat/same-time/no-new-event/cutoff/leakage tests；
- empty-axis/short-history/stable/emerging/promotion/fading/inactive/reactivation/drift golden fixtures；
- corruption/concurrency/existing-version/ref-closure and all P1/P2/P3 regression tests。

### 9.12 Baseline sensitivity boundary

`recent=5`、`max_long=20`、similarity `0.70`、promotion distinct-times `2`、EMA `0.20`、persistence saturation
`5`、recency half-life `7 days` 和 inactive `0.10` 是第一条 engineering/research baseline，不宣称为最终最优。
真实 BGE artifact 构建后必须报告 long-empty、stable/emerging/fading、promotion、inactive、atom-count 和 cosine
distribution audit；不得自动调 threshold。论文实验只在 validation 上选择或敏感性比较，例如 threshold
`{0.60,0.70,0.80}`，test 不参与选择。Alternative time windows、one-to-one matching、decay/EMA 和 learned
Memory 留作显式 ablation。

### P3-06 Decision Record

```text
Decision ID: P3-06
Status: Confirmed
Decision:
1. Short 是 cutoff 前最近 5 个 valid positive semantic observations；Long 是全 observed prefix chronological
   replay 形成的 user-specific tracks，两者重叠而非 history partition。View 最多投影 strongest 20 active longs。
2. 每个 observation 先匹配 long，再匹配 pending；cosine threshold=0.70，tie by atom ID。Long match 强化；
   pending 至少跨 2 个 distinct source timestamps 才 promotion；同时间 event 不增加 temporal persistence。
3. Long/pending embedding 使用 normalized EMA eta=0.20；公开 text 使用真实 support prototype medoid，不生成摘要。
4. Long strength=(1-exp(-support_count/3))*2^(-age_days/7)，persistence=min(distinct times/5,1)；Short
   strength=2^(-age_index/2)，persistence 使用其 assigned track 的 distinct-time mapping；全部 clip 到 [0,1]。
5. Final matching 是 each-short-one-best-long、many-shorts-to-one-long。>=0.70 是 stable；未匹配 short 是
   emerging；无 stable short 的 active long 是 fading；strength<0.10 是 internal inactive，不删除且可 re-activate。
6. Empty axes、match similarity 和 new/drop/global drift 的 None/1 semantics 固定。Drift 是 [0,1] 的只读派生
   summary，不反向改变 Memory/SASRec，也不提前确定 Information Need 或 Segment Value 算法。
7. 首版只离线构建 immutable exact-prefix snapshots；online build_or_update 验证 user/history fingerprint 后只读
   加载。一次 Agent run 内 View 固定，Evidence/Score Update 不更新 Memory；updated_at 使用 source event time。
8. Internal state、long centroid embeddings、matrices 和 views 作为独立 immutable Memory artifact 原子发布；
   Tensor/path 不进入公共 View。Existing/concurrent/corrupt/mismatch 全部 strict validate/fail closed，不 latest fallback。
9. Empty Memory View 合法，但不实现 SASRec cold-user fallback。semantic_profile=None。全部数值是首版 baseline，
   后续只用 validation audit/ablation 选择，不查看 test。
Rationale:
真实数据的短序列和极低 exact-item repeat 证明 long 不能是 recent window 之外的 item partition，也不能只靠同一
视频重复。重叠双时间尺度和 user-specific semantic tracks 让不同但相关的视频积累成可解释兴趣，同时以
recent-5/top-20、确定性 replay 和 immutable snapshot 控制复杂度。Drift 保持只读可避免循环自我更新，并给
后续 Information Need/Segment Value 留出明确消费边界。
Alternatives considered:
long=history minus short；只允许 exact-item repeat；recent-2/3/10；全量 long 不投影上限；global item clustering；
一次 observation 立即 promotion；same timestamp 增加 persistence；Hungarian/one-to-one matching；drift 反向调
threshold/update；fading 立即删除；wall-clock decay；online mutable Memory；Evidence 更新偏好；latest fallback；
第一版生成 semantic profile 或加入 cold-user ranker fallback。
P1/P2 compatibility evidence:
Public PreferenceAtomView/UserMemoryView/PreferenceMatchView shapes 不变，IDs/ref validation 继续成立；Tensor 只经
ResourceRef。Memory 只读取 P2 ordered facts/P3 cutoff 前 positive observations 和 exact semantic artifact，保持
behavior sequence、P2 Store/release、Agent Controller、Recommendation State 和一次 run snapshot immutability。
Affected schemas/interfaces:
New internal MemoryState/Track/Support/Snapshot/manifest/index records, replay updater, matrix/drift projector,
publisher/loader/resolvers and read-only real UserMemory adapter. No Phase 1 public schema/interface or Phase 2 semantic
change; existing UserMemory.build_or_update signature remains synchronous.
Affected docs/tests:
todo/phase_3_discussion.md；docs/01_dynamic_hybrid_user_memory.md；后续 update/matching/state/drift/snapshot/artifact/
prefix/concurrency/corruption/empty-axis/readiness tests 和全部 P1/P2/P3 regressions。
Resolved follow-up:
long/short selection、matching/ties/empty axes、threshold、strength/persistence/EMA、pending/promotion、fading/inactive/
reactivation、same-time/repeat/idempotency、drift、timestamps、semantic profile、offline runtime、artifact layout/
identity/atomicity/reload 和 Information Need readiness boundary。
Deferred follow-up:
P3-07 config/bootstrap/CLI/root bindings；P3-08 evaluation/DoD；Phase 4 Information Need；Phase 5 Segment Value；
P6 cold-user/cold-item and threshold calibration；later window/matching/EMA/decay/atom/learned-Memory ablations；
longer-duration dataset validation and future semantic-profile Gate。
Confirmed by: User
Date: 2026-08-04
```

---

## 10. P3-07 — Config, Bootstrap, Runtime Integration, and CLI

Status: `Confirmed`

### 10.1 目标

将真实 Memory 和 SASRec 通过显式 config/bootstrap 接入既有 Controller，同时保持
训练、Memory build、evaluation 和 online Agent run 的 lifecycle 分离。

### 10.2 Lifecycle/config separation

现有 `Phase1Config`、`load_config()`、`run_from_config()`、`configs/base.yaml` 和 `configs/mock.yaml` 保持原样，
不能扩成包含全部 P3 offline/runtime 字段的总模型。P3 使用同一 deterministic single-parent `extends` 语义，
但按生命周期建立独立 strict/frozen config 和 loader：

```text
configs/phase3/
  derived.yaml                → Phase3DerivedSequencesConfig
  semantic.yaml               → Phase3ItemSemanticsConfig
  sasrec_train.yaml           → Phase3SasrecTrainingConfig
  memory.yaml                 → Phase3MemoryConfig
  memory_audit.yaml           → Phase3MemoryAuditConfig
  runtime_zero_budget.yaml    → Phase3RuntimeConfig
  evaluate_*_test.yaml        → Phase3EvaluationConfig（指标语义已由 P3-08 确认）
```

每类 config 必须有 exact `kind`/`schema_version` discriminator，unknown/foreign fields fail；不能把 training
optimizer、embedding batch、Memory thresholds、runtime component selectors 和 evaluation metrics 混进同一 schema。
CLI 不支持 `key=value` semantic overrides、environment interpolation、reflection/plugin imports、`latest`、force
或静默 resume。Machine-local child 只允许改变 operational root/device/worker/batch bindings；任何改变 logical
output 的字段仍进入对应 artifact/checkpoint identity。

### 10.3 Root registry 和 exact artifact graph

P3 复用 P2 typed root-registry/path-safety 语义。Local config 将 portable root ID 显式绑定到 project-relative 或
absolute physical root，并声明 `read_only`/`write_new`；roots 必须 distinct/non-overlapping，resolver 继续拒绝
absolute/ambiguous resource keys、traversal 和 symlink/junction escape。推荐 root roles 至少覆盖：

```text
p2_processed     read_only
p3_derived       read_only/write_new by lifecycle
model_cache      read_only after explicit fetch
item_semantics   read_only/write_new by lifecycle
checkpoints      read_only/write_new by lifecycle
memory           read_only/write_new by lifecycle
runs             write_new
```

Runtime semantic config 只以带 full SHA-256 的 `ResourceRef` 固定 closed graph：

```text
exact P2 release ref
exact P3 derived dataset ref
exact P3 item-semantic artifact ref
exact SASRec checkpoint manifest ref
exact Memory artifact/snapshot ref
exact AgentInputBundle ref
```

Bootstrap 验证所有 refs 的 store/key/version/checksum、内部 manifest closure、dataset/split/vocabulary/prefix/model
compatibility，禁止 scan directories、mtime、latest、跨 release 混用或从其中一个 artifact 猜另一个。物理 root
paths 是 machine-local operational bindings，不进入 portable identity；P3 `resolved_config.json` 记录 root IDs/access
roles 和 exact refs，不写 absolute paths、tokens、credentials、model cache paths 或其他 secrets。本机绝对路径只可
进入 Git 忽略的 lifecycle execution report，不进入 Agent run 三件套。

`AgentRunResult.data_version` 继续记录 exact P2 `p2-...` data version；derived/semantic/checkpoint/memory/input 和
runtime-bundle identities 记录在 resolved config 与 result metadata，不能挤进一个含义混乱的 version string。

### 10.4 Exact AgentInputBundle

真实 runtime 不从 CLI 接收任意 user/history/candidate lists，也不把 source rows 塞进 YAML。增加 versioned internal
`AgentInputBundle`：

```text
schema_version
user_id
history_projection_recipe        # p3-positive-item-history-v1
ordered_history_prefix
history_prefix_sha256
candidate_ids
cutoff_identity
derived_dataset_ref
candidate_set_ref/provenance
bundle_checksum
```

`ordered_history_prefix` 固定为 target cutoff 前完整、未 recent-50 截断的 `positive_v1` item-ID 序列；
`history_prefix_sha256` 对 recipe/user/ordered tuple 的 canonical record 计算。`cutoff_identity` 另行锚定 P2
full-exposure exclusive cutoff。Bootstrap 必须验证 bundle history 与 derived target history 相同、cutoff 与
target/full-exposure prefix 相同、Memory snapshot 同时固定该 projection hash/cutoff；SASRec 才在 adapter 内
OOV-filter/recent-50。Runner 加入实际 run ID 后投影为既有 `AgentRunRequest`，不增加第二个 history 字段。

首条 Cheap Path smoke 使用 P3-02 development-only
`1 warm target + 100 fixed warm candidates` 中一个显式、checksum-pinned bundle；candidate 全部满足 SASRec
checkpoint vocabulary/coverage 和 P2 Store coverage。它只验证集成，不得作为论文 ranking result。真实 input/
Memory text/trace 继续视为 local sensitive artifacts，不进 Git、不公开分发。

### 10.5 Component selector mapping

Existing all-mock mapping/descriptor table 不改变。Phase 3 runtime 使用 explicit constructor registry：

| Role | Selector / implementation | Descriptor version |
| --- | --- | --- |
| user_memory | `artifact` / `ArtifactUserMemory` | `dynamic-hybrid-memory-v1` |
| initial_ranker | `sasrec` / `SasrecInitialRanker` | `sasrec-pytorch-v1` |
| item_feature_store | `persistent` / `FilesystemItemFeatureStore` | `filesystem-item-feature-store-v1` |
| segment_store | `persistent` / `FilesystemSegmentStore` | `filesystem-segment-store-v1` |
| state_builder | `default` / existing builder | `phase1-v1` |
| information_need/segment_value/perceiver/evidence/observation/score updater | role-specific `unavailable` guard | `phase3-zero-budget-v1` |
| stop_policy | `threshold` / existing policy | `phase1-v1` |
| trace_writer | `jsonl` / existing writer | `phase1-v1` |

Descriptor version 表示 implementation contract，不冒充 artifact version；exact artifact IDs/checksums 单独保存在
config/result metadata。每个 unavailable guard 实现相应 Protocol，但若被调用必须抛出 declared
`ComponentExecutionError`，不能返回 Mock/empty value。Runtime config 只要选择任何 unavailable role，就强制
`max_perception_actions=0`；`>0` 在 bootstrap 前作为 config error 拒绝。

验证组合固定为：

1. all-mock：继续走现有 P1 config/golden runner；
2. real-memory-only：直接通过 `ArtifactUserMemory` API + synthetic fixture 验证，不强塞进不兼容 Mock Controller；
3. real-ranker-only：直接通过 `SasrecInitialRanker` API + synthetic fixture 验证；
4. full-real-cheap：artifact Memory + SASRec + persistent Stores + unchanged Controller + zero budget。

Mixed component tests 只验证边界，不作为 research run；禁止把真实 user/item namespace 与 `mock-v1` signature table
硬拼。

### 10.6 Shared APIs 和 thin CLI

权威 lifecycle 只存在于 Python APIs：

```text
derive_sequences_from_config()
build_item_semantics_from_config()
train_initial_ranker_from_config()
build_memory_from_config()
audit_memory_from_config()
evaluate_from_config()        # exact metric semantics fixed by P3-08
run_phase3_from_config()
replay_run()
```

统一薄入口为：

```text
python -m pave_rec.cli.phase3 derive       --config <path>
python -m pave_rec.cli.phase3 semantics    --config <path>
python -m pave_rec.cli.phase3 train-ranker --config <path>
python -m pave_rec.cli.phase3 memory       --config <path>
python -m pave_rec.cli.phase3 memory-audit --config <path>
python -m pave_rec.cli.phase3 evaluate     --config <path>
python -m pave_rec.cli.phase3 run          --config <path>
python -m pave_rec.cli.phase3 replay       --run-dir <path>
```

CLI 只 parse → call API → print typed result/ref summary；不组装 components、不计算 identity、不写第二套业务逻辑。
`evaluate` 的命令/API seam 在 P3-07 固定；P3-08 已确认 metric config/DoD，因此实现后只允许按该 exact
full-catalog protocol 产出真实结果。各 offline command 返回 typed result、exact output ref/outcome 和 local execution-report path，供下一 lifecycle 显式 pin；
第一版不增加自动串联 latest outputs 的一键 pipeline。

Exit codes 统一：成功 `0`；合法启动后的 declared execution/publication/component failure `1`；config/input/ref/
compatibility/device preflight error `2`；interrupt `130`。CLI stdout 不打印 source titles/user history、absolute
paths、secrets 或 tensor payload。

### 10.7 Runtime preflight、run artifacts 和 replay

Real runner 的顺序固定为：

```text
load/validate config + roots
→ load/verify exact artifact graph and AgentInputBundle
→ validate request/checkpoint/Memory/Store coverage and device
→ compute portable resolved runtime record
→ exclusively allocate runs/<run_id>
→ write resolved_config.json
→ bind TraceWriter and build unchanged AgentController
→ Controller.run
```

Config/root/input/ref/checksum/coverage/device/bootstrap preparation failure发生在正式 run directory 分配前，exit=2；
不得留下看似开始的 Agent run。分配后 resolved-config write/TraceWriter failure 继续遵守 P1 语义。Controller 内
declared component failure 仍生成 terminal `component_failure` trace/result 并 exit=1；不把 bootstrap failure 伪造成
Controller StopDecision。

每个 Agent run 继续只有：

```text
runs/<run_id>/
  resolved_config.json
  trace.jsonl
  result.json
```

Checkpoint、Memory state/vectors/matrix、P2/P3 datasets、BGE cache 不复制进 run directory。Resolved config 和
result metadata 保存 runtime-bundle ID 与六类 exact refs；trace/state 继续只保存既有 public views/ResourceRefs，
不修改 `AgentStepTrace` schema。P3 resolved config 增加 explicit `kind=phase3-runtime`；`replay_run()` 先按 discriminator
解析 P3 record、否则保持 P1 parser，验证 refs/metadata/descriptors/run ID/data version 的持久化一致性，但 structural
replay 不联网、不加载外部 tensors 或重新执行组件。All P1 golden bytes/semantics 保持不变。

### 10.8 Confirmed real Cheap Path smoke

```text
exact Phase 2 release
+ exact P3 derived dataset/item semantics
+ fixed real Memory snapshot
+ fixed SASRec checkpoint
+ persistent Item/Segment Stores
+ exact 101-candidate AgentInputBundle
+ max_perception_actions = 0
→ unchanged AgentController
→ fixed UserMemoryView + full candidate SASRec scores
→ initial ranking
→ budget_exhausted
→ valid trace/result/replay
```

Controller 当前在每轮先执行 pre-value StopPolicy，再调用 Information Need；budget=0 因而确定性在真实
Recommendation State 建好后停止，不调用 unavailable Phase 4/5 roles。Smoke 必须断言 attempted actions=0、
terminal reason=`budget_exhausted`、ranking/Memory/store refs/metadata 完整、三件套 canonical 且 replay 等价。

### 10.9 交付结果和 tests

- six strict lifecycle configs/loaders and common deterministic config helper；
- typed root bindings, exact runtime graph and AgentInputBundle schema/loader；
- explicit component registry/descriptors/unavailable guards and bootstrap preflight；
- shared lifecycle Python APIs and one thin Phase 3 subcommand CLI；
- portable P3 resolved-runtime record/result metadata and P1/P3 replay dispatch；
- real-memory/real-ranker component smokes and full-real-cheap zero-budget E2E；
- config inheritance/kind/unknown-field/path/root/ref/closure/coverage/device tests；
- API/CLI equivalence、exit-code、no-run-on-preflight-failure、three-artifact-only、no-secret/path tests；
- all existing Phase 1/2 runner/config/replay/golden regressions byte/semantic unchanged。

### P3-07 Decision Record

```text
Decision ID: P3-07
Status: Confirmed
Decision:
1. Phase 1 config/runner remain unchanged. P3 uses separate strict derived, semantic, SASRec-training, Memory, runtime
   and evaluation config kinds/loaders under configs/phase3; no giant config or semantic CLI overrides/latest pipeline.
2. Reuse typed safe root registry. Physical paths are local operational bindings; portable configs/refs use root IDs and
   exact checksummed ResourceRefs. Runtime pins P2, derived, semantic, checkpoint, Memory and AgentInputBundle refs.
3. AgentInputBundle carries exact user/positive_v1-history-projection/candidates/full-exposure-cutoff provenance. The
   public tuple is complete positive history; Memory is bound by exact snapshot/cutoff and only validates the tuple,
   while SASRec applies recent-50 internally. First smoke uses one fixed P3-02 development-only 1+100 warm candidate
   bundle and is not a paper benchmark result.
4. Full-real-cheap selects ArtifactUserMemory, SasrecInitialRanker, persistent Stores, existing State/Stop/Trace and
   role-specific unavailable Phase4/5 guards. Any unavailable role requires max_perception_actions=0.
5. All-mock remains P1. Real-memory-only/ranker-only use direct component integration APIs/fixtures; do not combine real
   namespaces with incompatible mock-v1 tables. Full-real-cheap alone runs the real zero-budget Controller smoke.
6. Shared Python APIs own derive/embed/train/memory/evaluate/run lifecycles; one thin `pave_rec.cli.phase3` subcommand
   dispatcher calls them. Exit codes are 0/1/2/130; evaluate semantics are now fixed by confirmed P3-08.
7. Real runtime preflights exact graph/input/coverage/device before allocating run directory. Bootstrap failure is not a
   Controller stop; declared in-run failure remains component_failure.
8. Agent runs keep exactly resolved_config.json, trace.jsonl and result.json. Big artifacts stay external by ref. P3
   resolved config/result metadata store the exact graph without paths/secrets; trace public schema is unchanged.
9. Replay dispatches on explicit P3 runtime kind while preserving P1 parser/goldens, and structurally validates saved
   descriptors/refs/metadata without network, tensor load or component re-execution.
10. Zero-budget smoke builds real Memory/ranking/State then deterministically stops budget_exhausted before Information
    Need/Segment Value/Perception, proving the Cheap Path without pretending Phase 4/5 is implemented.
Rationale:
Separate lifecycle configs prevent training/build/runtime semantics from contaminating one another. Exact refs and a fixed
input bundle make the real run reproducible across machines while keeping root paths operational. Zero-budget exploits the
already-confirmed Controller order to validate every completed P3 component and persistent Store without adding fake
Information Need/MLLM behavior or changing public schemas/run artifacts.
Alternatives considered:
Widen Phase1Config into one experiment schema；one giant do-everything config/CLI；CLI key overrides/env interpolation；
latest/scan/mtime discovery；inline user/candidate lists；full catalog Agent smoke；copy checkpoints/vectors into run dir；
use mock-v1 Phase4 components with real IDs；allow unavailable roles at positive budget；modify Controller for P3；write
extra run files/change trace schema；bootstrap errors as component_failure；absolute paths/secrets in resolved config；
auto-chain latest outputs；force mixed real/mock full Controller runs。
P1/P2 compatibility evidence:
Existing AgentController pre-value budget stop occurs before InformationNeed. AgentComponents/UserMemory/InitialRanker/
Stores/State/Trace interfaces and three-file runner ownership already supply all seams. P2 RootRegistry/ReleaseLoader and
filesystem Stores already enforce exact refs/path safety. P1 configs, mock selectors, bytes, replay and public schemas stay
unchanged; P3 only adds parallel typed config/bootstrap adapters and discriminator-aware replay validation.
Affected schemas/interfaces:
New internal P3 lifecycle configs/resolved-runtime/AgentInputBundle/runtime-bundle records, config loaders, API result
types, unavailable guards and bootstrap registry. Existing public component protocols, AgentRunRequest/Result,
RecommendationState, AgentController and AgentStepTrace shapes remain unchanged.
Affected docs/tests:
todo/phase_3_discussion.md；configs/README.md；docs/08_agent_controller.md；后续 P3 config/root/input/bootstrap/API/CLI/
runner/replay/integration/E2E tests 和全部 P1/P2/P3 regressions。
Resolved follow-up:
config/lifecycle split、selectors/descriptors/guards、root/exact refs、input bundle、portable resolved config/result refs、
Python API/CLI names/exit codes、preflight-vs-runtime failure、three-file run/replay、zero-budget integration smoke，
以及由 P3-08 完成的 evaluation metrics/test matrix/DoD。
Deferred follow-up:
Phase 4 real Information Need/Perceiver、positive-budget config 和 expensive Top-L candidate/segment shortlist；Phase 5
Segment Value；service/async/concurrent online runtime；one-command orchestration。
Confirmed by: User
Date: 2026-08-04
```

---

## 11. P3-08 — Evaluation, Test Matrix, and Definition of Done

Status: `Confirmed`

### 11.1 Exact next-item metric protocol

P3-02 validation/test 每个 eligible user 各只有一个 positive target，因此 evaluator 使用 single-relevant-item、
per-user macro average。对 warm target 在过滤后的 full train-vocabulary candidate domain 中令其 1-based rank 为
`r`；不在可服务 vocabulary 中的 cold target 没有伪 rank：

```text
HR@K     = 1[r <= K]
NDCG@K   = 1[r <= K] / log2(r + 1)
MRR@10   = 1[r <= 10] / r
Recall@K = HR@K                 # only because each case has one relevant target
```

Primary metric 固定为 warm-target `NDCG@10`，与 P3-03 checkpoint selection 一致；secondary metrics 固定为
`HR@10`、`NDCG@20`、`HR@20`、`MRR@10` 和 `Recall@100`。不重复报告含义相同的 `Recall@10`。
Metric accumulator 使用 float64，aggregate 记录 numerator/denominator/count；空 subset、non-finite score、duplicate
candidate、invalid rank 或 target/coverage mismatch fail，不返回 `NaN` 或伪零均值。

Primary evaluation 继续使用 P3-02 已确认的完整 train vocabulary，不 sampled、不注入 target。Evaluator 在调用
ranker 前过滤 cutoff 前 positives；若 ground-truth 本身是 repeat，只把该 target 作为例外保留。Warm candidate
由 ranker 精确全覆盖，按 `(-raw_score, item_id)` 排序；cold target 不进入 scorer。Validation 只用于 early stop/
checkpoint selection 和后续显式 validation-only tuning；test 对每个 exact best checkpoint 只评价，不选模型。

报告必须同时给出：

1. 全部 target 的 `warm_count / all_target_count`、cold count 和 all-target retrieval coverage，cold 为 miss；
2. fixed warm-target subset 的上述 ranking metrics 和 exact subset ref/checksum。

P3-02 的 `1 labeled warm positive + 100 negatives`、seed `20260804` 仍只用于 evaluator/CPU/CI/dev smoke，不能进入
论文主结果，也不能与 full-catalog protocol 混表。

### 11.2 Full-catalog → Top-100 Agent handoff

`Recall@100` 不表示 primary evaluator 只排 100 个候选；它验证 full-catalog ranker 能否把 target 保留在后续 Agent
可消费的 Top-100 item pool 中：

```text
full warm catalog
    → SASRec deterministic ranking
    → ordered Top-100 item candidates
    → later Agent / reranking candidate pool
    → Phase 4/5 cheap filtering selects a smaller Top-L item/segment search space
```

Top-100 pool 不进行 offline target injection；若 target 不在其中，后续 conditional reranking/Perception 无权把它
伪造回来。Phase 4/5 再确认昂贵路径实际考虑的 Top-L items、segments 和 budget；P3 不要求 MLLM 感知全部 100 个
items。P3-07 fixed smoke 的 `1 positive + 100 negatives = 101 candidates` 是 development-only input contract，
不是这里 full-catalog 产生的 100-item research handoff。

### 11.3 Baselines、seeds 和 research/contract boundary

Phase 3 minimum real-data comparator 固定为：

```text
MostPop(train-only positive frequency; tie by item_id)
SASRec(sasrec-pytorch-v1)
```

两者使用相同 split、full candidates、seen filtering、warm/cold subsets 和 metrics。Deterministic Random ranking 只作
evaluator sanity fixture，不进入主要 research table。GRU4Rec/BERT4Rec、完整 method matrix 和 equal tuning budget
仍按 ranker/benchmark proposal 在第一条 Agent Loop 后推进。

第一条真实 Tsinghua Agent Loop/Phase 3 engineering acceptance 使用 training seed `20260804` 的 exact best
checkpoint；单 seed 只证明 pipeline 和研究 pilot，不冒充最终稳定效果。可公开报告的 stochastic ranker result
至少使用固定 seeds `{20260804, 20260805, 20260806}`，每个 seed 独立按 validation 选择 best，在 test 上报告
`mean ± sample standard deviation`；MostPop 等确定性方法只跑一次并标记 deterministic。Phase 3 不做大规模
hyperparameter sweep；P3-03 fixed recipe 是当前 baseline，更广 tuning budget 在 Phase 6 公平比较前锁定。

Contract fixtures 不设虚假的 research-performance threshold：手算 ranking cases 精确验证 metrics；fixed weights
验证 rank/tie/chunk/reload；tiny CPU train 只验证 finite loss、参数更新、best/last、reload 和完整 score coverage。
真实结果必须如实报告，但 “SASRec 必须超过 MostPop” 或某个 NDCG 数字不是代码正确性/Phase 3 completion gate。

### 11.4 Evaluation artifact boundary

每个 exact `(derived split, checkpoint/baseline, evaluation config)` 产生 immutable checksummed evaluation artifact，
而不是修改 checkpoint 或 Agent run：

```text
evaluation artifact
  ├── evaluation_manifest.json
  ├── aggregate_metrics.json
  └── per_target_outcomes.jsonl
```

Manifest 固定 source/P2/P3 derived refs、split/target/subset refs、ranker/checkpoint ref、candidate/filter/metric recipes、
K values、seed、schema/codec/evaluator versions、counts、payload checksums 和 execution provenance。Aggregate 同时保存
warm/cold coverage、metric sums/counts/means；per-target record 保存 sample/user/target/cutoff identity、warm/cold、
candidate count、target rank/miss reason 和 ordered Top-100 outcome，供审计并为后续 candidate handoff 提供确定事实。
它不保存 full-catalog score matrix，也不把 target label 作为 online Agent feature。

Multi-seed summary 是另一个只引用 exact per-seed evaluation refs 的 comparison artifact。所有 user/target/ranking
records 留在 Git 忽略的 local/external root；是否公开 aggregate 仍受 dataset license 约束。Agent run 继续严格只有
P3-07 三件套，不复制 evaluation artifact。

### 11.5 Dynamic Memory evaluation

Phase 3 Memory acceptance 使用 deterministic golden transitions 验证：stable reinforcement；unseen short → emerging；
repeated emerging → promotion；unmatched active long → fading/inactive；reactivation；empty long/short axes；same-time/
repeat/idempotency；cutoff/leakage；persistence/reload equivalence；drift boundary values；public `UserMemoryView` atom/
match/matrix/ref integrity。

真实 Tsinghua snapshot build 另外生成 aggregate audit，至少报告 semantic/Memory coverage、long-empty、stable/
emerging/fading、promotion/inactive、atom counts、cosine 和 drift distributions；它们是诊断，不设置自动调 threshold
或虚假的通过率。当前没有人工 stable/emerging/fading ground truth，因此 next-item gain、interest agreement、profile
freshness 和最终 Memory benchmark 留到 Phase 6。Fixture pass 和 real audit 都不能冒充 Memory 已有研究效果。

P3 `perception budget=0` 时没有 Phase 4/5 component 消费 Memory，故 `SASRec + loaded Dynamic Memory` 的初始 ranks
必须与同 checkpoint/同 candidates 的 SASRec ranks 一致；本阶段只证明 Memory 能正确进入 Recommendation State，
不声称它已经提高 NDCG。Information Need readiness 只验证 cutoff-safe View、Atom/drift/features/refs 可由后续
Segment Value/Need 读取，不提前定义其模型或 label。

### 11.6 Unit tests

- behavior loader/projection、derived split/vocabulary/prefix/repeat/negative/candidate semantics；
- exact metric formulas、macro aggregation、warm/cold denominators、full/dev separation 和 Top-100 handoff；
- future leakage、seen-target exception、history/candidate OOV 和 all-cold/empty subset failures；
- SASRec masking/causal behavior/loss/sampler/determinism/score/tie/chunk coverage；
- MostPop train-only counts、filtering 和 deterministic ties；
- checkpoint/config/version/identity/best-last/resume/corruption validation；
- Atom/text/embedding identity、normalization、missing-input 和 duplicate semantics；
- Memory matching/update/promotion/EMA/strength/persistence/inactive/reactivation/drift boundaries；
- snapshot idempotency、atomic persistence/reload、prefix/cutoff and public-view ref integrity；
- Phase 4 Information Need readiness/public-view-only consumption，不测试假 estimator；
- explicit device selection/unavailable-device failure 和 score/StopPolicy compatibility；
- evaluation artifact identity/bytes/refs/counts、multi-seed aggregation 和 no-label-as-feature boundary。

### 11.7 Integration/E2E tests

- synthetic P2 exact release → P3 derived dataset → warm/cold/dev evaluation records；
- tiny CPU fixture train → best/last checkpoint → reload → full candidate scores → evaluation artifact；
- fixture semantics/embeddings → Memory build/publish/reload → exact `UserMemoryView`；
- real Memory View → Information Need readiness contract validation；
- API/CLI semantic equivalence、exit codes、preflight/no-partial-publication；
- exact refs + real Memory + SASRec + persistent Stores → unchanged Controller zero-budget Agent run；
- budget-zero rank invariance、three Agent artifacts only 和 saved-output structural replay；
- corrupted/mismatched release/derived/semantic/checkpoint/memory/input/evaluation refs fail closed；
- all Phase 1/2 config/golden/replay/publication/persistent-Store regressions。

### 11.8 Quality gates

- local pytest 全部通过，整个 `pave_rec` package branch coverage 至少 `90%`，Ruff lint/format 通过；
- existing core CI matrix 保持 Ubuntu Python 3.10、Ubuntu Python 3.12、Windows Python 3.12；
- 增加 required Ubuntu Python 3.12 CPU-PyTorch job，安装 training extra 并执行真实 SASRec tiny train/checkpoint/
  reload/evaluate tests；普通 core matrix 仍不强制 Torch；
- BGE-M3/FlagEmbedding 真实模型不在 CI 下载，使用 `FixtureEmbeddingProvider` 测 contract；
- tests offline/CPU-only，不下载 dataset/pretrained model、不访问网络、不调用 GPU/MLLM/FFmpeg，不写仓库
  `data/`、`artifacts/` 或 `runs/`，所有写入只在 pytest `tmp_path` synthetic project；
- 真实 CUDA/BGE/Tsinghua commands 是独立 reproducible lifecycle，不成为普通 PR CI 前置条件；GPU smoke 在有稳定
  runner 前保持 local/manual evidence，不设 required public GPU job；
- local gates 与同一 candidate commit 的 project-wide remote CI 全部通过才可完成 Phase 3。

### 11.9 Phase 3 Definition of Done

- P3-00—P3-08 与 P3-XG-01 全部 Confirmed，stable docs、schemas 和 implementation 一致；
- exact pinned Tsinghua P2 release 可重建 immutable P3 derived/semantic artifacts；
- MostPop 和 SASRec 可独立 full-catalog evaluate，SASRec 可 train/select/save/load/resume/score，evaluation artifact
  可验证；
- Dynamic Memory 可由 exact cutoff 构建/update/publish/load/project，goldens 与真实 aggregate audit 完成；
- seed `20260804` 的真实 Tsinghua derive → semantics → SASRec → Memory → evaluate lifecycle 成功并固定 exact refs；
- unchanged Controller 完成 real-memory + real-ranker + persistent Stores 的 zero-budget run，初始 ranking 有效、
  `budget_exhausted`、attempted actions=0、三件套 canonical 且 replay 等价；
- P1/P2/P3 tests、goldens、replay、publication、path safety 和 persistent Stores 无回退；
- local quality gates 与同一 commit remote CI 全部通过，已知 research limitations/Deferred 项记录完整。

Phase 3 completion 不要求 SASRec 超过 MostPop，不要求三 seed paper table，也不要求真实 Information Need、Segment
Value、MLLM、MicroLens、BERT4Rec 或 cold-start recovery。三 seed 是 reportable stochastic result protocol；不阻塞
第一条 Agent Loop 和工程 DoD。

### P3-08 Decision Record

```text
Decision ID: P3-08
Status: Confirmed
Decision:
1. Single-target full-catalog warm ranking 使用 primary NDCG@10；secondary HR@10/NDCG@20/HR@20/MRR@10/
   Recall@100。指标按 per-user macro mean 精确定义；cold 不伪打分，另报 all-target coverage/counts。
2. Primary evaluation 排完整 train vocabulary，过滤 seen positives 并保留 repeated target 例外；不 sampled/
   target injection。P3-02 1+100 dev candidates 只用于 smoke/CI，不进 research results。
3. Full-catalog ordered Top-100 是后续 Agent item candidate handoff，Recall@100 测其 target ceiling；Phase 4/5 再
   缩到昂贵 Top-L item/segment search，不要求感知全部 100，也不与 101-candidate dev smoke 混淆。
4. Phase 3 minimum comparator 是 train-only MostPop 与 SASRec。首条真实 Agent/DoD 用 seed 20260804；正式随机
   ranker result 至少用 20260804/05/06 三 seed 报 mean±sample std，但不阻塞 Agent Loop/Phase 3 completion。
5. Fixture 只验证 metrics/train/checkpoint/rank/reload contracts，不设 research NDCG threshold；真实性能如实报告，
   “超过 MostPop”不是 implementation correctness gate。
6. 每个 exact evaluation 产生 immutable manifest/aggregate/per-target artifact，记录 Top-100 outcome 和 exact refs，
   不保存 full score matrix、不把 labels 暴露为 online features、不改变 Agent run 三件套。
7. Memory 用 exact transition goldens + 真实 aggregate audit 验收；无人工 ground truth 时不宣称 state/gain 效果。
   budget=0 时 loaded Memory 不改变 SASRec ranks，Information Need readiness 只验证 cutoff-safe public View。
8. Unit/integration/E2E 覆盖全部 P3 data/model/memory/runtime/evaluation/ref failure 和 P1/P2 regressions。
9. Quality gate 是 package branch coverage >=90%、Ruff、原三平台 core matrix，加 required Ubuntu 3.12 CPU-Torch
   job；CI offline/tmp-only，无真实 dataset/model/GPU/MLLM。真实 GPU/BGE/Tsinghua 是独立 reproducible lifecycle。
10. Phase 3 DoD 需要单 seed exact Tsinghua lifecycle、MostPop/SASRec evaluation、Memory audit、unchanged zero-budget
    Controller run/replay、全部 local/remote gates；三 seed论文表、完整 Agent、MicroLens/BERT4Rec/cold recovery 后置。
Rationale:
Full-catalog warm ranking 与单独 cold coverage 忠实反映 ID-only SASRec 的 ranking ability 和 retrieval ceiling；
Top-100 使后续 Agent 有明确 candidate handoff，但不把昂贵感知放大到全部 candidates。将 contract、单 seed real
pipeline 和三 seed reportable result 分层，可在不牺牲论文复现协议的情况下尽快打通 Agent Loop。Memory golden/
audit 分离避免把工程确定性误写为未知兴趣 ground truth。
Alternatives considered:
sampled candidates 作为主结果；target injection 替代 retrieval；只报 warm metrics/隐藏 cold；Recall@10 与 HR@10
重复列；full catalog 的全部 items 都进入 MLLM；把 101 dev pool 当 Top-100 handoff；Phase 3 同时实现全部 rankers；
要求三 seed/大调参先于 Agent Loop；用 tiny fixture NDCG 或必须胜过 MostPop 作为代码 gate；Memory fixture pass 冒充
真实效果；在普通 CI 下载 Torch/BGE/数据或要求 GPU；把 evaluation payload 复制进 Agent run。
P1/P2 compatibility evidence:
Evaluator/candidate handoff 在 Controller 外部，InitialRanker exact coverage/tie/OOV、P2 ordered facts/exact release、
P3 split/cutoff/checkpoint/Memory refs 均保持不变。Agent Controller/public schemas/三件套不修改；tests 继续沿用 P1/P2
offline/tmp-only、coverage、platform、publication/replay/path-safety gates。
Affected schemas/interfaces:
New internal strict Phase3EvaluationConfig, metric/outcome/evaluation-manifest/comparison schemas and evaluator APIs;
no Phase 1 public interface or Phase 2 release/Store schema change. P3-07 evaluate_from_config/CLI seam becomes active.
Affected docs/tests:
todo/phase_3_discussion.md；todo/benchmark_construction_proposal.md；todo/implementation_roadmap.md；
docs/02_sasrec_initial_ranking.md；docs/10_evaluation_and_training_plan.md；configs/README.md；all listed P3 unit/
integration/E2E/CI tests and complete P1/P2 regressions.
Resolved follow-up:
metric definitions/K/denominators、full-vs-dev candidates、seen/repeat/cold、Top-100 handoff、baseline/seeds、fixture-vs-
research boundary、evaluation artifact、Memory acceptance、test/CI matrix 和 Phase 3 DoD。
Deferred follow-up:
Phase 4/5 Top-L expensive shortlist/active metrics；Phase 5 Segment Value labels；Phase 6 final tuning budget、Memory
benchmark、three-seed full method tables/cold recovery/MicroLens；BERT4Rec/GRU4Rec；required public GPU CI。
Confirmed by: User
Date: 2026-08-04
```

---

## 12. P3-XG-01 — Cross-Gate Consistency Review

Status: `Confirmed`

### 12.1 Audit result

P3-00—P3-08 的 Decision Records、现有 P1/P2 code/docs 和 Phase 3 stable docs 已逐项交叉审计。没有发现需要
修改 P1 Controller/public schemas、P2 release/data plane 或阻止主体实现的 blocker：

| Cross-Gate invariant | Result | Evidence/implementation constraint |
| --- | --- | --- |
| P1 Controller/public interfaces | Pass | 真实 adapters 继续满足现有 `UserMemory`、`InitialRanker`、Stores 和 `AgentRunRequest`；Controller 不增加 role/branch/field |
| P2 exact release/data plane | Pass | 所有真实 source 先经 Tsinghua adapter → P2 processor/release；P3 artifacts 不回写 P2，复用 `LoadedRelease`/resolver/root/path/publication rules |
| Ordered fact and leakage | Pass | P2 `interaction_index` 是唯一顺序；leave-two-out、positive history 和 full-exposure exclusive cutoff 均显式固定；train/validation/test、Memory、sampler、evaluation 不读未来 |
| Version separation | Pass | `p2-...` data version、derived/semantic artifact refs、`p3ckpt-...`、`memory_version`、runtime/input/evaluation refs、descriptor/schema versions 各自独立 |
| Candidate/score contract | Pass | caller owns exact candidates；ranker full coverage、finite raw logits、`(-score,item_id)` ties、candidate OOV fail；seen/cold/Top-100 均在 evaluator/provider 外部处理 |
| Score/Stop compatibility | Pass | real score 未校准，`ranking_margin_threshold=null`；Mock `0.10` 不进入真实 runtime，zero-budget 先返回 `budget_exhausted` |
| Memory/ranker independence | Pass | SASRec ID embeddings 与 BGE semantic embeddings/Memory artifacts 分离，只在 `RecommendationState` 汇合；budget=0 loaded Memory 不改 ranks |
| Phase 4 readiness without preemption | Pass | Memory View 提供 atoms/matches/drift/refs；need vocabulary/formula、Top-L expensive shortlist、Segment Value/MLLM/Updater 仍由后续 Gate 决定 |
| Portable artifact/runtime boundary | Pass | tensors/large payloads 仅经 exact refs；physical paths/device/workers/timestamps/secrets 不进入 portable identity/public views；online Agent 不训练/切分/embed |
| Test/research/data boundary | Pass | fixtures 验证 contract，单 seed 打通真实 pipeline，三 seed才是可报告随机结果；CI offline/tmp-only，真实数据/模型/GPU 与 row-level outputs 留在 local/external roots |

### 12.2 Cross-Gate clarifications resolved

审计中消除了三处容易在实现时走错、但不需要修改公共接口的歧义：

1. **One public history tuple**：`AgentRunRequest.user_history` 固定为 exact cutoff 前完整、未 recent-50 截断的
   `positive_v1` item-ID projection。`AgentInputBundle` 增加 explicit projection recipe/hash；full-exposure cutoff
   identity 独立保存。Bootstrap 绑定 exact Memory snapshot，Memory 只验证 tuple/cutoff closure；SASRec 在内部
   OOV-filter/recent-50。禁止为 Memory 增加第二套 public history 或仅凭 tuple 猜 snapshot。
2. **Zero-budget media/segment feasibility**：P2 可以为无 media items 提供合法 empty `ItemSegmentCatalog`，但仍需
   item-level Store exact coverage。现有 StopPolicy 先检查 budget，因此 P3 `max_perception_actions=0` 在真实 State
   构建后确定返回 `budget_exhausted`；官方 1..100 media 足以独立做 media smoke，P4 positive-budget run 必须使用
   另行固定且 segment-complete 的 media subset。
3. **Two candidate counts**：P3-02/P3-07 `1 positive + 100 negatives = 101` 只用于 dev/CI/full-real-cheap smoke；
   P3-08 research path 是 full-catalog ranking 后的 ordered Top-100 Agent pool。二者 artifact recipe、用途、指标和
   label exposure 均不同；online Agent 不读取 target label，Phase 4/5 再确认昂贵 Top-L。

### 12.3 Version and ownership matrix

```text
P2 data_version
    → AgentRunResult.data_version and every P3 artifact provenance

P3 derived dataset ref
    → split / target / vocabulary / positive-history / full-exposure cutoff facts

P3 semantic artifact ref
    → semantic text + BGE recipe/vector inventory

SASRec checkpoint ID/ref
    → model/training/vocabulary/validation/weights identity

Memory artifact + memory_version
    → recipe/internal state/snapshot/user/projection/cutoff identity

ComponentDescriptor.version
    → implementation contract only; never an artifact version

AgentInput/runtime/evaluation refs
    → exact request, runtime graph and metric outcomes; never folded into p2 data_version
```

### 12.4 Current validation evidence and Windows path acceptance

2026-08-04 开始实现前，本地 Windows/Python 环境的 pure unit suite 为 `118 passed, 2 skipped`；完整 suite 曾为
`148 passed, 2 skipped, 18 failed`。18 个失败全部来自同一 P2 filesystem-publication `MAX_PATH` 边界，最长示例
为 `285` characters，没有 assertion/model/state regression。

Implementation 已关闭该 follow-up：portable `bundles/<data_version>/...`、完整 SHA-256 identity、
checksum 与 path-safety contract 保持不变；Windows physical staging 使用 deterministic 128-bit operational token，
trusted absolute storage roots 在实际 filesystem I/O 边界使用 extended-length path。原失败面定向测试为
`21 passed`；当前 short-basetemp 完整 suite 为 `275 passed, 2 skipped`，branch coverage `90.03%`，Ruff clean。
这关闭了 local Windows path、真实 lifecycle 与本地 quality gates；同一 candidate commit remote CI 仍须满足。

### 12.5 Authorization boundary

P3-XG-01 Confirmed 授权的 Phase 3 主体实现现已在本地完成，并遵守上述 constraints。它不授权提前实现
Phase 4/5/7、不授权发布受限数据/artifacts，也不表示 Phase 3 `Completed`。只有 P3-08 Definition of Done 的真实
single-seed Tsinghua lifecycle、zero-budget Agent/replay、Memory/evaluation artifacts、tests/coverage/Ruff 和同一
candidate commit remote CI 全部通过后，路线图才能从 `Local Implementation Complete / Remote CI Pending`
改为 `Completed`。

### P3-XG-01 Decision Record

```text
Decision ID: P3-XG-01
Status: Confirmed
Decision:
1. P3-00—P3-08 在 P1 interfaces/Controller、P2 release/Stores/resolver/path/publication 上一致，无 public-schema
   或 state-machine change，允许开始 Phase 3 主体实现。
2. P2 interaction_index/full-exposure cutoff 与 P3 positive split/history 是唯一时序链；vocabulary/sampler/Memory/
   checkpoint/evaluation 均禁止未来信息，test 不选择模型或参数。
3. data/derived/semantic/checkpoint/memory/component/schema/runtime/input/evaluation identities 保持独立，并通过
   exact full-SHA ResourceRefs/manifest closure 相连；AgentRunResult.data_version 只保留 P2 data version。
4. Public user_history 唯一固定为 cutoff 前完整 positive_v1 item projection；exact Memory snapshot/cutoff 由
   bootstrap 绑定，Memory 验证而不猜测，SASRec 内部 OOV-filter/recent-50，不增加第二套 public history。
5. Ranker 精确覆盖 caller candidates并返回 finite raw logits；tie/OOV/seen/cold 唯一。Real margin 不复用 Mock
   threshold。Full-catalog→Top-100 与 1+100=101 dev/smoke 是不同 artifacts/protocols。
6. SASRec/Memory 独立，只在 RecommendationState 汇合。Empty segment catalogs 对 zero-budget 合法，StopPolicy
   先 budget_exhausted；positive-budget media completeness 属于 Phase 4 subset/Gate。
7. P3 Memory public View 满足 Information Need/Segment Value feature readiness，但 need/value/MLLM/update/Top-L
   算法未提前确认；unavailable guards + zero budget 防止假 active path。
8. Tensor/paths/device/execution/secrets 不进入 public/portable schemas；offline lifecycle 与 online Agent 分离，
   real restricted data/artifacts 留在 local/external roots。
9. Contract fixture、single-seed real pipeline、three-seed reportable result 和 CI/real experiments 边界一致；P1/P2
   regressions 与 P3-08 quality/DoD gates 全部保留。
10. 当前状态是 Local Implementation Complete / Remote CI Pending，不是 Completed；Windows local full-suite
    path-length follow-up、真实 lifecycles 和本地 quality gates 已关闭，required remote CI 必须在完成前关闭。
Rationale:
逐项核对确认现有 P1/P2 seams 足以承载真实 Memory、SASRec、persistent Stores 和 zero-budget Controller run。
对 shared history、empty segment catalog 和两种 candidate count 的显式消歧，消除了实现时最可能导致接口扩张、
cutoff 误用或 benchmark 混表的风险，而无需改变任何 public contract。
Alternatives considered:
给 AgentRunRequest 增加 full-interaction/Memory history；让 Memory 从 tuple/latest 猜 snapshot；把 recent-50 回写
公共 history；要求 zero-budget candidates 全有 media；为 P3 改 Controller stop order；把 101 smoke 当 Top-100
research pool；复用 Mock threshold；合并 version fields；在 online Agent 训练/构建 artifacts；提前实现假 Phase4/5。
P1/P2 compatibility evidence:
Existing AgentRunRequest/UserMemory/InitialRanker/AgentComponents/RecommendationState/ThresholdStopPolicy/TraceWriter/
replay code already provides the required seams. P2 RootRegistry/FilesystemPathResolver/ReleaseLoader/persistent Stores and
publication contracts remain the only real data plane. Empty ItemSegmentCatalog is valid, and pre-value StopPolicy checks
zero budget before no-segment/InformationNeed.
Affected schemas/interfaces:
No existing public schema/interface changes. New internal P3 AgentInputBundle records history_projection_recipe/hash and
full-exposure cutoff separately; bootstrap binds exact Memory snapshot. All other P3 schemas/interfaces remain as confirmed.
Affected docs/tests:
todo/phase_3_discussion.md；todo/implementation_roadmap.md；README.md；configs/README.md；
docs/01_dynamic_hybrid_user_memory.md；docs/02_sasrec_initial_ranking.md；docs/08_agent_controller.md；all P3 cross-gate/
history-cutoff/snapshot/candidate/media/zero-budget/version/privacy tests, Windows long-path publication acceptance and
complete P1/P2 regressions.
Resolved follow-up:
All P3 decision gates；public positive-history vs full-exposure cutoff；exact snapshot selection；empty-segment zero-budget
feasibility；101 dev/smoke vs full-catalog Top-100；version ownership；implementation authorization boundary。
Deferred follow-up:
Phase 4 Information Need/real MLLM/residual updater/media-complete Top-L；Phase 5 Oracle/Segment Value；Phase 6 full
benchmark/tuning/Memory/cold/MicroLens；取得 Tsinghua processed recommendation package 后审计官方
`x_label=0/1/2` split 的 provenance、counts、overlap/cold coverage 与逐用户时间单调性，并据此决定它只用于
static MMRec reproduction 还是也可进入 sequential robustness track；Phase 7 learned fusion/stop/RL；external
data/artifact redistribution permission。
Resolved implementation follow-up:
Windows physical-path-length full-suite failure 已关闭，未缩短 portable full-SHA identity、未削弱 path safety；
定向 `21 passed`，当前完整 suite `275 passed, 2 skipped`，branch coverage `90.03%`，Ruff clean；真实 P3
lifecycles、evaluation、Memory audit 和 zero-budget replay 均已通过，remote required CI pending。
Confirmed by: User
Date: 2026-08-04
```

---

## 13. Phase 3 Discussion Order

按以下顺序推进，一次只处理一个 Gate：

1. `P3-00 Phase 1/2 Handoff and Compatibility Audit`
2. `P3-01 Target Dataset and Semantic Input Contract`
3. `P3-02 Versioned Derived Sequence Dataset`
4. `P3-03 Pluggable Initial Ranker and SASRec Training Baseline`
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
