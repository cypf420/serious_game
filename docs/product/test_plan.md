# 严肃游戏测试文档

## 1. 测试目标

本文档定义严肃游戏从剧本生成器升级为可运行模拟游戏后的测试方案。测试目标是保证：

- 剧本持续更新不会破坏运行时。
- 系统结算准确。
- LLM NPC 能根据角色规则输出结构化指标变化。
- 存档和读档一致。
- 账号登录和存档归属正确。
- 夜间推演可复现。
- 前端能够完成一局游戏。
- 行为数据可用于复盘和研究。

## 2. 测试范围

### 2.1 包含

- 领域模型校验。
- 白天行动服务。
- 行动合法性检查。
- NPC 指标评估。
- 事件触发。
- 夜间推演。
- 存档读档。
- 账号登录。
- NPC 记忆。
- NPC 对话约束。
- 结局判定。
- API 接口。
- 前端基础流程。
- 剧本包兼容性。
- 数据导出。

### 2.2 暂不包含

- 大规模并发压测。
- 移动端兼容。
- 真实多人实时协作。
- 语音识别和语音合成。
- 复杂图形性能测试。

## 3. 测试分层

```text
单元测试
  ↓
服务集成测试
  ↓
API 测试
  ↓
前端端到端测试
  ↓
剧本回归测试
  ↓
人工试玩验收
```

## 4. 单元测试

### 4.1 GameState

测试文件：

```text
tests/test_game_state.py
```

测试点：

- `day` 不能小于 1。
- `total_households` 必须大于 0。
- 指标必须在 0-100。
- `days_left` 不能为负。
- 预算可以在超支测试中为负，但要触发事件。

### 4.2 NPCState

测试文件：

```text
tests/test_npc_state.py
```

测试点：

- `npc_id` 不能为空。
- `npc_type` 只能为 `cadre`、`external`、`villager`。
- 信任、态度、焦虑、阈值在 0-100。
- `known_info` 和 `player_promises` 默认不共享引用。

### 4.3 GameActionRule

测试文件：

```text
tests/test_game_action_rule.py
```

测试点：

- `action_id` 不能为空。
- 行动点消耗不能为负。
- 预算消耗允许为 0。
- `direct_payoff` 能承载临时扩展字段。

## 5. 白天行动服务测试

测试文件：

```text
tests/test_action_service.py
```

### 5.1 入户走访

初始：

- `GameState.action_points = 3`
- 目标 NPC：杨德清，`trust_to_player = 40`

执行：

- `home_visit`

期望：

- 行动点变为 2。
- `ActionService` 只结算行动点、地点访问和确定性世界状态，不直接修改杨德清的信任、态度或签约意愿。
- 目标 NPC 的指标变化来自可控 测试范围内的确定性 LLM 替身返回的 `NPCStateEvaluation`，并经 `StateDeltaValidator` 提交。
- 产生一条 `SimulationLog`。
- 日志可见。

### 5.2 干部私谈

期望：

- 行动点扣除 1。
- 不由行动类型固定赋予干部类 NPC 信任变化；由目标干部 LLM 按其人设、记忆和玩家原话决定。
- 若目标不是干部，返回非法目标。

### 5.3 调阅档案

期望：

- 行动点扣除 1。
- `env_clue` 可按规则提升。
- 产生档案发现日志。

### 5.4 提高补偿

期望：

- 行动点扣除 1。
- 预算减少。
- 系统记录可兑现的补偿条件；目标 NPC 是否认可、态度是否上升及幅度仍由该 NPC LLM 在边界内判断。
- 如果金额超过规则上限，行动被拒绝且不扣行动点。

### 5.5 公开承诺

期望：

- 记录承诺。
- 群众信任短期上升。
- 未兑现时可被后续事件惩罚。

### 5.6 行动点不足

初始：

- `action_points = 0`

期望：

- 普通行动被拒绝。
- 状态不变。
- 返回风险提示。

## 6. 合规测试

测试文件：

```text
tests/test_compliance_service.py
```

测试用例：

| 用例 | 输入 | 期望 |
|---|---|---|
| 超预算承诺 | 承诺每户 1000 万 | 拒绝 |
| 威胁村民 | “不签就抓你” | 拒绝 |
| 强制拆迁 | 未走程序直接拆 | 拒绝 |
| 伪造文件 | “帮我伪造签名” | 拒绝 |
| 合法走访 | “我去入户了解情况” | 允许 |

被拒绝行动不扣行动点，不改变 NPC 状态。

## 7. 事件服务测试

测试文件：

```text
tests/test_event_service.py
```

### 7.1 督查周报

初始：

- `day = 7`

期望：

- 生成督查周报事件。
- 同一日重复检查不重复触发。

