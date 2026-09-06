> [已归档 2026-09-06] 本文档为一次性执行计划,状态:已过期未执行,内容不代表当前系统行为;索引见 docs/md/archive/README.md。

# Skills 集成与合规门禁合并执行计划

## 1. 文档状态与结论

| 项目 | 当前值 |
| --- | --- |
| 计划状态 | `READY_FOR_EXECUTION`，尚未开始代码实施 |
| 制定日期 | 2026-08-20 |
| 合并基线 | `main` / `a414127b540f56dab94699c923d6be8ef72b0ee8` |
| 待整理分支 | `feat/skills-integration-and-compliance-hardening` / `cfde44265ce77b58ecac4d2cc1f89fbefd6eb53e` |
| 当前拓扑 | 特性分支相对 `main` 为 `0 behind / 1 ahead`，技术上可快进 |
| 当前决定 | **禁止直接合入；先拆分、修复阻断项、建立 PR 级 CI，再按顺序合并** |
| 上游策略 | 不在本轮 PR 中 merge/rebase `upstream/main`；上游变更独立评估、选择性移植 |

本计划把原来的单一大提交拆成三个可独立审查和回滚的交付单元：

1. **PR-A：合规门禁与选题工具核心代码**；
2. **PR-B：外部 Skills 供应链与健康检查**；
3. **PR-C：弱网配置文档整理**。

在 PR-A 和 PR-B 完成前，已有分支只作为来源快照保留，不改写、不 force-push、不直接合并到 `main`。

## 2. 已核验基线

### 2.1 Git 与远程状态

- 工作区在制定本计划时为干净状态：`## main...origin/main`。
- 本地和远程 `origin/main` 均为 `a414127`。
- 本地和远程特性分支均为 `cfde442`。
- 当前差异为 154 个文件、约 `+23,293 / -91`；其中绝大多数为 `.agents/skills/` 外部内容。
- 根仓库 CI 仅在 push 到 `main` 或创建面向 `main` 的 PR 时运行；单纯 push 特性分支没有产生 CI 结果。
- `git diff --check main...feat/skills-integration-and-compliance-hardening` 当前有 86 项 finding（共 166 行原始输出）：
  - 弱网配置文档 78 项；
  - 外部 Skill Markdown 3 项；
  - 5 个 Python 文件各 1 项 EOF 空行问题。
- `upstream/main` 本地跟踪引用为 `13e3995`，执行前重新 fetch 后确认远程最新值；其相对本地旧跟踪引用新增的是 README 中的 sci-box 介绍，不构成本轮功能依赖。

### 2.2 已有验证证据的边界

原分支记录了 693 项后端单测通过、1 项跳过以及 Ruff 通过。该记录可以作为历史证据，但不能替代拆分和修复后的重新验证，原因包括：

- 当前没有该特性分支的远程 CI；
- Ruff 不检查 `git diff --check` 的 whitespace findings；
- 根仓库 CI 不会自动执行嵌套在 `.agents/skills/**/.github/workflows/` 中的工作流；
- 现有测试没有覆盖本计划列出的 fail-open、状态传播、DOCX 元数据和外部 Skill 许可问题。

## 3. 范围与非目标

### 3.1 本轮范围

- 修复冻结结果等价性验证和哈希更新的 fail-open 风险；
- 将跨模态审计的阻断结果真正接入论文预检和最终验收；
- 重构匿名扫描的高置信阻断、低置信预警和文档元数据覆盖；
- 保持 `topic_scorer` 为可解释、可测试的辅助决策工具；
- 对三套外部 Skill 建立来源、版本、许可、修改记录和运行边界；
- 删除无关或无法证明需要再分发的推广/支付二进制资产；
- 让健康检查脚本可移植，并由根 CI 实际执行必要的 Skill 测试；
- 清理 whitespace，拆出无关弱网文档改动；
- 通过 PR、CI 和可回滚提交完成合并。

### 3.2 非目标

