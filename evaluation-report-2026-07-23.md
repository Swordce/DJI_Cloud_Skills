# DJI-Cloud-Skills 评估报告

- **评估对象**：`D:\develop\workspace\dji\DJI_Cloud_Skills`（catalog 2488 条 + build 产物 + skills 源）
- **对照基准**：DJI 官方中文上云 API 教程（https://developer.dji.com/doc/cloud-api-tutorial/cn/）
- **评估时间**：2026-07-23
- **评估方法**：用项目自带 `fetch_official_docs.py` 实时重抓官网并逐页比对哈希；按协议分层抽样核对条目字段；静态审查 5 个流水线脚本与全部产物布局。

---

## 一、文档一致性检查

### 通过项

1. **版本与官网零漂移（实测）**。实时重抓官网：发布记录最新版本为 **v1.16.1**（2025.12.17 发布），与 `manifest.json` 钉住版本一致；`snapshot_sha256=7f856e08f7f4…`、app 哈希 `163638ee`、runtime 哈希、**104 个页面内容哈希逐页一致**，102 条 API Reference 路由无增删。catalog 内容与官网当前状态完全同步，不存在版本滞后。
2. **路由覆盖完整且例外受控**。102 条路由覆盖 99 条；3 条未覆盖路由（WPML overview、两个 topic-definition）均为无接口表格的说明页，例外写入 `coverage-report.json` 且校验器带 stale-exception 检测（例外失效会报错）。
3. **错误码收录完整**。官网错误码页 448 个数字错误码全部收录，另含 4 个首位来源码共 452 条；官网↔catalog 双向 diff 为 0。
4. **废弃接口识别准确**。10 个 MQTT 条目 `deprecated=true`（`flighttask_create`×3、`drone_control`×2、`drc_status_notify`×5），与官网章节标题"（废弃）/（已废弃）"逐一对应，名称保留官网废弃标记。
5. **抽样条目字段准确**。HTTP 获取航线列表（method/path/query 参数及必选性与官网一致）、WebSocket `device_online`（`biz_code=device_online`、官方示例原样保留）、JSBridge `apiGetToken`（签名 `window.djiBridge.apiGetToken()` 与用途描述逐字一致）、MQTT `flighttask_prepare`（topic/direction/method/reply 关系正确）。
6. **对官方数据缺陷忠实不伪造**。空调状态枚举在官网原文即缺逗号，catalog 原样镜像而非擅自"修复"；官网未标明必选的字段一律 `required=null` + `not_specified_by_source`，不擅自推断为可选——诚实性策略执行到位。
7. **源异常成文化**。`coverage-report.json` 记录 6 条 known_source_exceptions（HTTP 示例缺逗号、opId 复制粘贴错误、VuePress 动态表格重建等），每条示例带 `source: official | generated_from_schema` 溯源标记（official 914 条 / generated 3424 条）。

### 需改进项

1. **【严重】WPML 条目关键字段系统性丢失（130/130 全量受影响）**。官网 WPML 表格 7 列（元素/名称/类型/单位/取值与释义/是否必需（默认值）/支持机型）中，**名称、取值与释义、单位、是否必需、支持机型 5 列全部丢弃**：所有条目 `description=""`、`constraints=""`、`required_status` 全部为 `not_specified_by_source`（官网明确写"必需元素"的也是如此）、`compatibility=[]`（官网列有机型清单）。`SKILL.md` 宣称 WPML 应 "Honor each field's … range, ordering, requirement, and supported model"，**数据无法兑现文档承诺**。
2. **【严重】WPML 类型保真失败**。全部 130 条参数 `type` 一律映射为 `string`（整型×27、浮点型×25、布尔型×23、字符串×7…）；`schema` 字段出现脏值：`'°'`（单位被错位进类型列）、`'浮点型浮点型'`、`'布尔形'`（官网错别字未清洗）。下游按 `type` 生成校验代码会得到全字符串的错误 schema。
3. **【严重】MQTT services 参数层级被扁平化（306/2284 条涉及）**。官网用 `»url`、`»fingerprint` 表达 struct 父子关系，catalog 中子字段失去 parent 信息变成平级兄弟，且 `struct` 类型的 `type` 被错误映射为 `"string"`（应为 `object`）；`unique_parameters` 按名字去重，不同父级下的同名片段会被静默丢弃。按此生成 `flighttask_prepare` 调用会得到扁平 payload，**设备端会拒绝**。
4. **【中】JSBridge 模块分类失效（36/49 条目）**。这些条目 `module="3bc15c8aae3e"`——这是 `sha1("-")` 的截断值：所有纯中文章节标题（设备上云/直播/地图元素/MOP…）经 slug 后坍缩为同一个常量哈希，且页面顶部"概述"汇总表先解析占坑 + 全局 dedup，导致正文章节无法重新归类（`apiGetToken` 落进哈希桶而同模块的 `apiGetHost` 落进 `api`）。by-module 分片 `jsbridge-3bc15c8aae3e.json` 混合了 thing/live/map/mop 等本应分离的方法，模块检索与分片加载对该协议失效。
5. **【中】constraints 约束不可机读**。枚举约束以"近乎 JSON 但非法"的字符串存储（官网缺逗号问题原样透传，如 `"9":"除湿准备模式"10":"风冷准备中"`），下游 `json.loads(constraints)` 必然抛异常，但条目无任何格式有效性标记。
6. **【轻】204 条目无示例**。WPML 109、JSBridge 34、MQTT 61；核心域（device/wayline/flighttask 等）由校验器强制双示例，非核心域无强制。

