"""Task-local, hash-bound export-template overrides.

Official competition packages change faster than application releases.  This
module deliberately keeps a user-provided Word reference document and a small,
validated layout contract in the task directory instead of overwriting a shared
profile in the repository.  It is intentionally *not* a general TeX execution
channel: PDF settings are an allowlisted set of Pandoc variables only.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from typing import Any

from app.tools.export_profiles import normalize_export_profile


MANIFEST_FILENAME = "export_template_override.json"
OVERRIDE_DIRNAME = "template_overrides"
SCHEMA_VERSION = "mma.export-template-override.v1"
FORMAT_CONTRACT_SCHEMA_VERSION = "mma.export-format-contract.v1"
MAX_DOCX_BYTES = 25 * 1024 * 1024
MAX_DOCX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_DOCX_ENTRIES = 4096
MAX_MANIFEST_BYTES = 256 * 1024
MAX_CONTRACT_BYTES = 64 * 1024
_REQUIRED_DOCX_MEMBERS = {"[Content_Types].xml", "word/document.xml"}
_FORMAL_PROFILES = {"cumcm2025", "cumcm2026"}
_FONT_VARIABLES = {
    "mainfont",
    "sansfont",
    "monofont",
    "CJKmainfont",
    "CJKsansfont",
    "CJKmonofont",
}
_PDF_VARIABLES = _FONT_VARIABLES | {"fontsize", "linestretch", "geometry", "papersize"}
_DOCX_FIELDS = {
    "body_font_east_asia",
    "body_font_ascii",
    "body_font_hansi",
    "body_font_cs",
    "body_font_size_half_points",
    "body_line_spacing_twips",
    "body_line_rule",
    "body_start_page_break",
}
_PREFLIGHT_FIELDS = {
    "min_abstract_paragraphs",
    "require_references",
    "require_reference_style",
    "body_min_pages",
    "body_max_pages",
}
_SAFE_TEXT_RE = re.compile(r"^[^\x00-\x1f\\]{1,160}$")
_SAFE_FONT_RE = re.compile(r"^[\w .(),+\-]{1,160}$", re.UNICODE)
_SAFE_PATH_COMPONENT_RE = re.compile(r"^[A-Za-z0-9._-]{1,96}$")
_SAFE_GEOMETRY_RE = re.compile(r"^[A-Za-z0-9.,=:%+\- ]{1,240}$")
_SAFE_FONT_SIZE_RE = re.compile(r"^\d+(?:\.\d+)?pt$")
_SAFE_LINESTRETCH_RE = re.compile(r"^\d+(?:\.\d+)?$")
_RISKY_DOCX_MEMBERS = {"word/vbaproject.bin", "word/vbadata.xml"}
_RISKY_DOCX_PREFIXES = ("word/activex/", "word/embeddings/", "customui/")

# A task-local file may refine visual presentation after the team has checked
# a newly issued package.  It must never quietly lower the project's internal
# completeness and delivery safeguards.  A genuine rule relaxation requires a
# reviewed code/profile change, rather than an untrusted JSON switch.
_MIN_ABSTRACT_PARAGRAPHS = 2
_MIN_EDITORIAL_BODY_PAGES = 10
# 上限对齐 CUMCM 2026 官方口径“正文不超过 30 页”；合同仍只能保持或收紧，
# 不能放宽到 30 页以上。
_MAX_EDITORIAL_BODY_PAGES = 30
# cumcm2026 的严格门禁下限（用户指定，官方仅设 30 页上限）：该 profile 的合同
# body_min_pages/body_max_pages 不得低于 15。
_CUMCM2026_MIN_BODY_PAGES = 15
_MIN_CONTENT_MARGIN_CM = 2.5

TEMPLATE_OVERRIDE_AUDIT_FIELDS = (
    "active",
    "manifest",
    "manifest_sha256",
    "profile",
    "source",
    "official_rule",
    "format_contract_sha256",
    "docx_contract_sha256",
    "docx_reference_doc",
    "docx_sha256",
)
_WINDOWS_RESERVED_COMPONENTS = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


class TemplateOverrideError(ValueError):
    """Raised when an imported competition template is unsafe or inconsistent."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _write_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".mma-template-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _safe_relative_path(root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise TemplateOverrideError("模板清单包含非法相对路径")
    candidate = PurePosixPath(value)
    if (
        candidate.is_absolute()
        or not 1 <= len(candidate.parts) <= 4
        or any(
            part in {"", ".", ".."}
            or not _SAFE_PATH_COMPONENT_RE.fullmatch(part)
            or part.split(".", 1)[0].upper() in _WINDOWS_RESERVED_COMPONENTS
            for part in candidate.parts
        )
    ):
        raise TemplateOverrideError("模板清单包含路径穿越")
    path = root.joinpath(*candidate.parts)
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise TemplateOverrideError("模板路径越出任务目录") from exc
    return path


def _validate_docx_template(path: Path) -> None:
    if path.suffix.lower() != ".docx":
        raise TemplateOverrideError("官方 Word 参考模板必须是 .docx 文件")
    if path.is_symlink() or not path.is_file():
        raise TemplateOverrideError("模板必须是常规 .docx 文件，不能使用符号链接")
    if path.stat().st_size <= 0 or path.stat().st_size > MAX_DOCX_BYTES:
        raise TemplateOverrideError("DOCX 模板为空或超过 25 MiB 限制")
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_DOCX_ENTRIES:
                raise TemplateOverrideError("DOCX 模板条目数量异常")
            # Inspect member names before reading any relationship.  This
            # prevents a duplicate ``.rels`` entry from hiding an earlier
            # external relationship behind a later benign entry.
            names_in_order = [info.filename for info in infos]
            if not all(names_in_order) or len(set(names_in_order)) != len(names_in_order):
                raise TemplateOverrideError("DOCX 模板包含重复或空白压缩包条目")
            total = 0
            names: set[str] = set()
            for info in infos:
                name = info.filename
                member = PurePosixPath(name)
                if member.is_absolute() or ".." in member.parts or "\\" in name:
                    raise TemplateOverrideError("DOCX 模板包含不安全压缩包路径")
                if ((info.external_attr >> 16) & 0o170000) == 0o120000:
                    raise TemplateOverrideError("DOCX 模板不能包含符号链接条目")
                if info.flag_bits & 0x1:
                    raise TemplateOverrideError("DOCX 模板不能包含加密条目")
                lowered = name.lower()
                if lowered in _RISKY_DOCX_MEMBERS or lowered.startswith(
                    _RISKY_DOCX_PREFIXES
                ):
                    raise TemplateOverrideError("DOCX 模板不能包含宏、ActiveX 或嵌入对象")
                total += int(info.file_size)
                if total > MAX_DOCX_UNCOMPRESSED_BYTES:
                    raise TemplateOverrideError("DOCX 模板解压后体积超过限制")
                names.add(name)
                if lowered.endswith(".rels"):
                    relationships = archive.read(info)
                    # ElementTree accepts a declared UTF-16 encoding.  The
                    # byte-level pre-check catches DTD/entity declarations
                    # before parsing even when ASCII bytes are NUL-separated.
                    compact = relationships.decode("latin-1").replace("\x00", "").upper()
                    if "<!DOCTYPE" in compact or "<!ENTITY" in compact:
                        raise TemplateOverrideError("DOCX 模板关系文件不能包含 DTD 或实体声明")
                    try:
                        relation_root = ET.fromstring(relationships)
                    except ET.ParseError as exc:
                        raise TemplateOverrideError("DOCX 模板关系文件不是有效 XML") from exc
                    if any(
                        node.tag.rsplit("}", 1)[-1] == "Relationship"
                        and node.attrib.get("TargetMode", "").lower() == "external"
                        for node in relation_root.iter()
                    ):
                        raise TemplateOverrideError("DOCX 模板不能引用外部关系资源")
    except TemplateOverrideError:
        raise
    except (
        OSError,
        KeyError,
        NotImplementedError,
        RuntimeError,
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
    ) as exc:
        raise TemplateOverrideError("DOCX 模板不是有效的 Office Open XML 文件") from exc
    missing = sorted(_REQUIRED_DOCX_MEMBERS - names)
    if missing:
        raise TemplateOverrideError("DOCX 模板缺少必要部件: " + ", ".join(missing))


def _safe_text(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not _SAFE_TEXT_RE.fullmatch(value)
    ):
        raise TemplateOverrideError(f"{field} 必须是长度受限的普通文本")
    return value


def _safe_font_name(value: object, field: str) -> str:
    """Accept a font-family name, never arbitrary TeX/Pandoc source."""
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not _SAFE_FONT_RE.fullmatch(value)
    ):
        raise TemplateOverrideError(f"{field} 必须是普通字体名称，不能包含 TeX 特殊字符")
    return value


