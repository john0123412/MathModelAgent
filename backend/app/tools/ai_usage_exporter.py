"""Generate the CUMCM 2026 AI-usage disclosure support document."""

from __future__ import annotations

import datetime
import json
import os
from typing import Any

from app.tools.export_profiles import normalize_export_profile
from app.tools.pdf_exporter import export_markdown_to_pdf


DETAILS_JSON_NAME = "ai_usage_details.json"
DETAILS_MARKDOWN_NAME = "AI工具使用详情.md"
DETAILS_PDF_NAME = "AI工具使用详情.pdf"


def _read_existing_details(path: str) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    tools = value.get("tools")
    if not isinstance(tools, list) or not tools:
        return None
    return value


def _detected_stages(work_dir: str) -> list[str]:
    candidates = (
        ("题目拆解", "task_request.json"),
        ("建模方案", "modeler_plan.json"),
        ("代码求解与执行证据", "execution_validation.json"),
        ("论文写作与校正", "res.md"),
        ("技术门禁与导出", "paper_preflight_report.json"),
    )
    stages = [label for label, filename in candidates if os.path.isfile(os.path.join(work_dir, filename))]
    return stages or ["题目拆解、建模、代码求解和论文写作"]


def _default_details(work_dir: str) -> dict[str, Any]:
    return {
        "schema_version": "mathmodel.ai-usage-details.v1",
        "generated_at": datetime.datetime.now().isoformat(),
        "tools": [
            {
                "name": "MathModelAgent",
                "model": "由本次任务运行时配置确定；支撑材料不记录API密钥或账号凭据",
                "stages": _detected_stages(work_dir),
                "prompt_process": (
                    "按Coordinator、Modeler、Coder、Writer角色处理题面；"
                    "提示过程受题面契约、结构化ModelPlan、执行证据、冻结结果和论文预检约束。"
                ),
                "adoption_and_modification": (
                    "AI输出仅作为候选内容；数值结论须来自受控执行与冻结结果，"
                    "发现题面来源、约束、引用或复现证据不一致时应拒绝或修正。"
                ),
            }
        ],
        "human_review": {
            "status": "pending_participant_confirmation",
            "completed_technical_checks": [
                "题面契约与执行证据自动检查",
                "论文预检与产物哈希检查",
            ],
            "pending_items": [
                "参赛队员复核建模假设、推导和关键数值",
                "参赛队员确认AI使用记录完整且表述真实",
                "参赛队员确认匿名、排版和提交平台要求",
            ],
        },
    }


def _render_markdown(details: dict[str, Any]) -> str:
    def cell(value: object, fallback: str = "未记录") -> str:
        text = str(value or fallback).strip()
        return text.replace("|", "\\|").replace("\n", "<br>")

    lines = [
        "# AI工具使用详情",
        "",
        "本文件按结构化“AI工具使用详情”版式如实记录使用范围、关键交互摘要、采纳与人工修改情况。",
        "不包含API密钥、账号凭据、Cookie或完整内部提示词；最终参赛责任仍由参赛队员承担。",
        "",
    ]
    contest_rule = details.get("contest_rule")
    if isinstance(contest_rule, dict):
        rule_fields = (
            ("适用规定", contest_rule.get("title")),
            ("发布日期", contest_rule.get("published_at")),
            ("生效日期", contest_rule.get("effective_at")),
            ("官方页面", contest_rule.get("url")),
            ("本次核验日期", contest_rule.get("verified_at")),
        )
        lines.extend(
            [f"- {label}：{value}" for label, value in rule_fields if value]
        )
        lines.append("")

    lines.extend(
        [
            "## 一、使用原则与记录范围",
            "",
            "AI输出仅作为候选材料。模型假设、推导、数值、引用和提交合规性均须由参赛队员结合可复查证据独立确认。",
            "",
            "## 二、AI工具使用记录",
            "",
        ]
    )
    for index, tool in enumerate(details.get("tools", []), start=1):
        if not isinstance(tool, dict):
            continue
        name = str(tool.get("name") or "未命名AI工具")
        model = str(tool.get("model") or "未记录")
        stages = tool.get("stages", [])
        stage_text = "、".join(str(item) for item in stages) if isinstance(stages, list) else str(stages)
        lines.extend(
            [
                f"### {index}. {name}",
                "",
                "| 记录项目 | 本次情况 |",
                "| --- | --- |",
                f"| 工具名称 | {cell(name)} |",
                f"| 模型/版本 | {cell(model)} |",
                f"| 具体使用目的和环节 | {cell(stage_text)} |",
                f"| 关键交互记录（提示与回复摘要） | {cell(tool.get('prompt_process'))} |",
                f"| 采纳和人工修改情况 | {cell(tool.get('adoption_and_modification'))} |",
                "",
            ]
        )

    review = details.get("human_review", {})
    if not isinstance(review, dict):
        review = {}
    lines.extend(
        [
            "## 三、人工核验状态",
            "",
            f"当前状态：{cell(review.get('status'))}。",
            "",
        ]
    )
    for heading, key in (
        ("已完成的技术复核", "completed_technical_checks"),
        ("仍需参赛队员确认", "pending_items"),
    ):
        items = review.get(key, [])
        lines.extend([f"### {heading}", ""])
        if isinstance(items, list) and items:
            lines.extend(f"- {item}" for item in items)
        else:
            lines.append("- 未记录")
        lines.append("")

    lines.extend(
        [
            "## 四、真实性说明",
            "",
            "AI生成内容不被视为天然正确。最终建模假设、推导、数值、引用、匿名性和提交合规性仍由参赛队员确认。",
            "",
        ]
    )
    return "\n".join(lines)


def ensure_ai_usage_details(
    work_dir: str,
    *,
    export_profile: str | None,
) -> dict[str, Any]:
    """Create or refresh the required CUMCM 2026 AI-usage details PDF."""
    profile = normalize_export_profile(export_profile).value
    if profile != "cumcm2026":
        return {"success": True, "enabled": False, "profile": profile, "reason": "profile does not require AI disclosure"}

    json_path = os.path.join(work_dir, DETAILS_JSON_NAME)
    markdown_path = os.path.join(work_dir, DETAILS_MARKDOWN_NAME)
    pdf_path = os.path.join(work_dir, DETAILS_PDF_NAME)
    details = _read_existing_details(json_path) or _default_details(work_dir)
    details["generated_at"] = datetime.datetime.now().isoformat()

    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(details, handle, ensure_ascii=False, indent=2)
    with open(markdown_path, "w", encoding="utf-8") as handle:
        handle.write(_render_markdown(details))

    pdf_result = export_markdown_to_pdf(
        markdown_path,
        pdf_path,
        work_dir,
        export_profile=profile,
    )
    return {
        "success": bool(pdf_result.get("success")),
        "enabled": True,
        "profile": profile,
        "json": DETAILS_JSON_NAME,
        "markdown": DETAILS_MARKDOWN_NAME,
        "pdf": DETAILS_PDF_NAME,
        "pdf_export": pdf_result,
    }
