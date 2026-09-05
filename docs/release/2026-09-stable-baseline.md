# 稳定版本发布工程：基线登记（批次0，2026-09-05）

本轮目标：发布适用于个人部署、需人工审批、可恢复且可追溯的稳定版本。
本文档为修改前基线，供回退与审计对照。仅登记非敏感字段。

## 代码与运行基线

| 项 | 值 |
|---|---|
| 基线提交 | `a9b228a`（main = origin/main，tag `v2026.09.05`） |
| 修复分支 | `feat/stable-release-hardening` |
| 工作区状态 | 干净（登记时） |
| 后端镜像 | `sha256:bacd85d37beee67cd9735131bbcb8803435698d7a3175b00252a8b9e0634981d`（构建于 2026-08-24） |
| 运行代码来源 | 宿主机挂载 `backend/app -> /app/app`（**镜像不含当前代码**，版本自证缺失，批次4处理） |
| 数据挂载 | `backend/project/work_dir -> /app/project/work_dir`；`C:\Windows\Fonts -> /usr/local/share/fonts/mma-extra` |
| 依赖锁 | `backend/uv.lock` sha256 前缀 `360325d9b165aa92` |

## 三历史案例只读快照（2026-09-05 采集）

完整哈希与报告字段见各任务目录 `internal/pre_stable_20260905/index.json`（work_dir 为 gitignored，不入库）。

| 案例 | 主产物 | 质量审批 | checkpoint workflow_state | quality_review_status |
|---|---|---|---|---|
| 20260817 | 5/5 在位 | PASS / 4 来源 | `paper_preflight_passed` | `not_run`（报告存在但状态未跑，矛盾①） |
| 20260823 | 5/5 在位 | PASS / 4 来源 | `quality_repair` | `repair_requested`（矛盾②） |
| 20260830 | 5/5 在位 | PASS / **0 来源**（缺陷①实锤） | `paper_repair_pending_export` | `approved`（矛盾③） |

另登记：08-30 案例 `res.json` 仍含旧方法表述（ε-约束×10），与 `res.md` 5.2.2 新表述（碳价标量化）语义脱节（缺陷②）。

## 恢复方式

- 代码回退：`git checkout a9b228a`（或 tag `v2026.09.05`）。
- 历史交付件：各任务 `internal/pre_stable_20260905/` 为修改前逐字节备份（`shutil.copy2` 保留 mtime），恢复时按 index.json 哈希核对后回拷。
- 后续验证一律在独立测试任务目录执行；三历史案例仅作回归样本，不直接恢复运行。

## 修改批次边界（只动这些，不扩权）

1. 批次1：`execution_quality_review.py` 及其工作流/审批接口/测试——审批依据绑定。
2. 批次2：论文保存、受控返修、后处理、导出、候选清单——内容修订号统一。
3. 批次3：checkpoint、任务状态服务、完成处理、`/resume`——状态收敛。
4. 批次4：compose/镜像/版本注入/预算账本/取消——部署与预算加固。
5. 批次5：三历史案例定性登记。
6. 暂缓：新增模型能力、模板变更、智能体架构改动。
