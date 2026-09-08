# 《浊流之上》全量完善与验收 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立并执行一套只以全量结果为准的质量体系，完整覆盖 v3 的 D1–D90、全部发布内容、全部核心机制、24 个主结局、95 个子结局与真实 API 玩家体验。

**Architecture:** 由内容包自动生成稳定 ID 覆盖契约，以合法 API 操作产生 D1–D90 见证路线；自动测试、真实 API、浏览器体验和视觉证据分别运行，再由单一聚合器判定是否达到发布门槛。局部测试只用于开发反馈，每个任务结束时都运行 Backend/Web/Terminal 全量门，最终再运行全部真实路线与浏览器矩阵。

**Tech Stack:** Python 3.11、FastAPI、pytest、SQLite、Node.js 22.13+、React 19、Vinext、Node test runner、Playwright、PowerShell、GitNexus MCP、Codex Browser MCP。

**Spec:** `docs/superpowers/specs/2026-08-27-full-game-validation-design.md`

## Global Constraints

- 最终验收必须覆盖 D1–D90；D1–D20、单文件测试或单一路线不得作为完成证据。
- 每个独立修改任务结束时必须执行 Backend、Web、Terminal 全量测试；任一失败均不得进入下一任务。
- 真实玩家验收必须使用 `openai_compatible`，并设置 `ROLE_LLM_FALLBACK_TO_FAKE=false`。
- 真实验收中的 Fake、模板降级和静默回退计数必须为零。
- 单元测试可使用确定性协议桩，但不得计入真实体验结果。
- 禁止直接修改数据库、伪造存档或补写结局状态来制造覆盖。
- API Key 不得写入源码、数据库、日志、存档、快照、浏览器存储、截图或报告。
- v2 内容目录保持逐字节不变；v3 内容发生变化时必须更新版本与内容哈希。
- 保留工作区已有用户改动；每次提交只暂存当前任务的精确文件，不合并、不推送。
- 当前硬基线：90 日、24 主结局、95 子结局、18 事实、27 获取路径、11 档案、32 人物机会、29 NPC、8 地图地点、6 强制会谈、36 户。
- 视觉验收尺寸固定为 1920×1080、1366×768、390×844。

## 文件结构

```text
code/backend/
├── content/packages/pkg_gameplay_v3/
│   ├── facts.json                         # 线索及获取方式
│   ├── story_acceptance_matrix.json       # D1-D90 展示契约
│   └── package_manifest.json              # v3 版本与哈希
├── tools/full_acceptance/
│   ├── __init__.py
│   ├── coverage_contract.py               # 从内容包生成覆盖项
│   ├── evidence_store.py                  # 脱敏证据写入与校验
│   ├── ending_witnesses.py                # 合法结局见证路线发现与校验
│   └── report.py                          # 汇总发布门槛
├── tools/
│   ├── run_full_test_gate.ps1             # 三端全量自动测试门
│   ├── run_full_acceptance.py             # 全量真实 API 总入口
│   ├── run_real_v3_routes.py              # D1-D90 真实路线执行器
│   └── run_real_feature_workflows.py      # 全功能真实工作流
└── tests/
    ├── test_full_acceptance_contract.py
    ├── test_ending_witnesses_v3.py
    └── test_real_runner_contract.py

code/frontend/web/
├── e2e/
│   ├── full-game.spec.ts                  # 网页全流程与证据采集
│   └── visual-matrix.spec.ts              # 三尺寸视觉矩阵
├── playwright.config.ts
└── tests/full-acceptance-wiring.test.mjs

docs/testing/
├── baselines/pkg_gameplay_v2.sha256.json  # v2 字节基线
└── full-game-acceptance-report.md          # 最终报告

output/full-acceptance/<run-id>/            # 不提交的运行证据
```

---

### Task 1: 固化发布包覆盖契约

**Files:**
- Create: `code/backend/tools/full_acceptance/__init__.py`
- Create: `code/backend/tools/full_acceptance/coverage_contract.py`
- Create: `code/backend/tests/test_full_acceptance_contract.py`
- Read: `code/backend/content/packages/pkg_gameplay_v3/*.json`

**Interfaces:**
- Consumes: `FileScriptPackageLoader.load(Path) -> ScriptPackage`
- Produces: `build_coverage_contract(package: ScriptPackage) -> CoverageContract`
- Produces: `CoverageContract.to_dict() -> dict[str, object]`

- [ ] **Step 1: 写覆盖契约失败测试**

```python
def test_published_v3_full_acceptance_inventory_is_complete():
    package = FileScriptPackageLoader().load(PACKAGE_ROOT / "pkg_gameplay_v3")
    contract = build_coverage_contract(package)
    assert contract.counts == {
        "story_days": 90,
        "main_endings": 24,
        "sub_endings": 95,
        "facts": 18,
        "fact_acquisition_methods": 27,
        "archives": 11,
        "interaction_opportunities": 32,
        "npcs": 29,
        "map_locations": 8,
        "households": 36,
    }
    assert not contract.invalid_items
    assert len(contract.required_evidence_ids) == len(set(contract.required_evidence_ids))
```