---

## 二、DJI-Cloud-Skills 设计合理性分析

### 1）产物边界清晰度 —— 结论：主干清晰，存在局部冗余与一处耦合

**判断：合理，可通过。**

- 流水线单向无环：`fetch_official_docs.py`（抓取）→ `sync_catalog.py`（生成）→ `build_artifacts.py`（产物）→ `validate_catalog.py`（校验）→ `install_skill.py`（安装），职责切分与文件一一对应。
- `catalog/` 是唯一协议事实源，`skills/` 仅 2 个手工文件（SKILL.md + query_catalog.py），`build/` 全部可再生——事实源/产物/手工源三层边界明确，且源与产物经 diff 确认无漂移。
- 早期评估指出的两处边界问题已修复：`validate_catalog.py` 现在读取 `catalog/schema.json`（单一 schema 源），且是 `coverage-report.json` 唯一写者。

**潜在问题：**

- **校验器与生成器循环论证**：`validate_catalog.py` 通过 importlib 加载 `sync_catalog` 并重跑 `collect()` 来比对 ID 集合——"用生成器验证生成器"。一致性（确定性）能验证，但**生成器的系统性漏列抓不到**（WPML 五列丢失全部通过校验，实证了该盲区）。
- **物理副本过多**：同一 entry 数据在仓库内存在 5 份以上（`catalog/endpoints/` 2488 单文件、`references/` 53 聚合片、`references/index.json` 内嵌 operation、`build/install-test/` 副本、各 agent 安装副本）；`catalog/error-codes.json` 与 `references/error-codes.json` md5 字节级相同。
- **残留物未清理**：`build/install-test/` 含 8 个过期文件（早期安装测试残留，内容与当前产物不一致，有误导风险）；根目录 `_tmp_chunk.txt`/`_tmp_media_chunk.txt`/`_tmp_routes.txt` 为调试残留且未入 .gitignore；`__pycache__` 散见。

### 2）架构风格一致性 —— 结论：规范大体统一，错误处理哲学与版本钉扎不统一

**判断：基本合理，有两处系统性不一致。**

**统一面（通过）：**

- 全部脚本仅依赖 Python 标准库；模块级 docstring、snake_case、类型标注、`write_text_lf` 统一 LF 写入、JSON 一律 `ensure_ascii=False`。
- 命名策略全局一致：entry id 为 `{protocol}-{slug}`，tool name 为 `dji_` + id 下划线化、超长统一"截断 55 字符 + sha1 8 位后缀"；产物内 compact 序列化、dist 内 pretty 序列化，规则固定。
- `retry` 对象五字段（automatic/max_attempts/backoff/retry_on/notes）全库固定；分片 100 条上限由校验器强制（references 与 dist by-module 同策略）。
- SKILL.md frontmatter 符合 Agent Skills 规范（name/description ≤1024 字符均有校验）。

**不一致面（需改进）：**

