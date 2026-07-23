#!/usr/bin/env python3
"""Generate a structured DJI Cloud API catalog and agent tool adapters."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / ".upstream"
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


def slug(value: str) -> str:
    value = value.lower().replace("_", "-").replace(".", "-")
    value = re.sub(r"[^a-z0-9-]+", "-", value)
    return re.sub(r"-+", "-", value).strip("-") or hashlib.sha1(value.encode()).hexdigest()[:12]


def source_ref(path: Path, source: Path) -> dict[str, str]:
    rel = path.relative_to(source).as_posix()
    return {
        "file": rel,
        "url": f"https://github.com/dji-sdk/Cloud-API-Doc/blob/master/{rel}",
    }


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


def normalize_type(value: str) -> str:
    value = clean(value).lower()
    if any(x in value for x in ("int", "number", "float", "double", "enum_int")):
        return "number" if any(x in value for x in ("float", "double", "number")) else "integer"
    if "bool" in value:
        return "boolean"
    if "array" in value or value.startswith("["):
        return "array"
    if "object" in value or "json" in value:
        return "object"
    return "string"


def parameter(row: dict[str, str], default_location: str = "payload") -> dict[str, Any]:
    name = row.get("column") or row.get("参数名") or row.get("元素") or row.get("name")
    name = clean(name).lstrip("»›>- ")
    location = clean(row.get("in") or row.get("参数位置") or default_location).lower()
    if not name and location == "body":
        name = "body"
    required_raw = row.get("required") or row.get("必填") or ""
    required = required_raw.lower() in {"true", "yes", "是", "required"} if required_raw else None
    constraint = row.get("constraint") or row.get("restrictions") or row.get("范围") or ""
    description = row.get("description") or row.get("说明") or row.get("name") or ""
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


def unique_parameters(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not item["name"] or item["name"] in seen:
            continue
        seen.add(item["name"])
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
    module = slug(path.parent.name.split(".", 1)[-1])
    for n, match in enumerate(matches):
        method, url_path = match.group(1).upper(), match.group(2)
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
        blocks = code_blocks(text[match.start() : matches[n + 1].start() if n + 1 < len(matches) else len(text)])
        for lang, body in blocks:
            parsed = parse_jsonish(body) if lang.lower() in {"json", ""} else None
            if parsed is not None:
                kind = "response" if isinstance(parsed, dict) and "code" in parsed else "request"
                entry["examples"].append({"kind": kind, "format": "json", "value": parsed, "source": "official"})
                if len(entry["examples"]) >= 2:
                    break
        entry["errors"] = [
            {"code": "400", "meaning": "invalid_request", "retry": False},
            {"code": "401", "meaning": "token_expired_or_invalid", "retry": False},
            {"code": "403", "meaning": "forbidden", "retry": False},
            {"code": "404", "meaning": "resource_not_found", "retry": False},
            {"code": "5xx", "meaning": "server_error", "retry": method in {"GET", "PUT", "DELETE"}},
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
    device = "pilot" if "pilot-to-cloud" in path.as_posix() else ("dock2" if "dock2" in path.as_posix() else "dock1")
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
        eid = f"mqtt-{slug(method)}"
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
        entry["parameters"] = unique_parameters(parameter(row) for row in rows if row.get("column") or row.get("name"))
        blocks = code_blocks(chunk)
        for lang, body in blocks[:2]:
            parsed = parse_jsonish(body)
            if parsed is not None:
                entry["examples"].append(
                    {
                        "kind": "reply" if isinstance(parsed, dict) and "_reply" in (topics[min(len(entry["examples"]), len(topics) - 1)] if topics else "") else "request",
                        "format": "json",
                        "value": parsed,
                        "source": "official",
                    }
                )
        entry["responses"] = [{"transport": "mqtt", "topic": topics[1] if len(topics) > 1 else topic, "correlation": ["tid", "bid", "method"]}]
        entry["errors"] = [{"code": "data.result != 0", "meaning": "See catalog/error-codes.json", "retry": False}]
        entry["compatibility"] = [device]
        entry["retry"] = retry_policy("mqtt", eid, "")
        entries.append(entry)
    return entries


def parse_mqtt_properties(path: Path, source: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if "properties" not in path.name:
        return []
    device = "pilot" if "pilot-to-cloud" in path.as_posix() else ("dock2" if "dock2" in path.as_posix() else "dock1")
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
    for row in table:
        prop = row.get("column") or row.get("property") or row.get("参数") or row.get("属性") or ""
        prop = clean(prop)
        if not prop or prop in seen or prop.lower() in {"column", "name"}:
            continue
        seen.add(prop)
        eid = f"mqtt-property-{slug(prop)}"
        entry = base_entry(eid, "mqtt", module, prop, row.get("description") or row.get("name") or prop, source_ref(path, source))
        entry["operation"] = {
            "action": "subscribe",
            "topic": topics[0] if topics else "thing/product/{device_sn}/state|osd",
            "direction": "up",
            "method": "property_report",
        }
        p = parameter(row)
        p["name"] = prop
        entry["parameters"] = [p]
        entry["responses"] = [{"transport": "mqtt", "payload_field": f"data.{prop}"}]
        entry["compatibility"] = [device]
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
        entry["parameters"] = unique_parameters(
            parameter(row, "message")
            for row in payload_rows
            if row.get("name") and row.get("name") != "(root)"
        )
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


def parse_jsbridge(path: Path, source: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    entries: list[dict[str, Any]] = []
    current_module = "core"
    seen: set[str] = set()
    for i, line in enumerate(lines):
        if line.startswith("## "):
            current_module = slug(clean(line[3:]).replace("模块", "")) or "core"
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
            entry = base_entry(eid, "jsbridge", current_module, before or method, after or before or method, source_ref(path, source))
            entry["operation"] = {"method": f"window.{qualified_method}", "signature": signature}
            args_match = re.search(r"\((.*?)\)", signature)
            args = []
            for raw_arg in (args_match.group(1).split(",") if args_match and args_match.group(1).strip() else []):
                words = clean(raw_arg).replace(":", " ").split()
                arg_name = words[-1] if words else "value"
                arg_type = words[0] if len(words) > 1 else "string"
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
            entry = base_entry(eid, "wpml", slug(path.stem.split(".", 1)[-1]), name, row.get("说明") or row.get("description") or current_heading, source_ref(path, source))
            entry["operation"] = {"action": "define_element", "element": name, "document": path.name, "context": current_heading}
            entry["parameters"] = [parameter(row, "xml_element")]
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


def write_outputs(entries: list[dict[str, Any]], source: Path, commit: str) -> None:
    add_core_examples(entries)
    catalog = ROOT / "catalog"
    endpoint_root = catalog / "endpoints"
    if endpoint_root.exists():
        shutil.rmtree(endpoint_root)
    endpoint_root.mkdir(parents=True)
    counts: dict[str, int] = {}
    index: list[dict[str, Any]] = []
    for entry in entries:
        folder = endpoint_root / entry["protocol"]
        folder.mkdir(parents=True, exist_ok=True)
        rel = Path("catalog/endpoints") / entry["protocol"] / f"{entry['id']}.json"
        (ROOT / rel).write_text(json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        counts[entry["protocol"]] = counts.get(entry["protocol"], 0) + 1
        index.append({"id": entry["id"], "name": entry["name"], "protocol": entry["protocol"], "module": entry["module"], "file": rel.as_posix()})
    (catalog / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

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
    (catalog / "error-codes.json").write_text(json.dumps(errors, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    manifest = {
        "source": "https://github.com/dji-sdk/Cloud-API-Doc",
        "commit": commit,
        "source_language": "docs/cn",
        "fallback_language": "docs/en",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
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
    (ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def git_commit(source: Path) -> str:
    try:
        return subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    args = parser.parse_args()
    source = args.source.resolve()
    if not (source / CN_API).exists():
        raise SystemExit(f"DJI source docs not found under {source}")
    entries = collect(source)
    if not entries:
        raise SystemExit("No API entries parsed")
    write_outputs(entries, source, git_commit(source))
    print(f"Generated {len(entries)} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
