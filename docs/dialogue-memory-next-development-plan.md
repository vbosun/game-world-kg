# NPC 对话长期 Memory Graph 下一步开发计划

## 1. 背景与当前结论

当前代码已经实现了本地方案的主体骨架：

```text
SQLite EventLog / StateDelta / outbox
KuzuStore / KuzuProjector
ChromaStore / ChromaProjector
NPC dialogue API
DialogueMemoryPipeline
memory_ops / review_queue
source_texts / conversation_segments
scope_key / layer / memory_kind
```

这说明项目已经从“世界 KG MVP”进入了“NPC 对话记忆治理”阶段。

但按照最新研究报告，NPC 对话不应该直接变成“事实库”或“单条记忆摘要”。正确方向是：

```text
Conversation Log
→ Segment / EDU
→ Episodic Memory
→ Semantic Memory Candidate
→ Belief / Rumor / Misremembering
→ Governed Consolidation
→ Canonical truth only by authority/validation
```

核心原则：

> conversation log 必须作为不可变证据保存；LLM 只能生成带证据的候选 memory operation；canonical truth 与 subjective memory 必须隔离。

---

## 2. 当前实现审查

### 2.1 已完成的关键能力

#### 三存储依赖已经接入

`pyproject.toml` 已加入：

```text
chromadb
kuzu
numpy
httpx
```

说明项目已经按本地方案进入 SQLite + Kuzu + Chroma 架构。

#### SQLite 已经承担真值源

当前 `EventLog.append()` 会写入：

```text
events
state_deltas
evidence_refs_json
causal_parents_json
outbox
```

并根据事件类型写入：

```text
kuzu_graph_update
chroma_event_upsert
chroma_memory_upsert
chroma_evidence_upsert
```

这符合“SQLite EventLog 是 source of truth，Kuzu/Chroma 是物化视图”的方向。

#### conversation log 到 memory operation 已开始落地

`DialogueMemoryPipeline.process_npc_dialogue()` 已经完成：

```text
1. 保存 source_text
2. 切分 conversation_segments
3. 构建 MemoryOp
4. 校验 memory op
5. 非法 op 进入 review_queue
6. 合法 op 追加 ADD_MEMORY 事件
7. StateProjector 应用事件
```

这是正确方向。

#### canonical 防污染已初步实现

`DialogueMemoryPipeline._validate_op()` 已阻止：

```text
scope_key == canonical
layer == canonical
```

并且无 evidence 的操作进入 review。这符合研究报告强调的：

```text
对话不能直接写 canonical truth
无证据不得固化为长期记忆
```

#### API 已暴露记忆治理入口

当前 API 已有：

```text
POST /v1/conversation/turn
GET /v1/memory/query
GET /worlds/{world_id}/memory/ops
GET /worlds/{world_id}/memory/review
GET /worlds/{world_id}/chroma/search/memories
GET /worlds/{world_id}/chroma/search/evidence
```

说明基础调试与审查入口已经具备。

---

### 2.2 当前主要不足

#### 问题 1：segment 仍是 turn-level 二分，不是真正 EDU/事件命题分段

当前 `_segment_dialogue()` 只把对话拆成：

```text
player question segment
npc answer segment
```

这只是 turn-level segmentation，不是研究报告建议的：

```text
topical segment
event-centric EDU
claim-level proposition
```

风险：

```text
1. 一段 NPC 回答里多个事件/传闻/纠正会被混成一条记忆
2. 无法对单个 claim 做证据、冲突和衰减
3. dedup / supersedes 很难做准
```

下一步必须引入：

```text
ConversationSegmenter
EDUBuilder
ClaimExtractor
```

---

#### 问题 2：MemoryOp 生成仍偏规则样例，不是真正 LLM + 规则混合抽取

当前 `_build_ops()` 主要生成：

```text
ADD_MEMORY: 玩家曾向我询问...
FLAG_RUMOR: 简单 rumor heuristic
```

这还不是完整的 memory op 抽取器。

研究报告要求抽取：

```text
observation
self_report
hearsay
speculation
correction
preference
relationship_signal
promise
quest_hint
misremembering
```

并根据类型路由到：

```text
episodic
semantic_candidate
npc_belief
rumor
review
```

---

#### 问题 3：episodic / semantic / belief / rumor 分层字段有了，但演化逻辑不足

当前 `memories` 已有：

