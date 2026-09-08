# 严肃游戏技术设计文档

## 1. 设计目标

本文档定义严肃游戏运行时系统的技术方案。当前仓库以 `最终剧本.md` 和版本化结构剧本包为内容输入，可运行代码集中在 `code/`；旧剧本生成、修订和展示工具已经移除。

系统不把当前初版剧本写死。所有剧情、NPC、事件、行动、结局和数值阈值都通过剧本包或规则表加载。代码只维护稳定的运行时框架。

## 2. 当前代码基础

当前仓库已有以下能力：

- `code/backend/`：玩家 API、SQLite/MySQL 持久化、结构化剧本包、规则服务和研究治理基线。
- `code/backend/content/packages/pkg_gameplay_v2/`：optimization-0.5 当前发布剧本包。
- `code/backend/tests/`：从内容校验、运行时事务到 LLM 边界和研究治理的自动化验收。
- `code/frontend/terminal/`：只消费玩家 API 的最小文字客户端。

游戏产品区已经完成 M0–M3：具备玩家 API、SQLite session 存档、真实 LLM 单 NPC 回合、D1–D90 事件与决策状态机、逐日夜间模拟、地图、复盘、D90 完整结局正文和最小文字终端。真实网关已实现结构化响应、审计、预算、记忆与安全降级，并通过第三方 OpenAI 兼容端点的 `qwen3.6-plus` 完整回放。M4 代码基线已完成，正式研究制度与生产部署验收尚未完成。

## 3. 总体架构

```text
剧本 Markdown 母稿
      ↓
结构化抽取 JSON
      ↓
剧本包 Script Package
      ↓
开局锁定版本
      ↓
Game Session
      ↓
白天行动服务 → 事件服务 → 夜间推演服务 → 次日状态
      ↓
NPC 对话服务 / 复盘 / 数据导出
```

运行时分为五层：

1. 内容层：剧本、NPC、事件、规则、结局。
2. 规则层：行动结算、事件触发、夜间传播、结局判定。
3. Agent 层：NPC 对话、记忆、摘要、风格控制。
4. API 层：Session、Action、Dialogue、Save、Replay。
5. 前端层：游戏界面、复盘界面、编辑工具。

M0–M3 按本地优先实施，开发与文字验收使用 SQLite，数据访问通过仓储和事务端口隔离。正式浏览器测试及服务器部署仍以 MySQL 为生产基线；接入时替换基础设施适配器，不改变领域层、玩家 API、账号所有权和幂等事务契约。

## 4. 剧本包设计

### 4.1 目录结构

建议新增：

```text
code/backend/content/packages/
  pkg_<version>/
    package_manifest.json
    full_script.md
    script_structure.json
    npc_profiles.json
    action_rules.json
    event_rules.json
    ending_rules.json
    prompt_templates/
      npc_dialogue_system.md
      action_parser_system.md
      night_summary_system.md
    assets_manifest.json
    art_story_mapping.json
    art/
      player/
      brand/
      ui/
      icons/
      npc/
      map/
      scenes/
      events/
      evidence/
      endings/
      tutorial/
      system/
```

### 4.2 package_manifest.json

```json
{
  "package_id": "pkg_20260715_001",
  "title": "浊流之上",
  "package_version": "1.0.0",
  "source_version": "final_script_20260715",
  "created_at": "2026-07-15T00:00:00+08:00",
  "content_hash": "sha256:<64 hex chars>",
  "status": "published",
  "script_schema_version": 1,
  "rules_schema_version": 1,
  "prompt_version": "npc_prompt_v1",
  "model_profile": "dev_default",
  "notes": "以最终剧本.md 为内容权威；发布后不可原地覆盖"
}
```

### 4.3 内容加载原则

- `content_hash` 是对规范化 manifest（排除自身哈希字段）及包内所有运行时文件按路径排序后计算的 SHA-256；上传、发布、开局和读档四处都要复算。
- 剧本包状态只允许 `draft -> published -> retired`；`published` 后内容、提示词和美术均不可原地覆盖，任何变更必须生成新 `package_id + package_version + content_hash`。
- 开局时把 `package_id`、`package_version`、`package_content_hash` 和不可变存储地址写入 session；读档必须四者一致，不能只凭 `package_id` 找“最新版”。
- 已开局 session 不跟随剧本包变化；旧 session 仍读取原哈希对应的旧剧本和旧美术。
- 只要有 session、快照、复盘或研究记录引用，包对象就不得物理删除；`retired` 只禁止新开局。备份与保留策略必须覆盖最长存档和研究保留期。
- 包文件存入只读、可版本化的对象存储或内容寻址目录；数据库保存元数据和哈希，不把可变工作目录当作历史包仓库。

### 4.4 美术资源包

美术需求详见 `art_requirement.md`。技术侧只依赖该文档规定的资源契约，不直接依赖某张图片的临时文件名。

每个剧本包必须包含：

- `assets_manifest.json`：资源索引和程序读取入口。
- `art_story_mapping.json`：玩家、NPC、事件、证据、地点和结局到视觉入口的交叉引用。
- `art/`：游戏运行时资源导出目录。
- `art/ui/design_tokens.json`：前端可读取的颜色、间距、圆角和字体 token。
- `art/map/map_layers.json`：地图可交互元素与 NPC、地点、事件的映射。

禁止事项：

- 禁止在前端或后端硬编码具体图片路径。
- 禁止用 NPC 中文名、地点中文名作为资源主键。
- 禁止让旧 session 自动读取新剧本包中的美术资源。
- 禁止运行时读取 PSD、AI、Figma 源文件。

`assets_manifest.json` 顶层结构：

```json
{
  "schema_version": 1,
  "package_id": "pkg_20260715_001",
  "art_direction_version": "art_v1",
  "base_path": "art/",
  "design_tokens": {
    "file": "art/ui/design_tokens.json"
  },
  "assets": []
}
```

单个资源最小结构：

```json
{
  "asset_id": "npc_zhou_dashan_portrait_neutral",
  "category": "npc",
  "type": "portrait",
  "path": "art/npc/npc_zhou_dashan/portrait_neutral.webp",
  "fallback_asset_id": "npc_unknown_portrait_neutral",
  "linked_entity_type": "npc",
  "linked_entity_id": "npc_zhou_dashan",
  "state": "neutral",
  "usage": ["dialogue", "npc_profile", "review"],
  "format": "webp",
  "width": 512,
  "height": 512,
  "version": "1.0.0",
  "license": "project_internal",
  "commercial_use": true,
  "alt_text": "周大山普通状态头像"
}
```

后端需要新增 `AssetManifestService`：

```text
src/services/asset_manifest_service.py
```

职责：

- 加载指定 `package_id + package_content_hash` 的 `assets_manifest.json`；拒绝哈希不匹配或可变目录回退。
- 校验 `asset_id` 唯一。
- 校验 `path` 是否存在。
- 校验 `linked_entity_id` 是否能在玩家角色、NPC、事件、地点、证据、场景、地图、结局规则或系统保留实体表中找到；`player_li_zhiyuan` 是首版唯一玩家实体 ID，`system` 类型只能使用版本化保留 ID，不能接受任意字符串。
- 按 `asset_id`、`linked_entity_id`、`usage`、`state` 查询资源。
- 提供 fallback 链。

接口建议：

```python
class AssetManifestService:
    def load_manifest(self, package_id: str, package_content_hash: str) -> AssetManifest:
        ...

    def get_asset(self, package_id: str, package_content_hash: str, asset_id: str) -> AssetRef:
        ...

    def find_assets(
        self,
        package_id: str,
        package_content_hash: str,
        linked_entity_type: str | None = None,
        linked_entity_id: str | None = None,
        usage: str | None = None,
        state: str | None = None,
    ) -> list[AssetRef]:
        ...
```

建议新增 API：

```text
GET /api/game/session/{session_id}/assets-manifest
GET /api/game/session/{session_id}/assets/{asset_id}
GET /api/game/session/{session_id}/art/{path}
```

三个接口均先校验 session 所有权，再按 session 锁定的包哈希读取。第三个接口只允许读取该不可变包 `art/` 目录下已登记资源，禁止任意文件路径读取。

## 5. 领域模型扩展

现有 dataclass 只作为 v1 原型输入。第 14 章列出的核心状态必须迁移为显式 v2 字段，禁止把行动点规则、十项指标、真实/账面签约、未决决策、版本号或结局轴来源塞入无 schema 的 `metadata`；`metadata` 只容纳不参与规则判定的扩展信息。

建议逐步新增以下模型：

```text
src/domain/account.py
src/domain/game_session.py
src/domain/event_rule.py
src/domain/ending_rule.py
src/domain/dialogue_message.py
src/domain/player_action.py
src/domain/npc_memory.py
src/domain/script_package.py
```

### 5.1 Account

职责：

- 表示登录账号。
- 保存密码哈希元数据。
- 绑定玩家存档。
- 为后续角色权限预留字段。

核心字段：

```python
account_id: str
username: str
password_hash: str
password_hash_scheme: str
role: str
created_at: str
disabled: bool
metadata: dict
```

第一阶段 `role` 只需要支持 `player` 和 `admin`。权限系统先不展开，但字段必须保留。

密码要求：

- 长度至少 8 个字符；客户端不足时必须明确提示并原地重新输入。
- 禁止明文保存。
- 当前实现使用带随机盐和固定参数元数据的 `scrypt`；迁移算法时必须兼容存量哈希并轮换会话。
- 不使用普通 SHA256、MD5 或可逆加密保存密码。

### 5.2 GameSession

职责：

- 绑定剧本包版本。
- 绑定账号。
- 保存当前状态。
- 保存 NPC 状态集合。
- 保存日志。
- 标记是否结束。

核心字段：

```python
session_id: str
account_id: str
package_id: str
package_version: str
package_content_hash: str
created_at: str
status: str
state_version: int
processing_action_id: str | None
pending_decision_id: str | None
random_seed: str
game_state: GameState
npc_states: dict[str, NPCState]
flags: set[str]
triggered_events: set[str]
logs: list[SimulationLog]
metadata: dict
```

### 5.3 NPCMemory

第一阶段用结构化记忆，不直接上向量库：

```python
npc_id: str
facts_known: list[str]
rumors_heard: list[str]
promises_from_player: list[dict]
recent_dialogue_summary: str
relationship_notes: list[str]
hidden_state: dict
```

后续可把 `facts_known`、`rumors_heard`、对话摘要写入向量检索。

### 5.4 NPCState 与指标修改权威

本节以 `最终剧本.md` 第 5.3、5.4、7.4 节为运行时权威。第 5.4 节的概述与第 7.4 节的具体规则不一致时，以更具体的第 7.4 节为准。必须区分“LLM 驱动角色说话”与“LLM 有权修改数值”：角色可以由 LLM 驱动，但不是所有角色都保存数值，也不是所有数值都由 LLM 决定。

NPC 状态按修改权威分为四类：

| 状态 | 权威来源 | LLM 权限 | 实现要求 |
| --- | --- | --- | --- |
| 九维固定档案 | 剧本包内容 | 只读 | 开放性、尽责性、外向性、宜人性、情绪波动、网络位置、参照档、从众阈值、身份标签开局锁定，不随对话修改 |
| 人物信任度 `trust_*` | 规则派生 | 禁止修改 | 第一档统一初值 40，按已开启旗标的固定增减量计算并钳制到 0–100；锁定旗标置 0 并冻结；张立按第三章显式结算点处理 |
| 态度 `attitude_*` | 剧本硬结算或 LLM 受限判断 | 仅自由互动和非固定夜间影响可提议 | 固定选项、突发事件、自主工具已写明结果时按剧本结算；自由文字和未写死的关系传播由 LLM 判断方向与幅度档，服务端映射后写入 |
| 焦虑 `anxiety_*` | 剧本硬结算或 LLM 受限判断 | 仅自由互动和非固定夜间影响可提议 | 剧本显式结算优先；其他受控场景由 LLM 判断方向与轻/中/重档，服务端按剧本区间解析 |
| 亲近感 | 叙事层 | 可生成表现，不可写引擎数值 | 只进入台词、神情和关系摘要，不参与吐真、夜间或结局计算 |
| 立场（签/拒/观望） | 规则派生 | 禁止修改 | 根据签约比例、从众阈值、户群规则和已注册旗标计算，不保存第二套可漂移数值 |
| 专属旗标、证据、签约户数 | 剧本/规则权威 | 只能提议候选 | LLM 不得新造旗标或证据；候选必须命中已注册 ID、吐真闸门和节点条件后才由引擎提交 |
| 行动点、预算、十项全局指标、结局轴 | 规则权威 | 禁止修改 | 只读剧本结算行、动作价目、旗标和结局规则 |

可交互性必须按最终剧本分档：

