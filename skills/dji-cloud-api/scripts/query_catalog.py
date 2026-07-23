#!/usr/bin/env python3
"""Search the portable DJI Cloud API skill catalog."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REFERENCES = ROOT / "references"
PROTOCOLS = ("http", "mqtt", "websocket", "jsbridge", "wpml")


def searchable(entry: dict[str, Any]) -> str:
    operation = entry.get("operation", {})
    values = [
        entry.get("id", ""),
        entry.get("name", ""),
        entry.get("purpose", ""),
        entry.get("module", ""),
        operation.get("method", ""),
        operation.get("path", ""),
        operation.get("topic", ""),
        operation.get("biz_code", ""),
        operation.get("element", ""),
    ]
    return " ".join(str(value) for value in values if value).lower()


def load_matches(query: str, protocols: tuple[str, ...]) -> list[dict[str, Any]]:
    index_path = REFERENCES / "index.json"
    if index_path.exists():
        with index_path.open(encoding="utf-8") as handle:
            groups = json.load(handle)
        matches: list[dict[str, Any]] = []
        for group in groups:
            if group["protocol"] not in protocols:
                continue
            summary_hit = query in f"{group['group']} {group['module']}".lower()
            candidate_ids = {
                item["id"]
                for item in group["entries"]
                if summary_hit
                or query
                in f"{item['id']} {item['name']} {item['purpose']} {json.dumps(item['operation'], ensure_ascii=False)}".lower()
            }
            if not candidate_ids and not summary_hit:
                continue
            with (REFERENCES / group["file"]).open(encoding="utf-8") as handle:
                entries = json.load(handle)
            matches.extend(
                entry for entry in entries if summary_hit or entry["id"] in candidate_ids or query in searchable(entry)
            )
        return matches

    repo_catalog = ROOT.parents[1] / "catalog/endpoints"
    matches = []
    for protocol in protocols:
        for path in sorted((repo_catalog / protocol).glob("*.json")):
            with path.open(encoding="utf-8") as handle:
                entry = json.load(handle)
            if query in searchable(entry):
                matches.append(entry)
    return matches


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="ID, name, module, method, path, topic, biz_code, or WPML element")
    parser.add_argument("--protocol", choices=PROTOCOLS)
    parser.add_argument("--full", action="store_true", help="Print complete matching entries")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    protocols = (args.protocol,) if args.protocol else PROTOCOLS
    query = args.query.lower()
    matches = load_matches(query, protocols)

    matches.sort(key=lambda entry: (entry["protocol"], entry["id"]))
    selected = matches[: max(args.limit, 0)]
    if args.full:
        output: Any = selected
    else:
        output = [
            {
                "id": entry["id"],
                "name": entry["name"],
                "protocol": entry["protocol"],
                "module": entry["module"],
                "operation": entry["operation"],
            }
            for entry in selected
        ]
    print(json.dumps({"count": len(matches), "results": output}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
