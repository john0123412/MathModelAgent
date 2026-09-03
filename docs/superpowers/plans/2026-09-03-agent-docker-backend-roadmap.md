# 执行 Agent 调用 Docker 后端的建模改进计划

日期：2026-09-03。状态：待实施的设计与验收计划；本文件不代表下面的新接口、新命令已经实现。

## 1. 目标与架构选择

用户的主入口是外层执行 Agent。它接收赛题、分析路线、调用本机 Docker 后端、跟踪执行、审阅模型和结果、发起有界返修，最后取得经过复核的论文与支撑材料。前端不在必需链路中。

采用现有工作流的监督式调用：

    用户 → 外层执行 Agent → 结构化任务客户端 → 本机 FastAPI
                                          ↓
                  Docker 内 Coordinator → Modeler → 建模审阅
                                          ↓
                  Coder → 执行证据 → 冻结 → 结果复核
                                          ↓
                  Writer → 导出与技术门禁 → 六维内容评审
                                          ↓
                  候选包清单、版本、哈希 → 外层 Agent 交付

外层 Agent 负责策略与复核；后端负责任务状态、实际执行、证据登记、预算与产物发布。复核发现问题时，调用现有的定向修复流程，不能直接修改冻结文件或把哈希重算当作执行证明。

先实现 HTTP + CLI。后续如需 MCP，只给同一套操作加工具封装，不另建调度器，也不引入桌面私有 MCP。默认一个建模任务运行、一个 uvicorn worker；API 保持可响应不等于增加建模并发。

## 2. 本轮取证范围与当前基线

- 用户给出的 D:/Users/Johnny/downloads/mathmodel/_workspace/_0.0.15 在本机不存在。实际读取的参考目录是 D:/Users/Johnny/downloads/mathmodel_workspace_0.0.15。
- 安装包 mathmodel-0.0.15-x64.exe：323270661 字节；SHA256 为 48FC15066F935F170A9E47582D6A73AD8CA320C35C57245667097DB105423D44。package.json 版本 0.0.15，桥接依赖版本 0.3.0；这两项在上一轮实际核验。
- 参考对象主要是 2_app/resources/builtin-skills 内可读规则、模板配置与脚本。没有把混淆主进程中出现的字符串当作接口实现或可靠性证明，也未调用其私有云服务。
- 当前 main 为 30fb509，origin/main 为 114b938。PR #37 已合并，ac494ec 已在 main 历史中；不再安排旧 enhance 分支合并。
- 当前有 5 个后端文件及记忆文档的既有未提交改动；没有覆盖、提交或回滚。原有未跟踪文件也未清理。
- 本轮直接读取 8000 端口的 OpenAPI 与 /status：backend、Redis 均 running；解释器 selected_kind=local、status=ready、允许本地执行、单次执行超时 300 秒；未配置 E2B。该结果只证明服务自报能力和接口可访问，不证明真实建模已经验收。
- 上一轮在宿主机固定 backend 虚拟环境中运行相关四组测试，160 项通过；ruff check app 通过。本轮没有重跑这些测试，没有调用真实 provider，没有启动新建模任务，没有重建或停止容器，没有扫描历史任务产物。
- 本轮未调用子代理；当前接口与预算条件不满足仓库要求的子代理调用约束。

## 3. 已有能力：必须复用，避免重复建设

| 操作 | 当前入口 | 已有边界 |
| --- | --- | --- |
| 提交题面与附件 | POST /modeling，multipart/form-data | 题面、比赛类型、输出格式；附件保存并登记 input_manifest；可预注入引导 |
| 要求阶段审阅 | 创建时 require_model_review=true | Modeler 后暂停；冻结结果机器筛查通过后也仍需结果复核 |
| 定向引导 | POST /modeling/{task_id}/guidance | coordinator/modeler/coder/writer/all；属于建议，不覆盖验证规则 |
| 建模审批与退修 | approve-modeling、revise-modeling | 保留现有审阅要求与一次退修边界 |
| 外层建模方案接管 | codex-modeling | 仅适用于启用审阅门禁、Modeler 失败且无已执行/冻结产物的任务；不是通用初始方案接口 |
| 执行结果审批与定向重算 | execution-review | action=approve/repair；review_id 绑定当前结果；指定正式子题，有持久返修限制 |
| 续传与停止 | resume、cancel | 复用 checkpoint、变量快照和恢复限制；普通 resume 不绕过审阅状态 |
| 查询 | /status、/tasks、/messages、/track、/files | 已有基础能力；尚缺按任务聚合的紧凑查询、消息游标与完整机器可读控制契约 |
| 受控代码候选 | app.tools.repair_candidate_cli | 仅 backend 容器；脚本与证据必须在任务目录；不提供任意命令执行接口 |
| 受控论文候选 | app.tools.paper_repair_candidate_cli | 独立的论文/编辑质量/版式/格式修复边界；再走 resume 正式导出 |
| 模板覆盖与导出 | app.tools.export_cli template、task-refresh | 已有任务级模板合同、哈希校验、重导与最终验收；task-refresh 不重跑数值代码 |
| 候选产物 | candidate_manifest、artifact_set_id、技术门禁报告 | 用于交付和外部接管；不是数学正确性的自动批准 |

