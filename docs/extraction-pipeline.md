# 混合抽取与图谱更新管线

## 1. 设计目标

本项目不采用“全靠 LLM 自动建图”的方式，而采用**混合式图谱构建**：

```text
权威系统事件 → 直接写入
低歧义结构事实 → 规则/解析器抽取
高歧义叙事文本 → LLM 在严格 Schema 下抽取候选
候选结果 → Schema 校验 + 规则校验 + Scope 分流
```

目标：

- 降低 LLM 幻觉
- 保留证据链
- 支持低置信结果降级
- 区分 canonical / npc / rumor
- 让抽取结果可审计、可回滚、可重放

---

## 2. 输入类型

### 2.1 系统事件

来自规则引擎、UI、脚本、战斗系统、交易系统等。

特点：

```text
结构化
高权威
低歧义
可直接写入 canonical
```

示例：

```json
{
  "type": "TRANSFER_ITEM",
  "actor": "player",
  "item": "pass_token",
  "from": "player",
  "to": "guard_alos"
}
```

处理方式：

```text
直接规范化为 EventRecord + StateDelta
```

---

### 2.2 结构化文本日志

例如战斗日志、交易日志、任务日志。

特点：

```text
半结构化
可用规则/正则/解析器抽取
```

示例：

```text
[turn 12] 玩家向守卫阿洛斯出示通行令，守卫信任 +2。
```

处理方式：

```text
优先规则解析器
失败后交给 LLM 候选抽取
```

---

### 2.3 自然语言叙事

例如玩家输入、NPC 对话、旁白、小说文本。

特点：

```text
高歧义
隐含关系多
可能包含误会、传闻、主观判断
```

示例：

```text
守卫皱着眉看向玩家，似乎仍怀疑他和昨晚的盗贼有关。
```

处理方式：

```text
LLM 抽取候选
默认不直接进入 canonical
根据证据、规则、scope 判断写入 npc memory / rumor / canonical
```

---

## 3. 管线流程

```text
玩家输入 / 系统日志 / 叙事文本
        ↓
Event Normalizer
        ↓
规则解析器 + LLM 候选抽取
        ↓
Schema Validator
        ↓
Entity Resolver
        ↓
Rule Validator
        ↓
Conflict Resolver
        ↓
Scope Router
        ↓
EventLog 写入
        ↓
WorldGraph / MemoryGraph / Vector Memory 物化
```

---

## 4. LLM 抽取职责边界

LLM 负责：

```text
从文本中提出候选节点
从文本中提出候选关系
识别可能事件
识别主观记忆、谣言、误会
提取 evidence span
给出 confidence
```

LLM 不负责：

```text
直接修改 canonical 状态
直接决定行动是否合法
直接覆盖旧事实
直接把 rumor 变成 world truth
```

---

## 5. 抽取提示模板

```text
你是“游戏世界图谱抽取器”。请从输入文本中抽取：
1. nodes：实体节点，类型只能来自给定 schema
2. edges：实体关系
3. events：事件记录
4. state_deltas：可执行状态变化
5. memories：主观记忆、谣言、误会或角色认知

要求：
- 只能输出 JSON
- 不确定时设置 uncertain=true，并降低 confidence
- 每一条结果必须带 evidence span
- 若文本表达的是角色主观看法，不要写入 canonical，写入 npc 或 rumor scope
- 若出现与 canonical 冲突的事实，不要覆盖，写入 conflict 字段
- 不要发明输入中没有证据的实体和关系

输入文本：
{{text}}

已有 schema：
{{schema}}

已有上下文实体：
{{entity_candidates}}

当前世界状态摘要：
{{state_summary}}
```

---

## 6. 抽取输出格式

```json
{
  "source_id": "turn_128",
  "nodes": [
    {
      "tmp_id": "c1",
      "entity_type": "Character",
      "stable_key": "guard_alos",
      "properties": {"name": "阿洛斯"},
      "scope": "canonical",
      "confidence": 0.94,
      "uncertain": false,
      "evidence": {
        "source_id": "turn_128",
        "span": [0, 2],
        "text": "阿洛斯"
      }
    }
  ],
  "edges": [
    {
      "src": "guard_alos",
      "rel_type": "SUSPECTS",
      "dst": "player",
      "properties": {"reason": "盗贼传闻"},
      "scope": "npc",
      "owner_id": "guard_alos",
      "confidence": 0.76,
      "evidence": {
        "source_id": "turn_128",
        "span": [6, 21],
        "text": "似乎仍怀疑他和昨晚的盗贼有关"
      }
    }
  ],
  "events": [],
  "state_deltas": [],
  "memories": [
    {
      "owner_id": "guard_alos",
      "memory_text": "守卫怀疑玩家和昨晚的盗贼有关。",
      "truth_scope": "npc",
      "salience": 0.6,
      "valence": -0.3,
      "confidence": 0.76,
      "evidence": {
        "source_id": "turn_128",
        "span": [6, 21]
      }
    }
  ],
  "conflicts": []
}
```

---

## 7. Schema Validator

校验内容：

```text
entity_type 是否存在
rel_type 是否存在
scope 是否合法
required fields 是否完整
confidence 是否在 0-1
evidence span 是否存在
state_delta attr 是否允许
```

失败处理：

```text
硬错误 → 丢弃或进入 review queue
软错误 → 降低 confidence
```

---

## 8. Entity Resolver

实体消歧规则：

```text
1. stable_key 精确匹配优先
2. name + type + location 匹配
3. alias 匹配
4. LLM 辅助消歧
5. 低置信时创建 provisional entity
```

禁止：

```text
在证据不足时强行合并实体
```

临时实体示例：

```text
unknown_guard_001
mysterious_black_stone_001
```