- [ ] **Step 2: 运行 Backend 全量测试并确认新测试失败**

Run:

```powershell
cd code/backend
$env:PYTHONPATH = "src"
python -m pytest -q
```

Expected: 全量测试以 `ModuleNotFoundError: tools.full_acceptance` 或缺少 `build_coverage_contract` 失败。

- [ ] **Step 3: 实现不可变覆盖类型与内容发现**

```python
@dataclass(frozen=True, slots=True)
class CoverageItem:
    coverage_id: str
    category: str
    source_id: str
    required_evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CoverageContract:
    counts: dict[str, int]
    items: tuple[CoverageItem, ...]
    invalid_items: tuple[str, ...]

    @property
    def required_evidence_ids(self) -> tuple[str, ...]:
        return tuple(
            f"{item.coverage_id}:{evidence}"
            for item in self.items
            for evidence in item.required_evidence
        )
```

`build_coverage_contract` 必须直接遍历包内日期、结局、事实获取路径、档案、人物机会、NPC、地图和户表；不得维护第二份手工 ID 清单。每项生成稳定键，例如 `fact-route:<fact_id>:<route_type>:<source_id>`。

- [ ] **Step 4: 增加引用一致性断言**

覆盖测试同时断言：每条获取路径指向真实来源；每个结局 ID 唯一；日期恰为 1–90；每个地图地点至少有行动卡；每户存在稳定户号和签约人。

- [ ] **Step 5: 运行 Backend、Web、Terminal 全量门**

```powershell
cd code/backend
$env:PYTHONPATH = "src"
python -m pytest -q
cd ../frontend/web
npm test
npm run lint
cd ../terminal
$env:PYTHONPATH = "."
python -m pytest -q
```

Expected: 三端全部通过，无 deselected 测试。

- [ ] **Step 6: 精确提交**

```powershell
git add code/backend/tools/full_acceptance/__init__.py `
  code/backend/tools/full_acceptance/coverage_contract.py `
  code/backend/tests/test_full_acceptance_contract.py
git diff --cached --check
git commit -m "test: define full v3 acceptance inventory"
```

---

### Task 2: 建立脱敏证据存储和严格发布判定

**Files:**
- Create: `code/backend/tools/full_acceptance/evidence_store.py`
- Create: `code/backend/tools/full_acceptance/report.py`
- Modify: `code/backend/tests/test_full_acceptance_contract.py`

**Interfaces:**
- Consumes: `CoverageContract`
- Produces: `EvidenceStore.record(coverage_id, evidence_type, artifact_path, metadata)`
- Produces: `build_release_report(contract, evidence_store) -> ReleaseReport`

- [ ] **Step 1: 写缺失证据、假证据和密钥泄漏失败测试**

```python
def test_release_report_refuses_missing_fake_or_secret_evidence(tmp_path):
    store = EvidenceStore(tmp_path)
    store.record("route:ending_01", "audit", "audit.json", {
        "provider": "fake",
        "api_key": "sk-forbidden-example-value",
    })
    report = build_release_report(minimal_contract(), store)
    assert report.publishable is False
    assert "fake_provider" in report.blockers
    assert "secret_material" in report.blockers
    assert "missing_evidence" in report.blockers
```

- [ ] **Step 2: 运行 Backend 全量测试并确认失败**

Run: `python -m pytest -q` from `code/backend` with `PYTHONPATH=src`.

Expected: 缺少 `EvidenceStore` 或 `build_release_report`。

- [ ] **Step 3: 实现只追加证据清单**

每条记录写为 `manifest.jsonl`，字段固定为：

```python
{
    "coverage_id": coverage_id,
    "evidence_type": evidence_type,
    "artifact_path": relative_artifact_path,
    "sha256": sha256_bytes,
    "recorded_at": utc_iso8601,
    "metadata": redact(metadata),
}
```

`redact` 必须递归删除键名包含 `api_key`、`authorization`、`cookie`、`secret`、`token` 的值，并拒绝正文中匹配密钥模式的字符串。

- [ ] **Step 4: 实现发布判定**

`ReleaseReport.publishable` 仅在以下条件同时成立时返回真：所有 `required_evidence_ids` 均命中存在且哈希可复算的文件；Fake 计数为零；失败调用为零或明确标记为已按同状态恢复；没有密钥；没有控制台未归因错误；没有未覆盖项。

- [ ] **Step 5: 执行三端全量门**

运行 Task 1 Step 5 的全部命令。Expected: 全部通过。

- [ ] **Step 6: 精确提交**

```powershell
git add code/backend/tools/full_acceptance/evidence_store.py `
  code/backend/tools/full_acceptance/report.py `
  code/backend/tests/test_full_acceptance_contract.py
git diff --cached --check
git commit -m "test: require auditable acceptance evidence"
```

---

### Task 3: 建立一键全量自动测试门

