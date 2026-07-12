# AGENT_MEMORY

## 当前稳定状态

- 默认新建建模任务使用 `cumcm2026`。
- 主交付链路是：
  - `res.md`
  - `res.pdf`
  - `res.docx`
  - `res.json`
  - `candidate_manifest.json`
  - `paper_preflight_report.json`
  - `pdf_visual_check.json`
  - `submission_audit_report.json`
- `latex_project/` 是候选 LaTeX sidecar，不是主交付链路。
- `GET /download_all_url` 会按需生成任务目录下的 `all.zip`，用于下载当前任务工作区文件；
  打包时会排除已有 `all.zip`、临时文件和常见缓存目录，并设置单文件/总大小上限，避免
  意外打包过大目录。
- LaTeX sidecar 当前已修复 CUMCM 图片路径、新版 pandoc `\pandocbounded`
  图片宏、notebook `# Cell n` 原始代码段拆分问题；导出时会扫描 Markdown/LaTeX
  中引用的本地图片，将可找到的图片复制到 `latex_project/` 和
  `latex_project/figures/`，并在 `tex_export_status.json` 记录
  `copied_assets` / `missing_assets`；若图片文件名包含 `%`、中文、`±` 等
  LaTeX 高风险字符，sidecar 会复制为 `figures/figure_XX.ext` 并重写
  `sections/*.tex` 内的 `\includegraphics` 引用，不改 `res.md` 和主 PDF/DOCX。
  sidecar 与主 PDF 都禁用 raw TeX，自动编译向 XeLaTeX 传入 `-no-shell-escape`；
  若 `latexmk` 失败，会 fallback 到连续两次同样受限的 `xelatex`，并记录
  `compile_reason` / `compile_failure_summary`。
- CUMCM sidecar 模板字体 fallback 已覆盖 `KaiTi` / `STXinwei` / `LiSu`；Docker
  中缺少 Windows 字体或 `AR PL KaitiM GB` 时，会继续 fallback 到 Noto CJK 字体，
  优先保证候选 LaTeX 工程可编译。
- Docker 正式字体自动化方案：Compose 支持通过根目录 `.env` 的
  `MMA_OFFICIAL_FONTS_DIR=C:\Windows\Fonts` 只读挂载宿主机已合法安装的字体到
  `/usr/local/share/fonts/mma-extra`，后端入口自动 `fc-cache`。这不是把开源字体
  转换为专有字体，而是在 Docker 内复用宿主机正式字体；`font_utils` 已支持
  `fc-match` 返回 `SimSun,NSimSun` 这类字体族列表时正确命中。
- 任务完成时会自动生成 `submission_audit_report.json/md`，汇总主交付文件、
  preflight、PDF 视觉检查和 `export_status.json -> pdf.font_resolution`。
  由于 workflow 先导出 Markdown/PDF/LaTeX，再由路由最终生成 DOCX，正常完成后的
  收尾步骤会在 `res.docx` 生成后重新刷新 `submission_audit_report.json/md`，
  最后再刷新 `candidate_manifest.json`，避免审核报告读取到“缺少 res.docx”的旧状态。
  默认模式下 Docker fallback 字体记为 `WARN`；正式提交前可运行
  `uv run python -m app.tools.submission_audit --work-dir project\work_dir\<task_id> --require-official-fonts`
  作为严格门禁，fallback 或未知字体来源会 `FAIL`。
  `paper_preflight_report.json = CONDITIONAL_PASS` 会在 `submission_audit_report`
  中记为 `WARN` 而不是 `FAIL`，用于表达主交付可生成但存在需人工复核/接受的条件项；
  `paper_preflight_report.json = FAIL` 或无法读取报告仍是硬失败。
  用 `export_cli pdf` 手动/正式重导时加 `--update-status`，会同步刷新
  `export_status.json`、`pdf_visual_check.json`、`submission_audit_report.json`
  和已有的 manifest，避免审核读取旧字体记录。