- 不在本轮整体同步 `upstream/main`；
- 不把静态 AST 扫描包装成“已在全新环境 100% 可复现”；
- 不改变 Modeler/Coder/Writer 主状态机或重新设计整个导出系统；
- 不扫描或重跑 `backend/project/work_dir/` 历史任务，除非后续由用户明确指定任务 ID；
- 不运行 Windows 本机前端 Node 工具链；
- 不提交、推送、合并、删除分支或清理 worktree，除非执行阶段再次获得明确授权。

## 4. 强制设计原则

1. **冻结证据不可由预检静默改写。** 预检可以报告等价性，但不得悄悄改变 `frozen_results.json` 的证据哈希。
2. **任何无法验证的情况都要显式失败或降级。** 指标缺失、重复、数据源不可解析和抽取失败不能当作等价。
3. **报告状态必须单义。** 不允许同时出现 `status=PASS` 与 `passed=false`。
4. **阻断与预警分层。** 确定性泄露、证据冲突和私有依赖为阻断；有限词库命中、图片内文字和低置信上下文为预警与人工复核项。
5. **主交付 Baseline 优先。** 修改期间必须保留能生成 `res.md`、`res.json`、`res.docx` 的已验证最小路径。
6. **第三方内容先确认权利再分发。** 公共可访问不等于允许复制；每套 Skill 必须有可核验许可或权利声明。
7. **一个 PR 一个回滚边界。** 业务门禁、外部 Skill、弱网文档不得再次捆绑成单个大提交。
8. **验证结论只基于实际运行。** 未运行的 Docker、真实任务、LaTeX 编译或 Skill 测试必须明确标记为未验证。

## 5. 分支与 PR 拆分

### 5.1 来源分支保护

执行阶段先确认下列 SHA 未变化：

```text
main                                      a414127b540f56dab94699c923d6be8ef72b0ee8
feat/skills-integration-and-compliance-hardening
                                          cfde44265ce77b58ecac4d2cc1f89fbefd6eb53e
```

如 SHA 已变化，停止照搬本计划中的路径清单，重新生成差异和风险表。不要对远程特性分支 force-push；使用新分支承载拆分后的改动。

### 5.2 PR-A：合规门禁与选题工具

建议新分支：`codex/compliance-gates-merge-ready`

计划纳入：

```text
backend/app/core/prompts/coder.py
backend/app/core/prompts/modeler.py
backend/app/core/prompts/writer.py
backend/app/tools/cross_modal_validator.py
backend/app/tools/paper_postprocessor.py
backend/app/tools/result_integrity.py
backend/app/tools/submission_audit.py
backend/app/tools/topic_scorer.py
backend/app/tests/test_architecture_upgrade.py
backend/app/tests/test_submission_audit.py
backend/app/tests/test_topic_scorer.py
docs/md/CUMCM_FINAL_REVIEW_CHECKLIST.md
```

`AGENT_MEMORY.md` 和 `STARTUP.md` 不直接照搬旧分支版本；应在最终行为确定、验证完成后按实际结果重新同步。

建议提交边界：

1. `test: 补齐冻结等价性与审计状态失败用例`；
2. `fix(integrity): 冻结结果验证改为 fail-closed`；
3. `fix(audit): 接通跨模态阻断状态与论文预检`；
4. `fix(anonymity): 分层扫描正文、元数据与联系方式`；
5. `feat(topic): 接入可解释选题评分工具与提示规范`；
6. `docs: 同步合规门禁使用和人工复核边界`。

### 5.3 PR-B：外部 Skills 与供应链

建议新分支：`codex/modeling-skills-vendor-review`

计划纳入：

```text
.agents/skills/**
scripts/check_skills_health.ps1
.github/workflows/ci.yml
.agents/skills/README.md                  # 建议新增：总 provenance 清单
```

PR-B 必须以 PR-A 已合并后的 `main` 为新基线，避免把旧版门禁文件再次带回。建议提交边界：

1. `docs(skills): 登记来源、版本、许可与本地修改`；
2. `chore(skills): 精简运行时文件并移除无关二进制资产`；
3. `fix(scripts): 健康检查按脚本位置解析仓库根目录`；
4. `ci(skills): 在根工作流运行 Skill 冒烟与单测`；
5. `docs: 同步 Skill 安装、触发与维护边界`。

### 5.4 PR-C：弱网配置文档

建议新分支：`codex/weak-network-doc-cleanup`

