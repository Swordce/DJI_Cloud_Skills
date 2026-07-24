#!/usr/bin/env python3
"""Fetch and normalize the official DJI Cloud API VuePress documentation."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / ".official-cache"
HOST = "https://developer.dji.com"
SITE_ROOT = f"{HOST}/doc/cloud-api-tutorial/cn/"
ASSET_ROOT = f"{HOST}/doc/cloud-api-tutorial/assets/js/"
USER_AGENT = "DJI-Cloud-Skills/1.0 (+official documentation snapshot)"
ROUTE_RE = re.compile(
    r'\["(?P<chunk>v-[a-f0-9]+)","(?P<route>/cn/(?:api-reference/[^"]+|error-code)\.html)"'
)
STATIC_HTML_RE = re.compile(
    r"\.uE\)\((?P<quote>['\"])(?P<body>(?:\\.|(?!\1).)*?)(?P=quote)",
    re.S,
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def fetch(url: str, attempts: int = 4) -> tuple[bytes, dict[str, str]]:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/javascript,*/*",
                    "Cache-Control": "no-cache",
                },
            )
            with urlopen(request, timeout=60) as response:
                return response.read(), {
                    "etag": response.headers.get("ETag", ""),
                    "last_modified": response.headers.get("Last-Modified", ""),
                }
        except (HTTPError, URLError, TimeoutError) as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(2**attempt)
    raise RuntimeError(f"Failed to fetch {url}: {last_error}") from last_error


class MarkdownExtractor(HTMLParser):
    """Convert the static HTML emitted by VuePress into parser-friendly Markdown."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self.buffer: list[str] = []
        self.heading_level = 0
        self.in_pre = False
        self.pre_buffer: list[str] = []
        self.pre_language = ""
        self.in_table = False
        self.table_rows: list[list[str]] = []
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.skip_depth = 0
        self.strong_depth = 0
        self.list_depth = 0

    def flush_text(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self.buffer)).strip()
        self.buffer.clear()
        if text:
            self.lines.append(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        if self.skip_depth:
            self.skip_depth += 1
            return
        if tag == "a" and "header-anchor" in classes:
            self.skip_depth = 1
            return
        if tag == "div" and "line-numbers" in classes:
            self.skip_depth = 1
            return
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.flush_text()
            self.heading_level = int(tag[1])
        elif tag == "p":
            self.flush_text()
        elif tag == "strong":
            self.buffer.append("**")
            self.strong_depth += 1
        elif tag == "br":
            self.buffer.append(" ")
        elif tag in {"ul", "ol"}:
            self.flush_text()
            self.list_depth += 1
        elif tag == "li":
            self.flush_text()
            self.buffer.append("- ")
        elif tag == "table":
            self.flush_text()
            self.in_table = True
            self.table_rows = []
        elif tag == "tr" and self.in_table:
            self.row = []
        elif tag in {"th", "td"} and self.in_table:
            self.cell = []
        elif tag == "pre":
            self.flush_text()
            self.in_pre = True
            self.pre_buffer = []
            language = next((item[9:] for item in classes if item.startswith("language-")), "")
            self.pre_language = language
        elif tag == "code" and not self.in_pre:
            self.buffer.append("`")

    def handle_endtag(self, tag: str) -> None:
        if self.skip_depth:
            self.skip_depth -= 1
            return
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"} and self.heading_level:
            text = re.sub(r"\s+", " ", "".join(self.buffer)).strip()
            self.buffer.clear()
            if text:
                self.lines.append(f"{'#' * self.heading_level} {text}")
            self.heading_level = 0
        elif tag == "p":
            self.flush_text()
        elif tag == "strong" and self.strong_depth:
            self.buffer.append("**")
            self.strong_depth -= 1
        elif tag == "li":
            self.flush_text()
        elif tag in {"ul", "ol"}:
            self.flush_text()
            self.list_depth = max(0, self.list_depth - 1)
        elif tag in {"th", "td"} and self.in_table and self.cell is not None:
            value = re.sub(r"\s+", " ", "".join(self.cell)).strip().replace("|", r"\|")
            if self.row is not None:
                self.row.append(value)
            self.cell = None
        elif tag == "tr" and self.in_table and self.row is not None:
            self.table_rows.append(self.row)
            self.row = None
        elif tag == "table" and self.in_table:
            if self.table_rows:
                width = max(len(row) for row in self.table_rows)
                rows = [row + [""] * (width - len(row)) for row in self.table_rows]
                self.lines.append("| " + " | ".join(rows[0]) + " |")
                self.lines.append("| " + " | ".join(["---"] * width) + " |")
                self.lines.extend("| " + " | ".join(row) + " |" for row in rows[1:])
            self.table_rows = []
            self.in_table = False
        elif tag == "pre" and self.in_pre:
            body = "".join(self.pre_buffer).strip()
            self.lines.extend([f"```{self.pre_language}", body, "```"])
            self.in_pre = False
            self.pre_buffer = []
            self.pre_language = ""
        elif tag == "code" and not self.in_pre:
            self.buffer.append("`")

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        if self.in_pre:
            self.pre_buffer.append(data)
        elif self.cell is not None:
            self.cell.append(data)
        else:
            self.buffer.append(data)

    def markdown(self) -> str:
        self.flush_text()
        return "\n".join(line for line in self.lines if line).strip() + "\n"


def decode_static_html(javascript: str) -> list[tuple[int, str]]:
    fragments: list[tuple[int, str]] = []
    for match in STATIC_HTML_RE.finditer(javascript):
        quote = match.group("quote")
        try:
            value = ast.literal_eval(quote + match.group("body") + quote)
        except (SyntaxError, ValueError):
            continue
        if "<" in value and ">" in value:
            fragments.append((match.start(), value))
    return fragments


def html_to_markdown(fragments: list[str]) -> str:
    extractor = MarkdownExtractor()
    for fragment in fragments:
        extractor.feed(fragment)
    extractor.close()
    return extractor.markdown()


def balanced_call(javascript: str, open_paren: int) -> tuple[str, int]:
    depth = 0
    quote = ""
    escaped = False
    for index in range(open_paren, len(javascript)):
        char = javascript[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in {'"', "'", "`"}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return javascript[open_paren + 1 : index], index + 1
    raise ValueError("Unbalanced JavaScript call")


def split_js_args(value: str) -> list[str]:
    args: list[str] = []
    start = 0
    depths = {"(": 0, "[": 0, "{": 0}
    closing = {")": "(", "]": "[", "}": "{"}
    quote = ""
    escaped = False
    for index, char in enumerate(value):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in {'"', "'", "`"}:
            quote = char
        elif char in depths:
            depths[char] += 1
        elif char in closing:
            depths[closing[char]] -= 1
        elif char == "," and not any(depths.values()):
            args.append(value[start:index].strip())
            start = index + 1
    args.append(value[start:].strip())
    return args


def js_text(value: str) -> str:
    value = value.strip()
    if not value or value in {"null", "void 0"}:
        return ""
    if value[:1] in {'"', "'"}:
        try:
            return str(ast.literal_eval(value))
        except (SyntaxError, ValueError):
            return ""
    text_nodes = []
    for match in re.finditer(r"\.Uk\)\((['\"])((?:\\.|(?!\1).)*?)\1\)", value, re.S):
        try:
            text_nodes.append(str(ast.literal_eval(match.group(1) + match.group(2) + match.group(1))))
        except (SyntaxError, ValueError):
            pass
    return "".join(text_nodes)


def dynamic_table_markdown(javascript: str) -> list[tuple[int, str]]:
    cell_vars: dict[str, str] = {}
    for match in re.finditer(r"(?:const |,)([A-Za-z_$][\w$]*)=\(0,\w+\._\)\(\"t[dh]\"", javascript):
        open_paren = javascript.find("(", match.end() - 5)
        try:
            body, _ = balanced_call(javascript, open_paren)
        except ValueError:
            continue
        args = split_js_args(body)
        cell_vars[match.group(1)] = js_text(args[2]) if len(args) > 2 else ""

    rows: list[tuple[int, list[str]]] = []
    marker = re.compile(r"\._\)\(\"tr\"")
    for match in marker.finditer(javascript):
        open_paren = javascript.find("(", match.start())
        try:
            body, _ = balanced_call(javascript, open_paren)
        except ValueError:
            continue
        args = split_js_args(body)
        if len(args) < 3 or not args[2].startswith("["):
            continue
        cells: list[str] = []
        for expression in split_js_args(args[2][1:-1]):
            expression = expression.strip()
            direct = re.search(r"\._\)\(\"t[dh]\"", expression)
            if direct:
                cell_open = expression.find("(", direct.start())
                try:
                    cell_body, _ = balanced_call(expression, cell_open)
                    cell_args = split_js_args(cell_body)
                    value = js_text(cell_args[2]) if len(cell_args) > 2 else ""
                except ValueError:
                    value = ""
            else:
                value = cell_vars.get(expression, "")
            cells.append(re.sub(r"\s+", " ", value).strip().replace("|", r"\|"))
        if cells:
            rows.append((match.start(), cells))

    tables: list[tuple[int, list[list[str]]]] = []
    current: list[list[str]] = []
    start_position = 0
    for position, row in rows:
        if row and row[0] == "Column" and current:
            tables.append((start_position, current))
            current = []
        if not current:
            start_position = position
        current.append(row)
    if current:
        tables.append((start_position, current))
    output: list[tuple[int, str]] = []
    for position, table in tables:
        if not table or table[0][0] != "Column":
            continue
        width = max(len(row) for row in table)
        normalized = [row + [""] * (width - len(row)) for row in table]
        lines = [
            "| " + " | ".join(normalized[0]) + " |",
            "| " + " | ".join(["---"] * width) + " |",
            *["| " + " | ".join(row) + " |" for row in normalized[1:]],
        ]
        output.append((position, "\n".join(lines)))
    return output


def javascript_to_markdown(javascript: str) -> str:
    events: list[tuple[int, str]] = [
        (position, html_to_markdown([fragment]).strip())
        for position, fragment in decode_static_html(javascript)
    ]
    events.extend(dynamic_table_markdown(javascript))
    return "\n".join(text for _, text in sorted(events) if text).strip() + "\n"


def discover_routes(app_javascript: str) -> list[dict[str, str]]:
    routes: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in ROUTE_RE.finditer(app_javascript):
        route = match.group("route")
        if route in seen:
            continue
        record_end = app_javascript.find("]]", match.end())
        snippet = app_javascript[match.start() : record_end + 2 if record_end >= 0 else match.end() + 1200]
        alias = re.search(r'"(/cn/(?:60\.api-reference/[^"]+|71\.error-code)\.md)"', snippet)
        if not alias:
            raise RuntimeError(f"Official route lacks a source alias: {route}")
        routes.append({"chunk": match.group("chunk"), "route": route, "alias": alias.group(1)})
        seen.add(route)
    return sorted(routes, key=lambda item: item["route"])


def asset_map(index_html: str) -> dict[str, str]:
    return {
        chunk: f"{ASSET_ROOT}{chunk}.{digest}.js"
        for chunk, digest in re.findall(
            r"/doc/cloud-api-tutorial/assets/js/(v-[a-f0-9]+)\.([a-f0-9]+)\.js",
            index_html,
        )
    }


def release_record(app_javascript: str, index_html: str) -> dict[str, str]:
    route_marker = '["v-'
    route_position = app_javascript.find('","/cn/",')
    if route_position < 0:
        raise RuntimeError("Could not locate the official Chinese release-history route")
    start = app_javascript.rfind(route_marker, 0, route_position)
    chunk_match = re.match(r'\["(?P<chunk>v-[a-f0-9]+)"', app_javascript[start:])
    if not chunk_match:
        raise RuntimeError("Could not identify the release-history chunk")
    chunk = chunk_match.group("chunk")
    url = asset_map(index_html).get(chunk)
    if not url:
        raise RuntimeError(f"Release-history asset is missing for {chunk}")
    return {"chunk": chunk, "route": "/cn/", "alias": "/cn/00.index.md", "asset_url": url}


def cache_path(output: Path, alias: str) -> Path:
    return output / "docs" / alias.lstrip("/")


def extract_updated_time(javascript: str) -> str | None:
    match = re.search(r"updatedTime:(\d+)", javascript)
    if not match:
        return None
    timestamp = int(match.group(1))
    if timestamp > 10_000_000_000:
        timestamp /= 1000
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--expected-version", default="1.16.1")
    parser.add_argument("--min-api-routes", type=int, default=100)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    output = args.output.resolve()

    index_bytes, index_headers = fetch(SITE_ROOT)
    index_html = index_bytes.decode("utf-8")
    app_match = re.search(r"/doc/cloud-api-tutorial/assets/js/app\.([a-f0-9]+)\.js", index_html)
    if not app_match:
        raise SystemExit("Official VuePress app asset was not found")
    app_url = f"{HOST}{app_match.group(0)}"
    app_bytes, app_headers = fetch(app_url)
    app_javascript = app_bytes.decode("utf-8")
    runtime_match = re.search(
        r"/doc/cloud-api-tutorial/assets/js/runtime~app\.([a-f0-9]+)\.js",
        index_html,
    )
    if not runtime_match:
        raise SystemExit("Official VuePress runtime asset was not found")
    runtime_url = f"{HOST}{runtime_match.group(0)}"
    runtime_bytes, runtime_headers = fetch(runtime_url)
    assets = asset_map(index_html)
    routes = discover_routes(app_javascript)
    api_routes = [item for item in routes if "/api-reference/" in item["route"]]
    if len(api_routes) < args.min_api_routes:
        raise SystemExit(
            f"Official API route count dropped to {len(api_routes)}; expected at least {args.min_api_routes}"
        )
    release = release_record(app_javascript, index_html)
    work_items = routes + [release]
    for item in work_items:
        item["asset_url"] = item.get("asset_url") or assets.get(item["chunk"], "")
        if not item["asset_url"]:
            raise SystemExit(f"Official page asset was not found for {item['route']} ({item['chunk']})")

    fetched: dict[str, tuple[bytes, dict[str, str]]] = {}
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {executor.submit(fetch, item["asset_url"]): item["asset_url"] for item in work_items}
        for future in as_completed(futures):
            fetched[futures[future]] = future.result()

    page_records: list[dict[str, Any]] = []
    release_markdown = ""
    for item in work_items:
        chunk_bytes, headers = fetched[item["asset_url"]]
        javascript = chunk_bytes.decode("utf-8")
        markdown = javascript_to_markdown(javascript)
        if len(markdown.strip()) < 20:
            raise SystemExit(f"Official page normalized to empty content: {item['route']}")
        path = cache_path(output, item["alias"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown, encoding="utf-8")
        if item["route"] == "/cn/":
            release_markdown = markdown
        page_records.append(
            {
                "route": item["route"],
                "source_url": f"{HOST}/doc/cloud-api-tutorial{item['route']}",
                "file": path.relative_to(output).as_posix(),
                "chunk": item["chunk"],
                "asset_url": item["asset_url"],
                "asset_sha256": sha256_bytes(chunk_bytes),
                "content_sha256": sha256_bytes(markdown.encode("utf-8")),
                "updated_time": extract_updated_time(javascript),
                **headers,
            }
        )

    versions = re.findall(r"上云\s*API\s*v(\d+\.\d+(?:\.\d+)?)\s*发布记录", release_markdown, re.I)
    current_version = versions[0] if versions else ""
    if current_version != args.expected_version:
        raise SystemExit(
            f"Official release history reports v{current_version or 'unknown'}, "
            f"expected v{args.expected_version}"
        )
    identity = {
        "version": current_version,
        "app_sha256": sha256_bytes(app_bytes),
        "runtime_sha256": sha256_bytes(runtime_bytes),
        "pages": [
            {"route": page["route"], "content_sha256": page["content_sha256"]}
            for page in sorted(page_records, key=lambda page: page["route"])
        ],
    }
    snapshot_sha256 = sha256_bytes(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    manifest = {
        "source": SITE_ROOT,
        "version": current_version,
        "version_evidence_url": f"{HOST}/doc/cloud-api-tutorial/cn/",
        "fetched_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "snapshot_sha256": snapshot_sha256,
        "route_count": len(api_routes),
        "error_page_count": sum(item["route"] == "/cn/error-code.html" for item in routes),
        "app": {
            "url": app_url,
            "hash": app_match.group(1),
            "sha256": sha256_bytes(app_bytes),
            **app_headers,
        },
        "runtime": {
            "url": runtime_url,
            "hash": runtime_match.group(1),
            "sha256": sha256_bytes(runtime_bytes),
            **runtime_headers,
        },
        "index": {
            "url": SITE_ROOT,
            "sha256": sha256_bytes(index_bytes),
            **index_headers,
        },
        "pages": sorted(page_records, key=lambda page: page["route"]),
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "snapshot.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Fetched DJI Cloud API v{current_version}: "
        f"{len(api_routes)} API routes + error codes ({snapshot_sha256[:12]})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