关键代码锚点：backend/app/routers/modeling_router.py、common_router.py、files_router.py；backend/app/core/workflow.py、checkpoint.py；backend/app/tools/repair_candidate_cli.py、paper_repair_candidate_cli.py、export_cli.py。

已有 mathmodelagent-candidate-bridge 只负责已完成产物的只读交接，不负责运行中的任务控制。新建操作入口应与它分工，不改变该 bridge 的只读语义。

## 4. 0.0.15 借鉴矩阵

| 参考能力 | 借鉴内容 | 后端/外层落点 | 不直接复制的部分 |
| --- | --- | --- | --- |
| mma-figure | 数据图、模板图、结构图、物理图分类；源文件与插图用途清单 | 后端 figure plan、Coder 绘图工具、paper_assets_manifest；外层一个配图入口 | 本地没有同名 nature-figure/paper-diagram；固定 SimSun、仅 document.tex、项目根路径需适配 |
| mma-review | 六维审阅、致命项、每条意见的位置与改法、只评不改 | 外层审阅 + 后端结构化评审包、问题分流和版本校验 | 60 分不是获奖预测；半页摘要不是通用硬规则；不能让未知项按 0 分或 PASS 处理 |
| mma-paper | 模板源配置、入口存在时不覆盖、多面板图、逐问处理 | 任务合同、导出 profile、后端写作与图表规则 | 不把 14 个桌面目录整体搬进镜像；不以 LaTeX 原稿替换现有 Markdown/DOCX 主交付链 |
| doctor | 必需/建议/按需分级；结构化报告；Git 与 PATH 提示 | 宿主机连接检查 + 容器内部能力检查 | 宿主机有工具不代表容器有；容器建模不依赖 Git 快照时不将 Git 设成容器必需项 |
| paper-search | 检索 → 元数据核验 → 由来源生成引用 | 复用现有多源搜索；补文献条目、核验状态、正文断言绑定 | 不把联网失败等同于伪造；不重复实现现有检索聚合器 |
| data-search | 数据来源、口径、时间范围、原始文件哈希登记 | input_manifest 的补充来源记录；任务附件与外部数据共用验证入口 | 桌面 browser_* 和交互式下载不可假定在容器内可用 |
| metaheuristic-optimization | 确定性基线优先、原目标与罚项分开、预算和随机种子、独立可行性检查 | Modeler/Coder 阶段按题型加载的规则，冻结结果的算法语义字段 | 不默认安装 MEALPY/pymoo 全家桶；加权扫描不能自动声称完整 Pareto 前沿 |
| paper-diagram / nature-figure | 版式检查、统一样式、可编辑源、多面板规范 | 容器可执行的少量模板及导出能力；数值图优先现有 matplotlib | drawio 导出脚本依赖桌面 CLI；缺失时不能把 .drawio 源文件当作已导出图 |
| 桌面工具/MCP 思路 | 对 Agent 暴露少量结构化动作、明确结果与下一步 | 先任务客户端，后可选 MCP 适配层 | 不复用私有工具名或接口，不反向依赖 Electron |
| OpenAI–Anthropic bridge | 多协议能力探测和工具调用兼容测试的思路 | 现有 OpenAI/Responses/Anthropic provider 层 | Python 后端已有原生适配，不引入 Node 协议桥 |
| PDF 预览、paper-sharing | 逐页复核、独立交付副本、明确产物清单 | 本地 PDF 页面证据与 candidate manifest | 不引入广场上传、paperCloud、自动发布和脱敏后自动上传 |
| yjs/mDNS | 当前目标下没有必要引入 | 暂缓 | 不建设协同编辑与局域网发现 |