```text
layer
memory_kind
scope_key
valid_from_turn
valid_to_turn
supersedes_memory_id
merged_from_json
salience
valence
confidence
```

字段基本够用，但缺少：

```text
SemanticConsolidator
BeliefUpdater
RumorPropagation
MisrememberingModel
Correction/Supersedes resolver
Decay scheduler
Dedup/Merge policy
```

也就是说，schema 已经准备好，但生命周期管理还没完整实现。

---

#### 问题 4：KuzuStore 目前有 native schema，但查询主要仍用内存 fallback

`KuzuStore.init_schema()` 已定义：

```text
Entity
EventNode
MemoryNode
RELATES
EVENT_TARGETS
EVENT_CAUSED_BY
EVENT_CHANGED
REMEMBERS
MEMORY_ABOUT
MEMORY_FROM_EVENT
```

但 `upsert_entity/upsert_relation/upsert_event/upsert_memory/query_neighbors/query_current_graph` 仍主要操作 Python dict/list。

这意味着：

```text
Kuzu DB 创建了，但没有真正执行 Cypher upsert/query 路径
```

下一步要让 native Kuzu 成为主路径，fallback 只用于无依赖测试。

---

#### 问题 5：Chroma 已接入，但 embedding 仍是 mock hash

当前 ChromaStore 使用：

```text
_mock_embedding(text)
```

可以支撑测试，但不能验证真实语义检索效果。

下一步要支持：

```text
mock embedding: 单测
OpenAI-compatible embedding: bge-m3 本地服务
```

并且要把 query 评估纳入指标。

---

#### 问题 6：幻觉防固化目前只有基础规则，还没有完整治理指标

已有：

```text
missing evidence → review
canonical write → review
unknown op → review
```

还缺：

```text
unsupported_claim_rate
canonical_contamination_rate
stale_conflict_miss_rate
provenance_coverage
abstain_rate
review_resolution_rate
```

这些应该变成 evaluation 和 pytest 的硬指标。

---

## 3. 下一阶段目标

阶段名：

```text
Beta 1：Governed NPC Dialogue Memory Graph
```

目标：

> 把当前 NPC dialogue memory pipeline 从“保存对话问答记忆”升级为“conversation log → segment/EDU → episodic memory → semantic/belief/rumor 候选 → 治理化长期 memory graph”的完整链路。

完成后应具备：

```text
1. 对话全文不可变保存
2. 细粒度 segment / EDU / claim 抽取
3. episodic memory 与 semantic memory 分层
4. belief / rumor / misremembering 可表示、可传播、可纠正
5. LLM 不能固化幻觉为 canonical
6. salience / decay / dedup / consolidation 可运行
7. Kuzu 真正承载 memory graph 查询
8. Chroma 真正承载长文本语义记忆检索
9. evaluation 能检测污染、错记、过期和越权知识
```

---

## 4. 目标架构

```text
POST /v1/conversation/turn
        ↓
SQLite: ConversationTurnAdded event
        ↓
ConversationSegmenter
        ↓
EDUBuilder / ClaimExtractor
        ↓
MemoryOpGenerator
        ↓
SchemaValidator
        ↓
EvidenceLinker
        ↓
CanonicalGuard
        ↓
ConflictResolver
        ↓
MemoryGovernor
        ↓
SQLite: memory_ops + ADD_MEMORY / FLAG_RUMOR / CORRECT_MEMORY events
        ↓
KuzuProjector: typed memory graph
        ↓
ChromaProjector: segment / episode / memory vector index
        ↓
NPCDialogue: scoped recall + belief-aware answer
```

---

## 5. 数据模型补充

### 5.1 conversation_turns

当前 `turns` 可以继续使用，但为了对话长期记忆，建议增加独立表：

```sql
CREATE TABLE IF NOT EXISTS conversation_turns (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    speaker_id TEXT NOT NULL,
    listener_ids_json TEXT NOT NULL DEFAULT '[]',
    raw_text TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'npc_dialogue',
    created_at TEXT NOT NULL
);
```

用途：

```text
保留原始 utterance
支持多说话者
支持谁听到了这句话
支持 rumor propagation 的 heard_by 边
```

---

### 5.2 conversation_segments 扩展

当前已有 `conversation_segments`，建议增加：

```sql
ALTER TABLE conversation_segments ADD COLUMN edu_type TEXT DEFAULT 'statement';
ALTER TABLE conversation_segments ADD COLUMN topic_key TEXT;
ALTER TABLE conversation_segments ADD COLUMN claim_count INTEGER DEFAULT 0;
ALTER TABLE conversation_segments ADD COLUMN salience_hint REAL DEFAULT 0.0;
```