- 第一档深度交互：张立、赵建国、钱伟、刘三、陈默、石文斌，以及周大山、周奎元、周满仓、吴秀英、何铁柱、谭老六、马长顺、宁德海、袁桂兰、杨波、老倔头、苗喜旺、邓守本。保存信任度、态度、焦虑和结构化记忆。
- 第二档有限交互：蒋崇岳、郑向东、孙强、冯敬之、贺兴邦、罗健、柯启年、顾克明、崔广林。只保存专属旗标或剧情状态，不创建 `trust_*`、`attitude_*`、`anxiety_*` 数值；蒋崇岳的对话闸门直接读取轴 V。最终剧本 5.7 已将贺兴邦列为主要人物且规定其固定剧情职能，7.4.1 分档表漏列其名；技术侧将其归入第二档，避免丢失角色或擅造数值。
- 第三档跑龙套：王芳。只生成氛围和公开信息，不保存人物状态。

这里的档级必须存为全局 `state_tier`，只决定状态模型。各章正文里出现的“本章第一档/第二档/不可接触”应抽取为 `availability_mode=free|limited|closed`，只决定当章能否发起自由对话，不能覆盖 `state_tier`。例如周奎元在第 7.4.1 总表中是第一档、需要保存数值，但第四章可暂时是 `limited`；赵建国、钱伟、张立也可以有第一档数值而在某章只允许剧本场合接触。

同一回合的修改优先级固定为：不可变/派生字段保护 > 剧本显式结算 > 通过校验的 LLM 受限提议 > 数值钳制。若某个固定选项已经写明态度或焦虑变化，LLM 仍负责角色化回复，但不得再次给同一指标叠加变化。剧本区间值由服务端 `ScriptedDeltaResolver` 使用 session 固定随机种子解析，保证存档回放得到同一结果，不交给 LLM 任意选数。

典型例子：玩家在固定选项中选择施压刘三，剧本写明的刘三焦虑 `+15～25` 属于硬结算；使用“差异化补偿”使马长顺态度上升两档，也属于硬结算。玩家在开放对话里临时解释、承诺或施压，而当前节点没有写明人物数值后果时，才由刘三或马长顺各自的 LLM 依据人设和上下文判断态度/焦虑的方向与幅度档。

当前《最终剧本》还存在必须在内容发布前拦截的信任度口径冲突：第 7.4.3 节规定除张立外，人物信任度只能按旗标表派生，但刘三部分决策点仍写有直接 `+15～25`、`-5～10` 等区间。运行时以第 7.4.3 的总规则为准，`ScriptPackageValidator` 遇到“非张立人物直接修改信任度”的结算行必须报错并阻止发布；剧本作者应将其归并到已注册旗标增减量或修订第 7.4 总规则。程序不得同时执行直接区间和旗标增减，也不得自行猜测二者如何合并。

## 6. 服务设计

### 6.1 AccountService

文件：

```text
src/services/account_service.py
```

职责：

- 创建账号。
- 校验用户名和密码。
- 生成密码哈希。
- 验证密码哈希。
- 禁用账号。

接口建议：

```python
class AccountService:
    def create_account(self, username: str, password: str, role: str = "player") -> Account:
        ...

    def authenticate(self, username: str, password: str) -> Account | None:
        ...
```

第一阶段账号创建可以通过管理脚本或管理员接口完成。前端不做自助注册。

### 6.2 AuthSessionService

文件：

```text
src/services/auth_session_service.py
```

职责：

- 登录后创建服务端会话。
- 校验请求中的 session token。
- 注销登录。
- 把 `account_id` 注入游戏接口。

第一阶段即使用 HttpOnly Cookie 保存不少于 256 bit 的随机 session token，数据库只存 token hash。浏览器部署基线不能延期：

- Cookie 必须设置 `HttpOnly`、`Secure`（仅 `localhost` 开发例外）、`SameSite=Lax`、明确 `Path` 和有限 `Max-Age`；`expires_at` 必填，默认空闲 30 分钟、绝对 12 小时，可由部署配置缩短。
- 登录成功后轮换 token 并撤销登录前 token，权限变化和密码重置后撤销该账号全部会话，防止固定会话攻击。
- 所有改变状态的 Cookie 请求校验 CSRF token 与 `Origin/Referer`；登录和注销同样受保护。API 若改用 `Authorization` header，则不得同时接受 Cookie 旁路。
- 登录接口实施账号/IP 组合限流、统一错误信息和失败审计；生产环境只允许 HTTPS。
- 所有游戏路由先鉴权，再由仓储层强制查询 `session_id + current_account_id`；管理员跨账号读取走单独权限和审计路径。

### 6.3 ActionService

文件：

```text
src/services/action_service.py
```

职责：

- 加载行动规则。
- 校验行动点、预算和目标。
- 结算行动点、预算和确定性世界状态影响。
- 生成供 NPC LLM 评估的行动上下文。
- 输出日志。

接口建议：

```python
class ActionService:
    def execute(
        self,
        game_state: GameState,
        npc_states: dict[str, NPCState],
        action_id: str,
        target_npc_id: str | None = None,
        payload: dict | None = None,
    ) -> ActionResult:
        ...
```

第一阶段实现：

- `home_visit`
- `cadre_private_talk`
- `review_archive`
- `raise_compensation`
- `public_commitment`

### 6.4 ActionParserService

职责：

- 辅助识别玩家文字输入中的行动意图、目标 NPC、承诺、金额、话题和风险词。
- 输出候选行动和置信度，供合规检查和日志记录使用。
- 低置信度时要求玩家选择确认。

核心原则：

- 玩家与 NPC 的主要互动形式是“说服式文字输入”，不是固定按钮结算。
- ActionParserService 不决定 NPC 是否被说服，也不决定 NPC 指标变化。
- ActionParserService 不能用固定关键词规则替代 NPC 的态度判断。
- 无论解析出什么行动标签，玩家原始文本都必须完整传入 `NPCTurnService`；由该服务判断走剧本硬结算、LLM 受限评估或两者仅在不同字段上的组合。
- 快捷行动只用于降低输入成本和补充结构化参数，不能替代自由文字说服。

第一阶段可以用规则关键词做“行动归类”和“合规预筛”，但解析器不能据关键词直接给 NPC 加减信任、态度或签约意愿。只有命中剧本中具有明确 `action_id/option_id` 的结算声明时，规则层才能执行硬结算。

后续可接 LLM 做行动解析，但解析 LLM 也只输出 JSON，不承担 NPC 指标结算：

```json
{
  "action_id": "home_visit",
  "target_npc_id": "npc_zhou_dashan",
  "parameters": {
    "topic": "compensation"
  },
  "confidence": 0.82
}
```

### 6.5 ComplianceService

职责：

- 拒绝非法行动。
- 检查承诺是否超预算。
- 检查是否越权。
- 检查是否违反剧本边界。

设计原则：

- 先规则校验，再 LLM 回复。
- 被拒绝的行动不扣行动点。
- 拒绝日志仍需保存。

### 6.6 NPCStateEvaluationService

文件：

```text
src/services/npc_state_evaluation_service.py
```

职责：

- 将玩家说服文本、行动归类、目标 NPC 档案、NPC 当前状态、NPC 记忆、世界状态、相关事件和承诺组装为 prompt。
- 仅在自由文字互动或未被剧本写死的夜间关系影响中，调用“目标 NPC 自己”的 LLM 评估本次互动。
- 要求 LLM 按该 NPC 的人设、利益、红线、知识边界、语言风格和当前处境输出固定 JSON。
- 返回态度/焦虑的方向和幅度档、行为倾向、允许范围内的吐露候选、传播意图和风险说明。
- 固定选项或自主工具存在显式结算行时，不调用本服务决定数值；LLM 只生成与硬结算结果一致的角色回复。

接口建议：

```python
class NPCStateEvaluationService:
    def evaluate(
        self,
        game_state: GameState,
        npc_state: NPCState,
        player_text: str,
        action_context: dict,
        memory_context: dict,
        world_context: dict,
    ) -> NPCStateEvaluation:
        ...
```

LLM 输出示例：

```json
{
  "npc_id": "npc_zhou_dashan",
  "metric_assessment": {
    "attitude": {
      "direction": "decrease",
      "band": "micro"
    },
    "anxiety": {
      "direction": "increase",
      "band": "light"
    }
  },
  "proposals": {
    "disclosure_id": null,
    "flag_candidates": [],
    "will_share_with": ["npc_zhou_kuiyuan"],
    "active_response": "continue_observing"
  },
  "reasoning_summary": "玩家没有回应祖坟问题，角色愿意继续谈但态度略降、焦虑上升。",
  "dialogue_intent": "继续试探玩家，不直接拒绝",
  "risk_notes": ["祖坟问题未处理"]
}
```

设计原则：

- 目标 NPC 的 LLM 决定自由文字互动中该 NPC 态度、焦虑的变化方向和幅度档，不直接决定任意数值。
- 同一句玩家文本传给不同 NPC，可能产生不同指标变化。
- 同一句玩家文本在不同记忆、事件和世界状态下，可能产生不同指标变化。
- 系统规则负责行动合法性、资源扣除、信任度派生、从众/立场、显式剧本结算、幅度档映射、输出校验、数值裁剪和数据库提交。
- 系统不得用关键词固定加减表替代 NPC LLM 对自由说服文本的态度/焦虑判断；也不得让 LLM 覆盖剧本已经写死的选择后果。
- LLM 输出必须结构化。
- LLM 不直接写数据库。
- LLM 不得输出或改变 `trust_*`、九维档案、亲近感数值、立场、签约、预算、行动点、十项全局指标和结局轴。
- 系统保留 LLM 原始 JSON，供复盘和研究分析。

### 6.7 StateDeltaValidator

文件：

```text
src/services/state_delta_validator.py
```

职责：

- 校验 `NPCStateEvaluationService` 输出。
- 拒绝 LLM 对受保护字段的写入，特别是人物信任度、九维档案、立场、签约和全局指标。
- 将态度/焦虑幅度档映射为最终剧本允许的变化量并限制单次范围。
- 检查目标 NPC 是否存在。
- 检查目标 NPC 是否属于第一档；第二档和第三档输出任何数值变化都判为非法。
- 检查 LLM 是否引用超出 NPC 知识边界的信息。
- 检查吐露候选是否命中当前信任档、已注册旗标、人物知识范围和“每人每章一次”额度。
- 对可裁剪的数值进行裁剪。
- 对严重违规输出要求重试或降级。

映射规则：

- 态度只接受 `none/micro/medium/heavy`，分别映射为 `0/5/15/30`，方向由 `increase/decrease` 决定。
- 焦虑只接受 `none/light/medium/heavy`；分别映射为 `0`、剧本轻档 `5–10`、中档 `15–25`、重档约 `30`，区间由 session 固定随机种子解析。
- 关键事件若在剧本中有显式区间，直接走 `ScriptedDeltaResolver`，不采用 LLM 幅度。
- `trust_*` 每次提交后由 `TrustDerivationService` 根据初值、已结算旗标和锁定状态重新计算；LLM 输出包含信任度变化即整份评估失败并重试。
- `signed`、证据交付和旗标不能由 LLM 直接置真，只能提交候选，最终由规则服务核验并提交。

配套新增：

```text
src/services/scripted_delta_resolver.py   # 解析剧本显式值/区间，使用 session 固定随机种子
src/services/trust_derivation_service.py  # 40 + 已结算旗标增减；处理张立特例与不可逆锁定
```

`StateDeltaValidator` 输出必须按字段携带 `authority`（`script`、`derived_rule`、`llm_bounded`）和 `source_id`，供事务层阻止越权写入并供复盘解释。

### 6.8 EventService

文件：

```text
src/services/event_service.py
```

职责：

- 检查固定事件。
- 检查条件事件。
- 检查剧本包显式允许的随机事件；固定剧情不得被随机事件覆盖或取消。
- 将事件推进为可恢复、可幂等提交的 `pending_decision`，而不是只返回一段事件文本。

接口建议：

```python
class EventService:
    def check_events(
        self,
        game_state: GameState,
        npc_states: dict[str, NPCState],
        logs: list[SimulationLog],
        triggered_events: set[str],
    ) -> list[TriggeredEvent]:
        ...
```

最终剧本的固定日历不可改名或合并：市委巡察组由张立带队，在 D31 进驻、D45 撤离；D46–D89 张立不在云溪常驻；顾克明带领的环保迎检组在 D59 进驻；D90 张立以验收主检身份再次出现，倒计时归零后才触发结局计算。D31 巡察、D59 环保迎检和 D90 最终验收是三个独立事件。每 7 天周报、稳定风险和预算风险只有在 `event_rules.json` 注册后才能生成，不能凭技术文档另造剧情事件。

### 6.8.1 强制事件与决策状态机

突发事件、编号决策点、判断题、排序题和剧情内处置题统一使用以下状态机：

```text
scheduled/eligible
  -> presented
  -> pending_decision
  -> resolving
  -> resolved
  -> effects_committed
```