早期分叉后，本地在执行证据、冻结、受控返修、续传方面已有独立积累。升级应把桌面工作方法接到这些能力上，而不是追求目录或文件数量一致。

## 5. 分批实施计划

### 批 A：P0，先建立可复现的纯后端基线

改动内容：

1. 审核当前 5 个未提交后端文件，逐项区分通用修复、任务偏好和竞赛格式。处理上一轮已复现的手机号中文相邻漏检，以及摘要首页检查与 profile 配置矛盾。
2. 将页数、摘要、字体、行距等规则收敛到明确 profile/任务合同，不以单篇论文的排版需求改变所有任务。
3. 提供只启动 backend + redis 的正式入口。复用现有 local-execution 的用户隔离、环境白名单、资源限制和工作目录挂载，不因去掉前端而换成较弱配置。
4. 修复 SERVER_HOST 默认指向 5173/api 的残留。产物接口返回相对路径及可选绝对 URL；Agent 使用其配置的 8000 基址，不依赖前端代理。兼容原有前端入口。
5. 提供部署信息：代码版本、镜像标识、是否挂载源码、能力版本。存在未提交代码时显式标记，不能仅报 git SHA 冒充完全可复现。

涉及文件：docker-compose.yml、docker-compose.local-execution.yml、scripts/docker-local-execution.ps1；backend/app/routers/files_router.py、common_router.py、backend/app/utils/common_utils.py；既有五个改动文件。新的纯后端覆盖文件只在必要时增加。

验收：在隔离验收环境不启动 frontend，8000 上的状态、提交、查询、下载均可用；生成的下载链接不要求 5173；原有默认导出最小路径不退化。不要为验证本批擅自停止当前活跃服务。

### 批 B：P0，统一 Agent 调用契约与客户端

新增一个薄任务客户端，建议位置 backend/app/tools/task_client.py。它是宿主机调用工具，使用固定 backend 虚拟环境；普通操作发 HTTP，受控候选操作调用容器 CLI。避免导入后端配置而无意读取 provider 凭据。

拟提供命令族：doctor、submit、inspect、events、guide、approve-model、revise-model、review-results、resume、cancel、artifacts，以及受控 repair-code/repair-paper/export。命令名是设计草案，当前不存在。

优先补足以下后端契约，不替换已有 /modeling：

| 拟新增/增强项 | 设计要求 |
| --- | --- |
| 创建幂等键 | Idempotency-Key + 规范化请求/附件哈希；同键同内容返回原 task_id，不同内容返回 409；并发和进程重启后仍生效 |
| 单任务状态 | GET /tasks/{task_id}：task_status、workflow_state、revision、当前阶段/子题、最后活动时间、review_id、允许动作、阻断原因、预算摘要、产物版本 |
| 消息增量 | GET /tasks/{task_id}/events?after=...&limit=...；稳定序号、游标、过期提示；不每轮返回整份聊天或推理内容 |
| 产物清单 | GET /tasks/{task_id}/artifacts：复用 manifest，返回角色、路径、大小、哈希、新鲜度与审核状态 |
| 指令回执 | guidance_id；区分 accepted、consumed、expired/rejected；重启后不静默丢失未处理指令，也不重复消费 |
| 错误返回 | error_code、可否重试、allowed_actions、review_id、操作编号；不能只靠中文错误消息驱动下一步 |
| 状态前提 | 审批与修复绑定 revision/review_id；过期请求拒绝，重试不能再次消耗一次性预算 |

幂等实现优先使用已有任务持久目录与跨请求锁；必须覆盖创建后响应丢失、上传中断、进程重启和同键不同文件。不要宣称这能保证远端 LLM 请求绝不重复计费。

外层客户端持久保存任务回执与游标。短时查询每次有明确超时，遇到等待复核状态就返回控制权；不用一个长时间不返回的工具调用占住 Agent。

拟新增公共服务 backend/app/services/agent_operations.py，只做现有操作的收口。HTTP 与 CLI 使用同一状态守卫，不能各复制一套审批逻辑。

验收：重复提交、重复审批、两个客户端同时续传只产生一次有效状态迁移；客户端重启后仅凭 task_id 能继续；等待状态有明确可执行动作；查询单任务不扫描所有历史任务目录。

### 批 C：P0，长任务响应性、预算与恢复

