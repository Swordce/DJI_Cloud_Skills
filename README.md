# DJI Cloud API Skills

Structured, agent-ready definitions generated from the complete Chinese
[DJI Cloud API documentation](https://github.com/dji-sdk/Cloud-API-Doc).

The catalog covers HTTP, MQTT services/events/properties, WebSocket messages,
DJI Pilot 2 JSBridge methods, and WPML elements. It includes device management
and binding, livestreaming, wayline missions, media, firmware upgrades,
telemetry, remote operations, and protocol error codes.

## Source and build artifacts

- `skills/dji-cloud-api/` — hand-authored portable Skill source
- `skills/dji-cloud-api/scripts/query_catalog.py` — dependency-free catalog search
- `catalog/index.json` — searchable operation index
- `catalog/endpoints/<protocol>/*.json` — one structured entry per operation
- `catalog/error-codes.json` — DJI result-code mapping
- `catalog/schema.json` — authoritative catalog entry JSON Schema
- `.cursorrules` — legacy Cursor Rules compatibility
- `build/skills/dji-cloud-api/` — generated installable Skill package
- `build/dist/openai/` — generated OpenAI function tools
- `build/dist/claude/` — generated Claude tools
- `build/dist/<platform>/by-module/` — generated module-level tool shards
- `manifest.json` — pinned upstream revision and entry counts
- `coverage-report.json` — generation and validation coverage

Only `catalog/` is the protocol fact source. `build/`, platform installation
copies, references, assets, and tool adapters are reproducible outputs and are
excluded from version control.

The generated OpenAI and Claude files contain schema definitions only. A host
application still needs to implement the HTTP, MQTT, WebSocket, JSBridge, or
WPML executor and provide credentials at runtime. Prefer a `by-module` shard
instead of loading every tool when the host limits tool count or context size.

## Install for coding agents

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

## Refresh

Clone the upstream documentation into `.upstream`:

```bash
git clone --depth 1 https://github.com/dji-sdk/Cloud-API-Doc.git .upstream
```

Generate and validate:

```bash
python scripts/sync_catalog.py
python scripts/build_artifacts.py
python scripts/validate_catalog.py --check-determinism
```

To use a source checkout elsewhere:

```bash
python scripts/sync_catalog.py --source /path/to/Cloud-API-Doc
python scripts/validate_catalog.py --source /path/to/Cloud-API-Doc
```

The generators and validators use only the Python standard library.

## Catalog entry

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

## Safe execution

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

## Source and attribution

`manifest.json` pins the exact upstream commit used for generation. Each entry
links back to its source file. DJI owns and maintains the upstream protocol
documentation; review its applicable terms before redistributing generated
documentation content.
