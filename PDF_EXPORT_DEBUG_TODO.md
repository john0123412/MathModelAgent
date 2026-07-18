# PDF 导出失败诊断 — 交接文档

## 背景
- 任务 `20260717-144854-2f67cf50c60faf5ad02eea5d3b52f2b1` 内容修复(方案1/2/3、第7/8缺陷)已端到端验收通过:
  - 5.1 不越界引 Airy/多光束;5.3 正确用附件3/4硅晶圆多光束
  - problem_alignment、result_consistency 及全部 25 项预检 PASS
  - frozen 33 指标全有 subtask_id(ques1:5/ques2:13/ques3:15),无跨题污染,无占位符
- **任务最终 failed 的唯一原因:PDF 导出失败**,与内容修复无关。

## 根因(已用决定性对照实验证明,不是 Unicode 文件名)

失败图 `问题1_厚度扫描反射率.png` 是 **0 字节空文件**(SHA256=e3b0c44298fc...空哈希)。

容器内 xelatex 四组对照(pandoc 3.1.11.1 + XeTeX TeX Live 2025 + locale C.UTF-8):

| 图片 | 文件名 | 结果 |
|---|---|---|
| 非空(103KB) | 中文名 | ✅ 成功生成 PDF |
| 非空(103KB) | ASCII名 | ✅ 成功生成 PDF |
| 空(0字节) | 中文名 | ❌ Unable to load picture |
| 空(0字节) | ASCII名 | ❌ Unable to load picture |

**结论:根因是 0 字节空 PNG,不是中文文件名。** 中文文件名在本环境完全正常。
=> 用户预设的 "ASCII staging 重命名方案" 无法解决此问题(重命名空图还是空图)。

## 空图产生源头(已定位)

`res.md` 附录源码:
- 行 780:`fig.savefig('问题1_厚度扫描反射率.png')` — 首次正常生成(此时应非空)
- 行 862-866 (Cell 9):
  ```python
  from pathlib import Path
  p=Path('问题1_厚度扫描反射率.png')
  p.touch()   # ← 问题所在
  print('已更新：问题1_厚度扫描反射率.png')
  ```
- **`Path.touch()` 对已存在文件只更新 mtime、不应清空**。但最终文件是 0 字节。
  需进一步确认:是否 savefig 本身失败(如 matplotlib 异常被吞)导致文件从未有内容,
  还是 Cell 9 之外有其它写入把它截断。行 780 那个 cell 同时 savefig 了
  `问题1_波数相位差.png`(103KB,正常),所以更可能是**厚度扫描图的 savefig 静默失败/被空写覆盖**。
  → 下一步应在容器内重放该 cell 的 scan 相关代码,看 `问题1_厚度扫描反射率.png` savefig 是否真的产出非空。

## 空图成因已坐实(2026-07-17 补充)
证据链完整:
1. `ques1_phase_scan.csv` 有 81 行有效数据 → 绘图数据源正常,不是数据缺失。
2. 行 780 `fig.savefig('问题1_厚度扫描反射率.png')` 疑似静默失败或该 cell 未执行到该语句
   (否则图应非空;同 cell 的 `问题1_波数相位差.png` 正常 103KB)。
3. **已实测证实:`Path('不存在的文件.png').touch()` 会新建 0 字节文件**
   (容器内 /app/.venv/bin/python 验证:touch 不存在文件 → 大小 0 字节)。
4. => 完整机制:savefig 未成功产出该图 → Cell 9 的 `p.touch()` 把它**新建成 0 字节占位** →
   xelatex 无法加载 0 字节 PNG → PDF 失败。
   坏模式是 coder 生成代码里的 `Path(既有图).touch()` "更新图"写法,在图不存在时会造出空图。

## 修复状态（2026-07-18 已实现）

`backend/app/tools/pdf_exporter.py` 已实现并通过回归：

1. Pandoc 前验证 `res.md` 的本地图片存在、非 0 字节、位于任务工作目录且可由 Pillow 解码；失败会把图片名和原因写入 `pdf.reason`，不再落入不透明的 XeLaTeX 报错。
2. 有效图片仅在导出期间复制为 `asset_XXX.ext` ASCII 临时资源，并用临时 Markdown 重写引用；支持中文、空格、括号及同名不同目录，原 `res.md` 和源图不改动，临时文件会清理。
3. 真实本机 Pandoc/XeLaTeX 已验证含 `中文 图 (验证).png` 的 PDF 可成功生成。目标任务 export-only 已验证按预期明确报 0 字节图，未重跑 Coordinator/Modeler/Coder/Writer。