def validate_pdf_font_overrides(raw: object) -> dict[str, str]:
    """Validate explicit PDF font choices before they enter Pandoc variables."""
    if raw is None:
        return {}
    if not isinstance(raw, dict) or set(raw) - _FONT_VARIABLES:
        raise TemplateOverrideError("PDF 字体覆盖仅允许已知字体变量")
    return {
        key: _safe_font_name(value, f"font_overrides.{key}")
        for key, value in raw.items()
    }


def _normalise_docx_contract(raw: object) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict) or set(raw) - _DOCX_FIELDS:
        raise TemplateOverrideError("docx 合同包含不支持的字段")
    result: dict[str, Any] = {}
    for name in ("body_font_east_asia", "body_font_ascii", "body_font_hansi", "body_font_cs"):
        if name in raw:
            result[name] = _safe_font_name(raw[name], name)
    if "body_font_size_half_points" in raw:
        value = raw["body_font_size_half_points"]
        if isinstance(value, bool) or not isinstance(value, int) or not 16 <= value <= 48:
            raise TemplateOverrideError("body_font_size_half_points 必须在 16 至 48 之间")
        result["body_font_size_half_points"] = value
    if "body_line_spacing_twips" in raw:
        value = raw["body_line_spacing_twips"]
        if isinstance(value, bool) or not isinstance(value, int) or not 120 <= value <= 960:
            raise TemplateOverrideError("body_line_spacing_twips 必须在 120 至 960 之间")
        result["body_line_spacing_twips"] = value
    if "body_line_rule" in raw:
        value = raw["body_line_rule"]
        if value not in {"auto", "exact", "atLeast"}:
            raise TemplateOverrideError("body_line_rule 仅允许 auto、exact 或 atLeast")
        result["body_line_rule"] = value
    if "body_start_page_break" in raw:
        if not isinstance(raw["body_start_page_break"], bool):
            raise TemplateOverrideError("body_start_page_break 必须为布尔值")
        result["body_start_page_break"] = raw["body_start_page_break"]
    return result