- `presented` 时写入 `event_instance_id`、`decision_id`、可用 `option_id`、展示顺序、前置条件快照、`state_version` 和玩家可见文本；保存后断线重连仍返回同一实例。
- session 处于 `pending_decision` 时，除读取、提交该决策、退出登录和无副作用的复盘预览外，禁止 `/action`、`/end-day`、跳日或开启另一决策，返回 `409 DECISION_REQUIRED`。
- 选项提交必须携带 `decision_id`、`option_id`、`client_action_id` 和 `state_version`。服务端重新校验选项仍可用，结算成功后以同一事务写效果、事件日志、动作日志和新快照。
- 同一 `client_action_id` 的相同提交返回首次结果；同 ID 不同选项或不同请求体返回 `409 IDEMPOTENCY_KEY_REUSED`。一个 `decision_id` 一旦 `resolved`，换新 ID 再交也返回 `409 DECISION_ALREADY_RESOLVED`。
- 剧本决策默认没有现实时间超时；关闭页面不会替玩家作答。只有剧本包显式声明 `timeout_seconds` 与 `timeout_policy` 的研究模式才可自动处理，并必须记录 `resolution_source=timeout`，不得默认随机选项。
- `resolving` 失败不得产生部分结算。可重试失败回到 `pending_decision`；不可重试的内容错误把 session 标记为 `content_blocked`，保留证据并阻止继续推进。

### 6.8.2 StoryClockService：90 天与 45 分钟闭环

新增 `StoryClockService`，把“故事日期”和“玩家实际操作回合”分开。六章固定覆盖 D1–15、D16–30、D31–45、D46–60、D61–75、D76–90；不是要求玩家手动点击九十次日终。

`story_beats.json` 必须为每一天声明 `day_mode=playable|simulated|transition|ending`、所在章节、强制事件、可选机会、自动推进目标和夜间规则：

- `playable` 日显示自主行动窗口，基准每日 8 行动点；疲惫可按最终剧本降低当日额度。未使用行动点不结转。
- 编号决策点和突发事件选项固定消耗 0 点；自主工具按剧本价目扣点。敏感期和验收期读取预计算后的实耗列，禁止在代码中再次乘倍率。
- 玩家提交日终后，先结算当晚，再按顺序逐日模拟所有被跳过日期的固定事件、到期承诺、关系传播、风险和夜间日志；不能把 D20 直接改成 D25 而漏跑四晚。
- 自动推进遇到强制事件或决策立即停在该日并进入 `pending_decision`；遇到下一个 `playable` 日则重置该日行动点后停下。跳过日不发放可消费行动点，也不凭空替玩家执行自主工具。
- 每个模拟日都写 `day_advance_log` 和可回放的日末状态；一次跨多日推进在对外表现为一个幂等操作，在数据库中要么全部提交，要么不提交。
- D90 是 `ending` 日：先完成最终固定结转，冻结终局快照，再计算 14 条轴和结局；禁止中途通关或提前判负。

### 6.9 NightSimulationService

文件：

```text
src/services/night_simulation_service.py
```

职责：

- 执行 NPC 之间的信息传播。
- 执行 Granovetter 阈值变化。
- 生成隐藏日志。
- 生成玩家次日可见摘要。
- 推进到下一天。

接口建议：

```python
class NightSimulationService:
    def run_night(
        self,
        game_state: GameState,
        npc_states: dict[str, NPCState],
        logs: list[SimulationLog],
    ) -> NightSimulationResult:
        ...
```

夜间推演采用“规则先行、LLM 受限补充”。剧本明确写出夜戏触发条件、回写旗标或数值时，必须硬结算；只有关系网造成的未写死心理影响，才允许对第一档 NPC 调用 `NPCStateEvaluationService` 判断态度和焦虑。

第一阶段简化规则：

- 先执行已注册夜戏、互斥旗标、从众阈值和脚本回写，再重新派生第一档人物信任度。
- 签约率、核心诉求满足度和社会网络传播生成“夜间处境变化”上下文；其中已写死的旗标/数值走规则，未写死的态度/焦虑影响才交给 LLM。
- 高影响或状态临界的第一档 NPC 可由 `NPCStateEvaluationService` 输出受限态度/焦虑档；第二档只更新专属旗标，第三档不更新状态。
- 焦虑值高于 70 的 NPC 可能生成隐藏风险日志或夜间评估候选。
- 同一来源事件不得同时走硬编码和 LLM 两次结算；以 `source_event_id + npc_id + metric` 做去重键。
- 每晚生成一条可见摘要。

### 6.10 DialogueService

职责：

- 构建 NPC 对话 prompt。
- 注入固定人物档案、当前状态、记忆和最近对话。
- 调用 LLM。
- 对输出做规则校验。

重要约束：

- DialogueService 不直接修改 GameState 或 NPCState。
- 固定选项/自主工具的 NPCState 变化来自剧本硬结算；自由文字和未写死夜间影响的态度/焦虑变化来自 `NPCStateEvaluationService` 的受限输出。两类结果统一经过 `StateDeltaValidator` 和去重检查后提交。
- 人物信任度始终由已结算旗标或张立显式结算点派生，不从对话输出取值。
- NPC 说“我愿意签”不等于状态自动签约。
- 签约必须由 ActionService 或 EventService 结算。

### 6.11 MemoryService

第一阶段：

- 使用 MySQL 存储结构化记忆。
- 每次对话后写入摘要。
- 承诺单独存储。

第二阶段：

- 增加语义检索。
- 增加事件型记忆。
- 增加 NPC 反思摘要。

### 6.12 EndingService

职责：

- 仅在 D90 倒计时归零后冻结 `GameState`、flags、NPC 终局状态和事件记录。
- 按最终剧本计算 14 条结局轴，自上而下扫描 24 行主结局表，首行命中即停，末行恒真兜底。
- 读取命中行声明的自由轴，落入 95 个亚结局之一，再追加 3 个附加位文本。
- 输出主结局 ID、亚结局 ID、命中行、轴快照和结局文本；不输出综合评分。
- 保存复盘数据。

禁止增加中途通关、提前判负、综合评分、分数线或另一套结局短路链。NPC LLM 不参与结局裁决。

## 7. API 设计

游戏运行 API 当前位于：

```text
code/backend/src/serious_game_backend/api/app.py
```

### 7.1 新建游戏

`POST /api/game/session`

请求：

```json
{
  "client_request_id": "01J...",
  "package_id": "pkg_20260715_001",
  "difficulty": "standard"
}
```

响应：

```json
{
  "session_id": "sess_xxx",
  "state_version": 1,
  "visible_state": {},
  "visible_npcs": [],
  "opening_text": "",
  "pending_decision": null
}
```

该接口要求已登录。服务端从登录态读取 `account_id`，禁止前端自报账号归属。`client_request_id` 在同一账号内唯一，防止双击创建两局：相同 ID、相同请求返回首次创建的 session；相同 ID、不同请求返回 409。

### 7.2 执行动作

`POST /api/game/session/{session_id}/action`

这是唯一的玩家写操作契约；后文不得再定义另一套 `/action` 字段。请求使用按 `input_mode` 区分的联合类型：

```json
{
  "input_mode": "free_text",
  "client_action_id": "01J...",
  "state_version": 17,
  "opportunity_id": "opp_d51_zhou_kuiyuan_home_visit",
  "player_text": "我想先听您讲讲祠堂和搬迁的顾虑。",
  "target_npc_id": "npc_zhou_kuiyuan"
}
```

字段约束：

- `free_text`：必填 `opportunity_id`、`player_text`、`target_npc_id`；不接受 `decision_id/option_id`。
- `tool`：必填 `opportunity_id`、`action_id`，按工具规则决定是否必填 `target_npc_id` 和结构化 `parameters`；可选 `player_text` 只作原话记录。
- `decision`：必填 `decision_id`、`option_id`；排序题另填完整且无重复的 `ordered_option_ids`。决策点与突发事件恒为 0 行动点。
- 三类都必须携带 `client_action_id` 与客户端最近读取的 `state_version`；未知字段和空字符串占位一律拒绝，避免把错误请求悄悄解释成别的模式。

玩家可见响应：

```json
{
  "operation_id": "act_xxx",
  "status": "succeeded",
  "state_version": 18,
  "narrative": "周大山把茶杯往你这边推了半寸。",
  "npc_reply": "祠堂不是一间房的事。你先说，搬走以后香火落在哪。",
  "visible_state": {
    "day": 7,
    "days_left": 83,
    "action_points": 7,
    "signed_households": "0/36",
    "budget_remaining_wan": 8000,
    "indicators": {"public_trust": "观望"}
  },
  "visible_logs": [],
  "pending_decision": null
}
```

禁止响应 `llm_assessment`、精确人物数值、精确隐藏指标 delta、完整 `game_state`、隐藏 flags、结局轴或内部推理摘要。内部 `InternalTurnResult` 可保存 `scripted_effects`、模型审计、逐字段 authority 和完整快照，但只供规则服务、授权研究导出和管理员审计；API 必须经过 `PlayerVisibleDTOMapper` 白名单映射。玩家只能看到最终剧本允许的四项精确台账与五项文字体感，不得从日志反推出隐藏数值或人物信任度。

### 7.3 日终

`POST /api/game/session/{session_id}/end-day`

请求必须包含 `client_action_id` 和 `state_version`。若存在 `pending_decision`、当前日不允许日终或另一操作正在处理，返回 409；不得跳过强制事件。

响应：

```json
{
  "operation_id": "act_xxx",
  "state_version": 19,
  "day_summary": "",
  "night_summary": "",
  "advanced_days": [7, 8, 9],
  "visible_state": {},
  "pending_decision": null,
  "is_ended": false
}
```

### 7.4 读取存档

`GET /api/game/session/{session_id}`

只返回玩家可见 DTO、`state_version`、当前机会和未决决策，不返回内部快照。

### 7.5 复盘

`GET /api/game/session/{session_id}/review`

只读当前账号的本局复盘；研究字段、LLM 原始输出和隐藏数值不进入玩家复盘 DTO。

### 7.6 继续最近一局

`GET /api/game/session/latest-active`

该接口要求已登录。服务端按当前账号查找最近一局未结束游戏。

查询逻辑：

```sql
select *
from game_sessions
where account_id = ?
  and status in ('active', 'paused')
order by updated_at desc
limit 1;
```

如果不存在未结束游戏，返回 404 或 `{ "session": null }`，由前端展示“新开一局”。

### 7.6.1 Session 所有权与操作状态

除剧本包公共元数据外，所有读取、机会、动作、日终、未决决策、继续游戏、复盘、快照和导出接口都必须执行同一条仓储约束：

```sql
select ... from game_sessions
where session_id = :session_id and account_id = :current_account_id;
```

查不到统一返回 404，避免泄露 session 是否存在。禁止先按 `session_id` 读取完整对象再在业务层补判断。管理员跨账号访问使用独立 `/api/admin/...` 路由、RBAC 权限和审计日志。异步操作可由 `GET /api/game/session/{session_id}/operations/{client_action_id}` 查询 `processing|succeeded|failed_retryable|failed_final`；该接口同样校验所有权。

### 7.7 账号登录

`POST /api/auth/login`

请求：

```json
{
  "username": "demo001",
  "password": "plain_password_from_form"
}
```

响应：

```json
{
  "account_id": "acct_xxx",
  "username": "demo001",
  "role": "player"
}
```

服务端同时设置 HttpOnly Cookie。登录失败统一返回 401，不区分用户名不存在或密码错误。

### 7.8 退出登录

`POST /api/auth/logout`

### 7.9 当前账号

`GET /api/auth/me`

响应：

```json
{
  "account_id": "acct_xxx",
  "username": "demo001",
  "role": "player"
}
```

## 8. 前端设计

当前玩家前端位于：

```text
code/frontend/terminal/
```

正式图形前端可在后续切换到：

```text
frontend-app/
  Next.js
  TypeScript
  Tailwind CSS
  Zustand
```

第一阶段如果继续单页 HTML，必须做到：

- 登录页。
- 三栏布局。
- 对话流。
- 行动点显示。
- 日终结算。
- NPC 档案。
- 地图占位。
- 事件日志。
- 存档恢复。

前端状态只作展示。真实状态以服务端 session 为准。

正式浏览器登录页第一阶段只放用户名、密码和登录按钮，不开放无限制注册、找回密码、记住我、第三方登录和用户资料页。本地文字测试客户端另提供 SQLite 自助注册，仅在 `ALLOW_SELF_REGISTRATION=true` 的非生产环境可用。

### 8.1 前端美术资源加载

前端必须以 `package_id` 为边界加载美术资源：

```text
读取当前 game session
  ↓
取得 session.package_id + session.package_content_hash
  ↓
GET /api/game/session/{session_id}/assets-manifest
  ↓
建立 asset_id 索引、entity 索引和 usage 索引
  ↓
页面组件按 asset_id 或 linked_entity_id 渲染
```

该接口必须执行第 7.7 节统一的 session 所有权校验，并按 session 锁定的 `package_content_hash` 读取不可变资源包。前端不得绕过 session 直接请求某个可猜测的 `package_id`；缓存键至少包含 `package_content_hash + asset_id + asset.version`。

组件不得写死图片路径。示例：

- NPC 对话头像：按 `linked_entity_type=npc`、`linked_entity_id=<npc_id>`、`usage=dialogue`、`state=<PlayerVisibleDTO.portrait_state>` 查询；前端不得读取隐藏人物数值自行选图。
- 玩家肖像：按 `linked_entity_type=player`、`linked_entity_id=player_li_zhiyuan` 和当前 `usage` 查询，不创建 NPCState。
- NPC 档案头像：按 `usage=npc_profile` 查询。
- 地图底图：按 `category=map`、`type=map_base` 查询。
- 地图交互层：读取 `art/map/map_layers.json`，再按 `PlayerVisibleDTO.map_visual_state` 渲染；不得读取隐藏 NPC 数值或暗档自行推导高亮。
- 事件卡片：按 `linked_entity_type=event`、`linked_entity_id=<event_id>`、`usage=event_card` 查询。
- 结局页：按 `linked_entity_type=ending`、`linked_entity_id=<ending_id>`、`usage=ending` 查询。
- 证据库：按 `linked_entity_type=evidence`、`linked_entity_id=<evidence_id>`、`usage=evidence_viewer` 查询。