- **三种错误处理哲学并存**：抓取/构建/安装 fail-closed（SystemExit 立即终止）；生成器内部却静默降级（`parse_jsonish` 吞异常返回 None、`table_after` 表头不匹配返回 `[]`——WPML 数据丢失即由此静默发生）；`query_catalog.py` 在 index.json 缺失时静默返回空结果。同一项目对"数据缺失"时而熔断时而静默，排障困难。
- **版本钉扎分散 5 处**：`fetch_official_docs.py --expected-version` 默认值、`validate_catalog.py` 硬编码 `"1.16.1"`、`catalog/schema.json` 版本正则 `^1\.16\.1$`、`SKILL.md` metadata、README 文案。官网升版需多点同步修改，漏改即产生矛盾校验结果。
- **schema 语义双实现**：`validate_catalog.py` 内置手写迷你 JSON Schema 校验器（仅支持 type/enum/minLength/pattern/required 等子集，忽略 `additionalProperties`），是 `catalog/schema.json` 语义的第二份实现；schema 演进时校验器会静默漏检。

### 3）Token 消耗效率 —— 结论：主路径设计优秀，存在索引与工具定义冗余

**判断：查询主路径高效，存储层有明确可压缩空间。**

**高效面（通过）：**

- SKILL.md 仅 80 行，渐进式披露路径清晰：query_catalog.py 摘要（只输出 id/name/protocol/module/operation 的匹配子集）→ 按需 `--full` → 单 shard 阅读。agent 常规查询不接触大文件。
- `catalog/index.json` 条目极简（约 260B/条）；by-module 分片 ≤100 条且有校验强制；skill 包内全部 compact 序列化。

**冗余面（需改进）：**

- `references/index.json` 872KB，内嵌每条的完整 `operation` 对象（与 53 个 shard 内容重复）。SKILL.md 将其列为 query 工具的 fallback，agent 一旦直读约消耗 **22 万 token**。
- 同一 tool 集合 4 份序列化副本：`assets/openai-tools.json` 1.36MB + `assets/claude-tools.json` 1.29MB（compact）+ `dist/*/tools.json` 1.9MB/1.7MB（pretty），外加两套 by-module 与 406KB `tool-map.json`；每个安装副本再复制一份。
- 仓库内检索放大：`catalog/`、`build/`、`install-test/` 三处同内容导致 grep/glob 命中数放大 3–5 倍，增加 agent 浏览成本。
- MQTT 最大 shard `mqtt-remote-control-01.json` 302KB（约 7.5 万 token），接近"单片可读"上限。

---

## 三、具体修改建议

按优先级排列（P0 = 影响生成代码正确性；P1 = 影响数据可用性与可维护性；P2 = 卫生与效率）。

| # | 优先级 | 问题 | 修改建议 | 落点 |
|---|--------|------|----------|------|
| 1 | P0 | WPML 五列丢失 | `parameter()` 增加 WPML 中文表头映射：`取值与释义`→constraints、`名称`→description、`是否必需（默认值）`→required 解析（"必需元素"→true，含默认值文本→提取默认值）、`单位`→constraints 拼接、`支持机型`→写入 entry.compatibility | `sync_catalog.py:169 parameter()`、`parse_wpml()` |
| 2 | P0 | 中文类型未映射 | `normalize_type()` 增加中文映射：整型/整形→integer、浮点型→number、布尔型/布尔形→boolean、字符串→string、枚举_int→integer；struct→object | `sync_catalog.py:156 normalize_type()` |
| 3 | P0 | JSBridge 模块哈希化 | 解析时跳过"概述"汇总表（或最后处理并允许语义章节覆盖）；为中文标题建显式映射：设备上云→thing、直播→live、地图元素→map、TSA态势感知→tsa、航线→wayline、MOP→mop | `sync_catalog.py:534 parse_jsbridge()` |
| 4 | P1 | MQTT struct 扁平化 | `parameter()` 保留 `»` 层级：新增 `parent` 字段记录父路径；struct 类型 `type` 改 `object`；`unique_parameters` 按 `(parent, name)` 去重 | `sync_catalog.py:169/191` |
| 5 | P1 | 校验器盲区 | 增加字段级完整性断言：WPML description/constraints 非空率、module 白名单（拒绝纯哈希值）、constraints 可解析性检查（非法时打 `constraints_format: "unstructured"` 标记而非静默透传） | `validate_catalog.py` |
| 6 | P1 | 版本钉扎分散 | 版本号单点化：三脚本统一从 `manifest.json`（或共享常量模块）读取 expected version；schema.json 的版本正则由生成器写入而非手写 | `fetch_official_docs.py`、`validate_catalog.py`、`sync_catalog.py` |
| 7 | P2 | 残留与副本 | 删除 `build/install-test/`、`_tmp_*.txt`、`__pycache__`；`.gitignore` 增加 `_tmp_*`；`error-codes.json` 在 references 中改为构建期复制（已是）并在 README 明确以 catalog 为准 | 仓库根目录 |
| 8 | P2 | 索引臃肿 | `references/index.json` 移除内嵌 `operation`（与 catalog/index.json 对齐，仅留 id/name/protocol/module/file），872KB→约 650KB 且消除重复；或 SKILL.md 明确"禁止直读 index.json，只用 query_catalog.py" | `build_artifacts.py:132`、`SKILL.md` |
| 9 | P2 | tool 定义 4 份 | skill 包 `assets/` 与 `build/dist/` 二选一作为唯一发布物，另一处改为安装期生成或引用；`tool-map.json` 合并进 dist index | `build_artifacts.py` |
| 10 | P2 | 错误处理哲学 | 约定规则：解析器对"预期内缺表"可降级但须记入 coverage-report 的 known exceptions；"预期必须有"的解析失败一律 fail-closed；`query_catalog.py` 索引缺失时显式报错退出码 2 | `sync_catalog.py`、`query_catalog.py` |