1. 复用已存在的 local_interpreter 执行线程与取消逻辑；重点检查同步 Pandoc/TeX 导出、最终文件处理是否阻塞 API。若阻塞，使用受控执行通道，保留任务锁及取消后的清理/等待，不能只简单丢进线程就宣称可取消。
2. 增加任务级预算合同：最大 provider 调用次数、累计已知 token、运行时间、单子题执行时限、修复次数。已有全局 MAX_TOKENS/重试上限不是累计任务预算；已有一次性返修计数必须保留。
3. 在调用前检查额度，调用后登记使用量，重启续传继承账本。远端 usage 缺失标记 unknown；使用调用次数与时间上限兜底。金额只在有明确价格和计费口径时给估算，不把未知金额写成 0。
4. 外层执行 Agent 的费用与 Docker 后端 provider 费用分别记录；后端不能声称统计了整个会话费用。
5. 保存不含密钥的运行配置版本。任务启动时冻结配置指纹；provider 切换是明确的恢复事件，不能因全局运行配置变化让活任务静默换模型。
6. 保留单个运行任务默认值。已有任务运行时，新任务明确排队或返回 busy；不能用增加 uvicorn workers 规避状态设计。
7. 检查故障后的产物发布顺序。新导出在任务内部暂存区验证后再发布；失败不覆盖最后一次有效交付。临时文件不得混入支撑材料。

涉及文件：backend/app/core/llm/llm.py、llm_factory.py、workflow.py、checkpoint.py；backend/app/services/token_usage.py、task_recovery.py、user_input_queue.py；backend/app/routers/modeling_router.py；必要时增加 task_budget.py 服务。

验收：慢计算和慢导出期间状态查询保持响应；取消先确认收到，再报告进程实际停止；模拟 provider 中断后续传保留预算；超预算没有下一次调用；导出失败能取回上次有效产物。

### 批 D：P1，把 0.0.15 的建模与评审方法接入真实执行

本批优先于批量增加模板。

1. 沉淀少量按阶段/题型加载的建模规则：确定性基线优先、硬约束与量纲、随机试验/置信区间、加权折中与 Pareto 的区别、原始数据与代理变量口径。
2. 在 Modeler/Coder 实际 prompt 与工具路径加载，不只更新仓库 skills。Docker 构建上下文目前是 backend，根目录 skills 不会因新增文件自动进入镜像。
3. 建议把后端使用的精简规则与来源版本放在 backend/app/resources/modeling_guides/；登记源 skill、参考版本、文件哈希和本地适配差异。外层 skill 调用后端能力，避免维护两份独立计算逻辑。目录名为建议，实施时可复用现有资源结构。
4. Modeler 后审阅关注模型是否回答问题、基线与主模型是否可执行；冻结后复核关注实际运行、数值、约束、量纲、稳健性与领域合理性；最终论文评审采用 mma-review 六维。三者不互相替代。
5. 六维评审首先由外层执行 Agent 完成，后端只组装材料、校验提交结果和保存版本。默认不再增加一个长期运行 ReviewerAgent，避免额外调用成本和调度复杂度。
6. 拟增加 review packet：题面与问题合同、模型计划、当前冻结事实、关键结果表、图表清单、引用记录、论文与 PDF 页码定位。摘要索引用于定位，结论必须基于实际读到的证据。
7. 拟增加 paper_review.json/md：六维分数或 not_assessed、阅读范围、发现列表、严重性、章节/页码/资产定位、依据、建议修复范围、reviewer 身份类型、manuscript_sha256、frozen_result_id、artifact_set_id。
8. 技术结果、内容评审、提交人确认分别展示。六维分数是内部改进量表；致命项单列；没有真实阅读/核验的项目不能默认通过。
9. 不自动采纳全部评审建议。将问题分成模型、数值、文稿、版式、引用五类，分别分流至已有 revise-modeling、execution-review、受控代码候选、论文候选和导出流程。发现现有状态不允许的返修就报告，不能清零预算或伪造 FAIL 开通入口。
10. 结果错误必须真实重算并经受控执行证据/冻结链更新；文字修复不改数值真值；图表/模板变化使相关评审过期。具体的新后期数值返修状态若有必要，独立设计和验证，不能扩张现有失败接管入口。
11. 复用多源文献搜索，补来源核验状态与正文断言关联；暂不可访问、DOI 不存在/写错、文献真实但不支持该句分别记录。数据来源与 input_manifest 衔接，不另建一套互不一致的真值文件。