**Files:**
- Create: `code/backend/tools/run_full_test_gate.ps1`
- Create: `code/backend/tools/hash_content_tree.py`
- Create: `code/backend/tools/check_secret_leaks.py`
- Create: `docs/testing/baselines/pkg_gameplay_v2.sha256.json`
- Create: `code/backend/tests/test_full_gate_contract.py`

**Interfaces:**
- Produces: `run_full_test_gate.ps1 -EvidenceRoot <absolute path>`，失败时返回非零退出码
- Produces: `hash_content_tree.py <path> --compare <baseline>`
- Produces: `check_secret_leaks.py <repo-root> --evidence-root <path>`

- [ ] **Step 1: 写门禁脚本契约测试**

```python
def test_full_gate_contains_every_required_command():
    text = FULL_GATE.read_text(encoding="utf-8")
    for command in (
        "python -m pytest -q",
        "npm test",
        "npm run lint",
        "BEGIN.BAT --check",
        "hash_content_tree.py",
        "check_secret_leaks.py",
    ):
        assert command in text
    assert "-k " not in text
    assert "--test-name-pattern" not in text
```

- [ ] **Step 2: 运行 Backend 全量测试并确认失败**

Expected: `run_full_test_gate.ps1` 不存在。

- [ ] **Step 3: 生成并冻结 v2 文件哈希基线**

`hash_content_tree.py` 必须按相对路径排序，对每个文件记录 SHA-256 与字节数。基线来源只能是当前已加载且全量测试通过的 `pkg_gameplay_v2`，不得从 v3 推导。

- [ ] **Step 4: 实现 PowerShell 全量门**

脚本顺序固定：

```powershell
$ErrorActionPreference = "Stop"
cmd /c "BEGIN.BAT --check"
Push-Location code/backend
$env:PYTHONPATH = "src"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python tools/hash_content_tree.py content/packages/pkg_gameplay_v2 --compare ../../docs/testing/baselines/pkg_gameplay_v2.sha256.json
python tools/check_secret_leaks.py ../.. --evidence-root $EvidenceRoot
Pop-Location
Push-Location code/frontend/web
npm test
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
npm run lint
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Pop-Location
Push-Location code/frontend/terminal
$env:PYTHONPATH = "."
python -m pytest -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Pop-Location
```

每段 stdout/stderr 同时写入 `$EvidenceRoot/full-test-gate/`，日志文件名带 UTC 时间，不吞掉退出码。
密钥扫描只读取 `git ls-files` 返回的受版本控制文件以及本轮证据目录；不得读取被 Git 忽略的本地 `.env`，避免把合法的本机服务器配置复制进输出。

- [ ] **Step 5: 从仓库根目录实际运行门禁**

```powershell
powershell -ExecutionPolicy Bypass -File code/backend/tools/run_full_test_gate.ps1 `
  -EvidenceRoot output/full-acceptance/gate-bootstrap
```

Expected: Backend、Web、Lint、Terminal、启动器、v2 哈希和密钥扫描全部通过。

- [ ] **Step 6: 精确提交**

```powershell
git add code/backend/tools/run_full_test_gate.ps1 `
  code/backend/tools/hash_content_tree.py `
  code/backend/tools/check_secret_leaks.py `
  code/backend/tests/test_full_gate_contract.py `
  docs/testing/baselines/pkg_gameplay_v2.sha256.json
git diff --cached --check
git commit -m "test: add repository-wide release gate"
```

---

### Task 4: 完成 18 项事实的 27 条获取路径验收

**Files:**
- Modify: `code/backend/content/packages/pkg_gameplay_v3/facts.json`
- Modify: `code/backend/src/serious_game_backend/domain/story.py`
- Modify: `code/backend/src/serious_game_backend/infrastructure/script_packages/file_loader.py`
- Modify: `code/backend/src/serious_game_backend/api/app.py`
- Modify: `code/frontend/web/app/lib/player-ui.ts`
- Modify: `code/frontend/web/app/GameShell.tsx`
- Modify: `code/frontend/web/app/globals.css`
- Modify: `code/backend/tests/test_script_package.py`
- Modify: `code/backend/tests/test_archive_investigation_transactions_v3.py`
- Modify: `code/frontend/web/tests/player-ui.test.mjs`

**Interfaces:**
- Consumes: `FactDefinition.acquisition_methods`
- Produces: `GET /api/game/session/{session_id}/knowledge` 中的 `investigation_leads`
- Produces: `investigationLeadView(raw) -> InvestigationLead[]`

- [ ] **Step 1: 固化全部路径加载测试**

```python
def test_every_fact_route_maps_to_an_authoritative_source():
    package = load_v3()
    assert sum(len(f.acquisition_methods) for f in package.facts.values()) == 27
    assert sum(m["route_type"] == "archive" for f in package.facts.values() for m in f.acquisition_methods) == 11
    assert sum(m["route_type"] == "conversation" for f in package.facts.values() for m in f.acquisition_methods) == 16
