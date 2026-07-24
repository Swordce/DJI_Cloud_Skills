#!/usr/bin/env python3
"""Generate a structured DJI Cloud API catalog and agent tool adapters.

Error-handling convention: parsers may degrade silently only for structures
that are optional in the official documentation (a missing example, an absent
table). Every tolerated absence must stay visible: required coverage is
enforced fail-closed by validate_catalog.py (route/ID/field-completeness
assertions), and any newly accepted gap must be recorded in the
coverage-report known_source_exceptions. Unmapped classifications
(e.g. an unknown JSBridge section heading) fail loudly instead of falling
back to opaque hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / ".official-cache"
CN_API = Path("docs/cn/60.api-reference")
HTTP_RE = re.compile(r"`(GET|POST|PUT|DELETE)\s+([^`\s]+)`", re.I)
TOPIC_RE = re.compile(r"\*\*Topic:\*\*\s*(.+)")
DIRECTION_RE = re.compile(r"\*\*Direction:\*\*\s*(\w+)", re.I)
METHOD_RE = re.compile(r"\*\*Method:\*\*\s*`?([A-Za-z0-9_.-]+)`?", re.I)
JS_RE = re.compile(r"`?(window\.(?:(?:djiBridge|thing)\.[A-Za-z0-9_]+|open)\s*\([^`)]*\)(?:\s*:\s*[A-Za-z]+)?)`?")


def clean(value: str) -> str:
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.I)
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = value.replace("**", "").replace("`", "")
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def write_text_lf(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)


def slug(value: str) -> str:
    value = value.lower().replace("_", "-").replace(".", "-")
    value = re.sub(r"[^a-z0-9-]+", "-", value)
    return re.sub(r"-+", "-", value).strip("-") or hashlib.sha1(value.encode()).hexdigest()[:12]


@lru_cache(maxsize=4)
def source_snapshot(source: Path) -> dict[str, Any]:
    snapshot_path = source / "snapshot.json"
    if not snapshot_path.exists():
        raise RuntimeError(f"Official snapshot manifest is missing: {snapshot_path}")
    return json.loads(snapshot_path.read_text(encoding="utf-8"))


def source_ref(path: Path, source: Path) -> dict[str, str]:
    rel = path.relative_to(source).as_posix()
    snapshot = source_snapshot(source)
    page = next((item for item in snapshot["pages"] if item["file"] == rel), None)
    if not page:
        raise RuntimeError(f"Official snapshot does not contain source metadata for {rel}")
    return {
        "file": rel,
        "url": page["source_url"],
        "sha256": page["content_sha256"],
        "asset_sha256": page["asset_sha256"],
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "version": snapshot["version"],
    }


def product_for_path(path: Path) -> str:
    parts = [re.sub(r"^\d+\.", "", part.lower()) for part in path.parts]
    stem = re.sub(r"^\d+\.", "", path.stem.lower())
    for prefix, product in (
        ("m30-properties", "m30-series"),
        ("m3d-properties", "m3d-series"),
        ("m4d-properties", "m4d-series"),
    ):
        if stem == prefix:
            return product
    candidates = (
        "dock3",
        "dock2",
        "matrice-400",
        "m4-series",
        "dji-rc-plus-2",
        "rc-pro",
        "m3-series",
        "aircraft",
        "rc",
    )
    for candidate in candidates:
        if candidate in parts:
            return candidate
    if "pilot-to-cloud" in parts:
        return "pilot-generic"
    if "dock-to-cloud" in parts:
        return "dock1"
    return "generic"


def table_after(lines: list[str], start: int) -> list[dict[str, str]]:
    for i in range(start, min(len(lines), start + 30)):
        if lines[i].lstrip().startswith("|") and i + 1 < len(lines) and "---" in lines[i + 1]:
            headers = [clean(x).lower() for x in lines[i].strip().strip("|").split("|")]
            rows: list[dict[str, str]] = []
            for line in lines[i + 2 :]:
                if not line.lstrip().startswith("|"):
                    break
                cells = [clean(x) for x in line.strip().strip("|").split("|")]
                if len(cells) < len(headers):
                    cells += [""] * (len(headers) - len(cells))
                rows.append(dict(zip(headers, cells)))
            return rows
    return []


def code_blocks(text: str) -> list[tuple[str, str]]:
    return [(lang.strip(), body.strip()) for lang, body in re.findall(r"```([^\n]*)\n(.*?)```", text, re.S)]


def parse_jsonish(body: str) -> Any | None:
    candidate = re.sub(r"(?m)^\s*//.*$", "", body)
    candidate = re.sub(r'([0-9"truefalsenull}\]])(\s*\n\s*")', r"\1,\2", candidate)
    candidate = re.sub(r",(\s*[}\]])", r"\1", candidate)
    try:
        return json.loads(candidate)
    except Exception:
        return None


def fields_from_value(value: Any, location: str = "response") -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    fields: list[dict[str, Any]] = []
    for name, child in value.items():
        raw_type = type(child).__name__
        item = {
            "name": str(name),
            "in": location,
            "type": normalize_type(raw_type),
            "required": None,
            "required_status": "not_specified_by_source",
            "description": "Field present in the official example response.",
            "constraints": "",
            "schema": raw_type,
        }
        nested = fields_from_value(child, location)
        if nested:
            item["fields"] = nested
        fields.append(item)
    return fields


def normalize_type(value: str) -> str:
    value = clean(value).lower()
    if "array" in value or value.startswith("[") or "数组" in value:
        return "array"
    if "struct" in value or "object" in value or "json" in value:
        return "object"
    if any(x in value for x in ("int", "number", "float", "double", "enum_int", "整型", "整形", "浮点")):
        return "number" if any(x in value for x in ("float", "double", "number", "浮点")) else "integer"
    if "bool" in value or "布尔" in value:
        return "boolean"
    return "string"


def parse_required(value: str) -> bool | None:
    """Map a source required-column cell to True/False, or None when the cell is empty."""
    text = clean(str(value))
    if not text:
        return None
    low = text.lower()
    if "非必需" in text or "可选" in text or low in {"false", "no", "否", "optional", "-", "—"}:
        return False
    if low in {"true", "yes", "是", "required"} or "必需" in text:
        return True
    return False


def parameter(row: dict[str, str], default_location: str = "payload") -> dict[str, Any]:
    name = row.get("column") or row.get("参数名") or row.get("元素") or row.get("name")
    name = clean(name).lstrip("»›>- ")
    location = clean(row.get("in") or row.get("参数位置") or default_location).lower()
    if not name and location == "body":
        name = "body"
    required_raw = clean(row.get("required") or row.get("必填") or row.get("是否必需（默认值）") or "")
    required = parse_required(required_raw)
    constraint = row.get("constraint") or row.get("restrictions") or row.get("范围") or row.get("取值与释义") or ""
    default_match = re.search(r"默认值[:：]?\s*([^)）]+)", required_raw)
    if default_match:
        constraint = f"{constraint}；默认值:{default_match.group(1).strip()}" if constraint else f"默认值:{default_match.group(1).strip()}"
    unit = clean(row.get("单位") or "")
    if unit and unit != "-":
        constraint = f"{constraint}；单位:{unit}" if constraint else f"单位:{unit}"
    description = row.get("description") or row.get("说明") or row.get("name") or row.get("名称") or ""
    return {
        "name": name,
        "in": location,
        "type": normalize_type(row.get("type") or row.get("类型") or "string"),
        "required": required,
        "required_status": "required" if required is True else ("optional" if required is False else "not_specified_by_source"),
        "description": clean(description),
        "constraints": clean(constraint),
        "schema": clean(row.get("type") or row.get("类型") or "string"),
    }


ROW_NAME_KEYS = ("column", "参数名", "元素", "name")


def parameters_from_rows(rows: Iterable[dict[str, str]], default_location: str = "payload") -> list[dict[str, Any]]:
    """Build parameters from a source table, preserving »/› parent-child hierarchy."""
    params: list[dict[str, Any]] = []
    hierarchy: list[str] = []
    for row in rows:
        raw = ""
        for key in ROW_NAME_KEYS:
            if row.get(key):
                raw = clean(row[key])
                break
        if not raw or raw == "(root)":
            continue
        depth = len(raw) - len(raw.lstrip("»›"))
        item = parameter(row, default_location)
        if not item["name"]:
            continue
        hierarchy = hierarchy[:depth]
        if depth > 0 and hierarchy:
            item["parent"] = hierarchy[-1]
        hierarchy.append(item["name"])
        params.append(item)
    return unique_parameters(params)


def unique_parameters(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        key = (item.get("parent") or "", item["name"])
        if not item["name"] or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def schema_property_rows(lines: list[str], schema_name: str) -> list[dict[str, str]]:
    if not schema_name:
        return []
    target = schema_name.strip("[]").split("#", 1)[0]
    for i, line in enumerate(lines):
        if i > 0 and target.lower() in clean(line).lower():
            for j in range(i, min(i + 35, len(lines))):
                if clean(lines[j]).lower() in {"*properties*", "properties"}:
                    return table_after(lines, j)
    return []


def base_entry(
    entry_id: str,
    protocol: str,
    module: str,
    name: str,
    purpose: str,
    source: dict[str, str],
) -> dict[str, Any]:
    auth = {
        "http": {"type": "token", "location": "header", "name": "X-Auth-Token"},
        "mqtt": {"type": "broker_credentials", "location": "connection", "name": "username/password"},
        "websocket": {"type": "token", "location": "query", "name": "x-auth-token"},
        "jsbridge": {"type": "license", "location": "initialization", "name": "appId/appKey/license"},
        "wpml": {"type": "none", "location": "local_document", "name": None},
    }[protocol]
    return {
        "id": entry_id,
        "name": clean(name),
        "purpose": clean(purpose or name),
        "protocol": protocol,
        "module": module,
        "operation": {},
        "parameters": [],
        "authentication": auth,
        "responses": [],
        "errors": [],
        "examples": [],
        "retry": retry_policy(protocol, entry_id, ""),
        "compatibility": [],
        "deprecated": "废弃" in name or "deprecated" in name.lower(),
        "source": source,
    }


def retry_policy(protocol: str, entry_id: str, method: str) -> dict[str, Any]:
    dangerous = any(
        token in entry_id
        for token in ("flight", "takeoff", "return-home", "firmware", "upgrade", "ota-", "format", "reboot", "shutdown", "control")
    )
    if protocol == "http":
        idempotent = method.upper() in {"GET", "PUT", "DELETE"}
        return {
            "automatic": idempotent,
            "max_attempts": 3 if idempotent else 1,
            "backoff": "exponential_jitter",
            "retry_on": ["network_error", "408", "429", "502", "503", "504"] if idempotent else [],
            "notes": "POST requires an application idempotency key or explicit confirmation before retry.",
        }
    if protocol == "mqtt":
        return {
            "automatic": not dangerous,
            "max_attempts": 2 if not dangerous else 1,
            "backoff": "exponential_jitter",
            "retry_on": ["reply_timeout", "broker_disconnect"] if not dangerous else [],
            "notes": "Reuse tid/bid for correlation and deduplicate replies; never blindly replay flight, control, or upgrade commands.",
        }
    if protocol == "websocket":
        return {
            "automatic": True,
            "max_attempts": 0,
            "backoff": "capped_exponential_jitter",
            "retry_on": ["disconnect"],
            "notes": "Reconnect the transport, resubscribe, and deduplicate application messages.",
        }
    if protocol == "jsbridge":
        return {
            "automatic": False,
            "max_attempts": 1,
            "backoff": "none",
            "retry_on": [],
            "notes": "Verify the license and required component state before invoking again.",
        }
    return {
        "automatic": False,
        "max_attempts": 1,
        "backoff": "none",
        "retry_on": [],
        "notes": "Validate the WPML document locally; network retry is not applicable.",
    }


def parse_http(path: Path, source: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    matches = list(HTTP_RE.finditer(text))
    entries: list[dict[str, Any]] = []
    seen_operations: set[tuple[str, str]] = set()
    module = slug(path.parent.name.split(".", 1)[-1])
    for n, match in enumerate(matches):
        method, url_path = match.group(1).upper(), match.group(2)
        if (method, url_path) in seen_operations:
            continue
        seen_operations.add((method, url_path))
        prefix = text[: match.start()].splitlines()
        headings = [clean(line.lstrip("# ")) for line in prefix if line.startswith("#")]
        name = headings[-1] if headings else path.stem
        eid = f"http-{method.lower()}-{slug(url_path)}"
        entry = base_entry(eid, "http", module, name, f"{method} {url_path}", source_ref(path, source))
        entry["operation"] = {"method": method, "path": url_path, "content_type": "application/json"}
        entry["retry"] = retry_policy("http", eid, method)
        line_no = text[: match.start()].count("\n")
        params_index = next(
            (i for i in range(line_no, len(lines)) if re.search(r"\bParameters\b|参数", lines[i], re.I)),
            line_no,
        )
        rows = table_after(lines, params_index)
        entry["parameters"] = [parameter(row, "body") for row in rows if (row.get("name") or row.get("column"))]
        for param_item in entry["parameters"]:
            if param_item["in"] == "body":
                nested = schema_property_rows(lines, param_item["schema"])
                if nested:
                    param_item["fields"] = [parameter(row, "body") for row in nested]
        resp_index = next(
            (i for i in range(params_index + 1, len(lines)) if re.search(r"\bResponses\b|响应", lines[i], re.I)),
            len(lines),
        )
        response_rows = table_after(lines, resp_index)
        entry["responses"] = [
            {
                "status": clean(row.get("status") or row.get("状态码") or "200"),
                "description": clean(row.get("description") or row.get("meaning") or "OK"),
                "schema": clean(row.get("schema") or ""),
                "fields": [
                    parameter(field, "response")
                    for field in schema_property_rows(lines, clean(row.get("schema") or ""))
                ],
            }
            for row in response_rows
        ]
        operation_text = text[match.start() : matches[n + 1].start() if n + 1 < len(matches) else len(text)]
        response_section = operation_text.split("# Schemas", 1)[0]
        blocks = code_blocks(response_section)
        for lang, body in blocks:
            parsed = parse_jsonish(body) if lang.lower() in {"json", ""} else None
            if parsed is not None:
                kind = "response" if isinstance(parsed, dict) and any(key in parsed for key in ("code", "data", "message")) else "request"
                entry["examples"].append({"kind": kind, "format": "json", "value": parsed, "source": "official"})
                if kind == "response" and not entry["responses"]:
                    entry["responses"] = [
                        {
                            "status": "documented_example",
                            "description": "Response structure shown by the official documentation.",
                            "schema": "official_example",
                            "fields": fields_from_value(parsed),
                        }
                    ]
        entry["errors"] = [
            {
                "code": "code != 0",
                "meaning": "Resolve the returned code through catalog/error-codes.json.",
                "retry": False,
            }
        ]
        entries.append(entry)
    return entries


def section_chunks(lines: list[str]) -> Iterable[tuple[str, int, int]]:
    starts = [(i, clean(line[3:])) for i, line in enumerate(lines) if line.startswith("## ")]
    for idx, (start, title) in enumerate(starts):
        yield title, start, starts[idx + 1][0] if idx + 1 < len(starts) else len(lines)


def parse_mqtt(path: Path, source: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    module = slug(path.stem.split(".", 1)[-1])
    product = product_for_path(path)
    entries: list[dict[str, Any]] = []
    for title, start, end in section_chunks(lines):
        chunk_lines = lines[start:end]
        chunk = "\n".join(chunk_lines)
        methods = METHOD_RE.findall(chunk)
        topics = [clean(x) for x in TOPIC_RE.findall(chunk)]
        directions = DIRECTION_RE.findall(chunk)
        if not methods and not topics:
            continue
        method = methods[0] if methods else ("property_set" if "property/set" in chunk else slug(title))
        topic = topics[0] if topics else ""
        category = next((x for x in ("services", "events", "requests", "property", "state", "osd") if x in topic), "message")
        eid = f"mqtt-{product}-{slug(method)}-{slug(topic)}"
        entry = base_entry(eid, "mqtt", module, title, f"MQTT {category}: {method}", source_ref(path, source))
        entry["operation"] = {
            "action": "publish" if (directions and directions[0].lower() == "down") else "subscribe",
            "topic": topic,
            "direction": directions[0].lower() if directions else "bidirectional",
            "method": method,
            "reply_topic": topics[1] if len(topics) > 1 else None,
            "reply_direction": directions[1].lower() if len(directions) > 1 else None,
        }
        data_pos = next((i for i, line in enumerate(chunk_lines) if line.strip().lower() in {"**data:**", "**data:** null"}), 0)
        rows = table_after(chunk_lines, data_pos)
        entry["parameters"] = parameters_from_rows(rows)
        blocks = code_blocks(chunk)
        for example_index, (lang, body) in enumerate(blocks[:2]):
            parsed = parse_jsonish(body)
            if parsed is not None:
                entry["examples"].append(
                    {
                        "kind": "reply" if example_index > 0 and len(topics) > 1 else "request",
                        "format": "json",
                        "value": parsed,
                        "source": "official",
                    }
                )
        entry["responses"] = [{"transport": "mqtt", "topic": topics[1] if len(topics) > 1 else topic, "correlation": ["tid", "bid", "method"]}]
        entry["errors"] = [{"code": "data.result != 0", "meaning": "See catalog/error-codes.json", "retry": False}]
        entry["compatibility"] = [product]
        entry["retry"] = retry_policy("mqtt", eid, "")
        entries.append(entry)
    return entries


def parse_mqtt_properties(path: Path, source: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if "properties" not in path.name:
        return []
    product = product_for_path(path)
    module = "device-properties"
    topics = [clean(x) for x in TOPIC_RE.findall(text)]
    table = []
    for i, line in enumerate(lines):
        if line.lstrip().startswith("|") and i + 1 < len(lines) and "---" in lines[i + 1]:
            headers = [clean(x).lower() for x in line.strip().strip("|").split("|")]
            if any(h in headers for h in ("column", "参数", "property", "属性")):
                table.extend(table_after(lines, i))
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    hierarchy: list[str] = []
    for row in table:
        raw_prop = clean(row.get("column") or row.get("property") or row.get("参数") or row.get("属性") or "")
        depth = len(raw_prop) - len(raw_prop.lstrip("»›"))
        prop = raw_prop.lstrip("»›>- ")
        if not prop or prop.lower() in {"column", "name"}:
            continue
        hierarchy = hierarchy[:depth]
        hierarchy.append(prop)
        property_path = ".".join(hierarchy)
        if property_path in seen:
            continue
        seen.add(property_path)
        eid = f"mqtt-property-{product}-{slug(property_path)}"
        entry = base_entry(eid, "mqtt", module, prop, row.get("description") or row.get("name") or prop, source_ref(path, source))
        entry["operation"] = {
            "action": "read_write" if row.get("accessmode", "").lower() == "rw" else "subscribe",
            "topic": (
                "thing/product/{device_sn}/state"
                if row.get("pushmode") == "1"
                else "thing/product/{device_sn}/osd"
            ),
            "set_topic": (
                "thing/product/{gateway_sn}/property/set"
                if row.get("accessmode", "").lower() == "rw"
                else None
            ),
            "direction": "bidirectional" if row.get("accessmode", "").lower() == "rw" else "up",
            "method": "property_report",
            "property_path": property_path,
            "access_mode": row.get("accessmode") or None,
            "push_mode": row.get("pushmode") or None,
        }
        p = parameter(row)
        p["name"] = prop
        entry["parameters"] = [p]
        entry["responses"] = [{"transport": "mqtt", "payload_field": f"data.{prop}"}]
        entry["compatibility"] = [product]
        entries.append(entry)
    return entries


def parse_websocket(path: Path, source: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    module = slug(path.parent.name.split(".", 1)[-1])
    entries: list[dict[str, Any]] = []
    message_headings = list(re.finditer(r"(?m)^#{2,4}\s+Message\s+`([^`]+)`\s*$", text))
    for index, heading in enumerate(message_headings):
        title = clean(heading.group(1))
        end = message_headings[index + 1].start() if index + 1 < len(message_headings) else len(text)
        chunk = text[heading.start() : end]
        blocks = code_blocks(chunk)
        parsed = next((value for _, body in blocks if isinstance((value := parse_jsonish(body)), dict)), None)
        biz_code = parsed.get("biz_code") if isinstance(parsed, dict) else None
        eid = f"websocket-{module}-{slug(str(biz_code or title))}"
        entry = base_entry(eid, "websocket", module, title, title, source_ref(path, source))
        entry["operation"] = {
            "action": "receive",
            "endpoint": "platform-defined-wss-url",
            "message": title,
            "biz_code": biz_code,
        }
        chunk_lines = chunk.splitlines()
        payload_index = next((i for i, line in enumerate(chunk_lines) if clean(line.lstrip("# ")).lower() == "payload"), 0)
        payload_rows = table_after(chunk_lines, payload_index)
        entry["parameters"] = parameters_from_rows(payload_rows, "message")
        if isinstance(parsed, dict):
            if not entry["parameters"]:
                entry["parameters"] = [
                    {
                        "name": k,
                        "in": "message",
                        "type": normalize_type(type(v).__name__),
                        "required": True,
                        "required_status": "required",
                        "description": "",
                        "constraints": "",
                        "schema": type(v).__name__,
                    }
                    for k, v in parsed.items()
                ]
            entry["examples"] = [{"kind": "message", "format": "json", "value": parsed, "source": "official"}]
        entry["responses"] = [{"transport": "websocket", "description": "Application callback consumes the pushed message."}]
        entries.append(entry)
    return entries


JSBRIDGE_MODULE_MAP = {
    "设备上云": "thing",
    "直播": "live",
    "地图元素": "map",
    "航线": "wayline",
    "概述": "overview",
}


def parse_jsbridge(path: Path, source: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    sections: list[tuple[str, list[str]]] = []
    current_module = "core"
    current_lines: list[str] = []
    for line in lines:
        if line.startswith("## "):
            sections.append((current_module, current_lines))
            key = clean(line[3:]).replace("模块", "").strip()
            resolved = JSBRIDGE_MODULE_MAP.get(key) or slug(key)
            if re.fullmatch(r"[a-f0-9]{12}", resolved or ""):
                raise RuntimeError(
                    f"Unmapped JSBridge section heading {key!r} in {path.name}; "
                    "extend JSBRIDGE_MODULE_MAP instead of emitting a hash module"
                )
            current_module = resolved or "core"
            current_lines = []
        else:
            current_lines.append(line)
    sections.append((current_module, current_lines))
    # The overview table summarizes every method; parse it last so semantic
    # sections claim their methods first and the summary only adds the rest.
    sections.sort(key=lambda section: section[0] == "overview")
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for module, section_lines in sections:
        for line in section_lines:
            for match in JS_RE.finditer(line):
                signature = clean(match.group(1))
                method_match = re.search(r"window\.((?:(?:djiBridge|thing)\.)?[A-Za-z0-9_]+)", signature)
                if not method_match:
                    continue
                qualified_method = method_match.group(1)
                method = qualified_method.rsplit(".", 1)[-1]
                if qualified_method in seen:
                    continue
                seen.add(qualified_method)
                before = clean(line[: match.start()].strip("| -0123456789.：:"))
                after = clean(line[match.end() :].strip("| -"))
                eid = f"jsbridge-{slug(qualified_method)}"
                entry = base_entry(eid, "jsbridge", module, before or method, after or before or method, source_ref(path, source))
                entry["operation"] = {"method": f"window.{qualified_method}", "signature": signature}
                args_match = re.search(r"\((.*?)\)", signature)
                args = []
                for raw_arg in (args_match.group(1).split(",") if args_match and args_match.group(1).strip() else []):
                    cleaned_arg = clean(raw_arg)
                    if ":" in cleaned_arg:
                        arg_name, arg_type = (part.strip() for part in cleaned_arg.split(":", 1))
                    else:
                        words = cleaned_arg.split()
                        arg_type = words[0] if len(words) > 1 else "string"
                        arg_name = words[-1] if words else "value"
                    args.append(
                        {
                            "name": arg_name,
                            "in": "argument",
                            "type": normalize_type(arg_type),
                            "required": True,
                            "required_status": "required",
                            "description": after,
                            "constraints": "",
                            "schema": arg_type,
                        }
                    )
                entry["parameters"] = args
                entry["responses"] = [{"type": "string", "description": "JSON string with code, message, and data; parse with JSON.parse when applicable."}]
                entry["errors"] = [{"code": "code != 0", "meaning": "Bridge invocation failed; inspect message.", "retry": False}]
                entries.append(entry)
    return entries


def parse_wpml(path: Path, source: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    entries: list[dict[str, Any]] = []
    current_heading = path.stem
    id_counts: dict[str, int] = {}
    for i, line in enumerate(lines):
        if line.startswith("#"):
            current_heading = clean(line.lstrip("# "))
        if not line.lstrip().startswith("|") or i + 1 >= len(lines) or "---" not in lines[i + 1]:
            continue
        rows = table_after(lines, i)
        for row in rows:
            name = row.get("元素") or row.get("element") or row.get("name") or row.get("参数") or ""
            name = clean(name)
            if not name:
                continue
            context = slug(current_heading)
            base_id = f"wpml-{slug(path.stem.split('.', 1)[-1])}-{context}-{slug(name)}"
            id_counts[base_id] = id_counts.get(base_id, 0) + 1
            eid = base_id if id_counts[base_id] == 1 else f"{base_id}-{id_counts[base_id]}"
            purpose = row.get("说明") or row.get("description") or row.get("名称") or current_heading
            entry = base_entry(eid, "wpml", slug(path.stem.split(".", 1)[-1]), name, purpose, source_ref(path, source))
            entry["operation"] = {"action": "define_element", "element": name, "document": path.name, "context": current_heading}
            entry["parameters"] = [parameter(row, "xml_element")]
            models = clean(row.get("支持机型") or row.get("适用机型") or "")
            if models and models != "-":
                entry["compatibility"] = [item.strip() for item in re.split(r"[,，、]", models) if item.strip() and item.strip() != "-"]
            entry["responses"] = [{"type": "validated_xml", "description": "A locally validated WPML/KML document."}]
            entry["errors"] = [{"code": "validation_error", "meaning": "Element violates required type, range, order, or compatibility constraint.", "retry": False}]
            entries.append(entry)
    return entries


def deduplicate(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for entry in entries:
        key = entry["id"]
        if key not in merged:
            merged[key] = entry
            continue
        existing = merged[key]
        semantic_fields = ("operation", "parameters", "responses", "errors")
        if any(existing[field] != entry[field] for field in semantic_fields):
            digest = hashlib.sha256(
                json.dumps(
                    {
                        "source": entry["source"]["file"],
                        **{field: entry[field] for field in semantic_fields},
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()[:8]
            entry["id"] = f"{key}-{digest}"
            merged[entry["id"]] = entry
            continue
        existing["compatibility"] = sorted(set(existing["compatibility"] + entry["compatibility"]))
        existing.setdefault("alternate_sources", []).append(entry["source"])
        if not existing["examples"] and entry["examples"]:
            existing["examples"] = entry["examples"]
        if len(entry["parameters"]) > len(existing["parameters"]):
            existing["parameters"] = entry["parameters"]
    return sorted(merged.values(), key=lambda x: x["id"])


def source_candidate_metrics(source: Path) -> dict[str, int]:
    api = source / CN_API
    http_operations: set[tuple[str, str]] = set()
    websocket_messages = 0
    wpml_rows = 0
    mqtt_methods: set[str] = set()
    mqtt_property_rows = 0
    js_signatures: set[str] = set()
    for path in api.rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        posix = path.as_posix()
        if "/10.https/" in posix:
            http_operations.update((method.upper(), url) for method, url in HTTP_RE.findall(text))
        if "/20.websocket/" in posix:
            websocket_messages += len(re.findall(r"(?m)^#{2,4}\s+Message\s+`[^`]+`\s*$", text))
        if "/00.dji-wpml/" in posix:
            lines = text.splitlines()
            for i, line in enumerate(lines):
                if line.lstrip().startswith("|") and "元素" in line and i + 1 < len(lines) and "---" in lines[i + 1]:
                    wpml_rows += len(table_after(lines, i))
        if "/00.mqtt/" in posix:
            mqtt_methods.update(METHOD_RE.findall(text))
            if "properties" in path.name:
                lines = text.splitlines()
                for i, line in enumerate(lines):
                    if line.lstrip().startswith("|") and "Column" in line and i + 1 < len(lines) and "---" in lines[i + 1]:
                        mqtt_property_rows += len(table_after(lines, i))
        if path.name == "30.jsbridge.md":
            js_signatures.update(clean(match.group(1)) for match in JS_RE.finditer(text))
    return {
        "http_operations": len(http_operations),
        "websocket_messages": websocket_messages,
        "wpml_field_rows": wpml_rows,
        "mqtt_method_identifiers": len(mqtt_methods),
        "mqtt_property_rows": mqtt_property_rows,
        "jsbridge_signatures": len(js_signatures),
    }


def example_value(param: dict[str, Any]) -> Any:
    if param["type"] == "integer":
        return 0
    if param["type"] == "number":
        return 0.0
    if param["type"] == "boolean":
        return True
    if param["type"] == "array":
        return []
    if param["type"] == "object":
        return {}
    return f"<{param['name']}>"


def add_core_examples(entries: list[dict[str, Any]]) -> None:
    core_tokens = ("device", "organization", "bind", "live", "wayline", "flighttask", "media", "file", "firmware", "upgrade")
    for entry in entries:
        if not any(token in f"{entry['id']} {entry['module']}" for token in core_tokens):
            continue
        args = {p["name"]: example_value(p) for p in entry["parameters"] if p["required"] or len(entry["parameters"]) <= 4}
        if entry["protocol"] == "mqtt":
            request = {
                "bid": "00000000-0000-0000-0000-000000000000",
                "data": args,
                "method": entry["operation"].get("method"),
                "tid": "00000000-0000-0000-0000-000000000000",
                "timestamp": 0,
            }
            response = {
                "bid": request["bid"],
                "data": {"result": 0},
                "method": request["method"],
                "tid": request["tid"],
                "timestamp": 0,
            }
        elif entry["protocol"] == "http":
            request = args
            response = {"code": 0, "message": "success", "data": {}}
        elif entry["protocol"] == "jsbridge":
            request = {"method": entry["operation"].get("method"), "arguments": list(args.values())}
            response = {"code": 0, "message": "success", "data": None}
        else:
            request = args
            response = {"status": "accepted"}
        generated = [
            {"kind": "request", "format": "json", "value": request, "source": "generated_from_schema"},
            {"kind": "response", "format": "json", "value": response, "source": "generated_from_schema"},
        ]
        kinds = {example["kind"] for example in entry["examples"]}
        for example in generated:
            if len(entry["examples"]) >= 2:
                break
            if example["kind"] not in kinds:
                entry["examples"].append(example)
                kinds.add(example["kind"])
        while len(entry["examples"]) < 2:
            entry["examples"].append(generated[len(entry["examples"])])


def deep_changes(old: Any, new: Any, path: str = "") -> list[dict[str, Any]]:
    if type(old) is not type(new):
        return [{"field": path or "$", "old": old, "new": new}]
    if isinstance(old, dict):
        changes: list[dict[str, Any]] = []
        for key in sorted(set(old) | set(new)):
            child_path = f"{path}.{key}" if path else key
            if key not in old:
                changes.append({"field": child_path, "old": None, "new": new[key]})
            elif key not in new:
                changes.append({"field": child_path, "old": old[key], "new": None})
            else:
                changes.extend(deep_changes(old[key], new[key], child_path))
        return changes
    if isinstance(old, list):
        changes = []
        for index in range(max(len(old), len(new))):
            child_path = f"{path}[{index}]"
            if index >= len(old):
                changes.append({"field": child_path, "old": None, "new": new[index]})
            elif index >= len(new):
                changes.append({"field": child_path, "old": old[index], "new": None})
            else:
                changes.extend(deep_changes(old[index], new[index], child_path))
        return changes
    return [] if old == new else [{"field": path or "$", "old": old, "new": new}]


def operation_identity(entry: dict[str, Any]) -> str:
    return json.dumps(
        {
            "protocol": entry["protocol"],
            "operation": entry["operation"],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def build_change_report(
    old_entries: list[dict[str, Any]],
    entries: list[dict[str, Any]],
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    old_by_id = {entry["id"]: entry for entry in old_entries}
    new_by_id = {entry["id"]: entry for entry in entries}
    common = sorted(set(old_by_id) & set(new_by_id))
    tracked_fields = (
        "name",
        "purpose",
        "module",
        "operation",
        "parameters",
        "responses",
        "errors",
        "authentication",
        "compatibility",
        "deprecated",
    )
    modified = []
    for entry_id in common:
        old = {field: old_by_id[entry_id].get(field) for field in tracked_fields}
        new = {field: new_by_id[entry_id].get(field) for field in tracked_fields}
        changes = deep_changes(old, new)
        if changes:
            modified.append(
                {
                    "id": entry_id,
                    "changes": changes,
                    "evidence": new_by_id[entry_id]["source"],
                    "confidence": 1.0,
                }
            )

    added_ids = set(new_by_id) - set(old_by_id)
    removed_ids = set(old_by_id) - set(new_by_id)
    old_operations: dict[str, list[str]] = {}
    for entry_id in removed_ids:
        old_operations.setdefault(operation_identity(old_by_id[entry_id]), []).append(entry_id)
    renamed = []
    for new_id in sorted(list(added_ids)):
        candidates = old_operations.get(operation_identity(new_by_id[new_id]), [])
        old_id = next((candidate for candidate in candidates if candidate in removed_ids), None)
        if not old_id:
            continue
        renamed.append(
            {
                "old_id": old_id,
                "new_id": new_id,
                "changes": deep_changes(
                    {field: old_by_id[old_id].get(field) for field in tracked_fields},
                    {field: new_by_id[new_id].get(field) for field in tracked_fields},
                ),
                "evidence": new_by_id[new_id]["source"],
                "confidence": 0.95,
            }
        )
        added_ids.remove(new_id)
        removed_ids.remove(old_id)

    added = [
        {"id": entry_id, "entry": new_by_id[entry_id], "evidence": new_by_id[entry_id]["source"], "confidence": 1.0}
        for entry_id in sorted(added_ids)
    ]
    removed = [
        {
            "id": entry_id,
            "entry": old_by_id[entry_id],
            "reason": "Not present in the official v1.16.1 API Reference snapshot.",
            "confidence": 1.0,
        }
        for entry_id in sorted(removed_ids)
    ]
    return {
        "source_priority": "DJI official Cloud API tutorial",
        "official_version": snapshot["version"],
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "generated_at": snapshot["fetched_at"],
        "baseline": {
            "source": "existing catalog before official migration",
            "entry_count": len(old_entries),
            "ids": sorted(old_by_id),
        },
        "summary": {
            "added": len(added),
            "removed": len(removed),
            "renamed": len(renamed),
            "modified": len(modified),
            "unchanged": len(common) - len(modified),
        },
        "added": added,
        "removed": removed,
        "renamed": renamed,
        "modified": modified,
    }


def write_outputs(entries: list[dict[str, Any]], source: Path) -> None:
    add_core_examples(entries)
    catalog = ROOT / "catalog"
    endpoint_root = catalog / "endpoints"
    old_entries = []
    if endpoint_root.exists():
        old_entries = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(endpoint_root.rglob("*.json"))
        ]
    snapshot = source_snapshot(source)
    report_path = catalog / "change-report.json"
    existing_report = (
        json.loads(report_path.read_text(encoding="utf-8"))
        if report_path.exists()
        else None
    )
    if (
        existing_report
        and existing_report.get("official_version") == snapshot["version"]
        and existing_report.get("baseline", {}).get("source") == "existing catalog before official migration"
    ):
        existing_report["snapshot_sha256"] = snapshot["snapshot_sha256"]
        existing_report["generated_at"] = snapshot["fetched_at"]
        actual = {entry["id"]: entry for entry in entries}
        baseline_ids = set(existing_report["baseline"].get("ids", []))
        if not baseline_ids:
            try:
                baseline_index = json.loads(
                    subprocess.check_output(
                        ["git", "show", "HEAD:catalog/index.json"],
                        cwd=ROOT,
                        text=True,
                        encoding="utf-8",
                    )
                )
                baseline_ids = {item["id"] for item in baseline_index}
            except Exception:
                baseline_ids = {
                    item["id"] for item in existing_report.get("removed", [])
                } | {
                    item["old_id"] for item in existing_report.get("renamed", [])
                } | {
                    item["id"] for item in existing_report.get("modified", [])
                }
            existing_report["baseline"]["ids"] = sorted(baseline_ids)
        existing_report["renamed"] = [
            {
                **item,
                "evidence": actual[item["new_id"]]["source"],
            }
            for item in existing_report["renamed"]
            if (
                item["new_id"] in actual
                and item["new_id"] not in baseline_ids
                and item["old_id"] not in actual
            )
        ]
        renamed_new = {item["new_id"] for item in existing_report["renamed"]}
        added_ids = set(actual) - baseline_ids - renamed_new
        existing_report["added"] = [
            {
                "id": entry_id,
                "entry": actual[entry_id],
                "evidence": actual[entry_id]["source"],
                "confidence": 1.0,
            }
            for entry_id in sorted(added_ids)
        ]
        existing_report["modified"] = [
            {
                **item,
                "evidence": actual[item["id"]]["source"],
            }
            for item in existing_report["modified"]
            if item["id"] in actual and item["id"] in baseline_ids
        ]
        renamed_old = {item["old_id"] for item in existing_report["renamed"]}
        removed_ids = baseline_ids - set(actual) - renamed_old
        previous_removed = {item["id"]: item for item in existing_report["removed"]}
        existing_report["removed"] = [
            previous_removed.get(
                entry_id,
                {
                    "id": entry_id,
                    "entry": {"id": entry_id},
                    "reason": "Not present in the official v1.16.1 API Reference snapshot.",
                    "confidence": 1.0,
                },
            )
            for entry_id in sorted(removed_ids)
        ]
        summary = existing_report["summary"]
        summary.update(
            {
                "added": len(existing_report["added"]),
                "removed": len(existing_report["removed"]),
                "renamed": len(existing_report["renamed"]),
                "modified": len(existing_report["modified"]),
            }
        )
        summary["unchanged"] = (
            len(
                (baseline_ids & set(actual))
                - {item["id"] for item in existing_report["modified"]}
            )
        )
        change_report = existing_report
    else:
        change_report = build_change_report(old_entries, entries, snapshot)
    if endpoint_root.exists():
        shutil.rmtree(endpoint_root)
    endpoint_root.mkdir(parents=True)
    counts: dict[str, int] = {}
    index: list[dict[str, Any]] = []
    for entry in entries:
        folder = endpoint_root / entry["protocol"]
        folder.mkdir(parents=True, exist_ok=True)
        rel = Path("catalog/endpoints") / entry["protocol"] / f"{entry['id']}.json"
        write_text_lf(ROOT / rel, json.dumps(entry, ensure_ascii=False, indent=2) + "\n")
        counts[entry["protocol"]] = counts.get(entry["protocol"], 0) + 1
        index.append({"id": entry["id"], "name": entry["name"], "protocol": entry["protocol"], "module": entry["module"], "file": rel.as_posix()})
    write_text_lf(catalog / "index.json", json.dumps(index, ensure_ascii=False, indent=2) + "\n")

    error_source = source / "docs/cn/71.error-code.md"
    error_text = error_source.read_text(encoding="utf-8")
    errors = []
    for line in error_text.splitlines():
        if line.startswith("|") and not line.startswith("|---"):
            cells = [clean(x) for x in line.strip().strip("|").split("|")]
            if cells and re.fullmatch(r"-?\d+(?:\.\d+)?", cells[0]):
                errors.append({"code": cells[0], "description": cells[-1], "source": source_ref(error_source, source)})
    for row in re.findall(r"<tr>(.*?)</tr>", error_text, re.S | re.I):
        cells = [clean(re.sub(r"<[^>]+>", "", cell)) for cell in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S | re.I)]
        if len(cells) >= 2 and re.fullmatch(r"\d{6}", cells[0]):
            errors.append({"code": cells[0], "description": cells[1], "source": source_ref(error_source, source)})
    unique_errors = {
        (item["code"], item["description"]): item
        for item in errors
    }
    write_text_lf(
        catalog / "error-codes.json",
        json.dumps(list(unique_errors.values()), ensure_ascii=False, indent=2) + "\n",
    )
    write_text_lf(
        report_path,
        json.dumps(change_report, ensure_ascii=False, indent=2) + "\n",
    )

    manifest = {
        "source": snapshot["source"],
        "official_version": snapshot["version"],
        "version_evidence_url": snapshot["version_evidence_url"],
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "app_hash": snapshot["app"]["hash"],
        "runtime_hash": snapshot["runtime"]["hash"],
        "api_reference_route_count": snapshot["route_count"],
        "source_language": "cn",
        "generated_at": snapshot["fetched_at"],
        "generator": "scripts/sync_catalog.py",
        "entry_count": len(entries),
        "protocol_counts": counts,
        "portable_skill": {
            "source_path": "skills/dji-cloud-api",
            "build_path": "build/skills/dji-cloud-api",
            "standard": "https://agentskills.io/specification",
            "supported_project_targets": {
                "cursor": ".cursor/skills",
                "codex": ".agents/skills",
                "claude": ".claude/skills",
                "codebuddy": ".codebuddy/skills",
                "workbuddy": ".workbuddy/skills",
                "copilot": ".github/skills",
                "antigravity": ".agent/skills",
                "gemini": ".gemini/skills",
            },
        },
    }
    write_text_lf(ROOT / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")


def collect(source: Path) -> list[dict[str, Any]]:
    api = source / CN_API
    entries: list[dict[str, Any]] = []
    for path in sorted(api.rglob("*.md")):
        posix = path.as_posix()
        if "/10.https/" in posix:
            entries.extend(parse_http(path, source))
        if "/00.mqtt/" in posix:
            entries.extend(parse_mqtt(path, source))
            entries.extend(parse_mqtt_properties(path, source))
        if "/20.websocket/" in posix:
            entries.extend(parse_websocket(path, source))
        if path.name == "30.jsbridge.md":
            entries.extend(parse_jsbridge(path, source))
        if "/00.dji-wpml/" in posix and path.name != "10.overview.md":
            entries.extend(parse_wpml(path, source))
    return deduplicate(entries)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    args = parser.parse_args()
    source = args.source.resolve()
    if not (source / "snapshot.json").exists() or not (source / CN_API).exists():
        raise SystemExit(
            f"DJI official snapshot not found under {source}; "
            "run scripts/fetch_official_docs.py first"
        )
    snapshot = source_snapshot(source)
    if snapshot.get("version") != "1.16.1":
        raise SystemExit(f"Expected DJI Cloud API v1.16.1, found v{snapshot.get('version', 'unknown')}")
    entries = collect(source)
    if not entries:
        raise SystemExit("No API entries parsed")
    write_outputs(entries, source)
    print(f"Generated {len(entries)} entries from official v{snapshot['version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