涉及文件：backend/app/core/prompts/modeler.py、coder.py、writer.py；backend/app/core/flows.py、workflow.py；backend/app/tools/execution_quality_review.py、candidate_exporter.py；拟新增 paper_review.py 与相应 schema。复用已有 paper_assets_manifest 与执行证据，不重复造同义清单。

验收：种入少量已知问题（方法与代码不一致、指标方向错误、置信区间混淆、文献挂错句），评审能准确定位并进入正确修复范围；修改论文后旧评审不能继续作为当前通过依据；仅文字返修时冻结数值哈希不变。

### 批 E：P1，配图路由、模板配置和容器 doctor

配图：

- 把 mma-figure 转成后端 figure plan：图的类型、要支撑的结论、数据/指标来源、脚本、目标章节、输出形式。数据图使用已有 Coder + matplotlib；模板图映射已有 mathmodel-figure-templates；结构图复用现有 4drawio 模板和检查逻辑；物理图按实际 TeX 能力选择。
- 所有任务级文件位于 work_dir/<task_id>/ 内；图与脚本登记到已有 paper_assets_manifest；数值图须绑定真实数据及生成记录，模板样例数据不能作为正式结果。
- 采用 1×2/2×2 多面板规则，但以可读性和比较目的为准。保留 PDF 矢量与 PNG 预览；字体先探测，缺失时用现有字体 fallback。
- draw.io XML 生成/检查与 PNG/PDF 导出拆开报告。参考导出脚本需要 drawio 桌面 CLI，不能原样丢进无桌面容器。首批只交付经容器验证的路径；如需 DrawIO 导出，单独评估可选渲染镜像，未安装时报告不可用。

模板：

- 借鉴 template.source/id/entryFile，但统一进入已有 export_profile 与任务模板覆盖合同；配置优先级为任务显式选择/覆盖 → 已保存任务配置 → 默认 profile。
- 保留现有论文入口，不覆盖既有 Markdown、LaTeX 入口、AGENTS.md 或任务配置；后端重导时使用受控暂存与版本发布，不把软件模板误当赛事官方模板。
- 建立名称别名（huawei→huaweibei 等）与能力表。桌面 14 个目录不等于 14 个不同赛事；本地 skills 的多模板也不等于后端已支持对应 export profile。当前后端仅 default/cumcm2025/cumcm2026/huashubei 四个 profile。
- 首批验收现用 cumcm2026 与 default 回退路径；其他赛事逐个加入。英文 MCM 若成为实际需求，再做端到端语言与版式接入，而不是仅增加一个模板目录。

doctor：

- 宿主机层：Docker/Compose、后端地址、连接超时、任务目录映射、可选 Git。
- 容器层：实际解释器、数值库、Pandoc/XeLaTeX/字体、任务目录写权限、绘图与版式检查能力。
- provider 配置只报告完整性与协议能力；连通性验证作为显式操作，不能每次 doctor 都发送付费探测。绝不返回凭据正文。
- 能力探测结果、指南版本与模板版本可由客户端读取；不能将 JSON 文件存在当作执行验证通过。

涉及文件：backend/app/tools/matplotlib_setup.py、export_profiles.py、export_template_override.py、tex_project_exporter.py；backend/app/core/prompts/coder.py、writer.py；backend/Dockerfile/pyproject.toml 仅按确认所需依赖调整；拟增加后端 doctor/figure-plan 模块。

验收：每个启用的路由都有真实容器样例；图表数据来源可追溯；未安装能力明确返回 unavailable；同一任务重复模板操作不覆盖正文；代表性导出逐页复核。

### 批 F：P1，完整无前端验收与使用说明

分层验证，默认串行：

| 场景 | 要验证的结果 |
| --- | --- |
| 无 provider 合同测试 | 幂等、状态冲突、游标、未知 usage、过期审批、错误路由、路径限制 |
| Docker 受控执行 | 新内核运行代码；超时与取消；中文图；TeX 导出；执行期间 API 响应 |
| 轻量真实题 | 使用 AGENTS.md 工厂线性规划题；A=40、B=20、利润=2200；机器增加 10 小时后 A=140/3、B=50/3、利润=7100/3，增量=500/3；核对单位及连续变量假设 |
| 阶段复核与返修 | 外层 Agent 接到 waiting_review/waiting_quality_review；按当前授权记录决定；只重算指定子题，旧 Writer 事实失效 |
| 故障恢复 | 控制性中断 provider 或进程；状态变 interrupted/failed；不重复建任务；恢复沿用检查点与预算 |
| 完整历年题 | 一道完整长度题目，不用 LP 烟雾题代替；源码干净重跑、独立数学复算、真实引用核验、逐页 PDF/DOCX 检查 |
| 产物交付 | MD/JSON/DOCX/PDF/LaTeX 与 manifest 当前版本一致；submission audit、execution validation、preflight、PDF visual、final acceptance 均有真实结果；候选 bridge 兼容 |