`map_visual_state` 的唯一枚举与 `art_requirement.md` 一致：`unknown`、`known`、`visited`、`available`、`locked`、`cooldown`、`completed`、`signed`、`event_active`、`clue_available`、`clue_collected`。`newly_unlocked` 是服务端可选的一次性提示布尔值，不是第二套主状态；风险、人物立场、信任度和焦虑度不进入该枚举。

fallback 规则：

```text
目标状态资源
  ↓ 不存在
同实体 neutral/default 资源
  ↓ 不存在
同类别 default 资源
  ↓ 不存在
system_missing_asset
```

首屏需要预加载：

- 登录页背景和标题资源。
- 当前主界面 UI token。
- 当前玩家最近 session 的地图底图。
- 当前可见 NPC 的头像。

非首屏资源按需加载：

- 事件插图。
- 结局图。
- 复盘图表和证据大图。

前端缺图时必须显示 `system_missing_asset`，同时把缺失 `asset_id` 写入前端错误日志，便于美术和测试修复。

## 9. LLM 调用设计

### 9.1 Prompt 注入顺序

```text
[System] 角色固定档案
[System] 规则边界和禁止事项
[System] 本回合字段 authority mask 与剧本硬结算草案
[System] 当前 GameState 摘要
[System] 目标 NPC 当前状态
[System] 当前信任档、吐露白名单、不可吐露清单和本章剩余额度
[Memory] 结构化记忆
[History] 最近对话
[Human] 玩家当前行动和话语
```

### 9.2 NPC 自由互动评估输出格式

NPC 自由互动评估调用必须输出 JSON，不能输出散文。它只对第一档人物的态度和焦虑拥有受限提议权；人物信任度、立场和硬结算结果不在 Schema 中。

```json
{
  "npc_id": "npc_zhou_dashan",
  "metric_assessment": {
    "attitude": {
      "direction": "decrease",
      "band": "micro"
    },
    "anxiety": {
      "direction": "increase",
      "band": "light"
    }
  },
  "proposals": {
    "disclosure_id": null,
    "flag_candidates": [],
    "will_share_with": ["npc_zhou_kuiyuan"],
    "active_response": "continue_observing"
  },
  "reasoning_summary": "玩家没有回应祖坟问题，角色愿意继续谈但态度略降、焦虑上升。",
  "dialogue_intent": "继续试探玩家，不直接拒绝",
  "risk_notes": ["祖坟问题未处理"]
}
```

系统必须保存：

- LLM 原始 JSON。
- LLM 提议的方向/幅度档，以及服务端映射后的最终变化。
- 同回合执行的剧本硬结算和信任度派生结果，两者必须与 LLM 提议分栏记录。
- 被裁剪或拒绝的字段。
- 重试次数。

### 9.3 NPC 对话输出格式

NPC 对话可以是自然语言，但服务端内部需要附带结构化审计结果：

```json
{
  "reply": "你先别跟我讲大道理，我就问一句，我家那块地怎么算？",
  "risk_flags": [],
  "claimed_facts": ["询问土地补偿"],
  "requires_followup_evaluation": false
}
```

对话自然语言本身不承担指标结算。固定操作读取剧本硬结算；自由互动只采用同一原子回合中通过校验的态度/焦虑受限评估；信任度随后由规则重新派生。

### 9.4 输出校验

校验器检查：

- 是否泄露隐藏信息。
- 是否越过知识边界。
- 是否产生非法承诺。
- 是否改变剧情事实。
- 是否与 NPC 风格严重不符。
- 目标人物是否允许保存数值，以及态度/焦虑幅度档是否合法。
- 是否试图修改信任度、九维档案、立场、签约、旗标、全局指标或结局轴。
- 是否与本回合剧本显式结算重复。

失败处理：

1. 用更严格 prompt 重试一次。
2. 再失败则返回模板化回应。
3. 记录 LLM 输出失败日志。

## 10. 外部项目复用建议

以下项目可作为稳定代码或架构参考。复用前必须检查许可证，并在本仓库保留来源说明。

### 10.1 Generative Agents

项目：

- `https://github.com/joonspk-research/generative_agents`

可复用部分：

- `reverie/backend_server/persona/memory_structures/associative_memory.py`
- `reverie/backend_server/persona/memory_structures/scratch.py`
- `reverie/backend_server/persona/memory_structures/spatial_memory.py`
- `reverie/backend_server/persona/cognitive_modules/`

适合复用到：

- NPC 记忆流。
- 记忆重要性、最近性、相关性检索。
- NPC 反思摘要。
- NPC 日程和行为计划。

复用方式：

- 不建议直接照搬完整项目。该项目是研究原型，依赖旧式目录和环境。
- 建议把记忆结构和检索打分思想用于 `code/backend/src/serious_game_backend/application/npc_memory_service.py`。
- `associative_memory.py` 的记忆节点思想可改造成 `NPCMemoryEvent`。
- `cognitive_modules` 的 perceive/retrieve/reflect/plan 可改造成夜间推演中的可选步骤。

### 10.2 AI Town

项目：

- `https://github.com/a16z-infra/ai-town`

可复用部分：

- `ARCHITECTURE.md` 的分层方案。
- `convex/engine/` 的游戏引擎与业务规则分离思路。
- `convex/agent/` 的 Agent 异步处理思路。
- `convex/aiTown/agent.ts` 的游戏循环中 Agent 提交输入的思路。

适合复用到：

- 游戏循环架构。
- 服务端状态为准。
- 人类和 Agent 都通过输入提交到引擎。
- 前端只渲染状态。

复用方式：

- 本项目后端是 Python FastAPI，不建议直接迁移 Convex。
- 可以借鉴 `convex/engine` 的职责边界，在本项目中实现 `GameEngineService`。
- 可以借鉴 Agent 不直接改状态、只提交输入的模式。

### 10.3 LangGraph

项目：

- `https://github.com/langchain-ai/langgraph`

可复用部分：

- 状态图。
- durable execution。
- human-in-the-loop。
- short-term 和 long-term memory 接口。

适合复用到：

- 玩家输入解析流程。
- NPC 对话流程。
- 夜间高焦虑 NPC 行为流程。
- 失败重试和人工审查。

复用方式：

- 第一阶段不引入，避免增加复杂度。
- 第二阶段如果 NPC 流程复杂，可在后端基础设施层增加专用编排模块：
  `parse_action -> compliance_check -> rule_settlement -> npc_reply -> output_validation`。

### 10.4 LangGraph Memory Service

项目：

- `https://github.com/langchain-ai/langgraph-memory`

可复用部分：

- `memory_service/graph.py`
- 上游项目的 `tests/evals/test_memories.py`

适合复用到：

- 长期记忆抽取。
- 事件型记忆。
- 记忆 schema 持续更新。
- 记忆评估测试。

复用方式：

- 第一阶段只做结构化 JSON 记忆。
- 第二阶段可参考 `memory_service/graph.py`，把对话日志抽取成 NPC 记忆。
- 测试思路可改造成本项目的 NPC 记忆验收测试。

### 10.5 LangGraph Memory Agent

项目：

- `https://github.com/langchain-ai/memory-agent`

可复用部分：

- ReAct Agent 调用 `store_memory` 工具的模式。
- 按用户或线程隔离记忆的模式。

适合复用到：

- 玩家长期偏好记录。
- NPC 对玩家历史行为的记忆。
- 研究后台中的访谈式分析助手。

复用方式：

- 不建议让 NPC 自主决定保存所有记忆。
- 可以把 `store_memory` 模式改成受规则控制的 `record_npc_memory`。

### 10.6 AWS Dynamic Game NPC Dialogue

项目：

- `https://github.com/aws-solutions-library-samples/guidance-for-dynamic-game-npc-dialogue-on-aws`

可复用部分：

- NPC 知识库 RAG。
- NPC LLMOps。
- 质量审查流程。

适合复用到：

- 后期生产部署。
- NPC 知识库更新。
- 质量评估和回归测试。

复用方式：

- 该项目偏 AWS、Unreal、MetaHuman，当前阶段不直接复用代码。
- 可复用 RAG 和 QA 流程设计。

### 10.7 不建议直接复用的部分

- 完整 AI Town 前端地图和实时移动系统。当前游戏是治理对话和决策，地图是辅助信息，不需要实时角色移动。
- 完整 Generative Agents 小镇环境。它的空间模拟和日程机制超出第一阶段需求。
- Unreal/MetaHuman 相关代码。当前目标是桌面浏览器内测。

## 11. 状态流转

### 11.1 白天行动

```text
玩家输入
  ↓
选择目标 NPC / 场景
  ↓
玩家输入说服文本
  ↓
ActionParserService 辅助归类
  ↓
ComplianceService
  ↓
ActionService
  ↓
读取剧本显式结算并建立字段 authority mask
  ↓
自由文字且无显式人物结算时，NPCStateEvaluationService 将玩家原话传给目标 NPC LLM
  ↓
StateDeltaValidator 合并硬结算与受限提议，派生信任度/立场并去重
  ↓
DialogueService 生成或返回与最终状态一致的回复
  ↓
SessionRepository.save()
```

每次 `ActionService` 和 `DialogueService` 产生稳定结果后，必须调用 `SessionRepository.save_current_snapshot()`。保存失败时，接口应返回错误，不能让前端继续显示一个未持久化的状态。

### 11.2 日终夜间

```text
End Day
  ↓
校验无 pending_decision
  ↓
NightSimulationService.run_night()：脚本回写/旗标/从众优先
  ↓
仅对第一档未写死心理影响执行 LLM 态度/焦虑评估
  ↓
派生信任度、校验、去重
  ↓
StoryClockService 按 story_beats 逐日推进并模拟跳过日
  ↓
遇到强制事件则创建 pending_decision；否则停在下一 playable 日并重置当日额度
  ↓
SessionRepository.save()
```

日终和跨日推演作为同一个幂等操作提交；任一模拟日失败则不前移故事日期。数据库保存成功后再异步写 JSON 辅助快照。

### 11.3 结局

```text
D90 倒计时归零
  ↓
EndingService.evaluate()
  ↓
ReviewService.build_review()
  ↓
SessionRepository.save(status="ended")
```

结局判定后必须保存最终状态、结局结果和复盘数据。

## 12. 存储设计

### 12.1 第一阶段 MySQL 存储

数据库分两级实施。M0–M3 的本地文字运行时采用 SQLite，验证持久化、原子事务、重启恢复、幂等、LLM 审计和 NPC 记忆语义；正式浏览器测试与生产环境采用 MySQL，因为账号、行为日志、研究数据和后续多人访问需要生产级关系数据库。两者必须实现同一仓储与事务端口，禁止把 SQLite 方言或文件路径写入领域层。

JSON 文件仍可作为快照、调试和复盘辅助产物保留，但不作为主存储。

建议新增：

```text
data/
  mysql/
outputs/game_sessions/
  sess_xxx/
    snapshots/
    logs.jsonl
    dialogues.jsonl
    review.json
```

核心表：