只包含：

```text
docs/md/网络环境极差时的MathModelAgent配置过程.md
```

该 PR 只做事实核对、格式整理和 whitespace 清理，不与门禁或 Skill 代码绑定。涉及修改 Dockerfile、Compose、镜像源或用户命令时，必须重新核对 `STARTUP.md`，但本计划不预先假定需要改运行配置。

## 6. PR-A 详细实施任务

### 6.1 B-01：冻结结果等价性改为 fail-closed

责任文件：

- `backend/app/tools/result_integrity.py`
- `backend/app/tools/paper_postprocessor.py`
- `backend/app/tests/test_architecture_upgrade.py` 或新增聚焦测试模块

当前风险：

- 绑定指标从数据源中消失或改名时，当前实现可能因为没有发现明确冲突值而返回等价；
- 同名指标出现多行时，只要任一行保留旧值就可能掩盖另一行的新值；
- 无绑定指标、空结果、嵌套 JSON 和不支持格式可能被跳过；
- 论文预检会直接改写 `frozen_results.json` 中的 SHA-256，破坏冻结证据的不可变语义。

实施要求：

1. 规范化并限制所有 `source_path` 必须位于任务目录内；
2. 对每个变化的数据源建立显式绑定清单；
3. 每个绑定指标必须满足：
   - 能按稳定 ID 唯一定位；
   - 恰好找到一次；
   - 数值为有限数；
   - 数值在明确、可记录的容差内等价；
4. 发现 0 次、超过 1 次、同 ID 多值、解析失败、空表或不支持格式时一律拒绝刷新；
5. 标签只能作为受控兼容别名，不能覆盖稳定 ID 冲突；
6. JSON 需要递归支持项目实际声明的结构；不能把外层字典存在视为已找到内部指标；
7. Excel 多 Sheet 必须保留 Sheet 名和行定位，避免跨 Sheet 同名值误合并；
8. `prepare_paper_markdown()` 改为只读验证，不得自动写回冻结文件；
9. 如确需接受格式变化，使用独立、显式、可审计的重新登记/冻结命令；短期内原始 SHA 不一致应阻断预检；
10. 报告中记录来源路径、旧/新哈希、定位方法和失败类别，但不记录敏感原始数据全文。

必加测试：

- 绑定指标数值不变但格式变化：预检不得静默改写冻结文件；
- 绑定指标被删除：FAIL；
- 绑定指标改名：FAIL；
- 同一指标一旧一新两行：FAIL；
- 同一指标跨两个 Sheet 重复：FAIL；
- JSON 指标位于嵌套列表：能唯一验证；
- JSON 外层存在、内部指标缺失：FAIL；
- `NaN`、`Infinity`、空字符串：FAIL；
- 数据源路径越出任务目录：FAIL；
- 不支持格式或解析库缺失：FAIL，并给出可执行诊断。

完成标准：

- 任一来源哈希变化都不能在“指标未被完整唯一证明等价”时更新冻结状态；
- 预检前后 `frozen_results.json` 字节哈希保持不变；
- 所有新增对抗用例通过。

### 6.2 B-02：跨模态状态与预检真正闭环

责任文件：

- `backend/app/tools/cross_modal_validator.py`
- `backend/app/tools/paper_postprocessor.py`
- `backend/app/tools/submission_audit.py` 或最终验收聚合模块
- `backend/app/tests/test_architecture_upgrade.py`

实施要求：

1. 定义单一状态规则：
   - 存在 blocking issue：`status=FAIL, passed=false`；
   - 只有非阻断 warning：`status=WARN, passed=true`；
   - 无问题：`status=PASS, passed=true`；
2. 禁止 `status=PASS, passed=false` 等不一致组合；
3. 以下项目默认为 blocking：
   - 最优性证书自相矛盾；
   - 明确 LaTeX 损坏模式；
   - 正式执行源中引用仓库私有 `app.*`；
   - 正式执行源篡改 `sys.path` 以依赖仓库路径；
