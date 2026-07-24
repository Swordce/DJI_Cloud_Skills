# DJI Cloud API Skills

简体中文 | [English](README_EN.md)

从 DJI 官方中文[上云 API v1.16.1 教程](https://developer.dji.com/doc/cloud-api-tutorial/cn/)
生成的结构化、面向智能体的接口定义。官网 API Reference 页面和错误码页是
唯一协议来源。

目录覆盖 HTTP、MQTT 服务/事件/属性、WebSocket 消息、DJI Pilot 2
JSBridge 方法及 WPML 元素，包括设备管理与绑定、直播、航线任务、媒体、
固件升级、遥测、远程操作和协议错误码，共 2488 个接口条目。

**目录**

- [快速开始](#快速开始)
- [目录结构](#目录结构)
- [环境要求](#环境要求)
- [安装到开发工具](#安装到开发工具)
- [查询接口目录](#查询接口目录)
- [更新接口目录](#更新接口目录)
- [目录条目说明](#目录条目说明)
- [安全执行](#安全执行)
- [来源与归属](#来源与归属)

### 快速开始

```bash
# 1. 构建并安装 Skill 到开发工具（自动从 catalog/ 重新构建）
python scripts/install_skill.py --all

# 2. 查询接口目录
python skills/dji-cloud-api/scripts/query_catalog.py "获取航线列表"

# 3. 官网更新后，重新抓取并生成
python scripts/fetch_official_docs.py && python scripts/sync_catalog.py \
  && python scripts/build_artifacts.py \
  && python scripts/validate_catalog.py --check-determinism
```

### 目录结构

协议事实源（纳入版本控制）：

- `catalog/index.json` — 可搜索的接口索引
- `catalog/endpoints/<protocol>/*.json` — 每个接口对应一个结构化条目
- `catalog/error-codes.json` — DJI 错误码映射
- `catalog/change-report.json` — 旧目录到官网 v1.16.1 的字段级变更
- `catalog/schema.json` — 目录条目的权威 JSON Schema
- `skills/dji-cloud-api/` — 手工维护的可移植 Skill 源文件
- `skills/dji-cloud-api/scripts/query_catalog.py` — 目录查询工具
- `manifest.json` — 固定的官网版本、页面快照哈希和条目数量
- `coverage-report.json` — 生成与校验覆盖率
- `.cursorrules` — 兼容旧版 Cursor Rules

可重复生成的产物（不纳入版本控制，见 `.gitignore`）：

- `build/skills/dji-cloud-api/` — 生成的可安装 Skill 包
- `build/skills/dji-cloud-api/assets/` — 完整 OpenAI / Claude 工具文件的唯一权威副本
- `build/dist/<platform>/` — 按模块拆分的工具分片与注册表（不再含全量工具文件）
- `.official-cache/` — 官网页面快照缓存（`fetch_official_docs.py` 的默认输出）

OpenAI 和 Claude 工具文件只定义调用结构。宿主程序仍需实现 HTTP、
MQTT、WebSocket、JSBridge 或 WPML 执行器，并在运行时安全注入凭据。
当宿主限制工具数量或上下文大小时，应优先加载 `by-module` 分片。

### 环境要求

- Python 3.x
- 全部脚本仅使用 Python 标准库，无第三方依赖

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

### 查询接口目录

`query_catalog.py` 支持按 ID、名称、模块、method、path、topic、
biz_code 或 WPML 元素搜索：

```bash
# 关键词搜索（默认返回摘要）
python skills/dji-cloud-api/scripts/query_catalog.py "直播"

# 限定协议
python skills/dji-cloud-api/scripts/query_catalog.py "flighttask" --protocol mqtt

# 输出完整条目，限制条数
python skills/dji-cloud-api/scripts/query_catalog.py "wayline" --full --limit 5
```

### 更新接口目录

抓取官网 VuePress 路由和页面 chunk，并固定 v1.16.1 快照：

```bash
python scripts/fetch_official_docs.py
```

生成并校验：

```bash
python scripts/sync_catalog.py
python scripts/build_artifacts.py
python scripts/validate_catalog.py --check-determinism
```

使用其他位置的官网快照缓存：

```bash
python scripts/fetch_official_docs.py --output /path/to/official-cache
python scripts/sync_catalog.py --source /path/to/official-cache
python scripts/validate_catalog.py --source /path/to/official-cache
```

若官网路由异常减少、页面 chunk 缺失、内容为空或发布记录不是
v1.16.1，抓取会失败且不会回退到 GitHub 旧文档。

### 目录条目说明

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

`manifest.json` 固定官网版本、VuePress app/runtime hash、102 个动态发现的 API
Reference 路由和内容快照 hash。每个条目均链接到官网页面并记录页面 hash。
官网导航栏仍可能显示旧版本；版本判定以官网发布记录为证据。协议文档由
DJI 所有并维护；重新分发生成内容前请确认其适用条款。