```

测试继续核对档案必须授予对应 `fact_id`，会谈机会必须在 `allowed_fact_ids` 或 `completion_fact_ids` 中包含对应事实，开放日在真实窗口内。

- [ ] **Step 2: 写逐路径事务测试**

对 11 条档案路径逐条验证首次查阅、精力扣除、事实写入、重读免费、重复请求幂等、保存载入；对 16 条会谈路径逐条验证正确 NPC、可披露边界、成功写入、错误 NPC 不得披露、保存载入。

- [ ] **Step 3: 写未来信息和玩家安全 DTO 测试**

```python
assert future_fact_id not in lead_ids_before_unlock
assert future_fact_id in lead_ids_at_unlock
assert "source_id" not in json.dumps(response.json()["investigation_leads"])
```

- [ ] **Step 4: 实现或修正路径、加载校验、知识接口和前端调查方向**

前端只显示当前可达且尚未获得的方向；已掌握事实继续显示来源、证据等级和用途；内部来源 ID、隐藏旗标和未来开放日不得泄露。

- [ ] **Step 5: v3 有内容变化时更新版本和哈希**

版本采用 `3.5.1-clue-acquisition` 或当前更高的兼容版本。使用 `FileScriptPackageLoader.compute_content_hash` 计算，不手工猜测。

- [ ] **Step 6: 执行一键全量自动测试门**

```powershell
powershell -ExecutionPolicy Bypass -File code/backend/tools/run_full_test_gate.ps1 `
  -EvidenceRoot output/full-acceptance/task-04
```

Expected: 全部通过，v2 哈希不变。

- [ ] **Step 7: 精确提交**

只暂存上方列出的事实获取相关文件，检查 `git diff --cached --name-only` 后提交：

```powershell
git commit -m "feat: make every clue acquisition route reachable"
```

---

### Task 5: 验证 D1–D90 剧情、决策与人物出现顺序

**Files:**
- Modify: `code/backend/content/packages/pkg_gameplay_v3/story_acceptance_matrix.json`
- Modify: `code/backend/src/serious_game_backend/infrastructure/script_packages/file_loader.py`
- Modify: `code/backend/src/serious_game_backend/application/visible_state.py`
- Modify: `code/backend/tests/test_story_semantics_v3.py`
- Modify: `code/backend/tests/test_story_routes_v3.py`
- Modify: `code/frontend/web/tests/narrative-model.test.mjs`
- Modify: `code/frontend/web/tests/characters.test.mjs`

**Interfaces:**
- Consumes: `presentation_entry_id`、NPC discovery state、archive unlock day
- Produces: 每日 `story_acceptance_matrix` 的剧情、决策、人物、档案与强制事件断言

- [ ] **Step 1: 扩展 90 日矩阵结构**

每一天至少包含：

```json
{
  "story_day": 1,
  "required_story_entry_ids": [],
  "decision_presentation_order": [],
  "npc_discovery_transitions": [],
  "archive_unlock_ids": [],
  "forced_conversation_plan_ids": []
}
```

数组可以为空但键不得缺失；加载器拒绝重复日期、缺少日期和未知 ID。

- [ ] **Step 2: 写 1–90 无间断测试**

```python
assert [row.story_day for row in matrix] == list(range(1, 91))
```

每个决策必须先出现铺垫，再出现 `presentation_entry_id`，然后才进入 `pending_decision`；保存载入后不能跳过铺垫。

- [ ] **Step 3: 写人物出现时序测试**

每名 NPC 的 `mentioned → encountered → contactable` 转换必须由矩阵中的剧情或机会驱动。人物页不能把仅在后台配置中的人物描述成玩家已经见过。

- [ ] **Step 4: 写三条完整 D1–D90 自动路线测试**

保留技术、基层、廉洁三种选择序列；每条路线逐日经过 1–90、决策数不少于权威目录、内容实例 ID 不重复、强制会谈完成后才允许次晨推进。

- [ ] **Step 5: 修正矩阵或运行时顺序**

只修复失败测试指出的内容绑定和可见状态，不通过放宽断言绕过顺序错误。

- [ ] **Step 6: 执行一键全量自动测试门**

Evidence root: `output/full-acceptance/task-05`。Expected: 全部通过。

- [ ] **Step 7: 精确提交**

```powershell
git add code/backend/content/packages/pkg_gameplay_v3/story_acceptance_matrix.json `
  code/backend/src/serious_game_backend/infrastructure/script_packages/file_loader.py `
  code/backend/src/serious_game_backend/application/visible_state.py `
  code/backend/tests/test_story_semantics_v3.py `
  code/backend/tests/test_story_routes_v3.py `
  code/frontend/web/tests/narrative-model.test.mjs `
  code/frontend/web/tests/characters.test.mjs
git diff --cached --check
git commit -m "test: enforce D1-D90 presentation order"
```

---

### Task 6: 建立全部结局的合法见证路线

**Files:**
- Create: `code/backend/tools/full_acceptance/ending_witnesses.py`
- Create: `code/backend/tests/test_ending_witnesses_v3.py`
- Create: `code/backend/content/packages/pkg_gameplay_v3/acceptance_route_profiles.json`
- Modify: `code/backend/tests/test_story_routes_v3.py`