```sql
create table accounts (
  account_id varchar(64) primary key,
  username varchar(128) not null unique,
  password_hash varchar(255) not null,
  password_hash_scheme varchar(32) not null,
  role varchar(32) not null,
  disabled tinyint(1) not null default 0,
  created_at datetime(6) not null,
  metadata_json json not null
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table auth_sessions (
  token_hash varchar(128) primary key,
  account_id varchar(64) not null,
  created_at datetime(6) not null,
  last_seen_at datetime(6) not null,
  expires_at datetime(6) not null,
  revoked_at datetime(6) null,
  constraint fk_auth_sessions_account
    foreign key(account_id) references accounts(account_id)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table script_packages (
  package_id varchar(128) primary key,
  package_version varchar(64) not null,
  content_hash char(71) not null,
  status varchar(16) not null,
  immutable_uri varchar(1024) not null,
  manifest_json json not null,
  created_at datetime(6) not null,
  published_at datetime(6) null,
  retired_at datetime(6) null,
  unique key uq_script_packages_hash(content_hash),
  unique key uq_script_packages_id_hash(package_id, content_hash)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table game_session_requests (
  account_id varchar(64) not null,
  client_request_id varchar(128) not null,
  request_hash char(71) not null,
  session_id varchar(64) null,
  status varchar(32) not null,
  response_json json null,
  created_at datetime(6) not null,
  updated_at datetime(6) not null,
  primary key(account_id, client_request_id),
  constraint fk_game_session_requests_account foreign key(account_id) references accounts(account_id)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table game_sessions (
  session_id varchar(64) primary key,
  account_id varchar(64) not null,
  package_id varchar(128) not null,
  package_version varchar(64) not null,
  package_content_hash char(71) not null,
  status varchar(32) not null,
  state_version bigint unsigned not null default 1,
  processing_action_id varchar(64) null,
  pending_decision_id varchar(128) null,
  random_seed varchar(128) not null,
  consent_record_id varchar(64) null,
  experiment_group_id varchar(64) null,
  created_at datetime(6) not null,
  updated_at datetime(6) not null,
  current_snapshot_json json not null,
  metadata_json json not null,
  constraint fk_game_sessions_account
    foreign key(account_id) references accounts(account_id),
  constraint fk_game_sessions_package
    foreign key(package_id, package_content_hash)
    references script_packages(package_id, content_hash),
  index idx_game_sessions_account_updated(account_id, updated_at),
  index idx_game_sessions_package(package_id)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table game_snapshots (
  snapshot_id varchar(64) primary key,
  session_id varchar(64) not null,
  account_id varchar(64) not null,
  reason varchar(64) not null,
  day int not null,
  action_index int not null,
  snapshot_json json not null,
  json_file_path varchar(512) null,
  created_at datetime(6) not null,
  constraint fk_game_snapshots_session
    foreign key(session_id) references game_sessions(session_id),
  constraint fk_game_snapshots_account
    foreign key(account_id) references accounts(account_id),
  index idx_game_snapshots_session_created(session_id, created_at),
  index idx_game_snapshots_account_created(account_id, created_at)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table game_actions (
  action_record_id varchar(64) primary key,
  session_id varchar(64) not null,
  account_id varchar(64) not null,
  client_action_id varchar(128) not null,
  request_hash char(71) not null,
  input_mode varchar(32) not null,
  status varchar(32) not null,
  attempt_count int not null default 1,
  base_state_version bigint unsigned not null,
  committed_state_version bigint unsigned null,
  request_json json not null,
  response_json json null,
  error_code varchar(64) null,
  created_at datetime(6) not null,
  updated_at datetime(6) not null,
  constraint fk_game_actions_session foreign key(session_id) references game_sessions(session_id),
  constraint fk_game_actions_account foreign key(account_id) references accounts(account_id),
  unique key uq_game_actions_idempotency(session_id, client_action_id),
  index idx_game_actions_status(session_id, status, updated_at)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table action_logs (
  log_id varchar(64) primary key,
  action_record_id varchar(64) not null,
  session_id varchar(64) not null,
  day int not null,
  source_id varchar(128) not null,
  authority varchar(32) not null,
  internal_effects_json json not null,
  visible_effects_json json not null,
  created_at datetime(6) not null,
  constraint fk_action_logs_action foreign key(action_record_id) references game_actions(action_record_id),
  index idx_action_logs_session_day(session_id, day)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table dialogue_logs (
  dialogue_id varchar(64) primary key,
  action_record_id varchar(64) not null,
  session_id varchar(64) not null,
  npc_id varchar(128) not null,
  player_text_ciphertext mediumtext null,
  player_text_redacted mediumtext null,
  npc_reply mediumtext not null,
  visibility varchar(32) not null,
  created_at datetime(6) not null,
  constraint fk_dialogue_logs_action foreign key(action_record_id) references game_actions(action_record_id),
  index idx_dialogue_logs_session_npc(session_id, npc_id, created_at)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table event_logs (
  event_log_id varchar(64) primary key,
  session_id varchar(64) not null,
  event_instance_id varchar(128) not null,
  decision_id varchar(128) null,
  status varchar(32) not null,
  resolution_source varchar(32) null,
  payload_json json not null,
  created_at datetime(6) not null,
  unique key uq_event_instance(session_id, event_instance_id),
  index idx_event_logs_session_status(session_id, status)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table decision_instances (
  decision_instance_id varchar(64) primary key,
  session_id varchar(64) not null,
  event_instance_id varchar(128) not null,
  decision_id varchar(128) not null,
  status varchar(32) not null,
  presented_state_version bigint unsigned not null,
  options_json json not null,
  selected_option_json json null,
  resolved_action_record_id varchar(64) null,
  resolution_source varchar(32) null,
  presented_at datetime(6) not null,
  resolved_at datetime(6) null,
  unique key uq_decision_instance(session_id, event_instance_id, decision_id),
  index idx_decision_pending(session_id, status)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table night_logs (
  night_log_id varchar(64) primary key,
  session_id varchar(64) not null,
  story_day int not null,
  source_event_id varchar(128) not null,
  internal_result_json json not null,
  visible_summary text not null,
  created_at datetime(6) not null,
  unique key uq_night_source(session_id, story_day, source_event_id)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table llm_call_audits (
  audit_id varchar(64) primary key,
  action_record_id varchar(64) null,
  session_id varchar(64) not null,
  purpose varchar(64) not null,
  model_provider varchar(64) not null,
  model_id varchar(128) not null,
  prompt_version varchar(64) not null,
  request_hash char(71) not null,
  raw_output_ciphertext mediumtext null,
  validated_output_json json null,
  validation_status varchar(32) not null,
  token_usage_json json not null,
  latency_ms int not null,
  retry_count int not null,
  created_at datetime(6) not null,
  index idx_llm_audits_session_created(session_id, created_at)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table npc_state_evaluations (
  evaluation_id varchar(64) primary key,
  action_record_id varchar(64) not null,
  session_id varchar(64) not null,
  npc_id varchar(128) not null,
  scripted_effects_json json not null,
  llm_proposals_json json null,
  accepted_effects_json json not null,
  rejected_fields_json json not null,
  authority_json json not null,
  model_audit_id varchar(64) null,
  created_at datetime(6) not null,
  constraint fk_npc_eval_action foreign key(action_record_id) references game_actions(action_record_id),
  index idx_npc_eval_session_npc(session_id, npc_id, created_at)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table npc_memories (
  memory_id varchar(64) primary key,
  session_id varchar(64) not null,
  npc_id varchar(128) not null,
  source_action_record_id varchar(64) null,
  memory_type varchar(32) not null,
  content_json json not null,
  visibility varchar(32) not null,
  valid_from_day int not null,
  invalidated_at datetime(6) null,
  created_at datetime(6) not null,
  index idx_npc_memories_lookup(session_id, npc_id, valid_from_day)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;
```

Session token 只把原文返回到 HttpOnly Cookie。数据库中只保存 token hash。

`game_sessions.current_snapshot_json` 是恢复游戏的权威当前状态。`game_snapshots` 保存历史快照索引，便于复盘和研究查询。生产迁移还必须给上面省略的日志 `session_id/account_id` 外键补齐一致的删除策略；默认 `RESTRICT`，不能用级联删除意外抹掉研究审计。DDL、ORM 模型和迁移脚本由同一迁移版本管理，禁止只在文档后文“建议新增”而不进入第十二章基线。

### 12.2 JSON 快照

建议新增：

```text
outputs/game_sessions/
  sess_xxx/
    session_manifest.json
    snapshots/
      0001_opening.json
      0002_day001_after_action_home_visit.json
      0003_day001_after_npc_reply.json
      0004_day001_after_night.json
    logs.jsonl
    dialogues.jsonl
    review.json
```

用途：

- 便于调试。
- 便于人工检查。
- 便于复盘导出。
- 便于在 LLM 或规则服务故障后排查问题。

限制：

- JSON 快照不是主存储。
- 恢复游戏状态以 MySQL 中的当前 session 记录为准。
- JSON 快照可用于审计和回放，但不能替代数据库事务。
- 第一阶段不支持玩家从任意 JSON 快照回滚继续游戏。

### 12.3 后续存储扩展

建议：

- Redis：会话缓存和短期状态。
- 向量库：NPC 记忆和知识库检索，可选。

后续需要补全：

- 数据库迁移工具。
- MySQL 备份与恢复策略。
- 服务器连接池配置。
- 管理员创建账号页面。
- 用户角色权限表。
- 密码重置表。
- 登录失败审计。
- 数据匿名化导出表。
- 实验分组表。

## 13. 测试插桩

所有服务输出必须可测试：

- 不依赖真实 LLM。
- 可注入 测试范围内的确定性 LLM 替身。
- 可注入固定随机种子。
- 可读取 fixture 剧本包。
- 可回放日志重建状态。

NPC 指标权威必须至少覆盖以下回归测试：

- 测试范围内的确定性 LLM 替身尝试修改 `trust_*`、九维、签约户数或全局指标时，整份评估被拒绝且不产生部分写入。
- 固定选项已硬结算态度/焦虑时，即使 测试范围内的确定性 LLM 替身返回同指标变化也只执行一次。
- 自由文字没有显式结算时，测试范围内的确定性 LLM 替身的幅度档能被正确映射、钳制并标记为 `llm_bounded`。
- 同一旗标重复开启不重复增加信任度，关闭旗标不回退已结算分数；锁定后信任度保持 0。
- 张立显式结算可写信任度，其他人物直接信任度 delta 在剧本包校验阶段失败。
- 第二档和第三档人物不生成数值字段；章节 `availability_mode` 变化不改变全局 `state_tier`。
- 研究回放不再次调用 LLM，固定 seed 下硬结算区间和最终快照完全一致。

运行时闭环还必须覆盖：

- 强制事件进入 `pending_decision` 后动作、日终和跳日均被阻塞；断线重连仍返回同一决策实例。
- 相同幂等 ID/相同请求返回首次结果，不同请求返回 409；处理中可查询；可重试失败不重复扣资源；双击新开局只产生一个 session。
- 慢速 测试范围内的确定性 LLM 替身期间数据库不持有长事务，其他写请求得到 `SESSION_BUSY`；过期 worker 无法覆盖新版本。
- D30 日终后准确停在 D31 巡察进驻，D45 结转后张立离场，D59 触发顾克明迎检，D90 张立以验收主检身份返回并在终局结转后运行结局；跳过日夜间日志逐日齐全。
- 玩家 DTO 中不存在人物信任度、隐藏指标数值/delta、内部 flags、模型评估、完整快照或结局内部判据。
- 账号 A 猜中账号 B 的 session、机会、操作或复盘 ID 时统一得到 404，且仓储查询没有先读取后鉴权路径。
- 发布包被原地篡改、哈希不匹配或旧包缺失时拒绝开局/读档并报警；retired 包可读旧局但不可新开。
- 未同意研究原文采集的 session 不进入研究原文表；导出只含同意版本允许的字段并记录审计。

## 14. 迁移策略

现有领域对象只是原型，不能继续靠 `metadata` 容纳核心状态。迁移必须先引入 schema v2 与显式转换器，再接可玩循环；旧 fixture 通过迁移器读取，新写入一律使用 v2。

### 14.1 GameState v1 -> v2

| 现有字段 | v2 字段/处理 | 最终剧本口径 |
|---|---|---|
| `day` | `story_day` | 1–90；由 `StoryClockService` 推进 |
| `action_points=3` | `action_points` + `daily_action_point_cap` | 基准每日 8 点，按疲惫折减；未用不结转 |
| `budget_remaining` | 保留 | 初值 8000，单位万元，下界 0 |
| `signed_households` | `signed_households` 派生缓存 + `D75SettlementSnapshot` + `household_settlement_entries` | 真实签约 0–36；D75 首批冻结数与 D76–D89 逐户群事件共同构成验收审计真源，聚合字段只作显示与兼容缓存 |
| 无 | `reported_signed_households` | 只承载虚假签约造成的账面显示；不得进入结局与从众计算，核查后可冲销 |
| `days_left` | 保留 | 初值 90，每模拟一个故事日减 1，D90 归零 |
| `public_trust` | 保留 | 初值 50 |
| `social_stability_index` | `social_stability` | 初值 70 |
| `political_credit` | 保留 | 初值 70 |
| `media_pressure` | 保留 | 初值 30，越高越差 |
| `env_clue` | 保留 | 初值 0，暗档 |
| 无 | `integrity` | 初值 100，暗档 |
| `cadre_execution_index` | 删除；新增 `cadre_discontent` | 两者语义相反，禁止数值直接改名；新局按最终剧本初值 30，旧原型存档需显式转换或判为不可兼容 |
| 无 | `fatigue`、`stability_low_water`、`field_visit_count`、`lead_roster_disposition`、`corruption_evidence` | 按最终剧本分别初始化为 0、70、0、`not_acquired`、0 |

十项全局原始指标的唯一集合是：`signed_households`、`budget_remaining`、`days_left`、`public_trust`、`social_stability`、`political_credit`、`media_pressure`、`env_clue`、`integrity`、`cadre_discontent`。行动点是台账资源，不是第十一项指标；账面签约数是审计视图，不是第二套搬迁进度。

### 14.2 NPCState v1 -> v2

删除通用可写的 `trust_to_player`、`reference_point`、`core_demand_satisfied` 和逐 NPC `signed`。v2 使用 5.4 节唯一命名 `state_tier`，禁止再出现 `interaction_tier`：

- 第一档保存 `profile_id`、`state_tier=deep`、规则派生的 `trust_score`/`trust_locked`/`trust_effects_applied`、可写权限受控的 `attitude_score`、`anxiety_score`、记忆和吐露额度。
- 第二档保存 `state_tier=limited` 与已注册专属旗标，不创建人物数值。
- 第三档保存 `state_tier=ambient` 或完全不建状态，只从档案加载公开信息。
- `availability_mode=free|limited|closed` 是按章节和机会计算的临时可用性，不能替代或覆盖 `state_tier`。
- `granovetter_threshold`、参照档和九维人格移入不可变 `npc_profiles.json`；签/拒/观望由真实签约比例、阈值和旗标派生。

