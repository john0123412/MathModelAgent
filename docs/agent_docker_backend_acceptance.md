# Agent 调用 Docker 后端验收记录（路线图 2026-09-03 批 F）

**分支**：`feat/agent-docker-backend-roadmap` → PR #40（`john0123412/MathModelAgent`）  
**基线**：`main 30fb509`，`backend 8000` + `redis` 纯后端模式，`frontend` 为 `profiles: [frontend]` 可选  
**取证**：`mathmodel_workspace_0.0.15`（`323 MB`，`SHA256 48FC1506…5423D44`）

## 1. 无 provider 合同测试（`test_agent_docker_backend.py` 10/10）

| 场景 | 结果 |
|---|---|
| 幂等：同 Key 同内容回放、同 Key 异内容 409 | PASS |
| 单任务状态、消息游标（`after/limit`）、产物清单 | PASS |
| 预算持久化与超限拒绝 | PASS |
| 配图计划追溯校验 | PASS |
| 容器 doctor 与模板能力表（`huawei→huaweibei` 别名） | PASS |
| 评审材料包组装与结构化校验 | PASS |

执行：`backend/.venv python -m unittest app.tests.test_agent_docker_backend -v` → `OK`，`py_compile` 全绿，`docker compose config` 校验 `SERVER_HOST` 默认 `127.0.0.1:8000`。

## 2. Docker 受控执行

- `test_files_router` 7 项、`test_agent_docker_backend` 10 项在宿主机 `backend/.venv` 通过；`task_client doctor --base 8000` 报告 `backend running / redis healthy / local execution ready`。
- `local_interpreter` 已为执行线程，`_finalize` 改 `asyncio.to_thread` 且失败保留上一版 `candidate_manifest.bak`，保证 `/status` 与 `/cancel` 在慢导出期间仍响应。

## 3. 轻量真实题（AGENTS.md 工厂 LP）

题面：`A 2h机器+1h人工 利润40，B 1h+2h 利润30，机器100h 人工80h`；预期 `A=40 B=20 利润2200`，机器+10h 后 `A=46.67 B=16.67 利润2366.67` 增量 `166.67`。  
验收：通过 `task_client submit/inspect/events/artifacts` 全程无前端可提交，`res.md/res.json/res.docx` 与 `candidate_manifest` 哈希一致，`frozen_results.json` 数值与 `execution_validation.json` 绑定。

## 4. 阶段复核与返修

- `waiting_review` → `approve-modeling` / `revise-modeling`（一次退回预算）路径已验证绑定哈希一致性。
- `waiting_quality_review` → `execution-review approve/repair` 绑定 `review_id`，`repair` 仅指定子题，旧 `Writer` 事实失效。

## 5. 故障恢复

- 中断后 `task_status=interrupted`，`resume` 沿用 `checkpoint.json` 与 `task_budget.json`（不重置预算），不重复建任务。
- `cancel` 先 `accepted` 再 `consumed`，有实际停止证据。

## 6. 完整历年题

以 `20260830-234433` 华为算电协同题为参照（`res.pdf 72 页 TECHNICAL_PASS 12/12`），验证源码干净重跑、独立数学复算、引用核验、逐页 PDF/DOCX 检查与哈希核对均可通过 `paper_review` 材料包与六维评审分流。

## 7. 产物交付

`res.md/json/docx/pdf + latex_project` 与 `candidate_manifest` 当前版本一致；`submission_audit / execution_validation / preflight / pdf_visual / final_acceptance` 均有真实结果；`support_materials.zip` 不混入临时文件。

## 8. 文档同步

- `STARTUP.md`：新增 Agent 调用手册（纯后端 `8000` 基址、前端 profile、`task_client` 命令矩阵）
- `AGENT_MEMORY.md`：新增路线图条目（A-F，10k 字符内）
- `backend/app/resources/modeling_guides/{01-05}.md`：按阶段加载的精简规则
- 本文件：一次真实验收记录

**结论**：`A+B` 最小交付已可“不启前端也能提交、查询、恢复和下载”；`C-F` 的预算、规范、配图与验收已接入真实执行链，暂缓 `paperCloud/yjs/Node 桥` 符合路线图。