**Interfaces:**
- Produces: `discover_witnesses(package, route_driver) -> tuple[EndingWitness, ...]`
- Produces: `validate_witnesses(witnesses, package) -> WitnessCoverage`
- Consumes: 正式 API 的决策、治理、会谈和日终接口；不得写 session 内部状态

- [ ] **Step 1: 写 24/95 覆盖失败测试**

```python
def test_ending_witness_catalog_covers_every_published_ending():
    package = load_v3()
    witnesses = load_witnesses(ROUTE_PROFILE_PATH)
    coverage = validate_witnesses(witnesses, package)
    assert coverage.main_ending_ids == {item.ending_id for item in package.main_endings}
    assert coverage.sub_ending_ids == {
        item.sub_ending_id for item in package.sub_endings
    }
    assert coverage.invalid_state_patches == ()
```

- [ ] **Step 2: 运行 Backend 全量测试并确认失败**

Expected: 缺少见证目录或覆盖率低于 24/95。

- [ ] **Step 3: 实现语义状态哈希和合法路线搜索**

搜索节点只保存通过 API 获得的玩家状态摘要：日期、指标区间、旗标、已知事实、合同、文书、人物记忆摘要和待处理内容。扩展边只来自当前 API 返回的合法选项和行动描述器。相同语义哈希保留更短路线，避免无界重复。

- [ ] **Step 4: 生成见证路线目录**

每个 profile 固定包含：

```json
{
  "route_id": "route-ending-01-a",
  "target_main_ending_ids": ["ending_01"],
  "target_sub_ending_ids": ["ending_01a"],
  "origin_id": "integrity",
  "decision_policy": {},
  "daily_action_policy": [],
  "conversation_strategies": {},
  "expected_end_day": 90
}
```

`decision_policy` 使用真实 `decision_id → option_id/parameters`，路线运行时遇到不存在或不可用选项立即失败。目录禁止 `state_patch`、`flags_override`、`metric_override` 和数据库操作字段。

- [ ] **Step 5: 用正式 API 重放全部见证**

自动测试使用确定性协议桩，但所有剧情、选择和状态更新仍走正式 API。结束后断言实际主结局和子结局包含目标 ID。聚合后必须达到 24/24、95/95。

- [ ] **Step 6: 执行一键全量自动测试门**

Evidence root: `output/full-acceptance/task-06`。Expected: 全部通过。

- [ ] **Step 7: 精确提交**

```powershell
git add code/backend/tools/full_acceptance/ending_witnesses.py `
  code/backend/tests/test_ending_witnesses_v3.py `
  code/backend/content/packages/pkg_gameplay_v3/acceptance_route_profiles.json `
  code/backend/tests/test_story_routes_v3.py
git diff --cached --check
git commit -m "test: cover every published ending with a legal route"
```

---

### Task 7: 扩展真实 API 路线执行器到全部结局和系统

**Files:**
- Modify: `code/backend/tools/run_real_v3_routes.py`
- Modify: `code/backend/tools/run_real_feature_workflows.py`
- Create: `code/backend/tests/test_real_runner_contract.py`
- Create: `code/backend/tools/run_full_acceptance.py`

**Interfaces:**
- Consumes: `acceptance_route_profiles.json`、`CoverageContract`、真实个人/服务器默认网关
- Produces: `run_route(profile) -> RouteResult`
- Produces: `run_full_acceptance.py --output-dir <path>`

- [ ] **Step 1: 写真实执行器契约测试**

测试断言运行器拒绝：Fake provider、Fake fallback、缺少 API Key、目标结局不匹配、跳日、直接写 session、缺少审计、证据目录复用。

```python
with pytest.raises(SystemExit, match="refuses Fake fallback"):
    main_with(Settings(role_llm_fallback_to_fake=True))
```

- [ ] **Step 2: 运行 Backend 全量测试并确认失败**

Expected: 运行器尚不支持 route profile 或没有完整覆盖检查。

- [ ] **Step 3: 将三路线参数改为 profile 目录输入**

命令固定为：

```powershell
python tools/run_real_v3_routes.py `
  --profiles content/packages/pkg_gameplay_v3/acceptance_route_profiles.json `
  --output-dir ../../../output/full-acceptance