后续可通过 `MERGE_ENTITY` 事件合并。

---

## 9. Rule Validator

规则校验用于判断候选事实是否能进入 canonical。

校验示例：

```text
玩家是否真的拥有该物品？
NPC 是否位于同一地点？
该规则是否允许此行动？
这个事件是否来自权威系统日志？
谣言是否被误写成 canonical？
```

结果：

```text
pass → 可进入 canonical 或对应 scope
fail → 降级为 candidate / rumor / rejected
needs_review → 等待人工或后续证据
```

---

## 10. Conflict Resolver

### 10.1 事实冲突

已有 canonical：

```text
钥匙持有者 = 玩家
```

新候选：

```text
钥匙持有者 = 守卫
```

如果新候选来自系统事件：

```text
生成 TRANSFER_ITEM 事件并更新状态
```

如果新候选来自传闻：

```text
写入 rumor，不覆盖 canonical
```

### 10.2 主观冲突

NPC A 认为玩家偷了钥匙，NPC B 认为玩家没有偷。

处理方式：

```text
两条都保留在各自 npc scope
不修改 canonical
```

### 10.3 权威级别

从高到低：

```text
系统事件
设计器编排
规则引擎推导
玩家/NPC 明确行动
叙事文本暗示
谣言
模型推测
```

---

## 11. Scope Router

根据来源和语义把候选事实分流。

```text
系统结算 → canonical
玩家实际行动 → canonical 或 player-known
NPC 亲眼所见 → npc memory + canonical evidence
NPC 猜测 → npc scope
多人传闻 → rumor
未知来源 → candidate
```

示例：

```text
“守卫怀疑玩家偷了钥匙”
→ npc.guard SUSPECTS player
→ 不改变 canonical

“玩家从桌上拿起钥匙”
→ canonical TRANSFER_ITEM / MOVE_ENTITY

“村里都说玩家偷了钥匙”
→ rumor
```

---

## 12. Confidence 计算

不要只靠模型自报。

建议合成：

```text
confidence =
  0.30 * schema_score
+ 0.25 * rule_score
+ 0.20 * source_authority
+ 0.15 * self_consistency
+ 0.10 * evidence_quality
```

各项说明：

```text
schema_score：是否完全符合 schema
rule_score：是否通过规则校验
source_authority：来源权威程度
self_consistency：多次抽取是否一致
evidence_quality：证据 span 是否明确
```

阈值建议：

```text
>= 0.85：可进入 canonical，前提是 rule_pass
0.60 - 0.85：进入 npc / rumor / candidate
< 0.60：丢弃或人工审查
```

---

## 13. EvidenceRef

所有抽取结果必须绑定证据。

```json
{
  "source_id": "turn_128",
  "source_type": "player_input",
  "span_start": 6,
  "span_end": 21,
  "text": "似乎仍怀疑他和昨晚的盗贼有关",
  "extractor": "llm_extractor_v1",
  "confidence": 0.76
}
```

用途：

- 审计
- 回滚
- 错误修正
- NPC 解释
- 玩家查询“为什么系统这么判断”

---

## 14. 图谱更新策略

### 14.1 进入 canonical 的条件

必须同时满足：

```text
schema_pass
rule_pass
confidence >= threshold
scope == canonical
有 evidence
不与高权威事实冲突
```

### 14.2 进入 memory 的条件

满足：

```text
是角色主观认知
有 owner_id
有 source_event 或 evidence
```

### 14.3 进入 rumor 的条件

满足：

```text
来源不权威
表达为传闻/猜测/流言
影响 NPC 行为但不改变世界真相
```

---

## 15. 更新事务流程

本地 MVP：

```text
BEGIN TRANSACTION
1. 写 source 文本
2. 写 extraction candidates
3. 写 validated events
4. 写 state_deltas
5. 更新 states
6. 更新 nodes/edges
7. 写 memories/evidence_refs
COMMIT
```

如果任一步失败：

```text
ROLLBACK
```

---

## 16. 抽取器分层

### 16.1 SystemEventExtractor

处理结构化系统事件。

### 16.2 RuleBasedExtractor

处理半结构化日志。

### 16.3 LLMExtractor

处理自然语言。

### 16.4 Verifier

统一验证候选结果。

### 16.5 ScopeRouter

分流到 canonical / npc / rumor / candidate。

---

## 17. 测试用例

### 17.1 谣言不污染真值

输入：

```text
村里有人说玩家偷了钥匙。
```

预期：

```text
写入 rumor
不改变 canonical: key.holder
```

### 17.2 主观怀疑进入 NPC 记忆

输入：

```text
守卫怀疑玩家和盗贼有关。
```

预期：

```text
写入 npc.guard SUSPECTS player
不改变 canonical
```

### 17.3 明确行动进入事件

输入：

```text
玩家把通行令递给守卫。
```

预期：

```text
TRANSFER_ITEM event
pass_token holder: player -> guard
```

### 17.4 规则拦截非法事实

输入：

```text
玩家用并不存在的银钥匙打开铁门。
```

如果玩家没有银钥匙：

```text
拒绝 canonical 状态变化
生成 invalid_action 或 failed_action
```

### 17.5 低置信实体不强合并

输入：

```text
一个穿黑斗篷的人站在门口。
```

预期：

```text
创建 provisional entity
不强行合并到已知 NPC
```

---

## 18. MVP 简化建议

第一版先实现：

```text
SystemEventExtractor
LLMExtractor
SchemaValidator
RuleValidator
ScopeRouter
EvidenceRef
```

暂缓：

```text
复杂 self-consistency
人工审查队列 UI
实体合并工作流
多模型投票
异步 outbox
```

但数据结构必须预留这些字段。