def _normalise_pdf_contract(raw: object) -> dict[str, Any]:
    if raw is None:
        return {"variables": {}, "min_content_margin_cm": None}
    if not isinstance(raw, dict) or set(raw) - {"variables", "min_content_margin_cm"}:
        raise TemplateOverrideError("pdf 合同包含不支持的字段")
    variables = raw.get("variables", {})
    if not isinstance(variables, dict) or set(variables) - _PDF_VARIABLES:
        raise TemplateOverrideError("pdf.variables 包含不支持的字段")
    result: dict[str, str] = {}
    for key, value in variables.items():
        text = (
            _safe_font_name(value, f"pdf.variables.{key}")
            if key in _FONT_VARIABLES
            else _safe_text(value, f"pdf.variables.{key}")
        )
        if key == "geometry" and not _SAFE_GEOMETRY_RE.fullmatch(text):
            raise TemplateOverrideError("pdf.variables.geometry 包含不安全字符")
        if key == "fontsize" and not _SAFE_FONT_SIZE_RE.fullmatch(text):
            raise TemplateOverrideError("pdf.variables.fontsize 必须形如 12pt")
        if key == "linestretch":
            if not _SAFE_LINESTRETCH_RE.fullmatch(text) or not 0.8 <= float(text) <= 3.0:
                raise TemplateOverrideError("pdf.variables.linestretch 必须在 0.8 至 3.0 之间")
        if key == "papersize" and text.lower() not in {"a4", "a4paper"}:
            raise TemplateOverrideError("pdf.variables.papersize 当前仅允许 A4")
        result[key] = text
    margin = raw.get("min_content_margin_cm")
    if margin is not None:
        if isinstance(margin, bool) or not isinstance(margin, (int, float)):
            raise TemplateOverrideError("pdf.min_content_margin_cm 必须为数值")
        if not _MIN_CONTENT_MARGIN_CM <= float(margin) <= 5.0:
            raise TemplateOverrideError(
                "pdf.min_content_margin_cm 只能收紧内部边距下限（2.5 至 5.0）"
            )
        margin = round(float(margin), 3)
    return {"variables": result, "min_content_margin_cm": margin}