```

运行器逐条创建全新 SQLite、全新账号和全新 v3 存档，实际推进到 D90。每条路线输出访问日期、选择、行动、会谈、线索、档案、夜间日志、结局和模型审计。

- [ ] **Step 4: 扩展全功能工作流覆盖**

`run_real_feature_workflows.py` 必须聚合证明：

- 11 份档案均成功首次查阅；
- 27 条线索获取路径逐条成功；
- 32 个人物机会逐条可开始并完成；
- 29 名 NPC 的合法可见与会谈边界正确；
- 8 个地图地点均锁定真实地点；
- 36 户均能进入合法合同路径；
- 四种治理行动、会议、合同、文书、保存载入、复盘均完成；
- 服务器默认和个人 API 账号严格隔离。

- [ ] **Step 5: 实现总入口和失败即停**

`run_full_acceptance.py` 顺序执行：能力矩阵、全功能工作流、全部结局路线、夜间矩阵、浏览器证据导入、报告聚合。任何子进程非零退出立即停止并保留已有证据，不把部分结果标记为通过。

- [ ] **Step 6: 执行一键全量自动测试门**

Evidence root: `output/full-acceptance/task-07`。Expected: 全部通过。

- [ ] **Step 7: 精确提交**

```powershell
git add code/backend/tools/run_real_v3_routes.py `
  code/backend/tools/run_real_feature_workflows.py `
  code/backend/tools/run_full_acceptance.py `
  code/backend/tests/test_real_runner_contract.py
git diff --cached --check
git commit -m "test: run every route against the real model gateway"
```

---

### Task 8: 全量验证夜间 NPC 交流与六场强制会谈

**Files:**
- Create: `code/backend/tools/run_real_night_matrix.py`
- Modify: `code/backend/tests/test_night_agents_v3.py`
- Modify: `code/backend/tests/test_group_persuasion_v3.py`
- Modify: `code/backend/tools/run_full_acceptance.py`

**Interfaces:**
- Produces: 每场 `credible`、`vague`、`contradictory`、`injection` 四种真实话术运行结果
- Produces: `night-dialogues/<plan-id>/<strategy>.json`

- [ ] **Step 1: 写六场计划完整性测试**

```python
assert forced_plan_ids == {
    "followup_d10_county_reporting",
    "followup_d29_zhao_protection",
    "followup_d40_village_mediation",
    "followup_d55_environment",
    "followup_d70_public_oversight",
    "followup_d84_final_inspection",
}
```

- [ ] **Step 2: 写多人状态机与记忆回归**

覆盖 `active → wavering → settled → reopen → close → finish`，验证无轮次自动结束、历史记录不丢失、完成按钮只能在 resolved 后使用、承诺和矛盾进入人物记忆。

- [ ] **Step 3: 实现真实夜间矩阵运行器**

每场从合法前置路线到达触发日，分别提交四类话术。记录参与者、顺序、每轮动作、可见台词、人物状态、耗时、重试、最终收束、次晨简报和后续记忆回查。

- [ ] **Step 4: 验证普通夜间 NPC 主动交流**

除六场强制会谈外，至少遍历内容包中每个可生成的夜间联系组合，证明合法“不联系”和技术失败被区分；玩家可见晨卡必须来自成功结算而非技术保底。

- [ ] **Step 5: 执行一键全量自动测试门**

Evidence root: `output/full-acceptance/task-08`。Expected: 全部通过。

- [ ] **Step 6: 精确提交**

```powershell
git add code/backend/tools/run_real_night_matrix.py `
  code/backend/tests/test_night_agents_v3.py `
  code/backend/tests/test_group_persuasion_v3.py `
  code/backend/tools/run_full_acceptance.py
git diff --cached --check
git commit -m "test: validate every night conversation path"
```

---

### Task 9: 建立全量网页和三尺寸视觉验收

**Files:**
- Create: `code/frontend/web/playwright.config.ts`
- Create: `code/frontend/web/e2e/full-game.spec.ts`
- Create: `code/frontend/web/e2e/visual-matrix.spec.ts`
- Create: `code/frontend/web/tests/full-acceptance-wiring.test.mjs`
- Modify: `code/frontend/web/package.json`

**Interfaces:**
- Consumes: 本地 `http://127.0.0.1:3001` 和真实后端 `http://127.0.0.1:8100`
- Produces: screenshots、trace、console.json、network.json、browser-summary.json

- [ ] **Step 1: 安装并固定 Playwright 测试依赖**

```powershell
cd code/frontend/web
npm install --save-dev @playwright/test
npx playwright install chromium
```

`package-lock.json` 必须提交；Node 版本继续要求 22.13+。

- [ ] **Step 2: 写网页验收布线失败测试**

Node 测试检查 `full-game.spec.ts` 明确包含登录、API配置、剧情、人物、治理、卷宗、线索、地图、合同、会议、夜间、保存载入、复盘和结局选择器；检查三个 viewport 恰为权威尺寸。

```ts
const viewports = [
  { name: "desktop-1920", width: 1920, height: 1080 },
  { name: "laptop-1366", width: 1366, height: 768 },
  { name: "mobile-390", width: 390, height: 844 },
];
```

- [ ] **Step 3: 配置真实服务和证据输出**

```ts
export default defineConfig({
  testDir: "./e2e",
  outputDir: "../../../output/full-acceptance/playwright",
  use: {
    baseURL: "http://127.0.0.1:3001",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
});
```

测试不得把 API Key 写进 attachment；Key 只通过进程环境提供给后端。

- [ ] **Step 4: 实现完整游戏浏览器流程**

