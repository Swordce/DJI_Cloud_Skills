#!/usr/bin/env python3
"""Validate generated DJI Cloud API catalog completeness and adapters."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_HOST = "https://developer.dji.com/doc/cloud-api-tutorial/cn/"
NON_INTERFACE_ROUTES = {
    "/cn/api-reference/dji-wpml/overview.html": "WPML explanatory overview; contains no operation or element table.",
    "/cn/api-reference/dock-to-cloud/mqtt/topic-definition.html": "MQTT topic convention reference; contains no method operation.",
    "/cn/api-reference/pilot-to-cloud/mqtt/topic-definition.html": "MQTT topic convention reference; contains no method operation.",
}
HASH_MODULE_RE = re.compile(r"^[a-f0-9]{12}$")
# Field-completeness baselines measured on the official v1.16.1 snapshot
# (http 1.00, mqtt 0.9986, websocket 1.00, wpml 1.00, jsbridge 0.53).
# A parser degradation trips these fail-closed; lowering a baseline requires
# a recorded entry in coverage-report known_source_exceptions.
MIN_PARAM_DESCRIPTION_RATIO = {
    "http": 0.95,
    "mqtt": 0.99,
    "websocket": 0.95,
    "wpml": 1.0,
    "jsbridge": 0.5,
}


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_text_lf(path: Path, content: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)


def matches_type(value: Any, expected: str) -> bool:
    return {
        "object": lambda: isinstance(value, dict),
        "array": lambda: isinstance(value, list),
        "string": lambda: isinstance(value, str),
        "integer": lambda: isinstance(value, int) and not isinstance(value, bool),
        "number": lambda: isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": lambda: isinstance(value, bool),
        "null": lambda: value is None,
    }.get(expected, lambda: True)()


def validate_schema(value: Any, schema: dict[str, Any], location: str, errors: list[str]) -> None:
    expected_types = schema.get("type")
    if expected_types:
        expected_types = [expected_types] if isinstance(expected_types, str) else expected_types
        if not any(matches_type(value, expected) for expected in expected_types):
            errors.append(f"{location}: expected type {expected_types}")
            return
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{location}: value {value!r} is not in {schema['enum']}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{location}: string is shorter than minLength")
        if schema.get("pattern") and not re.fullmatch(schema["pattern"], value):
            errors.append(f"{location}: value does not match {schema['pattern']}")
    if isinstance(value, dict):
        missing = [name for name in schema.get("required", []) if name not in value]
        if missing:
            errors.append(f"{location}: missing required properties {missing}")
        if len(value) < schema.get("minProperties", 0):
            errors.append(f"{location}: object has fewer than minProperties")
        for name, child_schema in schema.get("properties", {}).items():
            if name in value:
                validate_schema(value[name], child_schema, f"{location}.{name}", errors)
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            validate_schema(item, schema["items"], f"{location}[{index}]", errors)


def load_generator():
    path = ROOT / "scripts/sync_catalog.py"
    spec = importlib.util.spec_from_file_location("sync_catalog", path)
    if not spec or not spec.loader:
        raise RuntimeError("Cannot import sync_catalog.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digests() -> dict[str, str]:
    roots = [ROOT / "catalog", ROOT / "build"]
    result: dict[str, str] = {}
    for folder in roots:
        for path in sorted(folder.rglob("*.json")):
            result[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def validate_entry(
    entry: dict[str, Any],
    path: Path,
    schema: dict[str, Any],
    source: Path,
    snapshot: dict[str, Any],
    errors: list[str],
) -> None:
    validate_schema(entry, schema, str(path), errors)
    if path.stem != entry["id"]:
        errors.append(f"{path}: filename does not match id")
    if HASH_MODULE_RE.fullmatch(entry["module"]):
        errors.append(f"{path}: module is a hash fallback; assign a semantic module")
    names = set()
    for parameter in entry["parameters"]:
        key = (parameter.get("parent"), parameter.get("name"))
        if key in names:
            errors.append(f"{path}: duplicate parameter {parameter.get('name')}")
        names.add(key)
    if entry["protocol"] == "http":
        if not entry["operation"].get("method") or not entry["operation"].get("path"):
            errors.append(f"{path}: HTTP operation lacks method/path")
        if entry["authentication"].get("name") != "X-Auth-Token":
            errors.append(f"{path}: HTTP token header mismatch")
    if entry["protocol"] == "mqtt":
        if not entry["operation"].get("topic") or not entry["operation"].get("method"):
            errors.append(f"{path}: MQTT operation lacks topic/method")
    if entry["protocol"] == "jsbridge" and not entry["operation"].get("signature"):
        errors.append(f"{path}: JSBridge operation lacks signature")
    source_file = source / entry["source"].get("file", "")
    if not source_file.exists():
        errors.append(f"{path}: missing source file {source_file}")
        return
    if not entry["source"].get("url", "").startswith(OFFICIAL_HOST):
        errors.append(f"{path}: source URL is not the official Chinese tutorial")
    page = next(
        (item for item in snapshot["pages"] if item["file"] == entry["source"].get("file")),
        None,
    )
    if not page:
        errors.append(f"{path}: source file is absent from the official snapshot")
    else:
        expected = {
            "url": page["source_url"],
            "sha256": page["content_sha256"],
            "asset_sha256": page["asset_sha256"],
            "snapshot_sha256": snapshot["snapshot_sha256"],
            "version": snapshot["version"],
        }
        for name, value in expected.items():
            if entry["source"].get(name) != value:
                errors.append(f"{path}: source {name} does not match the official snapshot")


def validate_tools(entries: list[dict[str, Any]], errors: list[str]) -> None:
    # The portable skill package is the canonical publisher of full tool files.
    openai = load_json(ROOT / "build/skills/dji-cloud-api/assets/openai-tools.json")
    claude = load_json(ROOT / "build/skills/dji-cloud-api/assets/claude-tools.json")
    if len(openai) != len(entries) or len(claude) != len(entries):
        errors.append("Tool adapter counts do not match catalog")
    openai_names = [item.get("function", {}).get("name") for item in openai]
    claude_names = [item.get("name") for item in claude]
    if len(openai_names) != len(set(openai_names)) or len(claude_names) != len(set(claude_names)):
        errors.append("Generated tool names are not unique")
    for item in openai:
        if set(item) != {"type", "function"} or item["type"] != "function":
            errors.append("Invalid OpenAI tool envelope")
            break
        function = item["function"]
        if set(function) != {"name", "description", "parameters"} or len(function["name"]) > 64:
            errors.append(f"Invalid OpenAI function {function.get('name')}")
            break
    for item in claude:
        if set(item) != {"name", "description", "input_schema"} or len(item["name"]) > 64:
            errors.append(f"Invalid Claude tool {item.get('name')}")
            break
    for platform in ("openai", "claude"):
        registry = load_json(ROOT / f"build/dist/{platform}/index.json")
        shard_count = sum(item["tool_count"] for item in registry)
        if shard_count != len(entries):
            errors.append(f"{platform} module shards do not cover the catalog")
        if any(item["tool_count"] > 100 for item in registry):
            errors.append(f"{platform} contains an oversized tool shard")


def validate_portable_skill(entries: list[dict[str, Any]], errors: list[str]) -> None:
    root = ROOT / "build/skills/dji-cloud-api"
    skill_file = root / "SKILL.md"
    if not skill_file.exists():
        errors.append("Portable skill is missing SKILL.md")
        return
    text = skill_file.read_text(encoding="utf-8")
    frontmatter = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not frontmatter:
        errors.append("Portable SKILL.md has invalid frontmatter")
    else:
        metadata = frontmatter.group(1)
        if not re.search(r"(?m)^name:\s*dji-cloud-api\s*$", metadata):
            errors.append("Portable skill name does not match its directory")
        description = re.search(r"(?m)^description:\s*(.+)$", metadata)
        if not description or len(description.group(1)) > 1024:
            errors.append("Portable skill description is missing or too long")
    if len(text.splitlines()) >= 500:
        errors.append("Portable SKILL.md must remain under 500 lines")
    package_files = [path for path in root.rglob("*") if path.is_file() and "__pycache__" not in path.parts]
    if len(package_files) > 500:
        errors.append("Portable skill exceeds the OpenAI hosted-skill 500-file limit")
    reference_index = load_json(root / "references/index.json")
    if sum(group["entry_count"] for group in reference_index) != len(entries):
        errors.append("Portable module references do not cover the catalog")
    for group in reference_index:
        if group["entry_count"] > 100:
            errors.append(f"Portable reference shard is oversized for {group['group']}")
        path = root / "references" / group["file"]
        if not path.exists() or len(load_json(path)) != group["entry_count"]:
            errors.append(f"Portable reference count mismatch for {group['group']}")
    if len(load_json(root / "assets/openai-tools.json")) != len(entries):
        errors.append("Portable OpenAI tools count mismatch")
    if len(load_json(root / "assets/claude-tools.json")) != len(entries):
        errors.append("Portable Claude tools count mismatch")
    if not (root / "scripts/query_catalog.py").exists():
        errors.append("Portable query helper is missing")
    if not (root / "references/source-manifest.json").exists():
        errors.append("Portable official source manifest is missing")
    if not (root / "references/change-report-summary.json").exists():
        errors.append("Portable migration change summary is missing")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=ROOT / ".official-cache")
    parser.add_argument("--check-determinism", action="store_true")
    args = parser.parse_args()
    errors: list[str] = []
    source = args.source.resolve()
    snapshot_path = source / "snapshot.json"
    if not snapshot_path.exists():
        raise SystemExit(f"Official snapshot is missing: {snapshot_path}")
    snapshot = load_json(snapshot_path)
    manifest = load_json(ROOT / "manifest.json")
    expected_version = manifest.get("official_version")
    if snapshot.get("version") != expected_version:
        errors.append(f"Official snapshot version is {snapshot.get('version')}, expected {expected_version}")
    if snapshot.get("route_count", 0) < 100 or snapshot.get("error_page_count") != 1:
        errors.append("Official snapshot route/error-page counts are implausible")
    schema = load_json(ROOT / "catalog/schema.json")
    files = sorted((ROOT / "catalog/endpoints").rglob("*.json"))
    entries = [load_json(path) for path in files]
    ids = [entry.get("id") for entry in entries]
    if len(ids) != len(set(ids)):
        errors.append("Catalog IDs are not unique")
    for entry, path in zip(entries, files):
        validate_entry(entry, path, schema, source, snapshot, errors)

    generator = load_generator()
    expected = generator.collect(source)
    expected_ids = {entry["id"] for entry in expected}
    actual_ids = set(ids)
    if expected_ids != actual_ids:
        errors.append(
            f"Source coverage mismatch: missing={sorted(expected_ids - actual_ids)[:20]}, extra={sorted(actual_ids - expected_ids)[:20]}"
        )

    official_routes = {
        page["route"]: page
        for page in snapshot["pages"]
        if "/api-reference/" in page["route"]
    }
    used_urls = {entry["source"]["url"] for entry in entries}
    uncovered = {
        route
        for route, page in official_routes.items()
        if page["source_url"] not in used_urls
    }
    unexpected_uncovered = uncovered - set(NON_INTERFACE_ROUTES)
    stale_exceptions = set(NON_INTERFACE_ROUTES) - uncovered
    if unexpected_uncovered:
        errors.append(f"Official API pages lack catalog coverage: {sorted(unexpected_uncovered)}")
    if stale_exceptions:
        errors.append(f"Non-interface route exceptions became stale: {sorted(stale_exceptions)}")

    core_tokens = ("device", "organization", "bind", "live", "wayline", "flighttask", "media", "file", "firmware", "upgrade")
    missing_examples = [
        entry["id"]
        for entry in entries
        if any(token in f"{entry['id']} {entry['module']}" for token in core_tokens) and len(entry["examples"]) < 2
    ]
    if missing_examples:
        errors.append(f"Core endpoints without request/response examples: {missing_examples[:20]}")

    if not load_json(ROOT / "catalog/error-codes.json"):
        errors.append("No DJI error codes extracted")
    else:
        for item in load_json(ROOT / "catalog/error-codes.json"):
            if not item["source"]["url"].startswith(OFFICIAL_HOST):
                errors.append("DJI error codes contain a non-official source")
                break
    wpml_entries = [entry for entry in entries if entry["protocol"] == "wpml"]
    if wpml_entries:
        empty_description = [
            entry["id"]
            for entry in wpml_entries
            if not entry["parameters"] or not entry["parameters"][0].get("description")
        ]
        if empty_description:
            errors.append(f"WPML entries missing description: {empty_description[:20]}")
        if all(not entry["compatibility"] for entry in wpml_entries):
            errors.append("WPML entries uniformly lack compatibility; the model-column mapping is broken")
        if all(
            entry["parameters"] and entry["parameters"][0].get("required_status") == "not_specified_by_source"
            for entry in wpml_entries
        ):
            errors.append("WPML required_status is uniformly unspecified; the required-column mapping is broken")
    param_totals: dict[str, list[int]] = {}
    for entry in entries:
        totals = param_totals.setdefault(entry["protocol"], [0, 0])
        for parameter in entry["parameters"]:
            totals[0] += 1
            if parameter.get("description"):
                totals[1] += 1
    for protocol, minimum in MIN_PARAM_DESCRIPTION_RATIO.items():
        total, filled = param_totals.get(protocol, [0, 0])
        if total and filled / total < minimum:
            errors.append(
                f"{protocol} parameter description ratio {filled}/{total} is below the {minimum:.2f} baseline; "
                "fix the parser degradation or record a known_source_exception"
            )
    change_report = load_json(ROOT / "catalog/change-report.json")
    if (
        change_report.get("official_version") != snapshot["version"]
        or change_report.get("snapshot_sha256") != snapshot["snapshot_sha256"]
    ):
        errors.append("Change report is not pinned to the current official snapshot")
    report_new_count = sum(
        change_report["summary"][key]
        for key in ("added", "renamed", "modified", "unchanged")
    )
    if report_new_count != len(entries):
        errors.append(
            f"Change report new-side count {report_new_count} does not match catalog {len(entries)}"
        )
    if (
        manifest.get("official_version") != snapshot["version"]
        or manifest.get("snapshot_sha256") != snapshot["snapshot_sha256"]
        or manifest.get("api_reference_route_count") != snapshot["route_count"]
        or manifest.get("app_hash") != snapshot["app"]["hash"]
        or manifest.get("runtime_hash") != snapshot["runtime"]["hash"]
    ):
        errors.append("manifest.json is not pinned to the current official snapshot")
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/build_artifacts.py")],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    validate_tools(entries, errors)
    validate_portable_skill(entries, errors)

    if args.check_determinism:
        before = digests()
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/sync_catalog.py"), "--source", str(args.source.resolve())],
            cwd=ROOT,
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        )
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/build_artifacts.py")],
            cwd=ROOT,
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        )
        after = digests()
        if before != after:
            changed = sorted(set(before) | set(after))
            changed = [name for name in changed if before.get(name) != after.get(name)]
            errors.append(f"Generation is not deterministic: {changed[:20]}")

    protocol_counts = {
        protocol: sum(entry["protocol"] == protocol for entry in entries)
        for protocol in ("http", "mqtt", "websocket", "jsbridge", "wpml")
    }
    candidates = generator.source_candidate_metrics(source)
    direct_checks = {
        "http": candidates.get("http_operations"),
        "websocket": candidates.get("websocket_messages"),
        "wpml": candidates.get("wpml_field_rows"),
        "jsbridge": candidates.get("jsbridge_signatures"),
    }
    for protocol, expected_count in direct_checks.items():
        actual_count = (
            len(
                {
                    (entry["operation"].get("method"), entry["operation"].get("path"))
                    for entry in entries
                    if entry["protocol"] == "http"
                }
            )
            if protocol == "http"
            else protocol_counts[protocol]
        )
        if expected_count is not None and actual_count != expected_count:
            errors.append(
                f"{protocol} source coverage mismatch: catalog={actual_count}, source_candidates={expected_count}"
            )
    if protocol_counts["mqtt"] < candidates.get("mqtt_method_identifiers", 0):
        errors.append("MQTT catalog contains fewer entries than unique source method identifiers")
    report = {
        "entry_count": len(entries),
        "protocol_counts": protocol_counts,
        "entries_with_examples": sum(bool(entry["examples"]) for entry in entries),
        "entries_without_examples": sum(not entry["examples"] for entry in entries),
        "official_version": snapshot["version"],
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "official_api_reference_routes": snapshot["route_count"],
        "covered_api_reference_routes": len(official_routes) - len(uncovered),
        "non_interface_route_exceptions": NON_INTERFACE_ROUTES,
        "source_markdown_files": len(list((source / generator.CN_API).rglob("*.md"))),
        "source_candidates": candidates,
        "known_source_exceptions": [
            "Several official HTTP examples omit a comma after code; JSON repair is limited to this documented pattern.",
            "The official waypoint cancel page duplicates the endpoint and is deduplicated by method/path.",
            "HTTP anchors/opIds contain copy-paste inconsistencies; the displayed method and path are authoritative.",
            "WebSocket message heading depth differs between map-elements and situation-awareness.",
            "WPML and MQTT property fields are context-scoped because repeated leaf names have different parent semantics.",
            "VuePress property tables use dynamic VNodes and are reconstructed from their compiled table rows.",
        ],
        "notes": [
            "Product variants are isolated; entries merge only when operation, parameters, responses, and errors are identical.",
            "Build artifacts are derived from catalog and are not repository facts.",
            "validate_catalog.py is the sole writer of this report.",
            "The official release history identifies v1.16.1 even though the navbar still displays v1.15.",
        ],
    }
    report["validation"] = {
        "status": "failed" if errors else "passed",
        "catalog_files": len(files),
        "unique_ids": len(set(ids)),
        "source_derived_ids": len(expected_ids),
        "errors": errors,
    }
    write_text_lf(
        ROOT / "coverage-report.json",
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
    )
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"Validated {len(entries)} entries; source coverage and adapters passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
