# docs/md 归档区

本目录存放**已完成使命或未实施的一次性计划/方案/诊断文档**。它们描述的是当时
的决策与状态,不代表当前系统行为;当前系统行为以 `AGENTS.md`、`AGENT_MEMORY.md`、
`STARTUP.md`、`docs/md/PDF模板导出说明.md` 为准。历史过程细节另见 `docs/memory/`
归档(全文 grep 检索)。

## 索引

| 文件 | 制定日期 | 状态 | 说明 |
|---|---|---|---|
| `Agent源码修复与最终验收计划.md` | 2026-07-14 | 已完成 | 执行证据、冻结结果、定向回修、final_acceptance 等门禁均已实现并写入 STARTUP.md;本计划仅存设计过程 |
| `PDF_EXPORT_DEBUG_TODO.md` | 2026-07-20 | 已完成 | 07-17 任务 PDF 导出失败诊断交接;根因(0 字节空 PNG)已收口进归档,原文件位于仓库根目录,归档时移入本目录 |
| `MATH_MODELING_SKILLS_INTEGRATION_PLAN.md` | 2026-07-14 | 结论有效,方案已归档 | "外部 skills 层作独立完善与审计层"的定位结论仍被引用;实施细节以现状为准 |
| `ARCHITECTURE_UPGRADE_PROPOSAL.md` | 2026-08-19 | 未整体实施 | 华数杯复盘后的架构升级构想;其中门禁/评审相关思路已被后续 PR 部分吸收,整体方案未排期 |
| `SKILLS_COMPLIANCE_MERGE_EXECUTION_PLAN.md` | 2026-08-22 | 已过期 | 自述 READY_FOR_EXECUTION;其待整理分支 `feat/skills-integration-and-compliance-hardening` 已不存在,计划未执行 |
| `skill-versioned-seeding-plan.md` | 2026-08-25 | 设计稿,未实施 | 技能版本化播种(hashSkillDir + seeded-builtins.json)设计,自述"本轮不实现代码" |

## 约定

- 新的一次性计划文档在收口或决定不实施后,移入本目录并在上表登记一行。
- 归档文件正文不作改写(仅允许在文首追加状态头);引用路径以本目录为准。