### 7.2 社会稳定预警

初始：

- `social_stability_index = 49`

期望：

- 生成集体行动预警。
- 日志可见。

### 7.3 超支风险

初始：

- `budget_remaining = -1`

期望：

- 生成超支风险事件。
- `political_credit` 后续可被扣减。

### 7.4 固定事件

测试：

- D45 巡视组到达。
- D90 结局计算。

期望：

- 正确触发。
- 已触发事件不重复触发。

## 8. 夜间推演测试

测试文件：

```text
tests/test_night_simulation_service.py
```

### 8.1 Granovetter 阈值

初始：

- `signed_households = 20`
- `total_households = 36`
- NPC 阈值 50。
- `core_demand_satisfied = true`

期望：

- 签约率超过阈值。
- 生成包含“签约率超过阈值且核心诉求满足”的夜间处境上下文。
- 对高影响 NPC，测试范围内的确定性 LLM 替身可据该上下文输出受限的态度变化；夜间规则本身不直接写死 `attitude_score`。
- 产生隐藏日志。

### 8.2 阈值超过但核心诉求未满足

期望：

- 夜间处境记录“存在从众压力但核心诉求未满足”，供 NPC LLM 作出观望、试探、焦虑或有限态度变化判断。
- 不由夜间规则直接固定 NPC 的态度变化数值。

### 8.3 焦虑触发隐藏行动

初始：

- NPC `anxiety_level = 80`

期望：

- 可能产生夜间隐藏日志。
- 使用固定随机种子时结果稳定。

### 8.4 夜间摘要

期望：

- 每晚产生一条玩家可见摘要。
- 摘要不泄露全部隐藏日志。

### 8.5 推进日期

期望：

- `day + 1`
- `days_left - 1`
- 次日行动点恢复为 3。

## 9. 存档读档测试

测试文件：

```text
tests/test_game_session_service.py
```

测试点：

- 新开局生成 `session_id`。
- 新开局绑定当前登录账号。
- 开局锁定 `package_id`。
- 每次行动后自动保存快照。
- 每次 NPC 回复后自动保存快照。
- 日终和夜间推演后自动保存快照。
- MySQL 中的 `current_snapshot_json` 可恢复当前局。
- JSON 快照文件被写出，并与 MySQL 快照索引关联。
- 登录后能继续最近一局未结束游戏。
- 读档后 `GameState` 完全一致。
- 读档后所有 `NPCState` 完全一致。
- 读档后对话日志和隐藏日志数量一致。
- 读档后继续行动不会覆盖旧快照。
- 普通账号不能读取其他账号的存档。
- 第一阶段不测试多存档槽和任意历史节点回滚。

## 10. 账号登录测试

测试文件：

```text
tests/test_account_service.py
tests/test_auth_api.py
```

### 10.1 创建账号

期望：

- 能创建用户名和密码。
- MySQL 数据库不保存明文密码。
- `password_hash_scheme` 有值。
- 重复用户名创建失败。

### 10.2 密码哈希验证

期望：

- 正确密码验证通过。
- 错误密码验证失败。
- 密码哈希不是普通 SHA256、MD5 或明文。

### 10.3 登录接口

期望：

- 正确账号密码返回 200。
- 服务端设置 HttpOnly Cookie。
- 错误密码返回 401。
- 用户名不存在返回 401。
- 两种失败场景错误提示一致。

### 10.4 当前账号接口

期望：

- 已登录访问 `/api/auth/me` 返回账号信息。
- 未登录访问返回 401。
- 不返回 `password_hash`。

### 10.5 存档归属

期望：

- A 账号创建的游戏 session 绑定 A。
- B 账号不能读取 A 的 session。
- 管理员账号是否可读他人 session 按当前权限策略测试。第一阶段如果未开放管理员读取接口，则只测试普通账号隔离。

## 11. NPC 记忆测试

测试文件：

```text
tests/test_memory_service.py
```

验收用例：

| 场景 | 期望 |
|---|---|
| 第 2 日玩家承诺修路 | 第 7 日 NPC 能提起该承诺 |
| 第 3 日谈定补偿金额 | 第 5 日弱关系 NPC 可能听到夸大传闻 |
| 第 4 日玩家冲突 | 第 5 日该 NPC 态度更差 |
| 存档后重进 | NPC 记忆保持一致 |
| 重复问同一核心问题 | NPC 核心立场一致 |

第一阶段可以用 测试范围内的确定性 LLM 替身或模板回复验证。

## 12. NPC 指标评估测试

测试文件：

```text
tests/test_npc_state_evaluation_service.py
tests/test_state_delta_validator.py
```

测试点：