- CUMCM 官方 2026 论文格式规范强调电子版论文为单独 PDF/Word 文件（建议 PDF、
  不超过 20MB），第一页必须是摘要页，不放承诺书和编号专用页；支撑材料单独压缩，
  至少包含所有可运行源程序、数据资料和较大篇幅中间结果图表。项目标准流程据此调整为：
  `res.pdf/res.docx` 论文附录只保留支撑材料清单和核心代码摘录，完整可运行
  `notebook.ipynb`/脚本保留在支撑材料并由 manifest/audit 登记。后处理会重建旧附录，
  删除批量 `print(...)`/`printf`/`console.log` 控制台输出语句，`paper_preflight_report`
  新增 `appendix_console_noise` 门禁。
- 当前最新真实烟雾任务的主链路曾达到：
  - `task_id = 20260709-091916-1ff165da`
  - `paper_preflight_report.json = PASS`
  - `export_status.json -> pdf.success = true`
  - `pdf_visual_check = PASS`
  - `tex_export_status.json -> compile_success = true`
  - `latex_project/main.pdf` 已生成
  - `submission_audit_report.json` 经 DOCX 后收尾刷新后为 `PASS`
  - 该任务使用 `mimo-v2.5` 真实接口完成轻量线性规划题，最优结果为
    `A=40, B=20, profit=2200`，机器时间增加 10 小时后利润约 `2366.67`。
- 2026-07-09 针对当前多 PR 风险修复分支重建 Docker 后，基础服务烟雾验证通过：
  `docker compose up --build -d`、前端入口 `http://127.0.0.1:5173/`、后端
  docs 代理 `http://127.0.0.1:5173/api/docs`、容器内后端单测与
  `ruff check app` 均可运行通过。完整真实建模 smoke 暂被外部 LLM provider
  阻塞，最新任务 `20260709-014347-c9ed2ddd` 在 Coordinator 阶段连续重试后失败：
  `403 GROUP_DISABLED` / `API Key 所属分组已停用`；任务目录仅生成
  `task_status.json` 和字体文件，无 `res.md`、`res.json`、`res.docx`、
  `candidate_manifest.json` 或 checkpoint。恢复有效 key 后需重跑项目规则中的
  轻量线性规划题，验收 `/tasks` 为 `completed` 且主交付文件存在。
- 2026-07-09 使用用户提供的新 `xiaomimimo` Responses provider key 后，模型验证
  `mimo-v2.5` + `https://api.xiaomimimo.com/v1` 成功，并完成一次真实轻量任务
  `20260709-091916-1ff165da`。随后在 PR #8 合并后的修复代码上
  再次重建 Docker 并重跑真实任务 `20260709-093451-96f6f897` 时，任务已越过
  Coordinator/Modeler/Coder，后续 Writer 阶段因 provider 返回 `402 Insufficient account balance`
  中断；这表示 key 已可用但账户余额不足，恢复余额后需继续重跑完整 smoke。
- `cumcm2026` 是基于 2026 修订稿规范实现的暂定模板，不是官方最终 DOCX/LaTeX 模板包。
- 主 PDF 导出会在摘要/关键词后做 PDF-only 分页，支持裸 `关键词：...` 与
  `**关键词**：...`，保证摘要页独占第一页、正文从第二页开始；该分页不写回
  `res.md`，也不影响 DOCX 或 LaTeX sidecar。
- `cumcm2026` 主 PDF 当前使用 `left=3.17cm,right=3.17cm,top=3cm,bottom=2.8cm`；
  底边距高于 2.5cm 是为了给实际字体字形 bbox 留安全余量，避免正文末行触发
  CUMCM 2.5cm 内容边距检查失败。
