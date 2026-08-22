"""Contest topic selection and modeling route scorer tool.

Ports and enhances the mathematical modeling topic route selection framework,
providing programmatic APIs and CLI commands for A/B/C topic comparison,
team-fit blending, anti-homogeneity checks, and structured decision outputs.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

from app.utils.log_util import logger

DEFAULT_TOPIC_CRITERIA: list[dict[str, Any]] = [
    {
        "key": "feasibility",
        "label": "Feasibility",
        "weight": 0.18,
        "description": "Can the team finish models, code, figures, and paper in time?",
    },
    {
        "key": "data_or_parameter_access",
        "label": "Data/Parameters",
        "weight": 0.14,
        "description": "Are data, parameters, or defensible assumptions available?",
    },
    {
        "key": "differentiation",
        "label": "Topic Differentiation",
        "weight": 0.18,
        "description": "Can the topic avoid generic AI similarity and show a clear angle?",
    },
    {
        "key": "validation_strength",
        "label": "Validation",
        "weight": 0.16,
        "description": "Can results be tested, compared, or stress-checked?",
    },
    {
        "key": "method_fit",
        "label": "Method Fit",
        "weight": 0.12,
        "description": "Do natural methods answer the problem rather than decorate it?",
    },
    {
        "key": "narrative_power",
        "label": "Narrative",
        "weight": 0.10,
        "description": "Can the paper tell a compact, convincing story?",
    },
    {
        "key": "risk_control",
        "label": "Risk Control",
        "weight": 0.12,
        "description": "Are fallback models and failure plans available?",
    },
]

DEFAULT_ROUTE_CRITERIA: list[dict[str, Any]] = [
    {
        "key": "route_problem_fit",
        "label": "Route Fit",
        "weight": 0.16,
        "description": "Does the route directly answer the required output?",
    },
    {
        "key": "engineering_solvability",
        "label": "Engineering",
        "weight": 0.16,
        "description": "Can the team implement, debug, and run the route in contest time?",
    },
    {
        "key": "data_parameter_control",
        "label": "Input Control",
        "weight": 0.14,
        "description": "Are inputs available, estimable, or defensibly assumed?",
    },
    {
        "key": "validation_design",
        "label": "Route Validation",
        "weight": 0.14,
        "description": "Is there a concrete baseline, sensitivity, ablation, or external check?",
    },
    {
        "key": "route_differentiation",
        "label": "Route Differentiation",
        "weight": 0.14,
        "description": "Does the route avoid generic AI method stacking?",
    },
    {
        "key": "paper_explainability",
        "label": "Explainability",
        "weight": 0.10,
        "description": "Can the route be explained with clear equations, steps, and figures?",
    },
    {
        "key": "implementation_cost_control",
        "label": "Cost Control",
        "weight": 0.08,
        "description": "Is runtime and coding complexity controlled?",
    },
    {
        "key": "route_risk_control",
        "label": "Route Risk Control",
        "weight": 0.08,
        "description": "Is there a trigger-based fallback and failure mode analysis?",
    },
]

DEFAULT_QUESTION_CRITERIA: list[dict[str, Any]] = [
    {
        "key": "question_deliverable_fit",
        "label": "Deliverable Fit",
        "weight": 0.20,
        "description": "Does the sub-question directly output what the problem asks for?",
    },
    {
        "key": "question_model_fit",
        "label": "Model Fit",
        "weight": 0.20,
        "description": "Is the model choice mathematically sound for this specific question?",
    },
    {
        "key": "question_validation_design",
        "label": "Validation Design",
        "weight": 0.20,
        "description": "Is there a clear baseline, sensitivity, ablation, or refutation test?",
    },
    {
        "key": "question_engineering_risk",
        "label": "Engineering Risk",
        "weight": 0.20,
        "description": "Can the solver run fast enough with controlled coding complexity?",
    },
    {
        "key": "question_chain_synergy",
        "label": "Chain Synergy",
        "weight": 0.20,
        "description": "Does this question cleanly support or depend on adjacent sub-questions?",
    },
]

DEFAULT_BLEND: dict[str, float] = {"topic_weight": 0.40, "route_weight": 0.60}
DEFAULT_ROUTE_QUESTION_BLEND: dict[str, float] = {
    "route_weight": 0.50,
    "question_chain_weight": 0.50,
}
DEFAULT_TEAM_FIT_BLEND: dict[str, float] = {
    "model_score_weight": 0.70,
    "team_fit_weight": 0.30,
}

DECISIVE_HIGH_SCORE = 4.2
DECISIVE_LOW_SCORE = 2.4
GAP_BOUNDARY_BUFFER = 0.03

EVIDENCE_FIELDS = ("evidence", "written_evidence", "justification", "score_evidence")
FLIP_FIELDS = ("flip_condition", "flip_conditions", "disprove_condition", "refutation_condition")
MODEL_CHOICE_FIELDS = ("why_chosen", "model_choice", "model_justification", "why")
REJECTED_ALTERNATIVE_FIELDS = ("rejected_alternatives", "rejected_alternative", "alternatives_rejected")
REFUTATION_FIELDS = ("refutation_test", "refutation", "falsification_test")
BINDING_CONSTRAINT_FIELDS = (
    "binding_constraints",
    "critical_constraints",
    "bottleneck_constraints",
    "key_constraints",
)
CROWD_ESCAPE_FIELDS = ("crowd_escape_mechanism", "crowd_escape", "anti_homogeneity_escape")


def load_payload(source: str | Path | dict[str, Any]) -> dict[str, Any]:
    if isinstance(source, dict):
        return source
    path = Path(source)
    if not path.is_file():
        raise FileNotFoundError(f"Input file not found: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_criteria(
    payload: dict[str, Any], key: str, defaults: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    configured = payload.get(key)
    if not configured:
        return defaults
    total_weight = 0.0
    for c in configured:
        try:
            w = float(c.get("weight", 0))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} contains non-numeric weight: {c.get('weight')!r}") from exc
        if not math.isfinite(w) or w < 0:
            raise ValueError(f"{key} contains invalid non-finite or negative weight: {w}")
        total_weight += w

    if total_weight <= 0:
        raise ValueError(f"{key} weights must sum to a positive number.")
    return [
        {
            "key": c["key"],
            "label": c.get("label", c["key"]),
            "weight": float(c.get("weight", 0)) / total_weight,
            "description": c.get("description", ""),
        }
        for c in configured
    ]


def get_blend(payload: dict[str, Any]) -> dict[str, float]:
    raw = payload.get("blend") or DEFAULT_BLEND
    try:
        topic_weight = float(raw.get("topic_weight", DEFAULT_BLEND["topic_weight"]))
        route_weight = float(raw.get("route_weight", DEFAULT_BLEND["route_weight"]))
    except (TypeError, ValueError) as exc:
        raise ValueError("blend weights must be numeric.") from exc

    if not (math.isfinite(topic_weight) and math.isfinite(route_weight)) or topic_weight < 0 or route_weight < 0:
        raise ValueError("blend weights must be finite and non-negative.")

    total = topic_weight + route_weight
    if total <= 0:
        raise ValueError("blend weights must sum to a positive number.")
    return {"topic_weight": topic_weight / total, "route_weight": route_weight / total}


def get_route_question_blend(payload: dict[str, Any]) -> dict[str, float]:
    raw = payload.get("route_question_blend") or DEFAULT_ROUTE_QUESTION_BLEND
    try:
        route_weight = float(raw.get("route_weight", DEFAULT_ROUTE_QUESTION_BLEND["route_weight"]))
        question_chain_weight = float(
            raw.get("question_chain_weight", DEFAULT_ROUTE_QUESTION_BLEND["question_chain_weight"])
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("route_question_blend weights must be numeric.") from exc

    if not (math.isfinite(route_weight) and math.isfinite(question_chain_weight)) or route_weight < 0 or question_chain_weight < 0:
        raise ValueError("route_question_blend weights must be finite and non-negative.")

    total = route_weight + question_chain_weight
    if total <= 0:
        raise ValueError("route_question_blend weights must sum to a positive number.")
    return {"route_weight": route_weight / total, "question_chain_weight": question_chain_weight / total}


def get_team_fit_blend(payload: dict[str, Any]) -> dict[str, float] | None:
    team_profile = payload.get("team_profile")
    raw = payload.get("team_fit_blend")
    if raw is None and isinstance(team_profile, dict):
        raw = team_profile.get("team_fit_blend") or team_profile.get("blend")
    if raw is None:
        return None
    if raw is True:
        raw = DEFAULT_TEAM_FIT_BLEND
    if not isinstance(raw, dict):
        raise ValueError("team_fit_blend must be an object when provided.")
    try:
        model_score_weight = float(raw.get("model_score_weight", DEFAULT_TEAM_FIT_BLEND["model_score_weight"]))
        team_fit_weight = float(raw.get("team_fit_weight", DEFAULT_TEAM_FIT_BLEND["team_fit_weight"]))
    except (TypeError, ValueError) as exc:
        raise ValueError("team_fit_blend weights must be numeric.") from exc

    if not (math.isfinite(model_score_weight) and math.isfinite(team_fit_weight)) or model_score_weight < 0 or team_fit_weight < 0:
        raise ValueError("team_fit_blend weights must be finite and non-negative.")

    total = model_score_weight + team_fit_weight
    if total <= 0:
        raise ValueError("team_fit_blend weights must sum to a positive number.")
    return {"model_score_weight": model_score_weight / total, "team_fit_weight": team_fit_weight / total}


def item_notes(item: dict[str, Any]) -> dict[str, Any]:
    notes = item.get("notes") or {}
    return notes if isinstance(notes, dict) else {}


def first_present(item: dict[str, Any], keys: tuple[str, ...]) -> Any:
    notes = item_notes(item)
    for key in keys:
        value = item.get(key, notes.get(key))
        if value is not None:
            return value
    return None


def support_value(
    item: dict[str, Any],
    fields: tuple[str, ...],
    criterion_key: str | None = None,
    allow_any: bool = False,
) -> Any:
    notes = item_notes(item)
    containers = (item, notes)
    for field in fields:
        for container in containers:
            value = container.get(field)
            if not value:
                continue
            if isinstance(value, dict):
                if criterion_key and value.get(criterion_key):
                    return value[criterion_key]
                if criterion_key and not allow_any:
                    continue
                for generic_key in ("overall", "summary", "decisive", "decision", "final"):
                    if value.get(generic_key):
                        return value[generic_key]
                if allow_any:
                    for nested in value.values():
                        if nested:
                            return nested
                continue
            if criterion_key and not allow_any:
                continue
            return value
    return None


def fallback_value(item: dict[str, Any]) -> Any:
    return first_present(item, ("fallback", "fallback_plan", "rescue", "rescue_plan"))


def model_choice_value(item: dict[str, Any]) -> Any:
    return first_present(item, MODEL_CHOICE_FIELDS)


def rejected_alternatives_value(item: dict[str, Any]) -> Any:
    return first_present(item, REJECTED_ALTERNATIVE_FIELDS)


def refutation_value(item: dict[str, Any]) -> Any:
    return first_present(item, REFUTATION_FIELDS)


def binding_constraints_value(item: dict[str, Any]) -> Any:
    return first_present(item, BINDING_CONSTRAINT_FIELDS)


def crowd_escape_value(item: dict[str, Any]) -> Any:
    return first_present(item, CROWD_ESCAPE_FIELDS)


def score_entity(
    entity: dict[str, Any],
    criteria: list[dict[str, Any]],
    entity_label: str,
    require_decisive_support: bool = True,
    strict_criterion_support: bool = True,
) -> float:
    scores = entity.get("scores", {})
    if not isinstance(scores, dict):
        raise ValueError(f"{entity_label} scores must be an object.")

    criterion_keys = {criterion["key"] for criterion in criteria}
    missing = [criterion["key"] for criterion in criteria if criterion["key"] not in scores]
    if missing:
        raise ValueError(f"{entity_label} missing required score field(s): {', '.join(missing)}.")
    extra = [key for key in scores if key not in criterion_keys]
    if extra:
        raise ValueError(f"{entity_label} has unrecognized score key(s): {', '.join(extra)}.")

    total = 0.0
    for criterion in criteria:
        score_was_provided = criterion["key"] in scores
        raw = scores.get(criterion["key"], 0)
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{entity_label} has non-numeric score for {criterion['key']}: {raw!r}"
            ) from exc
        if not math.isfinite(value) or not (0.0 <= value <= 5.0):
            raise ValueError(f"{entity_label} score for {criterion['key']} must be a finite number between 0 and 5.")
        if (
            score_was_provided
            and require_decisive_support
            and (value >= DECISIVE_HIGH_SCORE or value <= DECISIVE_LOW_SCORE)
        ):
            criterion_label = criterion.get("label", criterion["key"])
            criterion_key = criterion["key"] if strict_criterion_support else None
            if not support_value(entity, EVIDENCE_FIELDS, criterion_key):
                entity.setdefault("_warnings", []).append(
                    f"{entity_label} has decisive {criterion_label} score {value:.1f} but no evidence field."
                )
            if not support_value(entity, FLIP_FIELDS, criterion_key):
                entity.setdefault("_warnings", []).append(
                    f"{entity_label} has decisive {criterion_label} score {value:.1f} but no flip_condition field."
                )
        total += value * criterion["weight"]
    return total


def default_question_role(index: int, total: int) -> str:
    if total <= 1:
        return "main/final"
    if total == 2:
        return "first" if index == 0 else "final"
    if total == 3:
        return ["first", "main", "final"][index]
    if index == 0:
        return "first"
    if index == 1:
        return "main"
    if index == total - 1:
        return "final"
    return "extend"


def default_question_weight(index: int, total: int) -> float:
    if total <= 1:
        return 1.0
    if total == 2:
        return [0.35, 0.65][index]
    if total == 3:
        return [0.20, 0.45, 0.35][index]
    if index == 0:
        return 0.15
    if index == 1:
        return 0.40
    if index == total - 1:
        return 0.15
    return 0.30 / max(total - 3, 1)


def score_question(
    question: dict[str, Any],
    question_criteria: list[dict[str, Any]],
    index: int,
    total_questions: int,
) -> dict[str, Any]:
    scored = dict(question)
    scored.setdefault("_warnings", [])
    name = scored.get("name") or f"Q{index + 1}"
    scored["name"] = name
    role = scored.get("role") or default_question_role(index, total_questions)
    scored["_role"] = role

    raw_weight = scored.get("question_weight", scored.get("weight"))
    if raw_weight is None:
        weight = default_question_weight(index, total_questions)
    else:
        try:
            weight = float(raw_weight)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Question {name} weight must be numeric.") from exc
        if not math.isfinite(weight) or weight < 0:
            raise ValueError(f"Question {name} weight must be finite and non-negative.")
    scored["_raw_weight"] = weight

    base_score = score_entity(
        scored,
        question_criteria,
        f"Question {name}",
        require_decisive_support=False,
    )
    scored["_score"] = base_score
    return scored


def score_route(
    route: dict[str, Any],
    route_criteria: list[dict[str, Any]],
    question_criteria: list[dict[str, Any]],
    question_blend: dict[str, float],
) -> dict[str, Any]:
    scored = dict(route)
    scored.setdefault("_warnings", [])
    route_name = scored.get("name", "unnamed route")
    base_score = score_entity(
        scored,
        route_criteria,
        f"Route {route_name}",
        require_decisive_support=True,
    )
    scored["_base_score"] = base_score

    raw_questions = scored.get("question_chain") or scored.get("questions") or []
    if raw_questions:
        if not isinstance(raw_questions, list):
            raise ValueError(f"Route {route_name} question_chain must be a list.")
        total_q = len(raw_questions)
        scored_questions = [
            score_question(q, question_criteria, i, total_q)
            for i, q in enumerate(raw_questions)
        ]
        sum_weights = sum(q["_raw_weight"] for q in scored_questions)
        if sum_weights <= 0:
            raise ValueError(f"Route {route_name} question weights sum to non-positive value.")
        for q in scored_questions:
            q["_effective_weight"] = q["_raw_weight"] / sum_weights
        chain_score = sum(q["_score"] * q["_effective_weight"] for q in scored_questions)
        scored["_questions"] = scored_questions
        scored["_question_chain_score"] = chain_score
        final_route_score = (
            base_score * question_blend["route_weight"]
            + chain_score * question_blend["question_chain_weight"]
        )
        scored["_route_score_mode"] = "route+questions"
    else:
        scored["_questions"] = []
        scored["_question_chain_score"] = None
        final_route_score = base_score
        scored["_route_score_mode"] = "route-only"

    scored["_score"] = final_route_score
    return scored


def score_topic(
    topic: dict[str, Any],
    topic_criteria: list[dict[str, Any]],
    route_criteria: list[dict[str, Any]],
    question_criteria: list[dict[str, Any]],
    blend: dict[str, float],
    question_blend: dict[str, float],
) -> dict[str, Any]:
    scored = dict(topic)
    scored.setdefault("_warnings", [])
    topic_name = scored.get("name", "unnamed topic")
    topic_score = score_entity(
        scored,
        topic_criteria,
        f"Topic {topic_name}",
        require_decisive_support=True,
    )
    scored["_topic_score"] = topic_score

    raw_routes = scored.get("routes") or []
    if raw_routes:
        if not isinstance(raw_routes, list):
            raise ValueError(f"Topic {topic_name} routes must be a list.")
        scored_routes = [
            score_route(r, route_criteria, question_criteria, question_blend)
            for r in raw_routes
        ]
        scored_routes.sort(key=lambda r: r["_score"], reverse=True)
        scored["_routes"] = scored_routes
        best_r = scored_routes[0]
        scored["_best_route_score"] = best_r["_score"]
        final_model_score = (
            topic_score * blend["topic_weight"]
            + best_r["_score"] * blend["route_weight"]
        )
        scored["_mode"] = f"topic+best-route ({best_r['_route_score_mode']})"
    else:
        scored["_routes"] = []
        scored["_best_route_score"] = None
        final_model_score = topic_score
        scored["_mode"] = "topic-only"

    scored["_model_score"] = final_model_score
    scored["_final_score"] = final_model_score
    return scored


def apply_team_fit_scores(
    ranked: list[dict[str, Any]], team_fit_blend: dict[str, float] | None
) -> bool:
    if not team_fit_blend:
        return False
    applied = False
    for topic in ranked:
        raw_fit = topic.get("team_fit_score", topic.get("team_fit"))
        if isinstance(raw_fit, dict):
            raw_fit = raw_fit.get("score")
        if raw_fit is not None:
            try:
                fit_val = float(raw_fit)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Topic {topic.get('name')} team_fit_score must be numeric.") from exc
            if not 0 <= fit_val <= 5:
                raise ValueError(f"Topic {topic.get('name')} team_fit_score must be in [0, 5].")
            topic["_team_fit_score"] = fit_val
            model_score = topic["_model_score"]
            topic["_final_score"] = (
                model_score * team_fit_blend["model_score_weight"]
                + fit_val * team_fit_blend["team_fit_weight"]
            )
            applied = True
        else:
            topic["_team_fit_score"] = None
    return applied


def score_gap_note(ranked: list[dict[str, Any]]) -> str:
    if len(ranked) < 2:
        return "Only one candidate was scored; no score gap comparison is available."
    gap = ranked[0]["_final_score"] - ranked[1]["_final_score"]
    if gap <= 0.05:
        return f"Near tie: top two candidates differ by {gap:.2f}; choose by team strengths and available data."
    if gap <= 0.20:
        return f"Moderate uncertainty: top two candidates differ by {gap:.2f}; require written decisive evidence before treating the lead as stable."
    if gap <= 0.20 + GAP_BOUNDARY_BUFFER:
        return f"Boundary-sensitive lead: top candidate leads by {gap:.2f}, just above 0.20; treat as moderate unless decisive evidence and team fit both survive refutation."
    evidence = support_value(ranked[0], EVIDENCE_FIELDS, allow_any=True)
    flip = support_value(ranked[0], FLIP_FIELDS, allow_any=True)
    if evidence and flip:
        return f"Evidence-backed separation: top candidate leads by {gap:.2f} and includes evidence plus flip condition."
    return f"Numerical separation: top candidate leads by {gap:.2f}, but evidence and flip condition must be written before the ranking is treated as decisive."


def format_list(values: Any) -> str:
    if not values:
        return "-"
    if isinstance(values, str):
        return values
    return "; ".join(str(v) for v in values)


def format_fallback(value: Any) -> str:
    if not value:
        return "-"
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        trigger = value.get("trigger", "-")
        action = value.get("action", "-")
        return f"Trigger: {trigger}; Action: {action}"
    return str(value)


def cell(value: Any) -> str:
    text = "-" if value is None or value == "" else str(value)
    return text.replace("|", "\\|").replace("\r\n", "<br>").replace("\n", "<br>")


def score_text(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def weight_text(value: float | None) -> str:
    return "-" if value is None else f"{value:.0%}"


def build_markdown(
    payload: dict[str, Any],
    topic_criteria: list[dict[str, Any]],
    route_criteria: list[dict[str, Any]],
    question_criteria: list[dict[str, Any]],
) -> str:
    topics = payload.get("topics") or []
    if not isinstance(topics, list) or not topics:
        raise ValueError("Input JSON must contain a non-empty 'topics' list.")

    blend = get_blend(payload)
    question_blend = get_route_question_blend(payload)
    team_fit_blend = get_team_fit_blend(payload)
    ranked = [
        score_topic(topic, topic_criteria, route_criteria, question_criteria, blend, question_blend)
        for topic in topics
    ]
    team_fit_applied = apply_team_fit_scores(ranked, team_fit_blend)
    ranked.sort(key=lambda item: item["_final_score"], reverse=True)

    lines: list[str] = []
    title = payload.get("contest") or "Mathematical Modeling Topic Selection"
    lines.append(f"# {title}")
    lines.append("")
    lines.append("## Score Gap Note")
    lines.append("")
    lines.append(score_gap_note(ranked))
    lines.append("")
    lines.append("## Topic Ranking")
    lines.append("")

    if team_fit_applied:
        lines.append(
            "| Rank | Candidate | Final | Mode | Model Score | Team Fit | Topic | Best Route | Best Route Score | Recommendation | Evidence | Flip Condition | Main Risk |"
        )
        lines.append("| --- | --- | ---: | --- | ---: | ---: | ---: | --- | ---: | --- | --- | --- | --- |")
        for i, t in enumerate(ranked, start=1):
            notes = item_notes(t)
            best_r = t["_routes"][0] if t.get("_routes") else None
            lines.append(
                "| {rank} | {name} | {final} | {mode} | {model} | {fit} | {topic} | {b_route} | {b_score} | {rec} | {evidence} | {flip} | {risk} |".format(
                    rank=i,
                    name=cell(t.get("name", f"Topic {i}")),
                    final=score_text(t["_final_score"]),
                    mode=cell(t["_mode"]),
                    model=score_text(t["_model_score"]),
                    fit=score_text(t.get("_team_fit_score")),
                    topic=score_text(t["_topic_score"]),
                    b_route=cell(best_r.get("name") if best_r else "-"),
                    b_score=score_text(t.get("_best_route_score")),
                    rec=cell(t.get("recommendation") or notes.get("recommendation")),
                    evidence=cell(support_value(t, EVIDENCE_FIELDS, allow_any=True)),
                    flip=cell(support_value(t, FLIP_FIELDS, allow_any=True)),
                    risk=cell(t.get("main_risk") or notes.get("risk")),
                )
            )
    else:
        lines.append(
            "| Rank | Candidate | Final Score | Mode | Topic Score | Best Route | Best Route Score | Recommendation | Evidence | Flip Condition | Main Risk |"
        )
        lines.append("| --- | --- | ---: | --- | ---: | --- | ---: | --- | --- | --- | --- |")
        for i, t in enumerate(ranked, start=1):
            notes = item_notes(t)
            best_r = t["_routes"][0] if t.get("_routes") else None
            lines.append(
                "| {rank} | {name} | {final} | {mode} | {topic} | {b_route} | {b_score} | {rec} | {evidence} | {flip} | {risk} |".format(
                    rank=i,
                    name=cell(t.get("name", f"Topic {i}")),
                    final=score_text(t["_final_score"]),
                    mode=cell(t["_mode"]),
                    topic=score_text(t["_topic_score"]),
                    b_route=cell(best_r.get("name") if best_r else "-"),
                    b_score=score_text(t.get("_best_route_score")),
                    rec=cell(t.get("recommendation") or notes.get("recommendation")),
                    evidence=cell(support_value(t, EVIDENCE_FIELDS, allow_any=True)),
                    flip=cell(support_value(t, FLIP_FIELDS, allow_any=True)),
                    risk=cell(t.get("main_risk") or notes.get("risk")),
                )
            )

    # Routes summary
    has_routes = any(t.get("_routes") for t in ranked)
    if has_routes:
        lines.append("")
        lines.append("## Route Scores")
        for t in ranked:
            routes = t.get("_routes") or []
            if not routes:
                continue
            lines.append("")
            lines.append(f"### {cell(t.get('name', 'Unnamed Topic'))}")
            lines.append("")
            lines.append(
                "| Rank | Route | Score | Mode | Main Model | Why Chosen | Binding Constraints | Rejected Alternative | Refutation | Solver | Validation | Fallback |"
            )
            lines.append("| --- | --- | ---: | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
            for ri, r in enumerate(routes, start=1):
                r_notes = item_notes(r)
                lines.append(
                    "| {rank} | {name} | {score} | {mode} | {method} | {why} | {binding} | {rejected} | {refutation} | {solver} | {val} | {fb} |".format(
                        rank=ri,
                        name=cell(r.get("name", f"Route {ri}")),
                        score=score_text(r["_score"]),
                        mode=cell(r.get("_route_score_mode")),
                        method=cell(r.get("main_model") or r_notes.get("method")),
                        why=cell(model_choice_value(r)),
                        binding=cell(format_list(binding_constraints_value(r))),
                        rejected=cell(format_list(rejected_alternatives_value(r))),
                        refutation=cell(format_list(refutation_value(r))),
                        solver=cell(r.get("solver") or r_notes.get("solver")),
                        val=cell(r.get("validation") or r_notes.get("validation")),
                        fb=cell(format_fallback(fallback_value(r))),
                    )
                )

    return "\n".join(lines) + "\n"


def score_topics_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Score a topic payload dict and return scored dictionary with rankings."""
    topic_criteria = get_criteria(payload, "topic_criteria", DEFAULT_TOPIC_CRITERIA)
    route_criteria = get_criteria(payload, "route_criteria", DEFAULT_ROUTE_CRITERIA)
    question_criteria = get_criteria(payload, "question_criteria", DEFAULT_QUESTION_CRITERIA)

    blend = get_blend(payload)
    question_blend = get_route_question_blend(payload)
    team_fit_blend = get_team_fit_blend(payload)

    topics = payload.get("topics") or []
    if not isinstance(topics, list) or not topics:
        raise ValueError("Input payload must contain a non-empty 'topics' list.")

    ranked = [
        score_topic(t, topic_criteria, route_criteria, question_criteria, blend, question_blend)
        for t in topics
    ]
    team_fit_applied = apply_team_fit_scores(ranked, team_fit_blend)
    ranked.sort(key=lambda item: item["_final_score"], reverse=True)

    markdown_report = build_markdown(payload, topic_criteria, route_criteria, question_criteria)

    return {
        "status": "SUCCESS",
        "top_topic": ranked[0]["name"] if ranked else None,
        "score_gap_note": score_gap_note(ranked),
        "team_fit_applied": team_fit_applied,
        "ranked_topics": ranked,
        "markdown_report": markdown_report,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Score mathematical modeling topics and routes from JSON."
    )
    parser.add_argument("input", type=Path, help="Input JSON file with topics and routes.")
    parser.add_argument("-o", "--output", type=Path, help="Output markdown path.")
    parser.add_argument("--json-out", type=Path, help="Output scored JSON path.")
    args = parser.parse_args()

    try:
        payload = load_payload(args.input)
        result = score_topics_payload(payload)
        if args.output:
            args.output.write_text(result["markdown_report"], encoding="utf-8")
            logger.info("Saved markdown report to %s", args.output)
        else:
            print(result["markdown_report"])

        if args.json_out:
            args.json_out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info("Saved scored json to %s", args.json_out)
        return 0
    except Exception as exc:
        logger.error("Topic scoring failed: %s", exc)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