4. 有限关键词词库默认为 warning；只有当前 export profile 或正式规则明确要求时才升级为 blocking；
5. `prepare_paper_markdown()` 必须将跨模态结果写入 `paper_preflight_report.json.checks`；blocking fail 必须令 preflight 为 FAIL；
6. `submission_audit` / `final_acceptance` 必须检查跨模态报告与当前 Markdown/源码哈希一致，不能接受旧报告；
7. 将“100% 独立可复现”措辞改为“静态私有依赖检查通过”；真正的独立可复现仍须通过隔离新进程/新内核重跑证明；
8. AST 语法失败不能静默当作自包含通过：正式 `.py` 源语法错误应直接 FAIL；Markdown 片段可单独标记为不可解析 warning 或 fail，取决于是否声明为完整源程序；
9. 从 `frozen_results.json.executed_code_sources` 读取路径时必须做任务目录边界校验。

必加测试：

- keyword warning + 其他检查通过：整体 `WARN/passed=true`；
- 私有导入：整体 `FAIL/passed=false`，且 preflight 同步 FAIL；
- 跨模态报告内容哈希过期：submission/final audit 拒绝；
- 语法错误的正式求解器：FAIL；
- `../outside.py` executed source：FAIL；
- 只有普通领域词的关键词：warning 或按正式 profile 阻断，状态与配置一致；
- 领域词中包含“优化”但并非方法名时不得仅凭子串无条件通过。

完成标准：

- 跨模态 blocking issue 能稳定阻断预检和最终技术验收；
- warning 不伪装成 PASS，也不会无条件阻断交付；
- 报告状态和布尔值在所有测试中保持一致。

### 6.3 B-03：匿名扫描分层和覆盖面修复

责任文件：

- `backend/app/tools/submission_audit.py`
- `backend/app/tests/test_submission_audit.py`
- `docs/md/CUMCM_FINAL_REVIEW_CHECKLIST.md`

高置信 blocking 类别：

- 明确电子邮箱格式；
- 中国大陆手机号、带标签的联系电话；
- 学号、身份证号、报名号、参赛编号等“字段名 + 非占位值”；
- 作者、队员、指导教师、导师、学校名称、院系等“身份字段 + 实际值”；
- PDF/DOCX 元数据中的 author、creator、lastModifiedBy、company 等身份值；
- 明确的微信号、QQ 号等“标签 + 值”。

低置信 warning 类别：

- “学校、大学、学院、University、College、致谢”等普通词；
- 参考文献作者单位、公开数据源机构名、比赛全称；
- 图片、扫描页、公式对象内无法可靠抽取的文本。

扫描范围：

1. PDF：全文文本、文档 metadata、附件/注释可访问元数据；
2. DOCX：
   - `word/document.xml`；
   - headers / footers；
   - footnotes / endnotes / comments；
   - `docProps/core.xml`、`app.xml`、`custom.xml`；
   - 将拆分的 XML text run 先归一化再匹配；
3. 文件名和候选 manifest 中的提交文件名；
4. 报告只输出脱敏类别、文件部件和位置，不回显完整手机号、邮箱、身份证号或其他敏感正文。

严格模式行为：

- 高置信命中：FAIL；
- 文档损坏、加密或关键文本/元数据无法抽取：FAIL，并要求人工复核；
- 只有普通词命中：WARN，不直接 FAIL；
- 图片内文字未 OCR：明确记录 `PENDING_HUMAN_REVIEW`，不得宣称“全文严格匿名已证明”。

必加测试：

- 参考文献中 `University`：WARN，不 FAIL；
- 正文中“全国大学生数学建模竞赛”：不误报身份泄露；
- DOCX core properties 中真实作者名：FAIL；
- DOCX 页眉中的学校名：FAIL 或高置信身份字段命中；
- 被拆成多个 XML run 的邮箱/学号：仍能发现；
- PDF metadata 中 author：FAIL；
- 图片型 PDF 无可抽取文本：FAIL/PENDING_HUMAN_REVIEW，而不是无条件 PASS；
- 报告中敏感值被脱敏。

完成标准：

- 通用机构词不再造成大量硬误报；
- 常见可机检身份面全部覆盖；
- 自动检查边界在最终复核清单中明确记录。

### 6.4 B-04：关键词合规与 topic scorer 定位

责任文件：