**修复后验证闭环**：建议 1–4 实施完毕后，依次运行 `sync_catalog.py → build_artifacts.py → validate_catalog.py --check-determinism`，并按建议 5 新增的断言确认 WPML 非空率达标、JSBridge 无哈希模块名。

---

## 附：修复实施记录（2026-07-23 当日完成）

| 建议 | 状态 | 验证结果 |
|------|------|----------|
| 1 WPML 中文表头映射 | ✅ 已实施 | 130/130 条 description、compatibility 补全（hoverTime：type=number、必需、"> 0；单位：s"、7 机型） |
| 2 中文类型映射 + struct→object | ✅ 已实施 | WPML 类型正确分布（number 26/integer 34/boolean 24/string 46）；MQTT struct 全部 object |
| 3 JSBridge 模块分类 | ✅ 已实施 | 49 条全为语义模块（api 3/live 7/map 2/media 8/overview 20/thing 5/ws 4），哈希分片消除 |
| 4 MQTT struct 层级 | ✅ 已实施 | 子字段带 `parent`（file→url/fingerprint、ready_conditions→battery_capacity 等）；工具 schema 子级参数加 parent 前缀 |
| 5 校验器断言 | ✅ 已实施 | 哈希模块名拒绝、WPML 三项完整性断言、(parent,name) 去重键，全部生效 |
| 6 版本单点化 | ✅ 部分实施 | validate_catalog.py 改从 manifest.json 读取期望值（fetch CLI 默认值与 schema.json 正则保留为熔断闸） |
| 7 残留清理 | ✅ 已完成(07-24) | install-test、_tmp_*、__pycache__ 及全部备份目录已入回收站；`.gitignore` 已补 `_tmp_*` |
| 8 索引瘦身 | ✅ 已实施(07-24) | references/index.json 去除内嵌 operation：872KB→345KB；query_catalog 改为"索引快速路 + 零命中全扫兜底"，operation 字段检索召回保持（services_reply 命中 314 条）；SKILL.md 明示禁止整读索引 |
| 9 tool 定义去重 | ✅ 已实施(07-24) | dist/ 仅保留 by-module 分片与注册表（移除 2 份 pretty 全量 tools.json 与 tool-map.json），全量工具文件唯一定位于 Skill 包 assets/；validate_tools 改从 assets 校验 |
| 10 错误处理哲学 | ✅ 已实施(07-24) | sync_catalog 文档化降级约定；JSBridge 未映射标题 fail-loud（拒绝哈希模块）；validate 新增五协议参数描述率基线断言（http 0.95/mqtt 0.99/ws 0.95/wpml 1.0/jsbridge 0.5） |

**全量验证**：`sync_catalog.py` 生成 2488 条 → `build_artifacts.py` 重建 → `validate_catalog.py` 输出 "Validated 2488 entries; source coverage and adapters passed"；deprecated 保持 10 条；示例覆盖 2284 条不变。07-24 复审：生成器双跑输出字节一致（sha 75a02e82），磁盘 catalog 与生成器输出一致，build_tools 双跑一致；含基线断言的校验再次全绿。
**环境说明**：本环境安全层拦截脚本内 `rmtree`（回收站不可用），重建采用"改名避让"完成；`--check-determinism` 因内部重跑会触发删除而跳过，07-24 已用内存等价方案（双跑 collect/build_tools 比对）替代验证通过。
