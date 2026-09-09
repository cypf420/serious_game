# 合同方案与签约流程实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 实现用户已确认的填写方案、只读预览、本人签约流程，取消模型正文审校。

**Architecture:** 使用已校验方案生成确定性中文正文；复核只负责人物意愿。版本、相关会谈与事实指纹约束重复复核，签署仍沿用原子账务事务。

**Tech Stack:** Python/FastAPI、React/TypeScript、pytest、Node tests、Playwright。

**Spec:** 本任务用户确认的十项合同最终设计；此文件记录落地规则。

## Global Constraints

- 保留既有未提交修改；不提交、部署或改变实际存档。
- 已签署合同正文、签署记录和账务保持不变。
- 未签署旧正文需显式核对后转换，原文保留在历史版本。
- 玩家界面无资源编码、字段名、签署哈希和专业审校阶段。
- NPC 的隐藏条件不投影成玩家清单；口头说明不伪造客观事实。

## Task 1: 后端合同方案与核验

Files: application/contract_workflow.py (new), application/gameplay_governance_service.py, api/schemas.py, api/app.py; tests/test_contract_workflow_v2.py.

- [x] 编写真实 API 回归：保存方案不调用模型；中文日期与资源名称；原样保存版本不变；正文接口拒绝修改。
- [x] 运行 `python -m pytest tests/test_contract_workflow_v2.py -q`，确认新行为失败。
- [x] 实现 `render_contract(session, package, contract, terms)`；将保存方案转为模板生成。`created_by=contract_template_v2`、`audit_status=not_required`。
- [x] 旧草案保存必须传 `acknowledge_legacy_text=true`，旧 versions 不删除；已签署不转换。
- [x] 保存和签约前校验当前库存与政策；原子分配仍使用原账务路径。

## Task 2: 人物复核与公共状态

Files: 同 Task 1 application 文件；tests/test_contract_workflow_v2.py 与现有账务/信息边界测试。

- [x] 测试 explain/reject 后原样请求不重复调用 NPC；会谈增加或事实更新后相同版本可重审；不相关会谈不能解锁。
- [x] 增加当前会谈、选定房源名称及已知属性到签约上下文；以实际输入生成复核指纹并记在私有历史。
- [x] 公共响应补充 `review_version`, `can_review`, `review_blocked_reason`, `legacy_draft`, `legacy_versions`, `conversation_available`；剔除复核指纹。
- [x] 复核请求支持 `expected_contract_version`，不匹配时拒绝；旧客户端 state_version 约束仍有效。
- [x] 跑 `python -m pytest tests/test_contract_workflow_v2.py tests/test_contract_accounting.py tests/test_contract_information_boundary.py tests/test_contract_facts.py -q`。

## Task 3: 合同页面与会谈入口

Files: code/frontend/web/app/GameShell.tsx, app/lib/player-ui.ts, 合同样式、教程及对应 tests/e2e。

- [x] 将正文编辑与审校进度替换为方案表单、只读合同、提交签约。
- [x] 编辑未保存时禁止签约，切换合同和关闭弹窗保护草稿；相关字段显示核验错误。
- [x] 反馈按版本显示，历史折叠；继续协商只关闭合同返回对应会谈，不自动发送消息。
- [x] 旧草案核对提示和确认框；签署原文不做展示转换。
- [x] 跑 Node tests、TypeScript 检查与合同浏览器测试。

## Task 4: 集成验收与说明

- [x] 更新现有过时合同测试和玩家操作说明，保留行政文件审校。
- [x] 检查自动生成无需审校、协商后重提、版本一致、异常和重试不扣资源。
- [x] 总结实际测试结果与未能验证的环境限制。


## 验证结果

- 后端核心合同、账务、事实和信息边界：42项通过。
- 相关合同协议、治理与档案回归：70项通过。
- 原治理/剧情文件中合同与签约用例：8项通过、27项非合同用例未运行。
- 网页 Node 测试：59项通过；应用类型检查通过。
- Playwright 合同综合用例：1项通过，覆盖桌面与390px布局、旧草案确认、签署原文、字段错误和继续协商。
- 终端客户端：47项通过。
- 本次涉及文件的 diff --check 通过。
- 额外启动的整份长剧情见证测试在32项完成后仍未结束，已停止；不将此轮记为全量通过。真实远程模型未重跑，实际存档和运行服务未修改。

## 实施补充

代表会谈补充授权批次的合同背景，明确转述不能代签。跨日签署将实际付款日与签署哈希一并冻结。旧终端流程同步取消合同审校与全文编辑，防止仍使用旧入口时卡住。