`edu_type` 可选：

```text
question
answer
observation
self_report
hearsay
speculation
correction
promise
preference
relationship_signal
quest_hint
```

---

### 5.3 memory_claims

新增 claim 级表，解决“一个 segment 多条 claim”的问题。

```sql
CREATE TABLE IF NOT EXISTS memory_claims (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    segment_id TEXT NOT NULL,
    speaker_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    scope_key TEXT NOT NULL,
    layer TEXT NOT NULL,
    claim_type TEXT NOT NULL,
    subject_id TEXT,
    predicate TEXT,
    object_id TEXT,
    claim_text TEXT NOT NULL,
    normalized_key TEXT NOT NULL,
    certainty TEXT NOT NULL DEFAULT 'unknown',
    confidence REAL NOT NULL DEFAULT 0.5,
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'candidate',
    created_at TEXT NOT NULL
);
```

claim_type：

```text
episode
semantic_candidate
belief
rumor
misremembering
correction
preference
relationship_signal
```

certainty：

```text
observed
self_report
hearsay
speculation
inferred
corrected
contradicted
```

---

### 5.4 memory_consolidations

用于记录 episodic → semantic 的合并过程。

```sql
CREATE TABLE IF NOT EXISTS memory_consolidations (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    output_memory_id TEXT NOT NULL,
    input_memory_ids_json TEXT NOT NULL,
    consolidation_type TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    reason TEXT,
    created_turn INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
```

consolidation_type：

```text
dedup_merge
semantic_generalization
belief_update
rumor_strengthen
rumor_corrected
misremembering_detected
```

---

### 5.5 memory_edges / Kuzu 关系语义

Kuzu 中 memory graph 应至少支持：

```text
SUPPORTS
CONTRADICTS
SUPERSEDES
MERGED_FROM
HEARD_FROM
CORRECTED_BY
DERIVED_FROM
RECALLED_IN
```

这些关系比普通三元组更重要，因为长期 NPC 记忆的关键是演化链，不是当前一句摘要。

---

## 6. 模块开发计划

## Phase 1：Conversation Ledger 完整化

目标：对话全文可作为不可变证据账本。

任务：

```text
1. 新增 conversation_turns 表
2. NPC dialogue 时保存 player utterance 与 NPC answer 两条 conversation_turn
3. 每条 conversation_turn 绑定 source_event_id
4. source_texts 继续保留拼接全文，但不替代 conversation_turn
5. Chroma world_sources 写入 turn-level 与 segment-level 两种文档
```

验收：

```text
POST /v1/conversation/turn 后：
- turns 有记录
- events 有 NPC_DIALOGUE
- conversation_turns 有 player/npc utterance
- source_texts 有全文证据
- Chroma 可检索对应原文
```

---

## Phase 2：Segment / EDU / Claim 抽取

目标：从 turn-level 进入 event-centric memory unit。

任务：

```text
1. 新增 ConversationSegmenter
2. 支持规则分段：句号、问答、引用、转折、传闻关键词
3. 新增 EDUClassifier
4. 新增 ClaimExtractor
5. memory_claims 入库
6. 每条 claim 必须有 evidence span
```

第一版可以规则为主：

```text
听说/据说/有人说 → hearsay / rumor
我记得/我看到 → observed / episodic
可能/似乎/大概 → speculation
不是/其实/刚才说错了 → correction
喜欢/讨厌/习惯 → preference
答应/承诺/保证 → promise
```

第二版再加 LLM extractor。

验收：

```text
一段 NPC 回答包含 3 个 claim 时，memory_claims 应有 3 条，而不是 1 条混合记忆。
```

---

## Phase 3：Governed MemoryOpGenerator

目标：MemoryOp 不再只记录“玩家问过什么”，而是从 claim 生成治理化操作。

任务：

```text
1. MemoryOpGenerator 从 memory_claims 生成 ops
2. ADD_MEMORY：普通 episodic memory
3. FLAG_RUMOR：hearsay / low authority
4. UPDATE_MEMORY：同一 claim_key 重复加强
5. MERGE_MEMORY：重复 claim 合并
6. CORRECT_MEMORY：correction claim 纠正旧 claim
7. REVIEW：无证据、低置信、canonical 冲突
```