- 论文后处理会做内容一致性兜底：移除没有参考文献条目支撑的裸 `[n]`
  引用、为 Markdown 表格自动补 `表n` 标题、清洗 Markdown 图片 alt 文本避免
  PDF/DOCX 图题带 `.png`/下划线等文件名痕迹、把常见英文过渡词
  `Overall`/`However` 等替换为中文表达、在正式题目数不足时把可见 `问题3_...`
  扩展分析标签和 `问题三：...` 扩展段落规范为 `灵敏度分析...`（图片路径保持原文件名）。
  图片预检会区分正文图和支撑材料图：正文 `![](...)` 引用的图片必须存在；生成图片
  若没有正文引用但已在附录A支撑材料表中登记为 `图片文件`，视为 accounted support
  artifact，不再计入 `checks.images.unused_generated`；既未正文引用、也未登记的生成图片
  仍会触发图片 conditional。
  工作流会把原题拆分出的 `quesN` 数量传给后处理，避免 Writer 自行编出的额外问题
  污染题目数判断。后处理还会清理最终稿和附录代码中可见的 `用户`、`推断`、
  `估算`、`待验证` 等提交痕迹，改为 `题目`、`核定`、`测算`、`需核验` 等正式表达。
  代码附录中的纯装饰性超长分隔线会缩短到安全长度，避免 PDF 内容边距检查
  因源码页超宽文本误报失败。
  独占一行的加粗短标签（如 `**假设1：...**`）会规范为 Markdown 小标题，
  避免 Pandoc 把后续整段误解析成 LaTeX description label 导致正文不可换行。
  孤立的 `: ... DOI ...` 定义式参考行会被删除，避免同类 description list 误解析。
  预检还会阻断电子论文中出现 `承诺书`、`编号专用页`、`参赛队号`、`队员姓名`
  等身份/封面字段，避免违反高教社杯匿名电子稿口径。
  `paper_preflight_report.json -> checks.result_consistency` 会读取任务目录中
  结果 CSV 的结构化关键数值，目前重点检查机器时间/人工时间影子价格；如果正文
  同标签句子中的数值与 CSV 不一致，预检硬门禁 `FAIL`。没有可识别结果 CSV 时
  不阻断，因此该检查只能拦截已结构化事实的明显冲突，不替代完整数学复核。
  `flows.get_writer_prompt` 会把同一批结构化结果事实注入写作手提示，要求正文关键
  数值优先使用结果 CSV，减少 Writer 在摘要/求解/敏感性段落中复述错误数字。
  若正文已经说明题目参数是确定性常量、无随机样本数据，后处理会把
  `描述性统计` 这类样本数据 EDA 用语规范为 `参数核验`，并清理正文/支撑材料中的
  Monte Carlo、蒙特卡洛、随机模拟等探索性随机模拟内容；代码附录中的同类标签会
  降级为参数扰动表述。
- 参考文献条目会以空行分隔，避免 Pandoc PDF/DOCX 导出时把多条参考文献合并成
  同一段；若模型生成空参考文献段且正文无有效引用，后处理会删除空参考文献段，
  预检不再因为“无引用且无文献”单独失败。
- 代码手 EDA 提示已区分“无外部数据集”和“数据驱动题”：当当前数据集文件列表为空时，
  不得随机生成模拟样本或创建模拟数据集，只做题目给定参数、单位、约束和可行域核验。
- Docker 前端不再依赖浏览器直连宿主机 `8000` 端口：`frontend/.env.docker`
  使用 `VITE_API_BASE_URL=/api`、`VITE_WS_URL=ws://localhost:5173/ws`，由
  Vite dev server 代理到 Compose 内部 `backend:8000`；后端 Docker 场景的
  `SERVER_HOST` 也指向 `http://localhost:5173/api`，下载链接走同一代理入口。
- LLM provider 单次请求超时由 `LLM_REQUEST_TIMEOUT_SECONDS` 控制，默认 90 秒；
  用于兼容较慢的 OpenAI-compatible/Responses/Anthropic 端点，避免建模手或写作手
  在正常长响应时过早 `Request timed out`。
