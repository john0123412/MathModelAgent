# AGENT_MEMORY

> 活跃事实清单：只记现状结论 + 关键锚点 + 指针；过程叙事一律在 docs/memory/ 归档（grep 检索）。
> **硬上限：主文件 ≤5,000 字符**（用户 2026-08-29 指令，严于原 10,000 规则）。

## 归档索引

- [2026-07](docs/memory/2026-07.md) —— 华数杯前史与早期工程修复
- [2026-08](docs/memory/2026-08.md) —— 更早 235 条 + 2026-08-29 压缩轮出的 08-26~08-29 全部详细条目
- [2026-09](docs/memory/2026-09.md) —— v23 算电协同 09-02 落地与外评审九轮详文、稳定版本工程

- 8 月交付/导出基线已轮转至 docs/memory/2026-08.md；0825/0828 族复跑须用 huashubei。
- 一次性计划/诊断文档已收口至 docs/md/archive/（索引见其 README），不代表当前系统行为。
- 任务接管/引导/execution-review 接口详文独立为 docs/md/任务接管与引导接口.md
  （STARTUP.md 留短桩）；导出门禁权威口径在 docs/md/PDF模板导出说明.md。

## 仓库归属与环境要点

- john0123412 个人 fork；origin 唯一可写远程；upstream jihe520 严禁任何写操作（死命令）。
- 容器名 mathmodelagent_john_*；backend 容器重建/kill 曾三次 daemon 层挂起，处置 = 人工重启
  Docker Desktop 后 `docker compose up -d backend`；本地代码执行用 local-execution 覆盖档
  （pids_limit 1024、LOCAL_CODE_EXECUTION_TIMEOUT_SECONDS=300），标准档无 E2B key 时
  Coder 前置直接失败、不自动降级。
- LLM stealth/ox-alpha 池曾持续 429（两次有界重试即停）；reasoning_effort 管线已恢复（58d01d3）。
- 第 7 批（base-box 上架）被 jihe520 死命令封死，视为不执行。

## 待人工 / 待办

- 论文已达评审冻结终态（09-05 收口：86页正文30、九步全绿、缺字形0，评审定档92.5"可以冻结"）；
  平台上传三件事（文件命名 / 匿名目检 / 诚信声明）+ 四项人工复核待人工。tag v2026.08.24-paper-final
  已在 origin(48a0e69)，如需 -f 移至 37391e8 另行指示。
- 20260828 两个低危观察待决策：5.3 节"SOC 恰好回到初始值"与数据不符；全篇无论文献区。

## v23 算电协同·去伪造重建（task=20260830-234433-4b3226317d54a94062be7a3379cf1a10）

- 09-02 落地：notebook 全真实执行、frozen/manifest 受控重绑、四目标真实达标（非支配 6、
  CI 0.0457、区分度 0.7408、MC 均值 1,284,013,383）。
- 复用脚本：`internal/audit_20260901/`（lp_core/q1~q4 model、rerun_cells/rerun_q4_comment、
  fix_appendix+fix_support_caption 必配对、reconcile_gates2、regen_pdf、rebind_manifest、
  fix_rebind_fallout）。

### 评审九轮结论行（09-03~09-05，逐轮详文见 docs/memory/2026-09.md）

- 轨迹 89→91-92→92→92.5 定档"可以冻结、不再深挖审计"；LNS v2 双重证伪不采纳（产物留 v2
  目录不进主链）。终态：86页正文30、九步全绿、TECHNICAL_PASS 12/12、缺字形0、五件哈希
  MATCH、bc_dev=0（lam500 对齐后同迁移同 LP 严格一致）。
- 关键修正：Q1 调度器 v3（EDF+分数重叠占用+纯电费，538/538、违反全0）；λ=500 改"中等碳价
  参考方案（控制变量）"四层同步；γ~U(0.8,1.2) 补入摘要与 6.1.2；5.4.1 删 M 迁移变量改三维
  非支配+固定λ500；"Pareto 前沿"→"非支配情景结果集"；MC CI 改"均值估计不确定性"口径；
  符号全 ASCII 化（表头BOM、`$ `开界、listings λ/≤、附录注释均曾翻车）。

## 运维新坑备忘（重绑/复跑必查）

- rebind 后 executed_code_sources 被 walk 回填，须 post-patch 收窄回 notebook 单源（否则
  fix_appendix 把旧 LNS 脚本嵌进附录，104k→393k）；ques2 pareto_point_count target 对齐
  代码 >=2 规则并显式重算 feasible。