- `backend/app/tools/topic_scorer.py`
- `backend/app/tests/test_topic_scorer.py`
- `backend/app/core/prompts/modeler.py`
- `backend/app/core/prompts/coder.py`
- `backend/app/core/prompts/writer.py`

实施要求：

- `topic_scorer` 是决策辅助，不自动替代队伍选择或 Modeler 方案审批；
- 所有权重必须归一化、输出中显示证据和 flip condition；
- 输入缺失、未知字段、非有限分数和非法权重应给出确定性错误；
- CLI 仅在用户指定输出路径时写文件，不在仓库根目录制造临时产物；
- 关键词审计避免简单子串造成“种植优化策略”因包含“优化”即被视为规范方法名；
- 中文、英文和常见大小写/连字符变体需有规范化策略；
- Prompt 只描述已经由代码实现的能力，不写“100%”“绝对”等无法验证的承诺。

完成标准：

- 评分结果可复现且解释完整；
- 关键词 heuristic 的边界通过测试和文档公开；
- Prompt 与实际门禁行为一致。

## 7. PR-B 详细实施任务

### 7.1 B-05：外部 Skill provenance 与许可

为每个 Skill 在 `.agents/skills/README.md` 或各自 `PROVENANCE.md` 登记：

| 字段 | 要求 |
| --- | --- |
| Skill 名称 | 与 `SKILL.md` frontmatter 一致 |
| 原始来源 | 可访问的仓库或作者声明 |
| 固定版本 | tag 或完整 commit SHA，不能只写 branch 名 |
| 获取日期 | ISO 日期 |
| 许可 | SPDX 名称及许可文件路径 |
| 再分发判断 | 允许 / 不允许 / 待确认 |
| 本地修改 | 文件和行为摘要 |
| 运行时网络 | 是否下载外部资源、访问哪些域名 |
| 维护责任 | 谁负责检查上游更新与许可变化 |

当前处置要求：

- `mathmodel-skill`：保留其 MIT `LICENSE` 和 `THIRD_PARTY_NOTICES.md`，核对来源 SHA；
- `mathmodel-latex-skill`：在能证明原创权利或再分发许可前不得合入；
- `math-modeling-contest-route-selection`：在能证明原创权利或再分发许可前不得合入；
- 删除未被任何文档或运行逻辑引用的 `support-wechat-pay.jpg`；
- `github-promo-banner.svg` 等推广资产只有在有明确用途和许可时保留；
- 禁止把论文 PDF、字体、私钥、API Key、Cookie、个人支付码或无法证明来源的二进制模板带入仓库；
- 执行 secret scan 时只汇报命中路径和类别，不打印潜在秘密正文。

完成标准：

- 每个被合入的 Skill 都能回答“从哪里来、哪个版本、什么许可、改了什么”；
- 所有二进制资产都有必要性和再分发依据；
- 待确认许可的 Skill 不进入 PR-B 的可合并版本。

### 7.2 B-06：Skill 目录精简与发现规则

逐项判断以下内容是否为运行时所需：

```text
.github/
.codex-plugin/
tests/
state/
重复嵌套的 skills/<name>/SKILL.md
开发期 README、fixture、维护下载脚本
```

原则：

- 保留运行时真正需要的 `SKILL.md`、references、templates、scripts 和明确依赖；
- 如果保留上游测试和维护脚本，根 CI 必须能运行或明确标为维护期工具；
- 嵌套 `.github/workflows` 不会成为根仓库 CI，不能把它们存在当作已启用验证；
- 运行时下载脚本默认不得执行，必须要求用户显式调用并提示许可/网络风险；
- 确保 Skill discovery 只有一个权威入口，避免重复 Skill 名被加载两次。

完成标准：

- 目录结构有一份权威说明；
- 不存在重复发现、无效嵌套 CI 或无用途二进制资产；
- 保留下来的维护工具有明确依赖和调用边界。

### 7.3 B-07：健康脚本可移植化

责任文件：`scripts/check_skills_health.ps1`

实施要求：