- `HUMAN_MODEL_GATE_ENABLED=true` 时，Modeler 阶段会生成 `modeling_decision.md/json`
  并把任务状态置为 `waiting_review`；前端任务页会定时刷新任务状态并显示“确认建模方案并继续”，
  调用 `/modeling/{task_id}/approve-modeling` 后从 Coder 阶段续跑。
- 2026-07-10 在 PR #11 最新后端与 PR #6 前端的临时集成 worktree 中重建 Docker，
  真实任务 `20260710-010231-e6470545` 从 `running` 自动进入 `waiting_review`，无需刷新页面
  即显示审批按钮；审批后任务恢复并完成。`modeling_decision.json=approved`，checkpoint、
  变量快照、Markdown/JSON/DOCX/PDF、manifest 均生成，preflight、PDF 视觉检查和 LaTeX
  编译通过；submission audit 仅因 Docker fallback 字体为 `WARN`。
- `/status` 的 `backend.feature_warnings` 会报告配置存在但尚未接入主工作流的能力，
  例如 `RAG_ENABLED`、通用 `HIL_ENABLED`、`FALLBACK_ENABLED`、`EVALUATOR_ENABLED`；
  这些 warning 不阻断服务启动，只用于避免把配置开关误判为已完成功能。
- `/save-api-config` 只把验证后的模型配置应用到当前后端进程的 `settings`，
  不写回 `.env.dev`，响应中会明确 `scope=runtime`、`persisted=false`；
  空字段不会覆盖 `.env.dev` 已加载的默认值，且响应不回显 API key。前端 Pinia
  store 不再持久化用户填写的 API key，页面升级时会清理旧版 `localStorage.apiKeys`。
- 2026-07-11 安全默认值：Docker Compose 前后端端口只绑定 `127.0.0.1`；CORS、
  WebSocket Origin 和 Host 均为明确 allowlist（防 DNS rebinding）；工作区文件不再以任意静态目录直出，
  只有安全单层文件名可下载，非栅格图片附件强制下载。新 task_id 使用 128 位随机
  capability 后缀；上传按单文件/总量流式限额写入。
- 模型生成代码默认必须通过 E2B 远程沙箱执行（`CODE_INTERPRETER_KIND=remote`）；缺少
  `E2B_API_KEY` 时失败而不降级。`local` 仅在 `ALLOW_LOCAL_CODE_EXECUTION=true` 的
  受信任隔离开发环境可用，不能当作共享/正式环境的默认执行方式。
- LLM Base URL 默认要求 HTTPS、公开 IP/DNS 解析结果，且 SDK 请求禁用重定向与环境代理；
  私有地址必须显式设置 `ALLOW_PRIVATE_LLM_BASE_URLS=true`。
- LLM 成功调用后会在任务目录写入 `token_usage.json`，只保存按 agent 聚合的
  `chat_count`、`prompt_tokens`、`completion_tokens`、`total_tokens` 和模型名，
  不保存 prompt、completion、tool args、API key 或 base_url；`GET /track`
  读取该文件返回聚合统计。统计写入是 best-effort，失败不会让已成功的 LLM 调用重试；
  当前只保证单进程内加锁累加，多 worker/多进程场景不作为强一致账单依据。
- Anthropic provider 对 `api.anthropic.com` 官方地址继续使用 Anthropic SDK
  `api_key` 认证；对非官方 Anthropic 兼容网关改用 Bearer `auth_token`，
  以兼容 `ANTHROPIC_AUTH_TOKEN` 风格服务。2026-07-09 用户提供的 CloudBase
  网关已用 `hy3-preview` 验证文本请求和 `tool_choice=auto` 工具调用可用；
  本地忽略配置 `backend/.env.dev` 可设置四个 Agent 使用
  `COORDINATOR/MODELER/CODER/WRITER_API_TYPE=anthropic`、模型 `hy3-preview`
  和对应 CloudBase base URL，密钥不应写入 Git。