- reconcile_gates2 须以 backend 为 CWD（WORK_DIR_ROOT 相对）；notebook 变更后必须重打包
  support_materials.zip；跨页句子子串检查会被页码截断，语义验证需逐页或归一化后比对。
- 替换 notebook cell 前校验边界唯一性、恢复后全量旧短语扫描（曾误删121行/带回旧口径/
  二次 scrub 7处修净）。

## 门禁加固（PR #41-#50）与稳定版本工程（PR #51）

- PR #41-#50：ALGORITHM_CLAIMS 扩 ε-约束/LNS/MILP/NSGA/退火、结果 CSV 字面量写死检测、
  `$ ` 开界 lint+行内配对状态机、PDF 缺字形扫描、缓存键 SHA-256、章节式图引用不顶替扁平
  图号、表号连续性、mtime 链新鲜度哨兵（源晚于导出即 FAIL）、伪执行检测（print-无-stream/
  output-无-count）。09-05 全部署（容器 a1fb564），当晚六次链脱钩全部由哨兵归因。
- PR #51（main=4ab9d1b，tag v2026.09.05）五批次：质量审批绑定 execution_validation
  （PASS/NEEDS_REVIEW/BLOCKED 三态，0源阻断）、paper_revision 台账+preflight res_json_sync
  硬门+manifest 1.3、task_state_diagnosis 三值诊断+reconcile 审计修复、docker-compose.stable.yml
  代码入镜像+MMA_GIT_COMMIT 自证、三历史案例定性（docs/release/2026-09-historical-cases.md）。
  980 全量 OK。
- [09-05/06 后续修复] PR #56 禁思考参数不被支持时剥离 extra_body 重试（GLM-5.3/tokenrouter
  实测 400）；#57 modeler 校验失败日志附原文片段；#58 资产追溯兼容 quesN 单键+重复章节键豁免。
- [09-06 算法证据门禁] 独立分支 `fix/algorithm-evidence-ledger-v2`：当前方法声明硬阻断，未来/比较/待复算算法语境排除并留 `excluded_claims`；证据复用最终代码附录集合。`test_gate_hardening`、论文修订/候选/工作流共 228 项定向测试 + `ruff check app` 通过；详见 docs/memory/2026-09.md。
- [09-06 LP 导出恢复] task `20260906-033157-bd8195551a4a760570d999c09194c6ab` 冻结结果与执行证据 SHA 未变；`res_json_sync`、`algorithm_evidence` PASS，确定性 export-only 修复后 `preflight/pdf_visual/submission_audit=PASS`、`final_acceptance=TECHNICAL_PASS`、状态 `completed`。
- [09-06 失败恢复闭环] 初始 workflow 只在 final acceptance 失败后报告 `failed`，未自动继续导出修复；现对仅涉及视觉/新鲜度/清单重绑的失败持久化一次 `presentation_reflow_pending_export`，无 Provider/无数值重跑重建全链；执行证据、冻结哈希、算法、匿名、字体/模板等实质失败仍 fail-closed，预算耗尽不循环。详见 `STARTUP.md`、`docs/md/PDF模板导出说明.md`、`docs/md/CUMCM_FINAL_REVIEW_CHECKLIST.md`。
- [09-06 匿名审计误报] `submission_audit` 改为跳过 manifest 的 sha256/sha1/md5/hash/digest 校验值，仅扫描提交文件名、显式身份字段和路径；39 项匿名审计 + 236 项定向回归通过。LP 任务刷新审计后匿名检查 PASS，但随后并发进程更新 `res.md/res.json`，故未重绑 manifest/final acceptance；冻结/执行证据 SHA 仍为 `ea38a3c6...` / `bb30986d...`。详见 docs/memory/2026-09.md。
## 外部 skill 备查（2026-09）

- liufanshan11 cumcm-b/c-problem-lfs 已 clone 至 D:\workspace\cumcm-refs\（仓库外；勿装入
  .agents/skills/ 防触发冲突，勿采用其 LaTeX 交付链）。蒸馏落地：选题/路线→route-selection
  的 references/cumcm-bc-expert-notes.md；B/C 终检条目→CUMCM_FINAL_REVIEW_CHECKLIST
  "B/C 题专项复核"小节。