每个 route profile 使用全新账号和存档，通过玩家可见控件推进。每个关键状态读取 UI 文本并与后端玩家安全 DTO 对照；禁止直接调用后端写接口替代点击。长路线允许使用页面内批量阅读按钮，但按钮本身必须是正式玩家功能。

- [ ] **Step 5: 实现视觉矩阵**

对以下页面状态在三个 viewport 截图：登录/API、今日、人物、治理、档案结果、线索、八个地图地点、合同四阶段、班子会议、六场强制会谈、次晨简报、保存载入、复盘、24 个主结局。

检查：`document.documentElement.scrollWidth <= viewport.width`、正文不与立绘矩形相交、AI等待层可见、历史发言数量不减少、console error 数为零。

- [ ] **Step 6: 将 Playwright 加入 Web 全量测试命令**

保留 `npm test` 的静态和构建职责，新增：

```json
{
  "scripts": {
    "test:e2e:full": "playwright test e2e/full-game.spec.ts e2e/visual-matrix.spec.ts"
  }
}
```

真实 E2E 由最终全量入口调用，普通 `npm test` 不因缺少真实 Key 而隐式切 Fake。

- [ ] **Step 7: 执行一键全量自动测试门**

Evidence root: `output/full-acceptance/task-09`。Expected: 全部通过。

- [ ] **Step 8: 精确提交**

```powershell
git add code/frontend/web/playwright.config.ts `
  code/frontend/web/e2e/full-game.spec.ts `
  code/frontend/web/e2e/visual-matrix.spec.ts `
  code/frontend/web/tests/full-acceptance-wiring.test.mjs `
  code/frontend/web/package.json code/frontend/web/package-lock.json
git diff --cached --check
git commit -m "test: add full browser and visual acceptance"
```

---

### Task 10: 验证真实模型能力、失败原子性和凭据安全

**Files:**
- Modify: `code/backend/tools/run_choice_expression_live_matrix.py`
- Modify: `code/backend/tools/run_m3_live_role_matrix.py`
- Create: `code/backend/tools/run_real_failure_matrix.py`
- Modify: `code/backend/tests/test_player_llm_configuration.py`
- Modify: `code/backend/tests/test_choice_expression_protocol.py`
- Modify: `code/backend/tools/run_full_acceptance.py`

**Interfaces:**
- Produces: 单选、多选、人物表达、夜间、合同、文书六类能力成功率
- Produces: 真实超时、断流、非法 JSON、鉴权失败和重试证据

- [ ] **Step 1: 固化能力门槛测试**

每类任务重复真实调用；报告分别记录首次成功率和定向纠错后成功率。门槛固定为首次不低于 95%，纠错后不低于 99%，任何失败不得部分提交。

- [ ] **Step 2: 设计不使用 Fake 的失败注入**

使用本地只负责断开或延迟连接的透明代理制造网络故障，成功响应仍来自配置的真实供应商。鉴权失败使用专门的无效临时凭据；非法结构验证使用真实供应商在不兼容模型/端点下的实际返回或连接代理截断响应，不使用 Fake gateway。

- [ ] **Step 3: 写状态前后哈希断言**

每次失败前后比较 session 语义哈希、AP、会谈、合同、文书、旗标、状态版本和快照。失败时必须完全相等；重试成功时只提交一次。

- [ ] **Step 4: 验证两账号隔离和并发换配置**

账号 A 使用服务器默认，账号 B 使用个人 API；并发执行会谈、夜间、合同和文书，审计中的模型与端点摘要必须分别属于对应账号，请求内冻结版本不得混用。

- [ ] **Step 5: 执行一键全量自动测试门**

Evidence root: `output/full-acceptance/task-10`。Expected: 全部通过。

- [ ] **Step 6: 精确提交**

```powershell
git add code/backend/tools/run_choice_expression_live_matrix.py `
  code/backend/tools/run_m3_live_role_matrix.py `
  code/backend/tools/run_real_failure_matrix.py `
  code/backend/tests/test_player_llm_configuration.py `
  code/backend/tests/test_choice_expression_protocol.py `
  code/backend/tools/run_full_acceptance.py
git diff --cached --check
git commit -m "test: enforce real model reliability and atomic failure"
```

---

### Task 11: 执行全部真实 API 路线和浏览器矩阵

**Files:**
- Runtime evidence only: `output/full-acceptance/<run-id>/`
- Modify only if a defect is reproduced: corresponding source plus regression test

**Interfaces:**
- Consumes: Tasks 1–10 的总入口和 route profiles
- Produces: 完整证据目录；不得产生部分通过报告

- [ ] **Step 1: 修改前运行 GitNexus 影响检查**

对真实运行期间发现的每个缺陷，先用 GitNexus `context` 和 `impact` 获取直接调用者、受影响流程和测试范围；将结果保存到该缺陷证据目录。GitNexus 不代替测试。

- [ ] **Step 2: 运行全量自动测试门作为真实验收前置条件**

```powershell
powershell -ExecutionPolicy Bypass -File code/backend/tools/run_full_test_gate.ps1 `
  -EvidenceRoot output/full-acceptance/pre-real-gate
```

