---
name: dji-cloud-api
description: Generates integration code and answers protocol questions for the complete DJI Cloud API, including HTTP, MQTT, WebSocket, DJI Pilot 2 JSBridge, and WPML. Use for DJI drones, docks, device binding, livestreaming, wayline missions, media, firmware, remote control, telemetry, or Cloud API errors.
compatibility: Requires an agent that can read local JSON files. Python 3 is optional for fast catalog queries. Network calls require a host-provided protocol executor and credentials.
metadata:
  author: dji-cloud-skills
  version: "1.0"
---

# DJI Cloud API

Use this package as the source of truth for DJI Cloud API integration. Do not guess paths, topics, method identifiers, parameters, enum values, authentication, or errors.

## Find an operation

Resolve `<skill-root>` to the directory containing this `SKILL.md`, then run the bundled query helper when Python is available:

```bash
python <skill-root>/scripts/query_catalog.py "live_start_push"
python <skill-root>/scripts/query_catalog.py "航线" --protocol mqtt
python <skill-root>/scripts/query_catalog.py "固件升级" --full
```

Otherwise search [references/index.json](references/index.json). Each index group
names a small protocol/module reference file; read only the matching file.
Use [DJI error codes](references/error-codes.json) when an operation returns a
DJI result code.

## Generate calls

### HTTP

- Build `https://{endpoint}{operation.path}`.
- Send `Content-Type: application/json` and `X-Auth-Token`.
- Place each parameter according to `parameters[].in`.
- Handle both HTTP status and the `{code,message,data}` response envelope.

### MQTT

- Connect using the platform-provided broker URL and username/password.
- Follow `operation.action`, `topic`, `direction`, `method`, and reply topic.
- Preserve `tid`, `bid`, `method`, `data`, and millisecond `timestamp`.
- Correlate replies by `tid`, `bid`, and `method`; MQTT delivery is not operation success.
- Check `compatibility` for Pilot, Dock 1, and Dock 2 differences.

### WebSocket

- URL-encode the token in `x-auth-token`.
- Parse pushed messages by `biz_code`.
- Reconnect with capped exponential backoff and deduplicate replayed messages.

### JSBridge

- Verify `appId`, `appKey`, and `license` before protected calls.
- Load required components before invoking module methods.
- Parse JSON-string results before inspecting `code`, `message`, and `data`.

### WPML

- Honor each field's parent context, type, range, ordering, requirement, and supported model.
- Validate the XML document locally before upload.

## Safety and retries

- Never place tokens, broker passwords, app keys, licenses, or stream credentials in source or logs.
- On HTTP 401, renew/login; do not retry with the same token.
- Follow the selected entry's `retry` policy.
- Do not automatically replay POST or safety-sensitive MQTT commands.
- Require explicit confirmation for flight, remote control, return-home, formatting, reboot, and firmware-upgrade actions.
- After MQTT timeout, verify device state before considering a resend.

## Tool definitions

- OpenAI function tools: [assets/openai-tools.json](assets/openai-tools.json)
- Claude tools: [assets/claude-tools.json](assets/claude-tools.json)

Tool definitions are invocation contracts, not executors. The host must implement the transport and securely inject credentials.