- 用 `$PSScriptRoot` 计算脚本目录，并通过 `Resolve-Path` 得到仓库根目录；
- 禁止硬编码 `D:\workspace\MathModelAgent`；
- Python 固定使用 `<repo>\backend\.venv\Scripts\python.exe`；
- 每项失败都返回非零退出码；缺失 Skill 不得只 WARN 后继续宣称 SUCCESS；
- 显式运行：Skill 结构检查、topic scorer 测试、合规门禁定向测试、被保留的外部 Skill 测试；
- 不安装依赖、不调用本机 `frontend/node_modules`、不启动前端构建；
- 输出不包含 API Key、环境变量值或用户隐私正文。

必加验证：

- 从仓库根目录运行成功；
- 从任意其他当前目录调用同一绝对脚本路径也成功；
- 临时缺失一个 `SKILL.md` 时返回非零；
- Python venv 缺失时给出明确诊断并返回非零。

### 7.4 B-08：根 CI 覆盖外部 Skills

责任文件：`.github/workflows/ci.yml`

实施要求：

1. PR checkout 使用足够历史以支持 base diff；
2. 在 PR 上运行 `git diff --check`；
3. 保留后端 Ruff 和全量 unittest；
4. 新增 Skill health/test 步骤，不能依赖嵌套 workflow 自动触发；
5. 所有 Action 继续固定完整 commit SHA；
6. 权限保持 `contents: read`；
7. CI 不使用真实 provider key、不下载论文、不访问付费 API；
8. 如果 Skill 测试需要额外依赖，必须锁定版本并说明为何不进入后端运行时依赖。

完成标准：

- PR-B 的远程 Checks 页面存在实际运行记录；
- whitespace、后端回归和 Skill 回归任一失败都能阻断合并；
- CI 不依赖开发者 Windows 固定路径。

## 8. 验证矩阵

### 8.1 PR-A 本机后端验证

仅使用固定虚拟环境：

```powershell
cd D:\workspace\MathModelAgent\backend

.venv\Scripts\python.exe -m unittest `
  app.tests.test_result_integrity `
  app.tests.test_architecture_upgrade `
  app.tests.test_submission_audit `
  app.tests.test_topic_scorer

.venv\Scripts\python.exe -m unittest discover app/tests
.venv\Scripts\python.exe -m ruff check app
```

如第一条中某个模块名在实际仓库不存在，应按真实测试文件调整并在汇报中记录，不能跳过对应行为验证。

### 8.2 PR-B Skill 验证

计划命令以实际保留目录为准，至少包括：

```powershell
cd D:\workspace\MathModelAgent

backend\.venv\Scripts\python.exe -m unittest discover `
  -s .agents/skills/mathmodel-skill/tests `
  -p "test_*.py"

powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File scripts/check_skills_health.ps1
```

另外对每个保留的 Skill 脚本执行安全的 `--help` 或离线 fixture 冒烟测试。不得为了验证自动下载论文、模板或外部数据。

### 8.3 Git 与静态验证

```powershell
cd D:\workspace\MathModelAgent

git diff --check origin/main...HEAD
git status --short --branch
git diff --stat origin/main...HEAD
```

外部内容还应做路径级 secret pattern 扫描和二进制资产清单；报告只列路径、类型和处置，不打印潜在秘密。

### 8.4 Docker 与真实案例验证

由于 PR-A 改变论文预检、匿名和冻结完整性行为，合并前需要：

1. Docker 容器内重复 PR-A 的定向测试和 Ruff；
2. 运行项目规定的轻量线性规划烟雾题；
3. 确认任务为 `completed`，并存在 `res.md`、`res.json`、`res.docx`、`candidate_manifest.json`；
4. 如生成 PDF/LaTeX sidecar，核对 preflight、cross-modal、PDF visual、submission audit 和 candidate manifest 当前哈希；
5. 人工确认 DOCX/PDF 中没有匿名误报或漏报；
6. 不以该轻量题替代赛前完整长度历年题验收。

如果需要用历史真实任务做回归，必须先由用户指定 task ID；不得默认扫描整个 `backend/project/work_dir/`。

### 8.5 明确禁止的验证方式

- 不运行本机 `pnpm install`、`pnpm run build`、`vue-tsc`、Vite、Biome 或任何 `frontend/node_modules/.bin/*`；
- 不打印 API Key、token、cookie、私钥、完整手机号、邮箱或身份证号；
- 不为通过门禁手改报告状态、候选 manifest 或冻结哈希；
- 不在仓库根目录或 `scripts/` 新建一次性测试脚本。