### 14.3 结局状态

结局轴不作为可自由写入的十四个分数字段。D90 冻结后由 `EndingAxisProjector` 从审计签约台账和旗标投影：A 项目达线、C 贪腐归宿、D 自身入局、T 环境真相、M 胁迫程度、X 数字造假、R 上报口径、P 民心归宿、F 收官姿态、Z 周氏宗族、J 张立、K 领导班子、E 陈默、V 蒋崇岳与常委会。投影前必须验证 `signed_households == D75首批户数 + D76–D89有效追加户数`，不一致即拒绝终局。保存的是带规则版本的终局投影快照，供回放验证，不允许白天业务代码直接改轴。

### 14.4 实施顺序

该迁移已经在 `code/backend/` 中完成：领域模型、应用服务、玩家 API、SQLite/MySQL 仓储与顺序迁移均有独立实现和回归测试。正式图形前端尚未建立，当前验收入口为 `code/frontend/terminal/`。

## 15. 当前项目交付补充

本节记录本仓库从剧本生成原型走向《浊流之上》可玩运行时的交付边界。

### 15.1 本轮资料核验结论

当前工作区已核验存在：

- 根目录 `最终剧本.md`，它是内容、人物、日期、指标、事件和结局的当前权威。
- `code/backend/content/packages/`，包含开发基线包与 optimization-0.5 当前玩法包。
- `docs/product/art_need_arguments.md`，包含人物、群像、场景、关键事件插图和主结局封面的生产参数。
- `docs/product/`，包含美术、产品、技术与测试资料。
- `docs/development/specs/`，包含四册开发交接补充规格。

v01 剧情接入检查项：

- 从最终剧本抽取六章、D1–D90、全部固定事件、编号决策点、夜戏、旗标、暗变量和 14 条结局轴。
- 将 29 个非玩家人物实体（县委书记蒋崇岳 + 23 名九维主要 NPC + 5 名轻量配角）映射为稳定 `npc_id`；玩家李致远另有角色与美术 ID，不作为 NPCState。人物美术总数因此为 30。
- 校验 D31 张立进驻、D45 撤离、D59 顾克明迎检、D90 张立主检没有被合并，所有跨章在场状态一致。
- 生成 24 个主结局、95 个亚结局和 3 个附加位的结构化规则，并验证首命中和恒真兜底。
- 将 `art_need_arguments.md` 的资产 ID、规格和优先级合入 `assets_manifest.json`，运行剧本包兼容性测试。

### 15.2 类似项目启发

市面和开源项目对本项目的启发如下：

| 项目 | 可借鉴点 | 本项目取舍 |
|---|---|---|
| Generative Agents | 记忆、反思、计划、可信行为模拟 | 借鉴 NPC 记忆和反思机制，不照搬小镇空间模拟 |
| AI Town | 服务端状态、AI 角色社交、可部署样板 | 借鉴游戏循环和状态权威源，不照搬实时移动地图 |
| Interactive LLM Powered NPCs | LLM NPC 对话、语音/文本交互 | 借鉴 NPC 对话体验，第一版不做语音 |
| LLM 驱动 NPC 商业游戏案例 | 动态对话带来沉浸感，也容易被玩家诱导跑偏 | 必须设置知识边界、结构化指标输出和违规校验 |
| AgentSociety / 社会仿真类项目 | 多主体社会模拟、行为日志、实验回放 | 借鉴研究数据和社会网络分析，不做大规模仿真平台 |

这些项目说明：LLM NPC 的价值在于“角色能基于记忆和处境做出自己的判断”。本项目不能只做固定数值表，也不能让模型覆盖剧本硬后果。核心技术路线是“剧本/规则权威 + LLM 受限提议 + 服务端校验提交”。

### 15.3 开发技术路线和整体思路

第一阶段目标是做出能跑完整一局的游戏运行时。

整体路线：

```text
最终剧本.md
  ↓
剧本包标准化
  ↓
账号登录与 MySQL 存储
  ↓
GameSession 和自动存档
  ↓
玩家行动解析与合规检查
  ↓
剧本硬结算 / NPC LLM 受限评估
  ↓
NPC 对话生成
  ↓
事件系统和夜间推演
  ↓
结局判定
  ↓
复盘与数据导出
```

#### 15.3.1 剧本包先行

剧本会持续修改。所有开发必须围绕剧本包工作。

剧本包至少包括：

- `package_manifest.json`
- `full_script.md`
- `script_structure.json`
- `npc_profiles.json`
- `action_rules.json`
- `event_rules.json`
- `ending_rules.json`
- `prompt_templates/`
- `assets_manifest.json`
- `art_story_mapping.json`

每局开局锁定一个 `package_id`。旧局不随新剧本变化。

#### 15.3.2 MySQL 作为权威数据源

第一版就使用 MySQL。账号、存档、当前状态、历史快照索引、日志索引、研究数据都进入 MySQL。JSON 快照只用于调试、复盘和证据保留。

必须优先实现：

- `accounts`
- `auth_sessions`
- `script_packages`
- `game_session_requests`
- `game_sessions`
- `game_snapshots`
- `game_actions`
- `action_logs`
- `dialogue_logs`
- `npc_state_evaluations`
- `event_logs`
- `decision_instances`
- `night_logs`
- `llm_call_audits`
- `npc_memories`

#### 15.3.3 账号和存档作为第一版基础能力

第一版必须有登录、自动存档、继续最近一局。

最小闭环：

```text
登录
  ↓
继续最近一局 / 新开一局
  ↓
每次行动后保存 current_snapshot_json
  ↓
写 MySQL 快照索引
  ↓
写 JSON 快照文件
  ↓
读档时以 MySQL current_snapshot_json 恢复
```

#### 15.3.4 NPC 指标采用“剧本硬结算 + LLM 受限自评”

玩家通过固定选项、突发事件选项或自主工具执行了《最终剧本》已经写明结算的操作时，旗标、人物信任度来源、显式态度/焦虑变化、签约户数、全局指标和资源消耗全部由规则引擎硬结算。LLM 读取结算结果生成角色化反馈，不得重新裁决或追加数值。

玩家在已开放机会中输入自由说服文本，且该回合没有对应的显式人物数值结算时，系统才将以下内容传给目标 NPC 的 LLM：

- 玩家输入的完整说服文本。
- NPC 固定档案。
- NPC 当前指标。
- NPC 记忆。
- 玩家行动解析结果。
- 当前世界状态。
- 相关事件和承诺。
- NPC 的红线、收益函数、知识边界。

LLM 输出固定 JSON，只判断第一档 NPC 的态度/焦虑方向和幅度档，并可提交已注册吐露、旗标、传播和主动反应候选。系统负责幅度映射、信任度派生、吐真闸门、候选核验、去重、裁剪、重试和事务提交。

本项目的核心体验仍是“玩家用文字说服 NPC”。不能用关键词表替代目标 NPC 对自由文本的态度判断；同样不能为了强调 LLM 而抹掉最终剧本已经确定的硬后果。人物信任度尤其不是 LLM 情绪分，它严格按初值 40、已开旗标增减表、锁定规则和张立特例计算。

#### 15.3.5 夜间推演采用规则和 LLM 混合

普通传播用规则处理。关键 NPC、高焦虑 NPC、暗线相关 NPC 可调用 LLM 自评。

夜间推演输出三类结果：

- 玩家不可见的完整夜间日志。
- 玩家次日可见的失真摘要。
- NPC 状态变化和事件候选。

#### 15.3.6 前端第一版使用游戏页，不复用剧本生成页

现有页面用于剧本生成和审稿。游戏需要新增页面。

第一版页面：

- 登录页。
- 游戏首页：继续游戏 / 新开一局。
- 游戏主界面：三栏布局。
- 日终结算页。
- 复盘页。

### 15.4 对美工的要求

美术需求已独立成 `art_requirement.md`，该文件是美术制作、UI 设计、前端接入和测试验收的正式依据。本文档只保留技术侧必须遵守的接入原则。

美术资源必须服务于“基层治理推演”的真实感和信息清晰度。第一版不追求高成本动画，优先保证统一风格、状态可读、剧情沉浸和程序可接入。

技术侧必须支持的美术交付范围：

- 视觉风格板和 `design_tokens.json`。
- 登录页、游戏首页、三栏主界面、日终结算页、复盘页、结局页设计。
- UI 组件和图标系统。
- NPC 头像和后续情绪差分。
- 手绘地图、SVG 交互图层和 `map_layers.json`。
- 场景背景图。
- 事件插图。
- 证据和档案图。
- 结局图。
- 加载、空状态、错误状态图。

所有资源必须进入 `assets_manifest.json`，并满足以下条件：

- 有稳定 `asset_id`。
- 有 `category`、`type`、`usage`。
- 能关联到 `npc_id`、`event_id`、`location_id`、`evidence_id` 或 `ending_id`。
- 有尺寸、格式、版本、授权、fallback 说明。
- 路径真实存在，且位于当前剧本包 `art/` 目录下。

技术侧验收标准：

- 后端能加载并校验 `assets_manifest.json`。
- 前端能按 `asset_id`、`linked_entity_id`、`usage` 和 `state` 查询资源。
- 缺失目标资源时能按 fallback 链显示默认资源。
- 旧存档继续使用开局时锁定剧本包中的旧资源。
- 地图元素能按 NPC 状态、事件状态和风险等级变色或换图标。
- 资源缺失、尺寸错误、授权字段缺失必须在剧本包兼容性测试中报错。

### 15.5 已冻结基线与仍需配置的实现项

内容规模不再作为未决问题；模型供应商、部署额度等环境项仍需在 M1 配置。

#### 15.5.1 剧本规模

- 第一版固定 29 个非玩家人物实体：县委书记蒋崇岳、23 名有九维档案的主要 NPC，以及邓守本、苗喜旺、老倔头、罗健、崔广林 5 名轻量配角；玩家李致远不是 NPC。加上玩家后，共 30 名独立人物设定，详见 `art_need_arguments.md`。
- 故事时间完整覆盖 90 天，但交互体验按六章和 `story_beats.json` 压缩到约 45 分钟；模拟日不能删剧情结算。
- 第一版内容权威是 `最终剧本.md`；v01/v02/v03 仅作为历史生成产物。
- 结局固定为 24 个主结局、95 个亚结局、3 个附加位；禁止回退为 8 个或使用综合评分。

#### 15.5.2 LLM 调用策略

- NPC 自由互动态度/焦虑评估用哪个模型。
- NPC 对话用哪个模型。
- 夜间推演哪些 NPC 调用 LLM。
- 每局最大 LLM 调用次数。
- 每局成本上限。
- 是否需要本地模型备选。

#### 15.5.3 NPC 指标 Schema

《最终剧本》第 7.4 节已基本确定第一版 Schema，不再把所有候选字段都做成可由 LLM 修改的数字。第一档 NPC 运行时最小字段为：

- `state_tier`
- `availability_mode`：由当前章节/机会计算，不能反向修改 `state_tier`。
- `profile_id`：指向不可变九维档案。
- `trust_score`：0–100，规则派生，不接受 LLM delta。
- `trust_locked`：锁定后信任度固定为 0。
- `trust_effects_applied`：已结算旗标集合，保证同一旗标只计一次，关闭旗标不回退分数。
- `attitude_score`：0–100，剧本硬结算或 LLM 受限提议。
- `anxiety_score`：0–100，剧本硬结算或 LLM 受限提议。
- `memory_id`：结构化记忆引用。
- `chapter_disclosure_used`：第四档每人每章一次吐露额度。
- `known_fact_ids`、`owned_evidence_ids`：只保存注册 ID。

参照档、从众阈值和身份标签属于固定档案；亲近感属于叙事；签/拒/观望属于派生立场，不作为 LLM 可写字段。第二档只保存专属旗标/轴状态，第三档不建立 NPCState。`petition_risk`、`mobilization_tendency`、`media_contact_willingness` 等若后续需要，必须先在剧本 Schema 中登记来源和读取点，不能先塞进 `metadata` 让模型自由写。

#### 15.5.4 签约判定

签约不读取 `signed_intent`，LLM Schema 中删除该字段。签约户数按《最终剧本》的户群和注册入账点处理：满足对应旗标、从众阈值、核心诉求及节点前置后，由 `ActionService`/`EventService` 写入“已入账”护栏旗标。D75 以前的历史硬结算在 D75 夜间归并为不可变首批快照；D76–D89 的每次新增另写一条不可重复的 `HouseholdSettlementEntry`。D75 以后聚合字段 `signed_households` 必须等于首批快照加有效追加事件，不允许脱离分批台账单独增加。

每条结算事件至少保存 `entry_id`、`household_group_id`、`household_count`、`signed_day`、`entry_batch`、`entry_type`、`source_node_id`、`policy_version`、`eligibility_registered_day`、`early_reward_paid` 和 `validity_status`。同一户群首触即锁；同一个来源节点不得突破户群上限；全局审计合计不得超过 36。