def _normalise_preflight_contract(
    raw: object, *, export_profile: object = None
) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict) or set(raw) - _PREFLIGHT_FIELDS:
        raise TemplateOverrideError("preflight 合同包含不支持的字段")
    profile_value = normalize_export_profile(export_profile).value
    min_floor = (
        _CUMCM2026_MIN_BODY_PAGES
        if profile_value == "cumcm2026"
        else _MIN_EDITORIAL_BODY_PAGES
    )
    result: dict[str, Any] = {}
    for name in ("min_abstract_paragraphs", "body_min_pages", "body_max_pages"):
        if name in raw:
            value = raw[name]
            if isinstance(value, bool) or not isinstance(value, int):
                raise TemplateOverrideError(f"{name} 必须为整数")
            if (
                name == "min_abstract_paragraphs"
                and not _MIN_ABSTRACT_PARAGRAPHS <= value <= 10
            ):
                raise TemplateOverrideError(
                    "min_abstract_paragraphs 只能保持或提高内部下限（2 至 10）"
                )
            if name in ("body_min_pages", "body_max_pages") and not (
                min_floor <= value <= _MAX_EDITORIAL_BODY_PAGES
            ):
                raise TemplateOverrideError(
                    f"{name} 只能保持在内部范围内"
                    f"（{min_floor} 至 {_MAX_EDITORIAL_BODY_PAGES}）"
                )
            result[name] = value
    for name in ("require_references", "require_reference_style"):
        if name in raw:
            if not isinstance(raw[name], bool):
                raise TemplateOverrideError(f"{name} 必须为布尔值")
            if raw[name] is False:
                raise TemplateOverrideError(f"{name} 不能关闭内部正式交付门禁")
            result[name] = raw[name]
    minimum = result.get(
        "body_min_pages",
        _CUMCM2026_MIN_BODY_PAGES
        if profile_value == "cumcm2026"
        else _MIN_EDITORIAL_BODY_PAGES,
    )
    maximum = result.get("body_max_pages", _MAX_EDITORIAL_BODY_PAGES)
    if minimum > maximum:
        raise TemplateOverrideError("body_min_pages 不能大于 body_max_pages")
    return result


def normalise_format_contract(
    raw: object, *, export_profile: object = None
) -> dict[str, Any]:
    """Validate a user-supplied JSON layout contract into a small safe subset."""
    if not isinstance(raw, dict):
        raise TemplateOverrideError("版式合同必须是 JSON 对象")
    allowed = {
        "schema_version",
        "label",
        "docx",
        "pdf",
        "preflight",
        # These two fields are written by this module.  They are accepted on
        # reload but never trusted from an external JSON file.
        "source",
        "official_rule",
    }
    if set(raw) - allowed:
        raise TemplateOverrideError("版式合同包含不支持的顶层字段")
    version = raw.get("schema_version", FORMAT_CONTRACT_SCHEMA_VERSION)
    if version != FORMAT_CONTRACT_SCHEMA_VERSION:
        raise TemplateOverrideError("不支持的版式合同 schema_version")
    if "source" in raw and raw["source"] != "user_supplied_unverified":
        raise TemplateOverrideError("版式合同 source 不合法")
    if "official_rule" in raw and raw["official_rule"] is not False:
        raise TemplateOverrideError("版式合同不得自行声明为官方已验证")
    label = raw.get("label", "用户提供的竞赛版式合同")
    label = _safe_text(label, "label")
    return {
        "schema_version": FORMAT_CONTRACT_SCHEMA_VERSION,
        "label": label,
        # A human supplied file may be official, but the application cannot
        # verify that fact.  Keep the audit statement deliberately honest.
        "source": "user_supplied_unverified",
        "official_rule": False,
        "docx": _normalise_docx_contract(raw.get("docx")),
        "pdf": _normalise_pdf_contract(raw.get("pdf")),
        "preflight": _normalise_preflight_contract(
            raw.get("preflight"), export_profile=export_profile
        ),
    }