路由规则：

```text
observed + npc owner → episodic / npc_belief
hearsay → rumor
self_report → semantic_candidate 或 npc_belief
correction → CORRECT_MEMORY
speculation → uncertain / review
canonical conflict → review 或 rumor，不覆盖 canonical
```

验收：

```text
- hearsay 不进入 canonical
- correction 能生成 CORRECT_MEMORY
- low confidence 进入 review_queue
- 无 evidence 必须 review
```

---

## Phase 4：Dedup / Merge / Supersedes

目标：让长期记忆不无限膨胀，也不粗暴覆盖。

任务：

```text
1. normalized_key 生成器
2. embedding similarity 检查
3. exact duplicate merge
4. semantic duplicate merge
5. conflicting value supersedes
6. memory_consolidations 写入
7. Kuzu 写 MERGED_FROM / SUPERSEDES / CONTRADICTS
```

推荐规则：

```text
same normalized_key + similarity > 0.92 → MERGE_MEMORY
same fact_key + different object/value → CONTRADICTS 或 SUPERSEDES
correction claim 指向旧 claim → CORRECT_MEMORY
```

验收：

```text
同一 NPC 反复听到“银钥匙在井边”的传闻，应该增强同一 rumor，而不是产生 10 条重复 memory。
```

---

## Phase 5：Salience / Decay / Recall Update

目标：实现记忆强度随时间和回忆变化。

任务：

```text
1. MemoryStrengthCalculator
2. salience 初始化
3. decay 计算
4. recall_count / last_recalled_turn 更新
5. rumor 快衰减，semantic 慢衰减，canonical 不衰减
6. GET /v1/memory/query 返回 effective_strength
```

推荐公式：

```text
salience = sigmoid(
  valence*w1 + involvement*w2 + repetition*w3 + impact*w4 + authority*w5 + novelty*w6
)

strength(t) = salience * exp(-lambda_scope * age)
              * (1 + beta * recall_count)
              * (1 - duplicate_penalty)
```

scope decay 建议：

```text
canonical: 0
semantic: slow
npc_belief: medium
rumor: fast
uncertain: very_fast
```

验收：

```text
- 被 NPC 最近引用的记忆排名上升
- 长时间未验证的 rumor 排名下降
- semantic memory 比 episodic 更稳定
```

---

## Phase 6：Kuzu Native Memory Graph

目标：Kuzu 真正承载 memory graph，而不是只作为 fallback wrapper。

任务：

```text
1. KuzuStore.upsert_entity 执行 Cypher MERGE/CREATE
2. KuzuStore.upsert_memory 执行 MemoryNode 写入
3. KuzuStore.upsert_relation 执行 RELATES 写入
4. 增加 SUPPORTS / CONTRADICTS / SUPERSEDES / HEARD_FROM 等关系表
5. query_neighbors 使用 Cypher 查询
6. query_memory_evolution(memory_id)
7. query_beliefs(owner_id, topic)
8. query_rumor_spread(claim_key)
```

验收：

```text
GET /worlds/{world_id}/kuzu/graph 返回 backend=kuzu，且数据来自 Kuzu 查询而非内存 dict。
```

---

## Phase 7：Chroma Real Embedding + Scoped Retrieval

目标：让 Chroma 检索成为 NPC 对话的真实长期记忆来源。

任务：

```text
1. EmbeddingClient 支持 OpenAI-compatible embeddings
2. mock embedding 仅用于 test
3. world_sources 写 turn/segment 文档
4. world_memories 写 episodic/semantic/belief/rumor 文档
5. 检索必须带 world_id + owner_id + scope_key filter
6. roleplay mode 只返回该 NPC 可知记忆
7. dev mode 可返回全部证据与 scope
```

验收：

```text
- NPC 不能检索到其他 NPC 私有记忆
- dev mode 可以看到 scope 与证据
- bge-m3 服务启用后，语义近似问题能召回相关 memory
```

---

## Phase 8：Anti-Hallucination Evaluation

目标：把研究报告指标固化为测试。

新增指标：

```text
provenance_coverage
unsupported_claim_rate
canonical_contamination_rate
stale_conflict_miss_rate
abstain_rate
review_rate
rumor_correction_rate
npc_privileged_knowledge_rate
memory_dedup_rate
```

测试场景：