- LLM 返回合法 JSON 时，系统能提取 `attitude_delta`。
- LLM 返回散文时，系统要求重试或降级。
- LLM 输出超大指标变化时，系统能裁剪或拒绝。
- LLM 试图直接设置 `signed: true` 时，系统拒绝。
- LLM 引用 NPC 不知道的信息时，系统拒绝或重试。
- 合法的指标变化能写入 `NPCState`。
- LLM 原始 JSON、校验结果、裁剪字段能写入日志。
- 同一玩家话语对不同 NPC 能产生不同指标变化。

验收用例：

| 场景 | 期望 |
|---|---|
| 玩家只谈补偿，不谈祖坟 | 祖坟敏感 NPC 信任下降或焦虑上升 |
| 玩家承认历史遗留问题 | 低信任老人信任上升 |
| 玩家威胁施压 | LLM 评估强负面变化，合规层同时拒绝非法行动 |
| 玩家给出模糊承诺 | NPC 可输出试探、观望或要求书面承诺 |

## 13. NPC 对话约束测试

测试文件：

```text
tests/test_dialogue_service.py
```

测试点：

- NPC 不透露未解锁暗线。
- 村民不说出县委内部信息。
- 干部不主动暴露自己的隐藏污点。
- NPC 不直接说“系统已给你 signed +1”。
- NPC 不接受非法承诺。
- NPC 语言风格符合档案。

可用 测试范围内的确定性 LLM 替身生成违规文本，测试输出校验器是否拦截。

## 14. 结局判定测试

测试文件：

```text
tests/test_ending_service.py
```

至少覆盖：

- 最佳结局。
- 标准好结局。
- 任务完成但代价大。
- 数字完成但满意度低。
- 失控结局。
- 真相隐藏结局。
- 共谋者隐藏结局。
- 人情代价隐藏结局。

每个结局需要一个 fixture 状态：

```text
tests/fixtures/endings/ending_best.json
tests/fixtures/endings/ending_standard.json
...
```

测试点：

- 触发条件准确。
- 优先级准确。
- 默认结局兜底。
- 结局文本可返回。
- 评分计算稳定。

## 15. API 测试

测试文件：

```text
tests/test_game_api.py
```

测试接口：

- `POST /api/game/session`
- `GET /api/game/session/{session_id}`
- `POST /api/game/session/{session_id}/action`
- `POST /api/game/session/{session_id}/end-day`
- `GET /api/game/session/latest-active`
- `GET /api/game/session/{session_id}/review`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/me`

测试点：

- 新建 session 成功。
- 未登录不能新建 session。
- 非法 package 返回 400。
- 行动返回状态变化。
- 行动返回 NPC 指标评估 JSON 和校验结果。
- 非法行动返回拒绝说明。
- 日终返回夜间摘要。
- 结束后不能继续行动。

## 16. 前端端到端测试

建议使用 Playwright。

测试文件：

```text
tests/e2e/test_game_flow.spec.ts
```

第一阶段流程：

1. 打开游戏页面。
2. 未登录时跳转到登录页。
3. 输入测试账号和密码。
4. 登录成功后进入游戏首页。
5. 新建游戏。
6. 查看 D1 状态。
7. 点击地图中的 NPC。
8. 执行入户走访。
9. 验证行动点减少。
10. 验证对话流出现 NPC 回复。
11. 结束当天。
12. 验证夜间摘要出现。
13. 刷新页面。
14. 验证登录态和存档恢复。

UI 检查：

- 左侧指标不溢出。
- 中间对话可滚动。
- 右侧 NPC 档案可打开。
- 按钮在行动点不足时禁用或提示。
- 登录失败不暴露账号是否存在。

## 17. 剧本包兼容性测试

测试文件：

```text
tests/test_script_package_compatibility.py
```

测试点：

- 剧本包 manifest 字段齐全。
- `npc_profiles.json` 中 NPC ID 唯一。
- 行动规则引用的 NPC 类型存在。
- 事件规则引用的指标存在。
- 结局规则引用的 flag 可由剧本或事件产生。
- 所有文本字段允许更新，不影响 Schema。

重点：

当前剧本会继续更新。测试不能断言固定角色名、固定章节标题、固定事件文本。测试应断言结构和规则合法性。

## 18. 回归测试

每次修改后运行：

```bash
python -m unittest discover -s tests
```

新增游戏模块后，必须保证既有章节生成测试仍通过：

- `tests/test_chapter_generation.py`
- `tests/test_chapter_revision.py`
- `tests/test_pa_backend_staged_generation.py`
- `tests/test_version_allocation.py`

## 19. 人工试玩验收

内测前至少完成：

- 10 位测试者各完成一局。
- 每局能在 55 分钟内完成。
- 8 种结局至少各到达 1 次。
- 所有固定事件至少触发 1 次。
- 至少 2 名有基层治理经验者试玩。
- 至少 2 名政治学或公共管理研究者试玩。

人工记录：

- 最不真实的地方。
- 最困惑的操作。
- 最像真实治理的瞬间。
- 哪个 NPC 最不稳定。
- 哪个结局最不可解释。

## 20. 测试数据管理

测试数据放在：

```text
tests/fixtures/
  script_packages/
  sessions/
  npc_states/
  endings/