Expected: 全部通过，否则不调用真实 API。

- [ ] **Step 3: 启动本地生产式服务**

使用真实 `.env`，确认：`ROLE_LLM_PROVIDER=openai_compatible`、`ROLE_LLM_FALLBACK_TO_FAKE=false`、后端 ready、Web 生产构建启动。不得把密钥打印到终端。

- [ ] **Step 4: 运行全量真实后端验收**

```powershell
cd code/backend
$env:PYTHONPATH = "src"
python tools/run_full_acceptance.py `
  --output-dir ../../../output/full-acceptance
```

停止条件固定为：24/24 主结局、95/95 子结局、18/18 事实、27/27 获取路径、11/11 档案、32/32 人物机会、29/29 NPC 边界、8/8 地图地点、36/36 户、6/6 强制会谈、Fake 0。

- [ ] **Step 5: 运行全量真实浏览器验收**

```powershell
cd code/frontend/web
npm run test:e2e:full
```

Expected: 所有 route profile 和三个尺寸通过；console 未归因错误为零。

- [ ] **Step 6: 在 Codex 内部浏览器复核玩家可见证据**

使用 Browser MCP 打开本地游戏，抽查自动报告中的每类关键页面，并核对截图与实际页面一致。内部浏览器只做复核，不替代 Playwright 全量结果。

- [ ] **Step 7: 处理每个失败**

每个失败执行固定闭环：保存证据 → 写稳定回归测试 → 运行全量自动门确认失败 → 最小修复 → 再跑全量自动门 → 重跑受影响的完整 D1–D90 路线。全部缺陷关闭后，重新从 Step 2 执行整套真实验收，旧的部分通过结果不与新结果拼接。

---

### Task 12: 生成最终报告并执行独立审查

**Files:**
- Create: `docs/testing/full-game-acceptance-report.md`
- Modify: `docs/夜间博弈与前端体验综合优化记录.md`
- Read: `output/full-acceptance/<final-run-id>/**`

**Interfaces:**
- Consumes: 最后一轮完整运行的 `manifest.jsonl`、summary、截图、trace、console、night-dialogues、contracts、endings
- Produces: 可追溯的发布验收报告

- [ ] **Step 1: 从单一完整 run-id 生成报告**

报告必须列出运行环境、提交 SHA、v3 版本与哈希、v2 基线哈希、三端测试数量、真实模型摘要、总调用量、重试、Fake 计数、全部覆盖分母/分子和证据链接。不得混用不同代码版本的运行结果。

- [ ] **Step 2: 写夜间会谈实验记录**

六场会谈分别记录参与者、触发条件、完整发言顺序、玩家策略、NPC状态变化、耗时、最终结束方式、次晨简报和后续记忆反噬证据。

- [ ] **Step 3: 写玩家体验与剩余风险**

只记录有证据的体验问题；所有未解决问题必须进入 `release_blockers`，不能用“偶现”“可能不影响”降级为通过。

- [ ] **Step 4: 使用 GitNexus 检查最终工作区影响**

执行 `detect_changes(scope="all")`，核对每个高风险执行流程都在覆盖契约中有测试或真实路线。将摘要写入报告。

- [ ] **Step 5: 使用 `superpowers:requesting-code-review` 发起独立审查**

审查范围包括需求符合性、状态原子性、Fake禁用、凭据安全、内容可达性、结局覆盖和浏览器证据。所有 P0/P1 必须修复并重新执行 Task 11；P2 必须由用户明确决定是否阻塞发布。

- [ ] **Step 6: 使用 `superpowers:verification-before-completion` 运行最终新鲜验证**

重新执行：

```powershell
powershell -ExecutionPolicy Bypass -File code/backend/tools/run_full_test_gate.ps1 `
  -EvidenceRoot output/full-acceptance/final-gate
cd code/backend
$env:PYTHONPATH = "src"
python tools/run_full_acceptance.py --output-dir ../../../output/full-acceptance
cd ../frontend/web
npm run test:e2e:full
```

只有最后一次完整结果全部通过，才能写“验收通过”。

- [ ] **Step 7: 精确提交报告**

```powershell
git add docs/testing/full-game-acceptance-report.md `
  docs/夜间博弈与前端体验综合优化记录.md
git diff --cached --check
git commit -m "docs: record full D1-D90 acceptance evidence"
```

不提交 `output/`、API Key、个人数据库、Cookie、视频 trace 中的敏感输入。

## 执行顺序与停止规则

1. Tasks 1–3 建立不可绕过的全量门和证据模型。
2. Tasks 4–6 固化内容、时序和全部结局合法见证。
3. Tasks 7–10 建立真实 API、夜间和浏览器全量运行器。
4. Task 11 执行完整真实验收；发现缺陷即回到红测试闭环。
5. Task 12 只接受最后一轮完整运行证据并作发布判断。

任一 Task 的全量门失败时立即停止；不继续堆叠新修改，不用局部通过掩盖全量失败。