D75 采用“首批冻结、限定补签、D90 只读验收”：

1. D75 夜间先执行马长顺自然触发，再写入 `D75SettlementSnapshot`，冻结首批户数、首批奖励资格、政策版本和实名未决户群上限。
2. D76–D89 仅接受快照中登记的老倔头、苗喜旺、宁德海、邓守本、何铁柱、周大山六类可能未决户群，且只能由剧本包注册的指定节点提交。
3. 周大山 D86 路径额外要求 `周大山肯等=true`；只有 DP5-09 选项 E 可以形成该资格。选项 C、D 不自动恢复。
4. 何铁柱 D86 路径额外要求第五章存在已登记未决来源，医疗救治作为公共职责独立落实，本人真实签署后才结算。
5. D76–D89 事件必须记录真实签署日，`early_reward_paid=false`，不得倒签为 D75。
6. D90 对任何正向户数增量直接拒绝，只允许审计和终局投影。
7. 旧开发存档缺少 D75 快照时可以一次性生成带 `legacy_migrated=true` 的迁移快照以便本地回放，但正式研究存档不得使用该兼容通道。

行动点是否消耗取决于玩家发起的行动价目；编号决策点和突发事件选择恒为 0 点。预算、真实签约数与账面签约数必须分开保存。反悔只能由剧本明确登记的关闭/回退事件触发，不允许 LLM 根据一句台词自行撤销签约。

#### 15.5.5 承诺机制

需要明确：

- 玩家承诺如何被识别。
- 承诺是否需要玩家二次确认。
- 承诺如何绑定预算和行动期限。
- 未兑现承诺如何惩罚。
- NPC 如何在后续对话中提起承诺。

#### 15.5.6 夜间信息传播

需要明确：

- 社会关系矩阵由剧本生成，还是人工维护。
- 信息传播是否有概率。
- 金额传闻是否默认夸大。
- 哪些信息永远不可传播。
- 暗线证据是否可能被 NPC 转移。

#### 15.5.7 研究数据

研究数据按 16.7 节基线实施：是否采集玩家原文和 LLM 原始输出由版本化知情同意逐项控制；导出只用匿名研究 ID；`production|test|sandbox` 与 `experiment_group_id` 是必填服务端字段。未取得对应同意时不得把原文或模型原始输出写入研究数据集。

#### 15.5.8 后台管理

需要明确：

- 谁创建账号。
- 谁发布剧本包。
- 谁能查看全部存档。
- 谁能导出研究数据。
- 是否需要禁用某个剧本包。
- 是否需要重跑剧本包兼容性测试。

#### 15.5.9 美术生产边界

首版资产数量和提示词以 `art_need_arguments.md` 为准：30 名独立人物、5 类群像、24 个可复用场景、12 张关键事件插图和 24 张主结局封面。P0 先交中性头像和垂直切片资源，情绪差分按 P1/P2；地图交付 SVG 交互图层加 WebP 底图。AI 生成图是否可商用及最终授权证明仍须由项目法务/伦理流程确认，未确认的资产只能标记为 `prototype`，不得进入 `published` 包。

### 15.6 最后一轮流程检查

以下流程必须在开发前确认全部闭环。

#### 15.6.1 玩家主流程

```text
登录
  ↓
继续最近一局 / 新开一局
  ↓
读取剧本包
  ↓
进入 D1
  ↓
玩家行动
  ↓
识别固定结算 / 自由文字
  ↓
规则硬结算或 NPC LLM 受限评估
  ↓
派生信任度、校验并生成 NPC 回复
  ↓
自动存档
  ↓
日终结算
  ↓
夜间推演
  ↓
自动存档
  ↓
进入下一日
  ↓
D90 倒计时归零
  ↓
复盘
```

检查结果：当前文档已覆盖主流程。

#### 15.6.2 NPC 指标流程

```text
玩家输入或夜间来源事件
  ↓
读取 NPC 交互档级与剧本节点
  ↓
是否存在显式结算？
  ├─ 是 → 按剧本结算旗标/态度/焦虑/资源，LLM 只生成一致回复
  └─ 否 → 第一档 NPC LLM 读取完整自由文本与上下文
  ↓
LLM 仅输出态度/焦虑方向与幅度档、吐露/传播候选
  ↓
服务端映射、吐真闸门、知识边界和重复结算校验
  ↓
按已开旗标重新派生人物信任度；计算从众立场
  ↓
事务提交硬结算、LLM 有效提议、回复、日志和快照
  ↓
记录每个字段的 authority/source_id，支持复盘
```

检查结果：权威边界已覆盖。开发时仍需落地正式 JSON Schema、旗标到信任度规则表和 `metric_authority` 枚举。

#### 15.6.3 存档流程

```text
稳定状态产生
  ↓
写 MySQL current_snapshot_json
  ↓
写 game_snapshots 索引
  ↓
写 JSON 快照
  ↓
返回前端
```

检查结果：当前文档已覆盖。后续要补数据库迁移脚本和失败回滚策略。

#### 15.6.4 剧本更新流程

```text
修改剧本
  ↓
重新抽取结构化 JSON
  ↓
生成新 script_package
  ↓
运行兼容性测试
  ↓
发布新 package_id
  ↓
新局使用新包，旧局继续旧包
```

检查结果：当前文档已覆盖原则。后续要补后台发布页面和版本治理细则。

#### 15.6.5 美术接入流程

```text
根据 art_requirement.md 与 art_need_arguments.md 制作资源
  ↓
导出到 script_package/art/
  ↓
写入 assets_manifest.json、art_story_mapping.json、design_tokens.json、map_layers.json
  ↓
AssetManifestService 校验
  ↓
前端按 package_id 和 asset_id 加载
  ↓
按 NPC/事件状态切换
  ↓
复盘和结局复用
```

检查结果：技术契约以 `art_requirement.md` 为验收规范，以 `art_need_arguments.md` 为《最终剧本》对应的具体人物、场景、事件和结局生产清单；二者若冲突，以最终剧本的内容数量和禁止综合评分规则为准。

#### 15.6.6 测试流程

```text
单元测试
  ↓
服务集成测试
  ↓
API 测试
  ↓
前端 E2E
  ↓
人工试玩
  ↓
剧本包回归测试
```

2026-07-16 M2 回填结果：独立 `code/backend/tests/` 已覆盖决策状态机、90 天故事时钟、玩家 DTO 可见性、session 所有权、短事务单飞、幂等、SQLite 重启恢复、固定日锚、逐日夜间日志、地图、复盘和 D90 结局。生产账号、MySQL、研究数据治理与真实 LLM 的测试仍分别留在 M3/M4 和部署阶段补齐。

### 15.7 当前仍缺的输入

最终 NPC 名单、最终结局数量、美术风格和生产参数均已存在。真正的开工输入缺口是：

- 从 `最终剧本.md` 重新抽取并通过校验的第一版运行时剧本包，而不是历史 v01 包。
- 与 `docs/product/art_need_arguments.md` ID 对齐的成品资源、`assets_manifest.json` 和 `art_story_mapping.json`；提示词本身不是可加载美术资产。
- 可交互 SVG 地图图层及 `map_layers.json`。
- 第一版 MySQL 连接配置。
- 第一版 LLM 模型和 API 配置。
- 版本化知情同意文本、研究方案批准信息、保留期限和数据负责人。
- 后台管理页的最小权限矩阵与管理员名单。

## 16. 运行时闭环与实现补充

### 16.1 剧本运行时契约

`full_script.md` 是供人阅读和编辑的母稿；游戏运行时不得直接依赖其中的自然语言段落推断规则。每个可发布剧本包还必须提供以下结构化内容：

```text
story_beats.json                 # 关键日、事件节拍、强制事件、可快进日
interaction_opportunities.json   # 玩家获得 NPC 对话/行动机会的契约
facts.json                       # 事实、线索、证据、公开来源、关联人物和使用提示
public_briefing.json             # 五份开局卷宗、公开补偿口径、县长资源与31项工具说明
npc_profiles.json                # 角色档案、边界、收益、记忆种子、语言风格
action_rules.json                # 资源与程序规则
event_rules.json                 # 事件触发与后果
ending_rules.json                # 14 轴算法、24 行首命中表、95 亚结局和 3 个附加位
```

`interaction_opportunities.json` 的最小字段如下：

```json
{
  "opportunity_id": "opp_d51_zhou_kuiyuan_home_visit",
  "npc_id": "npc_zhou_kuiyuan",
  "entry_type": "map_visit",
  "available_when": {
    "day_min": 51,
    "day_max": 51,
    "requires_events": ["event_d51_zhou_kuiyuan_available"],
    "requires_clues": [],
    "availability_mode": "free"
  },
  "cost": {"action_points": 2, "budget": 0, "rule_id": "home_visit"},
  "conversation_scope": ["ancestral_graves", "ancestral_hall", "relocation_precedent"],
  "forbidden_topics": ["hidden_corruption_evidence"],
  "close_when": ["decision_dp4_04_resolved"],
  "on_complete": {"may_unlock": ["fact_zhou_grave_cause_known"]}
}
```

`ScriptPackageValidator` 必须在发布前校验：所有 `player_id`、`npc_id`、`event_id`、`decision_id`、`option_id`、地点、线索、结局和资源主键可解析；`art_story_mapping.json` 的引用全部存在于结构化剧本与 `assets_manifest.json`；不存在悬空前置条件；每个强制决策至少有一个可达选项、重复提交不重复结算；D1–D90 连续且自动推进不会跨过强制事件；每日基准额度为 8；D31 张立进驻、D45 撤离、D59 顾克明迎检、D90 张立主检四个在场锚点正确；所有关键日有入口；24 个主结局首命中、末行恒真且 95 个亚结局均可解析；母稿、结构化包、资产清单和内容哈希一致；第二/三档 NPC 不得声明越权数值字段；章节 `availability_mode` 不得覆盖全局 `state_tier`；除张立外不得出现直接人物信任度 delta；同一节点不得同时声明同一指标的剧本硬结算和 LLM 写权限。公开资料还必须正好包含五份背景卷宗，31 项 `tool_guidance` 必须与 `action_rules.json` 一一对应；未配置的补偿单价、面积、奖励、救助和审批额度必须列入 `unresolved_numeric_fields` 并受统一 `numeric_guardrail` 约束。

### 16.2 机会服务与玩家交互入口

新增：

```text
code/backend/src/serious_game_backend/application/interaction_opportunity_service.py
code/backend/src/serious_game_backend/domain/interaction_opportunity.py
code/backend/tests/test_runtime_services.py
```

`InteractionOpportunityService.list_available(session)` 根据当前日期、地点、事件、线索、NPC 状态、关系和冷却规则返回可用入口。前端只展示该服务返回的入口；地图图标、任务卡、来访通知、通讯录和档案追问都是同一机会模型的不同展示方式。

每个已发布互动机会还必须登记玩家可见的 `opening_narrative` 与 `conversation_goal`。前者说明本次为何能见到该人物、地点与前情如何衔接，后者只提示当前可谈方向，不泄露隐藏动机或未解锁事实。机会 DTO 还应根据当前 `known_fact_ids` 返回 `related_materials`，并始终附带公开补偿政策入口；已经掌握的材料可在会谈前和会谈中查阅，尚未解锁的事实不得因“相关”而提前暴露。发布校验要求 32 个机会全部非空；吴秀英首次会谈严格采用最终剧本中的“下村走访时在坡上偶遇、拎菜篮、老教师受人敬重”场景，巡察组 D31 与环保迎检组 D59 分别使用独立背景，禁止混用机构和时间。

#### 16.2.1 县长案头与公开政策资料

玩家从 D1 起始终可以调用 `GET /api/game/session/{session_id}/desk`，读取任务与硬约束、五份背景卷宗、补偿政策与当前财政盘、县长可调资源、31 项行动工具的用途/成本/当前可用状态，以及已掌握知识的分类计数。该接口与 `/knowledge` 都属于玩家可见 DTO，不返回隐藏旗标、NPC 精确信任、内部结算 delta 或未解锁事实。

`/knowledge` 必须按事实、线索、证据分组；每条记录至少包含正文、玩家可见来源和可使用方向，不能只返回标题。补偿政策不是待解锁事实，而是玩家作为专班指挥长默认持有的工作底册。当前母稿只锁定 90 天、36 户、30 户、500 米、8000/6000/2000 万元、2 亿元年税测算和 200 万元前期协调费等数字；每平方米、每亩、搬家与过渡、安置房、奖励、迁坟、救助及审批权限等参数，在正式细则补全前不得由代码或 LLM 推算。待确认字段统一记录在 `code/backend/docs/01_玩法与行动/01_补偿政策待确认数字.md`。

真实角色回合必须注入与玩家界面同源的 `player_reference_materials`。NPC 可以按自身身份对公开政策和玩家已掌握材料作出反应，但不得把案头异常自动当成已证实秘密，也不得编造尚未配置的补偿数字或替县长作出口头金额承诺。

调用流程：