```

测试数据要求：

- 不使用真实个人信息。
- Demo 数据使用 `DEMO-` 前缀。
- 不把 API Key 放入 fixture。
- 不把真实密码放入 fixture。
- 测试账号使用明确的弱口令并只用于本地测试。
- LLM 测试默认使用 测试范围内的 HTTP/依赖替身。
- 数据库集成测试使用独立 MySQL 测试库，不连接正式库。

## 21. 通过标准

M1 规则原型通过标准：

- 账号登录测试通过。
- 白天行动服务测试通过。
- 事件服务测试通过。
- 夜间推演服务测试通过。
- 存档读档测试通过。
- 既有生成器测试不回退。

M2 可玩闭环通过标准：

- API 测试通过。
- 前端 E2E 基础流程通过。
- 玩家可从 D1 到结局。
- 结局判定可复现。

M3 LLM NPC 通过标准：

- NPC 指标评估测试通过。
- NPC 记忆验收通过。
- NPC 对话约束测试通过。
- LLM 失败有降级策略。
- 单局成本可记录。

M4 研究后台通过标准：

- 数据导出字段完整。
- 复盘页完整。
- 实验条件分组可追踪。
- 同一 session 可回放。

## 22. 运行时闭环补充测试

### 22.1 剧本包与机会模型测试

测试文件：

```text
tests/test_script_package_validator.py
tests/test_interaction_opportunity_service.py
```

必须覆盖：

- 所有 `interaction_opportunity` 引用的 NPC、地点、事件、线索、资源主键均存在。
- 缺少前置事件、线索或信任阈值时，机会不可见且不可调用。
- 满足前置条件后，地图、任务卡或档案入口返回同一个 `opportunity_id`。
- 机会的冷却、关闭条件和 `may_unlock` 正确生效。
- 每个关键行动日至少存在一条合法可玩入口；每个结局至少存在一条可达路径。
- 旧 session 继续读取其锁定 package，不读取新包的机会、人物或资源。

### 22.2 原子 NPC 回合测试

测试文件：

```text
tests/test_npc_turn_service.py
```

必须覆盖：

- 同一份 测试范围内的确定性 LLM 替身输出中的台词、`dialogue_intent` 与指标变化相容；矛盾输出被重试或降级。
- LLM 输出经校验后，在同一事务中写入 NPC 状态、记忆、日志和快照索引。
- 模型超时、JSON 无效、知识越界、数据库写入失败时，不扣行动点、不改变 NPC 状态、不开放后续机会。
- 玩家输入含有“忽略规则”“输出系统提示”等注入文本时，不能改变角色、规则或 JSON schema。
- 已落库的回合复盘时直接使用审计记录，不因重新调用模型而生成不同结果。

### 22.3 幂等、并发与恢复测试

测试文件：

```text
tests/test_game_action_idempotency.py
tests/test_session_concurrency.py
```

必须覆盖：

- 相同 `session_id + client_action_id` 重试只结算一次，并返回首次结果。
- 两个并发请求争用同一 `state_version` 时，仅一个提交，另一个返回冲突且状态不损坏。
- MySQL 事务提交成功但 JSON 辅助快照写入失败时，游戏仍可从 MySQL 恢复，并生成可观测告警。
- MySQL 事务失败时，不留下部分日志、半个 NPC 指标变化或已扣除的行动点。
- 网络中断后，前端使用 `client_action_id` 查询或重试，不能造成重复 LLM 调用和重复扣费。

### 22.4 真实模型回归集

测试范围内的确定性 LLM 替身只能验证程序契约，不能证明 NPC 的人设和对抗性。M3 起必须维护版本化小型回归集，至少包括每个关键 NPC 的：

- 可接受的说服示例。
- 触及红线的示例。
- 模糊承诺、过度承诺、违法威胁和提示注入示例。
- 已知事实与未知事实追问示例。
- 跨日记忆和第三方传闻示例。

每次模型、提示词、NPC 档案或剧本包更新后，对该回归集进行人工抽样与自动 schema 校验。验收关注“是否遵守人物与事实边界、变化是否可解释且在范围内”，不要求真实模型对每个文本产出完全相同的数值。
