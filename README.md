# DJI Cloud API Skills

[简体中文](#简体中文) | [English](#english)

## 简体中文

本项目从完整的中文
[DJI 上云 API 文档](https://github.com/dji-sdk/Cloud-API-Doc)
生成结构化、面向智能体的接口定义。

目录覆盖 HTTP、MQTT 服务/事件/属性、WebSocket 消息、DJI Pilot 2
JSBridge 方法及 WPML 元素，包括设备管理与绑定、直播、航线任务、媒体、
固件升级、遥测、远程操作和协议错误码。

### 源文件与构建产物

- `skills/dji-cloud-api/` — 手工维护的可移植 Skill 源文件
- `skills/dji-cloud-api/scripts/query_catalog.py` — 无第三方依赖的目录查询工具
- `catalog/index.json` — 可搜索的接口索引
- `catalog/endpoints/<protocol>/*.json` — 每个接口对应一个结构化条目
- `catalog/error-codes.json` — DJI 错误码映射
- `catalog/schema.json` — 目录条目的权威 JSON Schema
- `.cursorrules` — 兼容旧版 Cursor Rules
- `build/skills/dji-cloud-api/` — 生成的可安装 Skill 包
- `build/dist/openai/` — 生成的 OpenAI function tools
- `build/dist/claude/` — 生成的 Claude tools
- `build/dist/<platform>/by-module/` — 按模块拆分的工具定义
- `manifest.json` — 固定的上游版本和条目数量
- `coverage-report.json` — 生成与校验覆盖率

只有 `catalog/` 是协议事实源。`build/`、各平台安装副本、references、
assets 和工具适配文件均可重复生成，不纳入版本控制。

OpenAI 和 Claude 工具文件只定义调用结构。宿主程序仍需实现 HTTP、
MQTT、WebSocket、JSBridge 或 WPML 执行器，并在运行时安全注入凭据。
当宿主限制工具数量或上下文大小时，应优先加载 `by-module` 分片。

### 安装到开发工具

生成的安装包遵循
[Agent Skills 规范](https://agentskills.io/specification)：

```text
build/skills/dji-cloud-api/
├── SKILL.md
├── references/
├── scripts/
└── assets/
```

安装到一个或多个开发工具：

```bash
python scripts/install_skill.py codex cursor claude
python scripts/install_skill.py codebuddy workbuddy
python scripts/install_skill.py --all
```

使用 `--force` 更新已有安装。支持的项目级目录：

- Cursor：`.cursor/skills/`
- OpenAI Codex：`.agents/skills/`
- Claude Code：`.claude/skills/`
- CodeBuddy：`.codebuddy/skills/`
- WorkBuddy：`.workbuddy/skills/`
- GitHub Copilot：`.github/skills/`
- Google Antigravity：`.agent/skills/`
- Gemini：`.gemini/skills/`

安装到其他项目或自定义目录：

```bash
python scripts/install_skill.py codex --project /path/to/project
python scripts/install_skill.py --target-dir /path/to/agent/skills
```

Codex 推荐使用 `.agents/skills`；`.codex/skills` 是旧版目录。安装器使用
文件复制而非符号链接，因此兼容 Windows 和归档文件。每次安装前都会根据
`catalog/` 重新构建 Skill 包。

### 更新接口目录

将上游文档克隆到 `.upstream`：

```bash
git clone --depth 1 https://github.com/dji-sdk/Cloud-API-Doc.git .upstream
```

生成并校验：

```bash
python scripts/sync_catalog.py
python scripts/build_artifacts.py
python scripts/validate_catalog.py --check-determinism
```

使用其他位置的上游源码：

```bash
python scripts/sync_catalog.py --source /path/to/Cloud-API-Doc
python scripts/validate_catalog.py --source /path/to/Cloud-API-Doc
```

生成器和校验器仅使用 Python 标准库。

### 目录条目

每个接口条目包含：

- 稳定 ID、名称、用途、协议、模块和设备兼容性
- HTTP method/path，MQTT action/topic/direction/method，JS 签名或 WPML 元素
- 参数位置、类型、约束、说明及必选/可选状态
- Token、Broker 凭据、License 或本地文档认证语义
- 响应 Schema/字段、协议关联信息和 DJI 错误码
- 官方或根据 Schema 生成的最小请求/响应示例
- 考虑幂等性的重试策略和原始文档地址

不适用于某个协议的字段不会被伪造为 HTTP 路径或签名要求。如果上游
MQTT/WPML 表格没有说明字段是否必选，则 `required` 为 `null`，
`required_status` 为 `not_specified_by_source`，生成器不会擅自将其解释为可选。

### 安全执行

- 从密钥存储注入 `X-Auth-Token`、Broker 密码、App Key 和 License，禁止写入源码或日志。
- HTTP 401 必须重新登录或刷新 Token；使用原 Token 重试不能解决问题。
- 仅对条目中允许的状态码重试幂等 HTTP 操作。
- 使用 `tid`、`bid` 和 `method` 关联 MQTT 响应；超时后先确认设备状态。
- 禁止自动重放飞行、远程控制、返航、格式化、重启或固件升级命令。
- 上传前在本地校验 WPML。

### 来源与归属

`manifest.json` 固定生成时使用的上游 commit，每个条目均链接到原始文档。
上游协议文档由 DJI 所有并维护；重新分发生成内容前请确认其适用条款。

## English

Structured, agent-ready definitions generated from the complete Chinese
[DJI Cloud API documentation](https://github.com/dji-sdk/Cloud-API-Doc).

The catalog covers HTTP, MQTT services/events/properties, WebSocket messages,
DJI Pilot 2 JSBridge methods, and WPML elements. It includes device management
and binding, livestreaming, wayline missions, media, firmware upgrades,
telemetry, remote operations, and protocol error codes.

### Source and build artifacts

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

### Refresh

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

`manifest.json` pins the exact upstream commit used for generation. Each entry
links back to its source file. DJI owns and maintains the upstream protocol
documentation; review its applicable terms before redistributing generated
documentation content.