目标任务已在保留冻结结果和 `res.md` 的前提下，使用已有 `ques1_phase_scan.csv` 的 80 行、4 组数据按原 Cell 7 绘图逻辑受控重建该图（本机 `Microsoft YaHei` 以保证中文图例/坐标可读），并完成 export-only。`res.pdf` 已生成；`pdf_visual_check.json = PASS`（49/49 页）、`submission_audit_report.json = PASS`、`final_acceptance_report.json = TECHNICAL_PASS`。第一页与图表页已人工渲染复核。任务状态已同步为 `completed`；仍需人类完成数学、引用和最终提交平台复核。

Docker 真实回归亦已完成：以当前工作树重建 backend 后，在容器 `/tmp` 临时目录复制该任务的 `res.md` 和全部 9 张 PNG，真实 Pandoc/XeLaTeX export-only 成功，49/49 页 `pdf_visual_check = PASS`。该验证不覆盖 Windows 正式字体候选稿。

## 修复方向（历史诊断，勿盲目按 Unicode 方案改）

真正根因是空图,所以修复重点应是 **导出前的图片有效性校验 + 明确失败**,而非文件名 staging。
候选(需与用户确认优先级):

1. **导出前校验图片非空/可解码**(推荐):PDF 导出前检查 res.md 引用的每张本地图,
   0 字节或无法被 PIL 解码 → 明确报错并列出坏图(不静默跳过)。符合用户"缺图仍应明确失败"要求。
2. 是否要连带修 coder 侧 `Path.touch()` 这种"占位更新图"的坏模式(它会留下空图)。
   这属于 coder_agent 证据/产物阶段,改动面更大,需谨慎、勿碰已验收内容路径。
3. 用户原要求的 ASCII staging(处理中文/空格/括号/#%&/同名不同目录/多格式)本身是**有价值的健壮性增强**,
   但**不是本次失败的根因**。可作为独立增强项,但要向用户说明它不解决空图问题。

## 关键约束(用户明确要求,务必遵守)
- **不要重跑 Coordinator/Modeler/Coder/Writer**,不改已通过预检的 res.md 正文和 frozen 结果。
- 修复+测试通过后**只做 export-only**(基于现有 res.md)→ pdf_visual_check → final acceptance/submission audit。
- 不产生第二份模型生成论文。
- 回归测试要求(见用户消息):中文名PNG导出成功、空格括号名、同名不同目录不覆盖、
  staging后引用可解析、原res.md与原图SHA256不变、缺图明确失败、导出后三项审计能执行。

## 现场固化位置(已持久化,容器重建不丢)
- 归档目录(挂载卷内): `backend/project/work_dir/_pdf_debug_archive_20260717-144854-2f67cf50c60faf5ad02eea5d3b52f2b1/`
  - `task_products/` — res.md/docx/json + 全部9张图 + 所有报告
  - `snapshot/` — 代码 diff、版本标记、上轮失败任务、本轮任务报告
  - `image_manifest.txt` — 9张图的文件名/绝对路径/大小/SHA256(含 0 字节图记录)
- 宿主机临时快照(冗余,勿依赖): `/tmp/rerun_snapshot_20260717_222729/` (= Windows temp)

## 环境事实
- pandoc 3.1.11.1 (+lua), XeTeX TeX Live 2025/dev/Debian, locale C.UTF-8
- 导出命令: `pandoc <md> -o <pdf> --pdf-engine=xelatex --pdf-engine-opt=-no-shell-escape --from <fmt> --standalone --listings --resource-path <work_dir>`
- 代码文件: `backend/app/tools/pdf_exporter.py`(导出), `backend/app/tools/tex_project_exporter.py`(latex工程)
- export-only 入口: 需查 `backend/app/core/workflow.py::_export_results` 是否有可单独调用的路径,或写脚本调 `export_markdown_to_pdf`

## 下一步起步动作(给下一个 agent)
1. 容器内重放 res.md 行 760-780 的 scan/savefig 代码,确认厚度扫描图 savefig 是否产出非空 → 坐实空图成因。
2. 与用户确认修复范围:仅加"导出前图片有效性校验+明确失败"(最小、对症),还是同时做 ASCII staging 健壮性增强。
3. 实现 + 单测(TDD)。
4. export-only 重新导出 → 验证 res.pdf 生成、页数、visual check、final acceptance/submission audit。