- 2026-07-09 CloudBase `hy3-preview` 真实轻量 smoke 任务
  `20260709-111913-995cfe14` 已在 Docker 中通过续传完成，主产物、变量快照、
  `paper_preflight_report=PASS`、`pdf_visual_check=PASS`、
  `tex_export_status.compile_success=true`、`candidate_manifest.json` 均生成；
  `submission_audit_report=WARN`，唯一 WARN 是 Docker 环境缺少 SimSun /
  Times New Roman 导致 PDF 字体 fallback 到 Noto Serif CJK SC /
  Liberation Serif。按项目规则这不视为主流程失败，正式提交前仍应挂载
  `MMA_OFFICIAL_FONTS_DIR=C:\Windows\Fonts` 或在 Windows 本机重导并跑严格字体门禁。
  在新增 `checks.result_consistency` 后，用当前分支代码只读复核该任务会因正文影子价格
  `26.7/13.3` 与 CSV 中 `16.67/6.67` 冲突而 `FAIL`；这说明旧报告的 PASS 不能代表
  当前代码门禁结果。该 smoke 只证明 provider/导出链路可用；preflight/audit 仍不等同
  于数学正确性证明。
- 2026-07-09 在 PR #11 对应代码上重建 Docker 后，CloudBase
  `hy3-preview` 真实轻量 smoke 任务 `20260709-153822-846f9e0e` 完成。刷新后
  `paper_preflight_report=PASS`、`checks.images.unused_generated=[]`、
  `checks.result_consistency.passed=true`、`pdf_visual_check=PASS`、
  `tex_export_status.compile_success=true`、`res.docx`、`candidate_manifest.json`
  均生成；`submission_audit_report=WARN`，唯一 WARN 是 Docker 环境字体 fallback，
  按项目规则不视为主流程失败。
   该 smoke 只证明 provider/导出链路可用；preflight/audit 仍不等同于数学正确性证明。
- 2026-07-11 在最终审计修复分支重建 Docker 后，前端入口、`/api/docs` 代理、
  后端 docs、容器内指定单测和 Ruff 均通过；真实轻量线性规划任务
  `20260711-005536-09d34201` 在 Coordinator 早期因 provider 授权失败而终止，
  未生成主交付物或 checkpoint。按当次验收要求未重试；恢复有效 provider 授权后，
  需重跑项目规则中的轻量线性规划题并核验任务状态和交付物。
- 2026-07-11 更新有效的 OpenAI Responses 兼容运行配置并重建后端后，模型枚举与
  真实轻量线性规划任务 `20260711-133616-38439fe3` 均成功。任务状态为 `completed`，
  已生成 Markdown/JSON/DOCX/PDF、manifest、checkpoint 和变量快照；
  `paper_preflight_report`、结果一致性、PDF 视觉检查、submission audit、PDF 导出和
  LaTeX 编译均为 `PASS`/成功。正文经人工数值核验为 `A=40`、`B=20`、利润 `2200`，
  机器时间增加 10 小时后利润 `2366.67`；`/track` 返回四个 Agent 的聚合统计，
  `/download_all_url` 生成并成功下载 ZIP 归档。
- 2026-07-11 安全收尾验证：Docker 重建后，容器内全量非 E2B 单测 `214 tests`、
  Ruff（含 `--select S`）、Bandit、pip-audit、前端 TypeScript/生产构建和生产依赖
  audit 均通过；前后端仅监听 `127.0.0.1`，未受信任 Host 分别被后端 `400`、前端
  `403` 拒绝。对任务 `20260711-133616-38439fe3` 重新执行
  `submission_audit --require-official-fonts` 为 `PASS`。这轮没有另起真实模型/E2B
  任务，严格审核复用的是已完成真实任务的交付物。
- 当前 Git 跟踪文件的无回显凭据模式扫描为零命中；但已删除的
  `frontend/src/assets/jupyter copy.json` 仍存在于历史提交 `236d158` 与 `190dc98`。
  该资产曾含 token 形态内容，正式公开发布前应轮换相关凭据并在获得明确 force-push
  授权后重写远程 Git 历史；不要读取或回显其内容。