## 9. PR 验收与合并顺序

### 9.1 PR-A 合并条件

- B-01 至 B-04 全部完成；
- 新增对抗性测试实际通过；
- 全量后端 unittest 和 Ruff 通过；
- `git diff --check` 为零；
- Docker 定向回归通过；
- 远程 PR CI 通过；
- `AGENT_MEMORY.md`、`STARTUP.md`、PDF 导出说明、最终复核清单按最终行为完成同步或明确说明无需更新；
- PR 审查确认没有修改外部 Skill 大目录或弱网文档。

### 9.2 PR-B 合并条件

- B-05 至 B-08 全部完成；
- 所有 Skill 许可和 provenance 明确；
- 无关支付/推广资产已删除或有书面保留理由；
- 健康脚本可从任意 cwd 工作；
- 根 CI 实际运行 Skill 测试；
- 全量后端回归、Skill 回归、Ruff、`git diff --check` 和远程 PR CI 全部通过；
- PR 基于已经包含 PR-A 的最新 `main`。

### 9.3 PR-C 合并条件

- 文档中的镜像版本、Compose 命令、代理变量名和字体挂载路径与当前代码一致；
- 文档 whitespace 清零；
- 不混入 Dockerfile、Compose 或业务代码改动；如确实需要改代码，升级为单独功能 PR；
- 文档 PR CI 通过。

### 9.4 合并顺序

```text
PR-A 合规门禁
    ↓ 远程 CI 通过并合并
PR-B 外部 Skills
    ↓ 重新基于最新 main，远程 CI 通过并合并
PR-C 弱网文档
    ↓ 独立审查后合并
upstream 选择性评估
```

每个 PR 建议使用 squash merge，形成独立可 revert 的提交。不得在三个 PR 中夹带 upstream merge commit。分支删除、标签创建和远程清理由用户另行授权。

## 10. 上游同步策略

本轮保持 fork 独立，原因是：

- 当前上游新增提交只涉及 README 中的外部项目介绍；
- 本地 fork 已对执行证据、冻结、导出和复核链路做了大量独立加固；
- 整体 merge/rebase 会扩大冲突面，并使本轮 154 文件的审查边界失真。

后续单独执行以下流程：

1. 更新 `upstream/main` 跟踪引用；
2. 列出上游新增提交及文件；
3. 按“需要 / 已有等价实现 / 冲突 / 不采纳”分类；
4. 对需要内容建立独立 `codex/upstream-selective-sync-*` 分支；
5. 只选择性移植并重新运行本地完整门禁；
6. 在 `AGENT_MEMORY.md` 记录采纳和拒绝理由。

## 11. 风险登记与停止条件

| 风险 | 等级 | 预防措施 | 停止条件 |
| --- | --- | --- | --- |
| 冻结哈希被预检自动改变 | P0 | 预检只读、显式重新冻结 | 仍能在指标缺失时刷新即停止合并 |
| 跨模态报告显示 PASS 但实际未通过 | P0 | 状态不变量和聚合测试 | 出现状态/布尔矛盾即停止 |
| 匿名扫描误伤正常引用 | P0 | 高/低置信分层、上下文测试 | 正常 University 引用仍硬 FAIL 即停止 |
| 匿名扫描漏掉 metadata/header | P0 | 扫描 DOCX/PDF 元数据与部件 | 作者元数据测试未拦截即停止 |
| 外部 Skill 无许可 | P0 | provenance 与许可清单 | 无法证明再分发权即移出 PR |
| 大提交掩盖核心代码审查 | P1 | 三 PR 拆分 | PR-A 再次包含 `.agents/skills/**` 即退回 |
| 健康脚本只适用于单机路径 | P1 | `$PSScriptRoot` 推导根目录 | 从其他 cwd 调用失败即退回 |
| Skill 测试没有进入根 CI | P1 | 根 workflow 显式执行 | PR Checks 无 Skill 步骤即不合并 |
| 上游同步扩大冲突面 | P1 | 本轮禁止整体同步 | PR 出现 upstream merge commit 即退回 |
| 前端本机工具链造成资源异常 | P0 | 禁止本机 Node 命令 | 需要前端验证时停止并改走 Docker/人工 |

