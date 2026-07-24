# DJI Cloud API Skills

[简体中文](README.md) | English

Structured, agent-ready definitions generated exclusively from the official
Chinese [DJI Cloud API v1.16.1 tutorial](https://developer.dji.com/doc/cloud-api-tutorial/cn/).

The catalog covers HTTP, MQTT services/events/properties, WebSocket messages,
DJI Pilot 2 JSBridge methods, and WPML elements. It includes device management
and binding, livestreaming, wayline missions, media, firmware upgrades,
telemetry, remote operations, and protocol error codes — 2,488 endpoint
entries in total.

**Contents**

- [Quick start](#quick-start)
- [Repository layout](#repository-layout)
- [Requirements](#requirements)
- [Install for coding agents](#install-for-coding-agents)
- [Search the catalog](#search-the-catalog)
- [Refresh](#refresh)
- [Catalog entry](#catalog-entry)
- [Safe execution](#safe-execution)
- [Source and attribution](#source-and-attribution)

### Quick start

```bash
# 1. Build and install the Skill (rebuilds from catalog/ first)
python scripts/install_skill.py --all

# 2. Search the catalog
python skills/dji-cloud-api/scripts/query_catalog.py "list waylines"

# 3. Re-fetch and regenerate after an official docs update
python scripts/fetch_official_docs.py && python scripts/sync_catalog.py \
  && python scripts/build_artifacts.py \
  && python scripts/validate_catalog.py --check-determinism
```

### Repository layout

Protocol fact source (version-controlled):

- `catalog/index.json` — searchable operation index
- `catalog/endpoints/<protocol>/*.json` — one structured entry per operation
- `catalog/error-codes.json` — DJI result-code mapping
- `catalog/change-report.json` — field-level legacy-to-v1.16.1 changes
- `catalog/schema.json` — authoritative catalog entry JSON Schema
- `skills/dji-cloud-api/` — hand-authored portable Skill source
- `skills/dji-cloud-api/scripts/query_catalog.py` — catalog search tool
- `manifest.json` — pinned official version, snapshot hash, and entry counts
- `coverage-report.json` — generation and validation coverage
- `.cursorrules` — legacy Cursor Rules compatibility

Reproducible outputs (excluded from version control, see `.gitignore`):

- `build/skills/dji-cloud-api/` — generated installable Skill package
- `build/skills/dji-cloud-api/assets/` — canonical full OpenAI / Claude tool files
- `build/dist/<platform>/` — module-level tool shards and their registry (no full tool files)
- `.official-cache/` — official page snapshot cache (default output of `fetch_official_docs.py`)

The generated OpenAI and Claude files contain schema definitions only. A host
application still needs to implement the HTTP, MQTT, WebSocket, JSBridge, or
WPML executor and provide credentials at runtime. Prefer a `by-module` shard
instead of loading every tool when the host limits tool count or context size.

### Requirements

- Python 3.x
- All scripts use only the Python standard library; no third-party dependencies

### Install for coding agents

The generated package follows the [Agent Skills specification](https://agentskills.io/specification):

```text
build/skills/dji-cloud-api/
├── SKILL.md
├── references/
├── scripts/
└── assets/
```

Install a project-local copy for one or more tools:

```bash
python scripts/install_skill.py codex cursor claude
python scripts/install_skill.py codebuddy workbuddy
python scripts/install_skill.py --all
```

Use `--force` to refresh an existing installation. Supported discovery targets:

- Cursor: `.cursor/skills/`
- OpenAI Codex: `.agents/skills/`
- Claude Code: `.claude/skills/`
- CodeBuddy: `.codebuddy/skills/`
- WorkBuddy: `.workbuddy/skills/`
- GitHub Copilot: `.github/skills/`
- Google Antigravity: `.agent/skills/`
- Gemini: `.gemini/skills/`

Install into another project or a custom skill directory:

```bash
python scripts/install_skill.py codex --project /path/to/project
python scripts/install_skill.py --target-dir /path/to/agent/skills
```

Codex should use `.agents/skills`; `.codex/skills` is a legacy location. The
installer copies the package instead of creating symlinks so it works on
Windows and in archives. It rebuilds the package from `catalog/` before
installation.

### Search the catalog

`query_catalog.py` searches by ID, name, module, method, path, topic,
biz_code, or WPML element:

```bash
# Keyword search (summary output by default)
python skills/dji-cloud-api/scripts/query_catalog.py "livestream"

# Restrict to one protocol
python skills/dji-cloud-api/scripts/query_catalog.py "flighttask" --protocol mqtt

# Print full entries, capped result count
python skills/dji-cloud-api/scripts/query_catalog.py "wayline" --full --limit 5
```

### Refresh

Fetch the official VuePress routes and pin the v1.16.1 page snapshot:

```bash
python scripts/fetch_official_docs.py
```

Generate and validate:

```bash
python scripts/sync_catalog.py
python scripts/build_artifacts.py
python scripts/validate_catalog.py --check-determinism
```

To use an official snapshot cache elsewhere:

```bash
python scripts/fetch_official_docs.py --output /path/to/official-cache
python scripts/sync_catalog.py --source /path/to/official-cache
python scripts/validate_catalog.py --source /path/to/official-cache
```

Fetching fails closed if routes disappear, chunks are missing, pages are
empty, or the release record is not v1.16.1; it never falls back to the
legacy GitHub documentation.

### Catalog entry

Each endpoint entry records:

- Stable ID, name, purpose, protocol, module, and device compatibility
- HTTP method/path, MQTT action/topic/direction/method, JS signature, or WPML element
- Required and optional parameters with location, type, constraints, and description
- Token, broker-credential, license, or local-document authentication semantics
- Response schemas/fields, protocol correlation data, and DJI error mapping
- Official or schema-derived minimum request/response examples
- Idempotency-aware retry policy and source-document URL

Fields that do not apply to a protocol are represented by protocol-specific
operation data rather than fabricated HTTP paths or signature requirements.
When an upstream MQTT/WPML table does not declare whether a field is mandatory,
`required` is `null` and `required_status` is `not_specified_by_source`; the
generator does not silently reinterpret an undocumented field as optional.

### Safe execution

- Inject `X-Auth-Token`, broker passwords, app keys, and licenses from a secret
  store. Never embed them in generated code or logs.
- HTTP 401 requires login/token renewal. Repeating the same request with the
  same token is not a recovery strategy.
- Retry idempotent HTTP operations only for the statuses listed in the entry.
- Correlate MQTT replies with `tid`, `bid`, and `method`; verify device state
  after a timeout.
- Do not automatically replay flight, remote-control, return-home, formatting,
  reboot, or firmware-upgrade commands.
- Validate WPML locally before upload.

### Source and attribution

`manifest.json` pins the official release, VuePress app/runtime hashes, 102 dynamically
discovered API Reference routes, and the content snapshot hash. Every entry
links to its official page and records page hashes. The navbar may lag the
release record; the official release history is the version evidence. DJI owns
and maintains the protocol documentation; review its applicable terms before
redistributing generated content.