def _read_json(path: Path, *, max_bytes: int, kind: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise TemplateOverrideError(f"{kind} 必须是常规文件，不能使用符号链接")
    try:
        if path.stat().st_size > max_bytes:
            raise TemplateOverrideError(f"{kind} 超过大小上限")
        value = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TemplateOverrideError(f"{kind} 不是有效 JSON") from exc
    if not isinstance(value, dict):
        raise TemplateOverrideError(f"{kind} 必须是 JSON 对象")
    return value


def _load_manifest(root: Path) -> dict[str, Any] | None:
    path = root / MANIFEST_FILENAME
    if path.is_symlink():
        raise TemplateOverrideError("模板覆盖清单不能使用符号链接")
    if not path.exists():
        return None
    return _read_json(path, max_bytes=MAX_MANIFEST_BYTES, kind="模板覆盖清单")


def load_export_template_override(work_dir: str, export_profile: object) -> dict[str, Any]:
    """Resolve a checked task-local override, failing closed on tampering."""
    root = Path(work_dir).resolve()
    manifest = _load_manifest(root)
    profile = normalize_export_profile(export_profile).value
    if manifest is None:
        return {"active": False, "profile": profile, "audit": {"active": False}}
    if manifest.get("schema_version") != SCHEMA_VERSION or not isinstance(manifest.get("profiles"), dict):
        raise TemplateOverrideError("模板覆盖清单 schema 无效")
    entry = manifest["profiles"].get(profile)
    if entry is None:
        return {"active": False, "profile": profile, "audit": {"active": False}}
    if not isinstance(entry, dict):
        raise TemplateOverrideError("模板覆盖 profile 条目无效")

    contract = normalise_format_contract(
        entry.get("format_contract", {}), export_profile=profile
    )
    expected_contract_hash = entry.get("format_contract_sha256")
    if expected_contract_hash != _canonical_sha256(contract):
        raise TemplateOverrideError("版式合同哈希不匹配；请重新导入模板")

    reference_doc: Path | None = None
    reference_name = entry.get("docx_reference_doc")
    if reference_name is not None:
        reference_doc = _safe_relative_path(root, reference_name)
        if reference_doc.is_symlink() or not reference_doc.is_file():
            raise TemplateOverrideError("模板引用文件不存在或不是常规文件")
        if entry.get("docx_sha256") != _sha256(reference_doc):
            raise TemplateOverrideError("DOCX 模板哈希不匹配；请重新导入模板")
        _validate_docx_template(reference_doc)

    return {
        "active": True,
        "profile": profile,
        "docx_reference_doc": str(reference_doc) if reference_doc else None,
        "format_contract": contract,
        "audit": {
            "active": True,
            "manifest": MANIFEST_FILENAME,
            "manifest_sha256": _sha256(root / MANIFEST_FILENAME),
            "profile": profile,
            "source": contract["source"],
            "official_rule": False,
            "format_contract_sha256": expected_contract_hash,
            "docx_contract_sha256": _canonical_sha256(contract["docx"]),
            "docx_reference_doc": str(reference_name) if reference_name else None,
            "docx_sha256": entry.get("docx_sha256"),
        },
    }


def merge_pdf_variables(profile_variables: list[str], override_variables: dict[str, str]) -> list[str]:
    """Merge only validated variable values, preserving profile TeX headers."""
    if not override_variables:
        return list(profile_variables)
    result: list[str] = []
    seen: set[str] = set()
    for variable in profile_variables:
        key, separator, _value = variable.partition("=")
        base_key = "geometry" if key.startswith("geometry:") else key
        if separator and base_key in override_variables:
            if base_key not in seen:
                value = override_variables[base_key]
                result.append(f"geometry:{value}" if base_key == "geometry" else f"{base_key}={value}")
                seen.add(base_key)
            continue
        result.append(variable)
    for key, value in override_variables.items():
        if key in seen:
            continue
        result.append(f"geometry:{value}" if key == "geometry" else f"{key}={value}")
    return result


def template_override_audit_matches(expected: object, recorded: object) -> bool:
    """Compare immutable template identity without trusting status-file extras."""
    return (
        isinstance(expected, dict)
        and isinstance(recorded, dict)
        and all(
            recorded.get(name) == expected.get(name)
            for name in TEMPLATE_OVERRIDE_AUDIT_FIELDS
        )
    )


def get_editorial_policy_override(work_dir: str, export_profile: object) -> str | dict:
    """Return only safe manuscript-preflight settings from an installed override."""
    override = load_export_template_override(work_dir, export_profile)
    preflight = override.get("format_contract", {}).get("preflight", {})
    if not preflight:
        return "auto"
    return {
        "base": "cumcm_formal",
        **{
            name: value
            for name, value in preflight.items()
            if name
            in {
                "min_abstract_paragraphs",
                "require_references",
                "require_reference_style",
            }
        },
    }


def get_pdf_visual_constraints(work_dir: str, export_profile: object) -> dict[str, Any]:
    """Return bounded page-range settings for the PDF post-check."""
    override = load_export_template_override(work_dir, export_profile)
    preflight = override.get("format_contract", {}).get("preflight", {})
    return {
        "body_min_pages": preflight.get("body_min_pages"),
        "body_max_pages": preflight.get("body_max_pages"),
        "min_content_margin_cm": (
            override.get("format_contract", {})
            .get("pdf", {})
            .get("min_content_margin_cm")
        ),
    }


def install_export_template_override(
    work_dir: str,
    export_profile: object,
    *,
    docx_template_path: str | None = None,
    format_contract_path: str | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    """Import a Word template and/or a validated layout contract for one task."""
    root = Path(work_dir).resolve()
    if not root.is_dir():
        raise TemplateOverrideError("任务工作目录不存在")
    profile = normalize_export_profile(export_profile).value
    if profile not in _FORMAL_PROFILES:
        raise TemplateOverrideError("模板覆盖目前仅支持 cumcm2025 或 cumcm2026")
    if not docx_template_path and not format_contract_path:
        raise TemplateOverrideError("至少提供一个 DOCX 模板或版式合同 JSON")

    manifest = _load_manifest(root) or {"schema_version": SCHEMA_VERSION, "profiles": {}}
    if manifest.get("schema_version") != SCHEMA_VERSION or not isinstance(manifest.get("profiles"), dict):
        raise TemplateOverrideError("现有模板覆盖清单 schema 无效")
    previous = manifest["profiles"].get(profile, {})
    if not isinstance(previous, dict):
        raise TemplateOverrideError("现有模板覆盖 profile 条目无效")
    entry = dict(previous)

    # Validate every new input before changing either the template file or the
    # manifest.  A later failure must not leave a fresh DOCX behind a stale
    # hash record.
    if format_contract_path:
        contract_source = Path(format_contract_path).expanduser()
        raw_contract = _read_json(
            contract_source, max_bytes=MAX_CONTRACT_BYTES, kind="版式合同 JSON"
        )
        contract = normalise_format_contract(raw_contract, export_profile=profile)
    elif isinstance(entry.get("format_contract"), dict):
        contract = normalise_format_contract(
            entry["format_contract"], export_profile=profile
        )
    else:
        contract = normalise_format_contract(
            {"label": label or "用户提供的竞赛版式合同"}, export_profile=profile
        )
    if label:
        contract["label"] = _safe_text(label, "label")

    destination: Path | None = None
    pending_template: str | None = None
    new_template_hash: str | None = None
    if docx_template_path:
        source = Path(docx_template_path).expanduser()
        _validate_docx_template(source)
        source = source.resolve()
        relative = f"{OVERRIDE_DIRNAME}/{profile}_reference.docx"
        destination = _safe_relative_path(root, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, pending_template = tempfile.mkstemp(
            prefix=".mma-template-copy-", suffix=".docx", dir=destination.parent
        )
        os.close(descriptor)
        try:
            shutil.copyfile(source, pending_template)
            _validate_docx_template(Path(pending_template))
            new_template_hash = _sha256(Path(pending_template))
        except Exception:
            if pending_template and os.path.exists(pending_template):
                os.unlink(pending_template)
            raise
        entry["docx_reference_doc"] = relative
        entry["docx_sha256"] = new_template_hash

    entry.update(
        {
            "label": contract["label"],
            "format_contract": contract,
            "format_contract_sha256": _canonical_sha256(contract),
            "updated_at": datetime.datetime.now().isoformat(),
        }
    )
    manifest["profiles"][profile] = entry
    manifest["updated_at"] = datetime.datetime.now().isoformat()
    manifest_path = root / MANIFEST_FILENAME
    original_manifest = manifest_path.read_bytes() if manifest_path.is_file() else None
    original_template = (
        destination.read_bytes() if destination is not None and destination.is_file() else None
    )
    template_replaced = False
    try:
        if destination is not None and pending_template is not None:
            os.replace(pending_template, destination)
            template_replaced = True
            pending_template = None
        _write_atomic(
            manifest_path,
            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        )
        resolved = load_export_template_override(str(root), profile)
    except Exception:
        if template_replaced and destination is not None:
            if original_template is None:
                destination.unlink(missing_ok=True)
            else:
                _write_atomic(destination, original_template)
        if original_manifest is None:
            manifest_path.unlink(missing_ok=True)
        else:
            _write_atomic(manifest_path, original_manifest)
        raise
    finally:
        if pending_template and os.path.exists(pending_template):
            os.unlink(pending_template)
    return {
        "status": "installed",
        "profile": profile,
        "manifest": MANIFEST_FILENAME,
        "audit": resolved["audit"],
    }