- 2026-07-11 已核验 PR #1-#14 全部合并到 `main`，随后删除其历史本地/远程
  `codex/*` 分支、六个不再使用的 worktree 以及一个失效 worktree 注册。后续工作应
  从干净的 `main` 创建新分支；归档计划中的 PR 编号可用于追溯历史实现。
- 真实提交前仍需人工复核论文内容和 PDF 排版。

## 接手时禁止全盘扫描

- 新 agent 接手时先读 `AGENT_MEMORY.md`。
- 再读 `AGENTS.md`。
- 再按任务需要读指定指南。
- 不要一上来 grep/search 全仓库。
- 不要读取 `.venv/`。
- 不要读取 `frontend/node_modules/`。
- 不要扫描 `backend/project/work_dir/` 下大量历史任务，除非用户明确要求。
- 诊断具体任务时只读对应 `<task_id>` 目录里的报告文件。
- 如果用户没有给 task_id，先按时间列出最近任务目录和报告状态。
- 不要重跑长任务，除非用户明确要求。
- 不要提交、推送、合并，除非用户明确要求。

## 核心文档入口

- `AGENTS.md`
  - 项目级规则、验证方式、前端 Node 限制。
- `STARTUP.md`
  - 启动方式、导出 profile、Docker 验证、CUMCM 2026 状态说明。
- `docs/md/PDF模板导出说明.md`
  - PDF/DOCX/LaTeX 导出说明、字体 fallback、验收要点。
- `docs/md/CUMCM2026模板替换指南.md`
  - 官方模板发布后的快速替换路径。
- `docs/md/CUMCM_FINAL_REVIEW_CHECKLIST.md`
  - preflight/PDF 通过后的人工复核清单。
- `backend/app/templates/export_profiles/README.md`
  - 模板资源目录说明。

## 每次任务完成后的同步检查

完成任何代码或导出链路修改后，提交前必须检查是否需要更新：

- `AGENT_MEMORY.md`
- `STARTUP.md`
- `docs/md/PDF模板导出说明.md`
- `docs/md/CUMCM2026模板替换指南.md`
- `docs/md/CUMCM_FINAL_REVIEW_CHECKLIST.md`
- `backend/app/templates/export_profiles/README.md`

如果改动改变了当前稳定状态、已知风险、验证命令、失败诊断顺序或最近关键提交，必须更新本文件。

## 核心代码入口

- `backend/app/schemas/request.py`
  - `DEFAULT_MODELING_EXPORT_PROFILE = ExportProfile.CUMCM2026`
  - 新建建模任务默认 profile 的源头。
- `backend/app/routers/modeling_router.py`
  - `/modeling` 默认 export profile。
  - 任务创建、取消、续传、建模确认入口。
- `backend/app/tools/export_profiles.py`
  - `CUMCM2026_PROFILE`
  - PDF 变量、DOCX reference、LaTeX sidecar 模板路径。
- `backend/app/tools/pdf_exporter.py`
  - 主 PDF 导出。
  - Pandoc + XeLaTeX。
  - 主 PDF 禁 raw TeX，支持 `$...$` 和 `\(...\)`。
  - PDF-only 预处理会在关键词后插入内部分页标记，再由
    `pandoc_filters/pdf_pagebreak.lua` 转为 LaTeX `\clearpage`。
  - PDF-only 预处理会给连续中文长句插入内部断行标记，再由同一 Lua filter 转为
    LaTeX 断点；不回写 `res.md`，不影响 DOCX 或 LaTeX sidecar。
- `backend/app/tools/tex_project_exporter.py`
  - LaTeX sidecar 导出。
  - `latex_project/` 是候选产物。
  - 负责复制 Markdown/LaTeX 引用的本地图片并记录 `copied_assets` /
    `missing_assets`。
  - 会把 LaTeX 高风险图片文件名复制为安全文件名并重写 sidecar 内部引用。
