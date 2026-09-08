# 《浊流之上》后端

这是游戏的权威后端工程。M0–M3 已完成：D1–D90 权威运行时、Qwen/OpenAI 兼容网关、结构化输出、调用审计、预算、NPC 记忆和失败即停的真实模型调用均已通过自动化与真实供应商回放验收。

## 目录

```text
code/backend/
  content/packages/       # 外置、版本化剧本包配置
  docs/                   # 玩家 API 与终端文字协议
  migrations/             # MySQL 迁移基线
  src/serious_game_backend/
    api/                   # FastAPI 与玩家可见 DTO
    application/           # 用例服务与端口
    domain/                # 不依赖框架的权威领域模型
    infrastructure/        # SQLite/内存适配器、文件剧本包、真实 LLM
  tests/                   # 独立后端测试
```

## 本地运行

在 `code/backend` 下执行：

```powershell
python -m pip install -r requirements-dev.txt
$env:PYTHONPATH = "src"
python run_server.py --reload
```

接口文档：`http://localhost:8100/docs`。

操作预留租约默认 300 秒，可通过 `OPERATION_LEASE_SECONDS` 调整。服务启动时会回收超过该期限且仍处于 processing 的操作。

当前默认使用 SQLite 持久化仓储和 `X-Account-ID` 沙盒身份头。数据库默认写入 `code/backend/data/serious_game.db`，后端重启后可用终端的 `continue` 或 `load` 继续已提交的存档。测试可设置 `GAME_REPOSITORY=memory` 使用内存仓储。正式环境必须使用已实现的 MySQL 仓储、服务端 Cookie 登录、CSRF 与 RBAC；`X-Account-ID` 在 production 中无效，所有游戏存取继续按 `session_id + account_id` 校验所有权。

本地需要测试真实账号流程时设置 `AUTH_REQUIRED=true`、`ALLOW_SELF_REGISTRATION=true` 和 `AUTH_COOKIE_SECURE=false`。此时可调用 `POST /api/auth/register` 自助注册，注册成功即建立 Cookie 会话；后续使用 `/api/auth/login`、`/api/auth/logout` 和 `/api/auth/me`。正式环境强制关闭无限制自助注册，只允许通过受控账号或后续邀请码流程入场。

## 当前已落地的规则

- 新局锁定 `package_id + package_version + package_content_hash`。
- v2 GameState：每日基准 8 行动点、90 天、36 户、8000 万元及十项全局指标。
- 31 项自主工具从剧本包读取预计算的常态/敏感/验收实耗，决策和突发事件不扣点。
- 行动点与疲惫正交；剩余行动点不跨日；日终按疲惫档重发 8/7/6/5 点。
- D31、D45、D59、D90 四个固定时间锚点独立触发。
- 幂等请求哈希、`state_version` 乐观锁和 session 单飞字段；session 与操作记录同事务提交。
- 真实角色回合在 Web 事件循环之外运行；模型生成期间健康检查和幂等操作查询保持可响应。终端超时后凭原 `client_action_id` 回查，不重复提交玩家发言。模型不可用时明确返回错误，不生成替代台词。
- 玩家 DTO 只暴露四项精确台账和五项文字档位，不下发暗档、人物信任度、flags 或完整快照。
- 角色 LLM 使用 `RoleLLMGateway`，产品运行时只接入 OpenAI 兼容真实网关；测试替身仅位于 `tests/`。
- 真实网关具备严格结构校验、调用审计、请求级幂等复用、次数/Token 上限、瞬时重试及超时降级；401/403 禁止重试和伪降级。
- NPC 记忆具备持久化、检索、压缩、TTL 过期和显式失效机制；指令型候选不会写入记忆。
- 增量叙事 feed、待决策阻塞状态和统一的三模式 `/action` 契约。
- 五种开局出身协议，以及按出身筛选的 D1 条件叙事。
- D1 EV1-01、D2 DP1-01、吴秀英首次自由文字互动、受限状态变化和事实披露。
- D3“派系图成形”阶段收束，并开放周大山后续互动机会。
- D1–D90 六章故事时钟、62 个编号决策、14 个突发事件和 1 个支撑决策的统一待决策队列。
- 模拟日自动推进与 D1–D89 逐日夜间日志；D31、D45、D59、D90 锚点纳入回放测试。
- 8 个玩家可见地图入口、只读复盘接口和 session 所有权隔离。
- D90 冻结终局状态，投影 14 条轴并按顺序解析 24 个主结局、95 个亚结局和 3 个附加位。
- 完整剧本包发布校验：母稿哈希、90 天日历、80 个运行决策、32 个互动机会、事件/旗标/地图引用和 24/95/3 结局结构。
- SQLite 显式 JSON 存档、操作/新局幂等记录、乐观锁和重启恢复。
- 每次成功状态提交追加不可变历史快照；SQLite/MySQL 共用时间线与哈希校验语义。
- 1–5 号手动存档槽位只更新快照指针，覆盖不会删除旧快照。
- 加载历史快照会创建新时间线并继续递增 `state_version`，不会回退并发版本。
- 启动时回收超时的 processing 操作租约，释放 session 并要求客户端显式重试。
- 结构化剧情块使用稳定 `content_instance_id` 服务端去重；夜间文本不会在晨间卡再次复制。
- `GET /view?after=N` 为文字客户端提供玩家状态、增量文本和服务端命令门禁。
- `GET /health/live` 发布终端协议版本；旧后端进程未重启时，新终端会停止进入游戏并给出明确重启提示。

## 当前里程碑边界

M0–M3 已完成。M4 的可测试代码基线已落地，但正式制度文本、生产资源和类生产验收尚未完成，因此 M4 状态仍为进行中。详见 `../MILESTONES.md`、`docs/02_NPC与AI/01_M3角色LLM运行时.md` 与 `docs/04_验收与治理/02_M4研究与生产治理基线.md`。

- 正式 MySQL/KMS 环境的迁移、恢复、并发和删除演练。
- 第三方供应商生产级 SLA、余额告警、数据治理及正式密钥轮换。
- 正式图形前端；当前只有同级 `code/frontend/terminal/` 文字测试客户端，不得复用仓库根目录的旧 `frontend/`。

后端文档总导航见 [docs/README.md](docs/README.md)。M2 协议详见 [终端文字协议](docs/03_API与终端/01_M2终端文字协议.md)。文字客户端见 [code/frontend/terminal](../frontend/terminal/README.md)。

## 测试

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests -q
```

## 手动存档 API

```text
GET  /api/game/session/{session_id}/manual-saves
POST /api/game/session/{session_id}/manual-saves
POST /api/game/session/{session_id}/load-snapshot
```

加载操作必须提交 `confirmed=true`。所有接口校验账号归属、幂等键、
当前 `state_version`、剧本包内容哈希和快照哈希。