真实 provider 验收开始前明确题目、预算、允许的外层复核范围与人工决策人；这属于后续验收准备，不在本轮计划编写时发起调用。审批人明确由人承担的门禁不能由 Agent 自行代签。

测试通过与实际读到的证据分别记录。PDF 生成但未逐页看过，只能写“已导出，视觉未验收”。最终文件命名、匿名目检、诚信声明和提交平台确认仍由提交人负责。

需要新增的说明：Agent 调用手册、命令/接口矩阵、状态与恢复表、一次真实验收记录。同步 STARTUP.md、AGENT_MEMORY.md、PDF 模板导出说明；涉及 CUMCM 模板与最终复核口径时同步相应指南和 checklist。

## 6. 目标调用体验与当前可用入口

下面是已经存在、可作为客户端封装基础的操作形态，不代表本轮执行过：

    POST http://127.0.0.1:8000/modeling
    multipart: ques_all, comp_template=CHINA, format_output=Markdown,
               export_profile=cumcm2026, require_model_review=true, files

    POST /modeling/<task_id>/approve-modeling
    POST /modeling/<task_id>/execution-review
    POST /modeling/<task_id>/resume

    docker compose exec -T backend uv run python -m app.tools.repair_candidate_cli TASK_ID SUBTASK_ID REVIEW_ID internal/candidate.py internal/evidence.json
    docker compose exec -T backend uv run python -m app.tools.paper_repair_candidate_cli TASK_ID internal/paper_candidate.json
    docker compose exec -T backend uv run python -m app.tools.export_cli task-refresh --task-id TASK_ID --profile cumcm2026

这些入口有各自状态前提，不能无条件顺序执行。task-refresh 适用于既有导出配置对应的重建，不是更改求解器结果后的重新执行工具。

拟建客户端应让外层 Agent 用“提交 → 检查 → 审阅 → 必要时返修 → 导出 → 取包”完成任务，无需手写复杂 curl、反复读取全量日志或编辑 checkpoint。新增端点/命令上线前应由 doctor 返回能力版本，旧后端不支持时明确降级，不伪造成功。

## 7. 顺序、交付边界与不做项

依赖顺序：A → B → C → D → E → F。每批完成自己的验收再进入下一批；不以新功能堆叠掩盖已有回归。首次最小交付止于 A+B，目标是无前端地可靠调用已有建模与复核链路。

每批先提供可审阅 diff、相关测试及文档同步；提交、推送、合并仍按用户明确授权执行。当前分支不干净，实施前保存并确认既有改动归属；不能用强制还原解决冲突。

本计划不包含：合并旧 PR #37；整体搬入桌面 app.asar；paperCloud/广场上传；yjs/mDNS；引入 Node 协议桥；默认开启所有实验性算法；给每个技能创建子 Agent；取消已有审阅与一次性返修门禁。

若未来需要“外层 Agent 从一开始直接提交 ModelPlan，Docker 只执行”的第二模式，应新增显式任务初始化契约并单独验收，不借用仅限失败场景的 codex-modeling，也不故意制造 Modeler 失败来进入接管路径。

## 8. 公开技术依据与文档同步说明

- Docker 支持按服务/可选 profile 组织启动，适合将 frontend 作为可选入口；参见 [Docker Compose profiles](https://docs.docker.com/compose/how-tos/profiles/)。
- 自动化容器 CLI 使用 -T 禁用默认 TTY，参见 [docker compose exec](https://docs.docker.com/reference/cli/docker/compose/exec/)。
- 异步函数中直接调用同步工具函数不会自动变成非阻塞执行；响应性改造需针对实际调用路径，参见 [FastAPI async 技术细节](https://fastapi.tiangolo.com/async/)。本地代码执行已用 executor，本计划不把该能力误记为缺失。

本轮只新增本计划文件，未改变代码、运行配置、默认 profile 或操作命令；因此现行记忆和使用说明无需作为“已实现变更”同步。实施各批时按本文件要求同步，避免把路线图写成当前能力。