- `backend/app/tools/paper_postprocessor.py`
  - 参考文献、附录、支撑材料、预检、claim trace。
  - 负责 `paper_preflight_report.json/md`。
  - 检查正文引用编号是否都有文末参考文献条目、表格是否有编号标题、图片图题是否
    避免文件名痕迹、生成图片是否已被正文引用或附录A支撑材料表登记、常见英文过渡词
    是否已转为中文、扩展分析是否被误标为不存在的“问题3”。
- `backend/app/tools/pdf_visual_checker.py`
  - PDF 后验视觉检查。
  - 检查 A4、非空、文本可提取、20MB 文件大小、摘要首页、无目录、
    正文 30 页以内、物理边缘越界和 CUMCM 2.5cm 内容边距风险
    （允许少量字形 bbox 容差），并扫描全文页的 A4 尺寸与承诺书/编号页/
    参赛队号等身份字段。
- `backend/app/templates/export_profiles/`
  - DOCX/LaTeX 模板资源。
  - 当前 `cumcm2026` 暂时复用 2025 资源。

## 已知风险

1. LaTeX sidecar 编译失败是非阻断风险；不要把它当成主交付失败。
2. `paper_preflight_report.json = PASS` 不代表数学模型、求解结果、论文论证正确。
3. `cumcm2026` 暂时复用 2025 DOCX reference 和 2025 LaTeX 模板资源；官方 2026 模板发布后按指南替换。
4. 主 PDF 禁 raw TeX；正文应使用 Markdown 表格和标准 `$...$`、`\(...\)` 数学公式。
5. `pdf_visual_check.json = PASS` 会覆盖 A4、摘要首页、无目录、正文页数、
   文件大小和 2.5cm 内容边距等低成本格式风险，但仍不替代人工翻阅 PDF。
6. Docker 字体未挂载正式字体时会 fallback 到开源字体；正式提交前建议设置
   `MMA_OFFICIAL_FONTS_DIR=C:\Windows\Fonts` 重导，或用 Windows 本机官方字体复核。
   `submission_audit_report.json` 严格字体门禁可确认 PDF 是否仍在 fallback。
   后端 Dockerfile 通过带超时和重试的 `pip install uv==0.11.14` 安装 uv，
   不再依赖 `ghcr.io/astral-sh/uv:latest` 多阶段镜像，降低 GHCR
   token/metadata 网络失败和 PyPI 大 wheel 弱网 read timeout 导致的构建中断风险。
   当前 Docker 前端通过 `5173/api` / `5173/ws` 代理访问后端，即使 Docker
   Desktop 宿主机 `8000` 端口发布异常，Web UI 也仍可通过前端入口访问后端。
7. `candidate_manifest.json` 登记的是候选产物和证据链，不保证论文内容正确。
8. 历史任务目录可能保存旧导出器状态，诊断时要区分“当前代码行为”和“历史产物状态”。

## 失败诊断顺序

- 先看对应任务目录：
  `backend/project/work_dir/<task_id>/`
- 依次读：
  1. `paper_preflight_report.json`
  2. `paper_preflight_report.md`
  3. `export_status.json`
  4. `pdf_visual_check.json`
  5. `tex_export_status.json`
  6. `candidate_manifest.json`
  7. 必要时再看 `res.md`
  8. 若 PDF 出现大量 `print(...)`/控制台输出，优先检查
     `paper_preflight_report.json -> checks.appendix_console_noise`，再重新运行
     `prepare_paper_markdown` 重建附录并重导 DOCX/PDF。
- 如果 PDF 失败，优先看：
  `export_status.json -> pdf.stderr`
- 如果 preflight FAIL，优先看：
  `paper_preflight_report.json -> checks`