```text
GET /api/game/session/{session_id}/opportunities
  ↓
玩家选择 opportunity_id 和目标 NPC，读取前情提要并确认进入
  ↓
POST /action 使用第 7.2 节唯一契约，携带 input_mode、client_action_id、state_version 及该模式必填字段
  ↓
服务端再次验证机会仍可用并锁定本次操作
  ↓
只在进入会谈时扣一次行动点并建立 active_conversation

同一 conversation_id 下循环执行 NPC 回合，不再扣行动点

玩家主动结束，或 NPC 返回 end 与人物化离场叙事

结束时一次性提交完成事实/旗标/硬结算并解锁或关闭后续机会
```

这保证玩家获得 LLM 交互机会的来源是剧本和当前状态，而不是前端任意开放的聊天框；同时允许玩家通过信任、证据、事件和地图探索逐步打开新的角色与话题。

### 16.3 原子 NPC 回合

当前的 `NPCStateEvaluationService` 与 `DialogueService` 逻辑上属于同一回合，不能分别独立调用后再拼接，否则可能出现“指标说拒绝、台词却同意”的矛盾。第一阶段应增加门面服务：

```text
src/services/npc_turn_service.py
```

`NPCTurnService` 先读取剧本结算声明和指标权威，再决定是否需要模型评估。固定选项/自主工具有显式结算时，服务端先形成硬结算草案，模型只生成与草案一致的角色台词、记忆候选和传播意图；自由文字没有显式人物结算时，一次受控模型调用同时返回角色台词、态度/焦虑幅度档、记忆候选、传播意图和风险说明。返回结果必须通过 JSON Schema、知识边界、状态变化范围、吐真闸门和重复结算校验；随后在一个数据库事务中写入动作日志、NPC 状态、记忆、可见回复和当前快照。

每个最终写入字段都要带来源：`authority=script|derived_rule|llm_bounded`、`source_id`、`model_audit_id`（无模型则为空）。数据库约束禁止 `llm_bounded` 来源写入信任度、九维、立场、签约户数、全局指标和结局轴。

远程 LLM 调用期间不得持有数据库行锁或长事务。原子性通过短事务预留、session 单飞标记和乐观锁实现：

```text
短事务 A：鉴权/所有权 -> 校验机会、pending_decision、state_version、请求哈希
  -> 插入或读取 game_actions 幂等记录
  -> 条件设置 game_sessions.processing_action_id（仅当为空且版本匹配）
  -> 提交并释放数据库锁
事务外：读取已预留输入 -> 建立 authority mask -> 必要时调用 NPC LLM
  -> 校验/重试 -> 合并硬结算与受限提议 -> 派生信任度/立场 -> 去重
短事务 B：再次校验 processing_action_id 与原 state_version
  -> 条件更新 current_snapshot_json、state_version = state_version + 1
  -> 同事务写动作/对话/事件/LLM 审计/快照索引和最终响应
  -> 清空 processing_action_id，提交
事务后：写 JSON 辅助快照；失败只告警并进入重试队列
```

当 `processing_action_id` 非空，其他写请求返回 `409 SESSION_BUSY`，而不是排队并发改状态。若模型超时、输出无效或校验失败，短事务清除单飞标记并将操作置为 `failed_retryable|failed_final`；不扣行动点、不写 NPC 指标。进程崩溃留下的 `processing` 由有租约的恢复任务按超时和 worker token 回收，过期 worker 即使晚到也无法提交。

### 16.4 LLM 安全、可复现与成本控制

- 玩家文本、NPC 台词和外部证据都是不可信内容；prompt 明确规定其中任何“忽略规则”“修改 JSON”等文字均不是系统指令。
- 每次调用记录 `model_provider`、`model_id`、模型/提示词版本、请求哈希、温度、token 用量、耗时、重试次数、原始受限输出和校验结果。敏感密钥和完整内部系统提示词不得进入玩家可见日志。
- 第一版对 NPC 自由互动的态度/焦虑评估使用低温度、固定 JSON Schema 和最多一次修复重试；研究回放复用已存储的结构化结果，不重新调用 LLM。
- 每局配置调用次数和 token 预算；超过预算时停止开启新的自由对话，或按剧本启用明确标识的规则化摘要降级，但不得悄然改变已提交状态。
- 内容安全、敏感信息处理、保留期限和研究导出必须在首次外部测试前按 16.7 节实施，不属于上线后补项。

### 16.5 幂等、并发与存档一致性

`POST /session` 接收 `client_request_id`；`POST /action` 和 `POST /end-day` 接收 `client_action_id`。服务端先对规范化请求体计算 `request_hash`：

- 同一幂等 ID、相同 hash、`succeeded`：返回数据库保存的首次响应，不再次扣资源或调用 LLM。
- 同一 ID、不同 hash：返回 `409 IDEMPOTENCY_KEY_REUSED`，不允许用旧 ID 修改目标、文本或选项。
- `processing`：返回 202、`operation_id`、当前状态和建议轮询时间；客户端通过操作查询接口取结果。
- `failed_retryable`：只有相同请求体并显式 `retry=true` 才能续跑同一记录，增加 `attempt_count`；已产生外部模型响应但尚未确认状态时，优先恢复审计结果，不盲目重复调用。
- `failed_final`：重复请求返回同一终态错误；玩家修改请求必须换新 ID。
- 新开局用 `account_id + client_request_id` 唯一约束和相同 hash 规则，双击只能得到同一局。

`game_sessions.state_version` 已纳入第十二章 DDL；所有写入条件包含当前版本。两个浏览器标签或网络重试同时提交时，只有一个成功，另一个返回冲突并要求刷新。MySQL 当前快照、操作日志和历史快照索引必须处于同一事务；JSON 文件写入失败只记录告警并重试，不得回滚已合法提交的数据库状态。

第十二章已将以下表纳入首版 DDL，不再视为可选建议：

```text
game_actions       # client_action_id、输入摘要、机会、处理状态、最终响应索引
llm_call_audits    # 可复现和成本审计字段
npc_memories       # 结构化记忆、来源 turn、可见性和过期/失效标记
```

### 16.6 实现顺序修正

原 M1 只做规则原型不足以验证核心玩法。建议顺序调整为：

1. M0：确定上述剧本 schema、版本治理、状态事务和 测试范围内的确定性 LLM 替身契约。
2. M1：实现 `InteractionOpportunityService`、单 NPC 原子回合、存档和一条从 D1 到小结局的垂直切片。
3. M2：扩展白天、事件、夜间、地图入口、复盘和完整剧本包校验。
4. M3：接入真实 LLM、成本控制、记忆压缩与对抗难度。
5. M4：研究后台、实验分组、匿名导出与权限体系。

这样可最早验证“玩家文字 -> NPC LLM 态度判断 -> 系统提交 -> 新机会”的游戏核心，而不是先做大量固定行动后再回头替换结算逻辑。

截至 2026-07-19，独立游戏代码区 `code/` 的实现状态如下。状态只按各里程碑正式范围计数；代码完成不替代正式研究制度、伦理审批或生产环境验收。

| 里程碑 | 正式范围 | 当前状态 |
|---|---|---|
| M0 | 剧本 Schema、版本治理、状态事务、测试范围内的确定性 LLM 替身契约 | 完成 |
| M1 | 互动机会、单 NPC 原子回合、持久化存档、首条完整垂直切片 | 完成 |
| M2 | 扩展白天、事件、夜间、地图入口、复盘、完整剧本包校验 | 完成 |
| M3 | 接入真实 LLM、成本控制、记忆压缩、对抗难度 | 完成 |
| M4 | 研究后台、实验分组、匿名导出、权限体系 | 进行中（代码基线完成，外部治理与生产验收待办） |

M0 的状态事务已经按“短预留 -> 锁外执行 -> 短提交”实现；SQLite 中 session 状态与幂等操作记录同事务提交，任一写入失败整体回滚，不在 LLM 调用期间持有数据库锁。M1 已完成五种出身、D1 条件叙事、吴秀英首次互动、测试范围内的确定性 LLM 替身受限提交、重启恢复和 D3 收束。M2 已接通六章 D1–D90，装载 62 个 DP、14 个 EV 和 4 个配套运行节点，登记 29 名 NPC 的 32 个互动机会、18 条事实/线索、29 个夜间/次日文本块、9 条条件夜间结算、8 个地图地点、玩家可见复盘以及带正文的 24/95/3 结局结构。M3 已完成真实角色 LLM、成本、记忆、安全与完整回放。M4 已落地 MySQL 生产适配、Cookie/CSRF/RBAC、版本化同意、PII 最小化、字段加密、服务端实验分组、研究 outbox、双人审批匿名导出、数据主体请求、保留期清理和特权审计；正式研究制度与类生产部署验收仍未完成。详细口径记录在 `code/MILESTONES.md`、`code/backend/docs/04_验收与治理/01_M2剧本语义闭环.md` 与 `code/backend/docs/04_验收与治理/02_M4研究与生产治理基线.md`。

### 16.7 数据治理与研究合规基线

账号、玩家原文、LLM 原始输出、行为序列和实验分组均属于受控数据。首次招募外部玩家前必须具备以下基线；不能以“研究用途”为由跳过：

| 主题 | 首版强制要求 |
|---|---|
| 知情同意 | 保存 `consent_version`、用途、采集字段、是否发送第三方模型、保留期、退出方式、签署时间与撤回时间；运营存档与研究采集分开勾选。未同意研究采集仍可按产品政策游玩时，只记录维持服务所必需的数据。 |
| 身份隔离 | 账号表与研究表使用不同权限；研究侧只见随机 `research_subject_id`，不得导出用户名、Cookie、IP 或直接账号 ID。 |
| 原文与模型输出 | 运行时确有必要的原文进入加密业务库；另生成脱敏副本供分析。未获原文研究同意时，研究层只保留结构化特征。发送模型前执行个人信息检测与最小化，并在同意文本中列明供应商和区域。 |
| 保留期限 | 默认原始玩家文本和 LLM 原始输出 180 天、可识别账号/存档至账号删除或最后活跃后 24 个月；匿名聚合结果按获批研究方案保存。项目可缩短，延长必须更新同意与审批。到期任务需可审计。 |
| 删除与导出 | 玩家可申请导出自己的玩家可见存档并删除账号；删除任务清除或不可逆匿名化业务、缓存、对象存储和待处理队列中的个人数据，备份按既定周期到期。受法定/科研完整性保留约束的记录只留最小匿名审计字段并告知原因。 |
| 加密与密钥 | 全程 TLS；数据库、对象存储、备份和包含原文的 JSON 辅助快照静态加密；密钥进密钥管理系统并轮换，禁止写入仓库或日志。高敏原文/模型输出使用字段级加密。 |
| 权限与审计 | 玩家、研究员、内容编辑、运维、管理员分权；原文查看、批量导出、跨账号检索和删除均需专门权限、理由、审批记录和不可篡改审计日志。 |
| 实验隔离 | `environment=production|test|sandbox`、`experiment_id`、`experiment_group_id`、包哈希、模型/提示词版本由服务端分配并锁定；不同实验的数据集、导出和统计默认隔离，测试账号不得混入正式样本。 |

研究导出采用字段白名单、最小样本门槛和重识别风险检查。任何 CSV/JSON 导出都生成数据集版本、查询条件、同意过滤结果、操作者、用途、时间和文件哈希；禁止研究员直接复制生产数据库。

### 16.8 当前工作区基线与开工门槛

2026-08-02 整理结果：旧剧本生成、修订、展示代码及历史生成草稿已从版本库移除。根目录只保留权威 `最终剧本.md`；产品代码位于 `code/`，设计与开发资料位于 `docs/`。

`code/` 已形成可执行的 M0–M3 本地文字运行时：v2 状态、8 点行动制、玩家 DTO 隔离、内容哈希锁定、幂等与乐观锁、SQLite 原子事务、持久化存档、真实 LLM、调用审计、NPC 记忆、D1–D90 故事时钟、事件/决策、夜间模拟、地图、复盘与终局全文均有自动化验收。文字客户端默认使用全流程编号菜单，原始命令模式只保留为开发入口。NPC 会谈使用 `role-turn-v2`：32 个入口均有前情，进入时扣点一次，会谈内不限轮次，玩家或 NPC 明确离场后才做机会完成结算。失败即停的真实 `qwen3.6-plus` 已完成 D1–D90 回放、31 个可调用 NPC 机会全量角色矩阵、4 类真实提示词对抗测试，以及正常续谈/越过底线自主离场的真实会谈验证。

1. M3 已完成真实供应商 D1–D90 回放签字；后续只需在生产部署前落实第三方服务商 SLA、余额告警、并发限额、数据治理和密钥轮换。
2. MySQL 生产适配器、Cookie 登录、CSRF、会话安全与迁移代码已经落地；正式部署前仍需完成真实 MySQL/KMS、备份恢复与并发演练。SQLite 可启用本地 Cookie 注册登录，`X-Account-ID` 只保留为显式关闭认证时的兼容沙盒边界。
3. M4 研究后台、实验分组、匿名导出、权限与数据治理代码基线已经落地，正式制度与生产验收仍待完成。
4. 正式图形前端等待美术和交互方案冻结后，在 `code/frontend/` 下另建，不复用根目录旧前端。

只有 M4、生产安全适配和正式图形前端对应的首发范围完成并通过验收后，才可把当前工程称为生产首发版；当前是已完成 M0–M3 的本地文字运行时，不是生产首发版。
