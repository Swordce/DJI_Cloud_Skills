#!/usr/bin/env python3
"""Build portable skill bundles and platform tool adapters from catalog/.

Publishing convention: the portable skill package (build/skills/dji-cloud-api)
is the single canonical publisher of full tool files (assets/*.json); dist/
carries only the module shards and their registry. The catalog-id to tool-name
mapping is derivable via tool_name(entry_id) and is not serialized separately.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog"
BUILD = ROOT / "build"
SKILL_SOURCE = ROOT / "skills/dji-cloud-api"
PACKAGE = BUILD / "skills/dji-cloud-api"
DIST = BUILD / "dist"
PROTOCOLS = ("http", "mqtt", "websocket", "jsbridge", "wpml")


def load_entries() -> list[dict[str, Any]]:
    entries = []
    for path in sorted((CATALOG / "endpoints").rglob("*.json")):
        with path.open(encoding="utf-8") as handle:
            entries.append(json.load(handle))
    return entries


def slug(value: str) -> str:
    value = value.lower().replace("_", "-").replace(".", "-")
    value = re.sub(r"[^a-z0-9-]+", "-", value)
    return re.sub(r"-+", "-", value).strip("-") or hashlib.sha1(value.encode()).hexdigest()[:12]


def tool_name(entry_id: str) -> str:
    raw = "dji_" + entry_id.replace("-", "_")
    if len(raw) <= 64:
        return raw
    return f"{raw[:55]}_{hashlib.sha1(raw.encode()).hexdigest()[:8]}"


def tool_input_schema(entry: dict[str, Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    for parameter in entry["parameters"]:
        raw_name = f"{parameter['parent']}_{parameter['name']}" if parameter.get("parent") else parameter["name"]
        name = re.sub(r"[^A-Za-z0-9_]", "_", raw_name).strip("_")
        if not name or name in properties:
            continue
        spec: dict[str, Any] = {
            "type": parameter["type"],
            "description": parameter["description"] or parameter["constraints"] or parameter["name"],
        }
        if parameter["type"] == "array":
            spec["items"] = {}
        properties[name] = spec
        if parameter["required"]:
            required.append(name)
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def build_tools(entries: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    openai: list[dict[str, Any]] = []
    claude: list[dict[str, Any]] = []
    for entry in entries:
        description = (
            f"{entry['purpose']} [{entry['protocol']}; {entry['id']}]. "
            f"Authentication: {entry['authentication']['type']}. "
            "See the skill catalog for response and retry semantics."
        )
        schema = tool_input_schema(entry)
        name = tool_name(entry["id"])
        openai.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description[:1024],
                    "parameters": schema,
                },
            }
        )
        claude.append({"name": name, "description": description, "input_schema": schema})
    return openai, claude


def write_json(path: Path, value: Any, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if compact:
        content = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    else:
        content = json.dumps(value, ensure_ascii=False, indent=2)
    path.write_text(content + "\n", encoding="utf-8")


def chunks(items: list[Any], size: int = 100) -> list[list[Any]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def build_skill(entries: list[dict[str, Any]], openai: list[dict[str, Any]], claude: list[dict[str, Any]]) -> None:
    if PACKAGE.exists():
        shutil.rmtree(PACKAGE)
    shutil.copytree(
        SKILL_SOURCE,
        PACKAGE,
        ignore=shutil.ignore_patterns("references", "assets", "__pycache__", "*.pyc"),
    )
    groups: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        group = f"{entry['protocol']}-{entry['module']}"
        groups.setdefault(group, []).append(entry)
    reference_index = []
    for group, group_entries in sorted(groups.items()):
        parts = chunks(group_entries)
        for part_index, part_entries in enumerate(parts, start=1):
            suffix = f"-{part_index:02d}" if len(parts) > 1 else ""
            filename = f"{slug(group)}{suffix}.json"
            write_json(PACKAGE / "references" / filename, part_entries, compact=True)
            reference_index.append(
                {
                    "group": group,
                    "protocol": part_entries[0]["protocol"],
                    "module": part_entries[0]["module"],
                    "file": filename,
                    "entry_count": len(part_entries),
                    "entries": [
                        {
                            "id": entry["id"],
                            "name": entry["name"],
                            "purpose": entry["purpose"],
                        }
                        for entry in part_entries
                    ],
                }
            )
    write_json(PACKAGE / "references/index.json", reference_index, compact=True)
    shutil.copy2(CATALOG / "error-codes.json", PACKAGE / "references/error-codes.json")
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    change_report = json.loads((CATALOG / "change-report.json").read_text(encoding="utf-8"))
    write_json(PACKAGE / "references/source-manifest.json", manifest, compact=True)
    write_json(
        PACKAGE / "references/change-report-summary.json",
        {
            "source_priority": change_report["source_priority"],
            "official_version": change_report["official_version"],
            "snapshot_sha256": change_report["snapshot_sha256"],
            "baseline": change_report["baseline"],
            "summary": change_report["summary"],
        },
        compact=True,
    )
    write_json(PACKAGE / "assets/openai-tools.json", openai, compact=True)
    write_json(PACKAGE / "assets/claude-tools.json", claude, compact=True)


def build_dist(entries: list[dict[str, Any]], openai: list[dict[str, Any]], claude: list[dict[str, Any]]) -> None:
    if DIST.exists():
        shutil.rmtree(DIST)
    for platform, tools in (("openai", openai), ("claude", claude)):
        grouped: dict[str, list[dict[str, Any]]] = {}
        for entry, tool in zip(entries, tools):
            grouped.setdefault(f"{entry['protocol']}-{entry['module']}", []).append(tool)
        registry = []
        for group, group_tools in sorted(grouped.items()):
            parts = chunks(group_tools)
            for part_index, part_tools in enumerate(parts, start=1):
                suffix = f"-{part_index:02d}" if len(parts) > 1 else ""
                filename = f"{slug(group)}{suffix}.json"
                write_json(DIST / platform / "by-module" / filename, part_tools)
                registry.append({"group": group, "file": f"by-module/{filename}", "tool_count": len(part_tools)})
        write_json(DIST / platform / "index.json", registry)


def main() -> int:
    entries = load_entries()
    if not entries:
        raise SystemExit("catalog/endpoints contains no entries; run sync_catalog.py first")
    openai, claude = build_tools(entries)
    build_skill(entries, openai, claude)
    build_dist(entries, openai, claude)
    print(f"Built portable skill and adapters for {len(entries)} entries under {BUILD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