同一功能或真实案例连续两次失败后，按项目恢复规程停止增加新方案，记录失败条件并回退到已验证 Baseline；不得无限重试。

## 12. 回滚方案

- 原远程特性分支保留为来源快照，不以 reset 或 force-push 改写；
- PR-A、PR-B、PR-C 各自 squash 后可通过单独 `git revert <merge_commit>` 回滚；
- 禁止使用 `git reset --hard` 回滚共享 `main`；
- PR-A 失败时不继续 PR-B，`main` 保持原有可交付链路；
- PR-B 失败时可只回滚 Skill vendor，不影响已经验证的合规核心；
- PR-C 文档问题不影响前两个功能 PR；
- 回滚后重新运行受影响范围测试，并同步 `AGENT_MEMORY.md` 中的风险和当前处置。

## 13. Definition of Done

只有同时满足以下条件，才能宣布本轮合并完成：

- [ ] PR-A、PR-B、PR-C 按边界完成，或明确记录某 PR 被取消的理由；
- [ ] 冻结结果验证在缺失、重复、解析失败和越界路径场景全部 fail-closed；
- [ ] 论文预检不会静默改写冻结证据；
- [ ] 跨模态 blocking issue 能真实阻断 preflight/final acceptance；
- [ ] 所有报告不存在 `PASS/false` 状态矛盾；
- [ ] 匿名扫描覆盖正文、元数据、页眉页脚等可机检面，并明确图片人工复核边界；
- [ ] 三套 Skill 均有固定来源、版本、许可和本地修改记录；许可不明内容未合入；
- [ ] 无关支付、推广或来源不明二进制资产不在最终树中；
- [ ] 健康脚本无绝对工作区硬编码；
- [ ] 根 CI 实际执行后端和 Skill 测试；
- [ ] `git diff --check`、Ruff、定向测试、全量测试和远程 CI 全部通过；
- [ ] Docker 轻量真实案例完成并保持主交付 Baseline；
- [ ] `AGENT_MEMORY.md` 及所有受影响说明文件按实际行为同步；
- [ ] upstream 未被整体混入本轮 PR；
- [ ] 最终合并、推送和分支清理由用户明确授权并有实际结果记录。

## 14. 每阶段汇报模板

每个 PR 或阶段结束时按以下格式汇报：

```text
阶段 / PR：
状态：PASS / FAIL / BLOCKED

代码改动文件：
- ...

文档与记忆同步：
- 已更新：...
- 未更新：...，原因：...

验证命令与结果：
- 命令：...
  结果：...

未验证项目：
- ...

风险与回滚点：
- ...

下一步：
- ...
```

任何未实际执行的验证不得写为 PASS；自动技术门禁通过也不得替代数学、引用、匿名图片和最终版式的人工确认。

## 15. 相关文档与边界

- [`MATH_MODELING_SKILLS_INTEGRATION_PLAN.md`](MATH_MODELING_SKILLS_INTEGRATION_PLAN.md) 描述独立 `math-modeling-skills` 仓库与 MathModelAgent 候选包的只读交接，不等同于本文件的仓内 Skill vendor 合并计划；两者不得混为同一 orchestrator。
- [`CUMCM_FINAL_REVIEW_CHECKLIST.md`](CUMCM_FINAL_REVIEW_CHECKLIST.md) 是最终人工复核口径；本计划只能调整其技术前置项，不能删除数学、引用、匿名图片和最终排版确认。
- [`PDF模板导出说明.md`](PDF模板导出说明.md) 在 PDF/DOCX/LaTeX 行为或验收标准发生实际变化时同步更新。
- [`CUMCM2026模板替换指南.md`](CUMCM2026模板替换指南.md) 只在官方模板、reference DOCX、LaTeX 模板资源或替换路径实际变化时同步更新。
- 仓库根目录 `AGENTS.md` 与 `AGENT_MEMORY.md` 始终优先于本计划中的一般执行建议；实施期间如规则变化，应先更新计划再继续。