```text
1. 无证据 claim → review
2. NPC 说“我听说钥匙在井边” → rumor，不改 canonical
3. NPC 后来承认“我记错了” → CORRECT_MEMORY
4. 玩家私下藏钥匙，守卫不知道 → 守卫问答不得泄露
5. 同一传闻重复 5 次 → merge/reinforce，不生成 5 条独立记忆
6. 旧记忆与新纠正冲突 → SUPERSEDES 或 CORRECTED_BY
```

验收阈值：

```text
provenance_coverage = 100%
canonical_contamination_rate = 0%
npc_privileged_knowledge_rate <= 5%
unsupported_claim_rate <= 5%
stale_conflict_miss_rate <= 10%
memory_dedup_rate >= 80%
```

---

## 7. API 扩展计划

新增：

```text
GET /worlds/{world_id}/conversation/turns
GET /worlds/{world_id}/conversation/segments
GET /worlds/{world_id}/memory/claims
GET /worlds/{world_id}/memory/consolidations
POST /worlds/{world_id}/memory/consolidate
POST /worlds/{world_id}/memory/decay
GET /worlds/{world_id}/memory/evolution/{memory_id}
GET /worlds/{world_id}/memory/rumor-spread/{claim_key}
GET /worlds/{world_id}/memory/beliefs/{owner_id}
GET /worlds/{world_id}/evaluation/memory-governance
```

模式区分：

```text
roleplay mode：只给 NPC 可知内容，不暴露系统真相
dev mode：返回 evidence、scope、confidence、conflict chain
```

---

## 8. 推荐 Codex Issue 顺序

### Issue 1：Add conversation_turns and claim-level memory schema

验收：

```text
conversation_turns / memory_claims / memory_consolidations 表存在
NPC dialogue 写入 player/npc utterance
pytest 覆盖原文不可变保存
```

---

### Issue 2：Implement segment/EDU/claim extraction pipeline

验收：

```text
一个 NPC answer 中多个 hearsay/correction/preference 可拆成多个 claim
每个 claim 有 evidence span
无 evidence 进入 review
```

---

### Issue 3：Implement governed MemoryOpGenerator

验收：

```text
hearsay → FLAG_RUMOR
observed → ADD_MEMORY episodic
correction → CORRECT_MEMORY
canonical conflict → review
```

---

### Issue 4：Implement dedup/merge/supersedes/consolidation

验收：

```text
重复传闻 merge
冲突记忆产生 CONTRADICTS/SUPERSEDES
memory_consolidations 有记录
```

---

### Issue 5：Implement salience/decay/recall strength

验收：

```text
/v1/memory/query 返回 effective_strength
rumor 衰减快于 semantic
recall 更新 last_recalled_turn
```

---

### Issue 6：Make Kuzu native graph path real

验收：

```text
KuzuStore 写入和查询使用 Cypher
backend=kuzu 时不依赖内存 dict
支持 memory evolution / rumor spread 查询
```

---

### Issue 7：Add real embedding client for Chroma

验收：

```text
支持 mock 与 OpenAI-compatible embedding
world_sources/world_memories 有 scope metadata
owner_id filter 严格生效
```

---

### Issue 8：Add memory governance evaluation suite

验收：

```text
canonical_contamination_rate = 0%
provenance_coverage = 100%
npc_privileged_knowledge_rate <= 5%
pytest + /evaluation 均可查看
```

---

## 9. 不建议现在做的事

暂时不要做：

```text
1. 让 NPC 自动行动大规模自运行
2. 世界生成器
3. 复杂 UI
4. 多人联网
5. 生产级 Postgres/Neo4j/Qdrant 迁移
```

当前阶段最重要的是：

> 把 NPC 对话记忆这条链做可靠。否则后续世界自运行会被错误记忆、幻觉和谣言污染拖垮。

---

## 10. 完成标准

Beta 1 完成后，应能演示：

```text
玩家与守卫、酒馆老板、商人连续对话 30 回合；
系统保留全部原始对话；
每条长期记忆都能追溯到 segment span；
NPC 可以听信传闻，也可以被纠正；
谣言不会污染 canonical；
重复记忆会合并，旧记忆会衰减；
Kuzu 能查询记忆演化链；
Chroma 能按 owner/scope 召回相关记忆；
评估能量化 unsupported claim、canonical contamination、privileged knowledge。
```

这一步完成后，项目才真正具备“长期运行的 NPC 记忆系统”。

下一阶段再进入：

```text
Beta 2：WorldSpec 小世界生成器 + NPC 自运行
```