- 如果参考文献或表格细节异常，优先看：
  `checks.references.missing_inline`、`checks.tables.uncaptioned_tables`、
  `checks.extra_problem_labels.issues`。
- 如果正文关键数值与代码/CSV 输出疑似不一致，优先看：
  `checks.result_consistency.conflicts`，再对照对应 `source` CSV 和 `res.md`
  中的 `sentence`。
- 如果轻量题目没有外部数据集但论文出现“模拟数据集”“随机生成样本”等内容，
  优先检查代码手 EDA 输出和 `flows.py`/`prompts/coder.py` 的无数据 EDA 边界提示。
- 如果 PDF 视觉检查失败，优先看：
  `pdf_visual_check.json -> checks`
  尤其是 `submission_anonymity`、`a4_size`、`content_margin`、`abstract_first_page`。
- 如果 sidecar 失败，先确认是否影响主交付；通常不阻断。
- 如果 sidecar 报图片缺失，先看 `tex_export_status.json -> missing_assets`，再确认
  `res.md` 或 `sections/*.tex` 中的图片引用是否存在于任务 work_dir。
- 如果报告被后续重新导出覆盖，先说明无法从当前文件复原旧 stderr。

## 常用验证命令

```powershell
cd backend
uv run ruff check app
uv run python -m unittest app/tests/test_export_profiles.py app/tests/test_pdf_template_command.py app/tests/test_tex_project_exporter.py app/tests/test_paper_postprocessor.py app/tests/test_user_output_and_tasks.py
uv run python -m unittest app.tests.test_font_utils app.tests.test_submission_audit
uv run python scripts/smoke_pdf_export.py
```

## 常见判断

- 主链路成功通常看：
  - `paper_preflight_report.json = PASS`
  - `export_status.json -> pdf.success = true`
  - `pdf_visual_check.json = PASS`
  - `candidate_manifest.json` 登记主交付文件。
- sidecar 候选工程成功通常看：
  - `tex_export_status.json -> compile_success = true`
  - `latex_project/main.pdf` 存在且非空
  - `tex_export_status.json -> missing_assets = []`
- 如果 `res.pdf` 成功但 `latex_project/` 编译失败，先汇报 sidecar 非阻断。
- 如果 `preflight PASS` 但论文内容可疑，使用最终人工复核清单。
- 如果 `checks.result_consistency` 为 PASS，仅表示已识别 CSV 事实没有与正文冲突；
  未结构化入 CSV 的公式推导、模型选择和单位理解仍需人工复核。
- 如果官方发布 2026 Word/DOCX 模板，按 `docs/md/CUMCM2026模板替换指南.md` 替换 `cumcm2026_docx`。
- 如果官方发布 2026 LaTeX 模板，按 `docs/md/CUMCM2026模板替换指南.md` 新增 `cumcm2026/`。
- 不要覆盖 `cumcm2025/` 或 `cumcm2025_docx/`。
- 如果用户只要求诊断，不要改代码、不要重跑长任务、不要提交。
- 如果用户要求真实烟雾测试，先确认 API key 处理方式，不要在回复里回显 key。
- 如果用户要求前端验证，优先使用 Docker 前端 `http://127.0.0.1:5173`。
- 不要运行本机前端 Node 命令，除非用户明确授权。
- 如果需要看历史任务，先列目录和报告状态，再读取最相关的一个任务。
- 每次声称通过验证前，必须实际运行对应命令。

## 最近相关提交

- `43db371 docs: require handoff memory sync after tasks`
- `b05bc2f Fix LaTeX sidecar compilation fallback`
- `93b02b5 docs: add CUMCM 2026 template replacement guide`
- `dfa89d1 Default modeling exports to cumcm2026`
- `012a68f Fix CUMCM 2026 export validation`

## 沟通口径

- 汇报用中文。
- 不要打印 API key、token、私钥、完整环境变量。
- 未运行验证时必须明确说“未验证”。
- 诊断任务失败时先给结论，再列证据文件和字段。
