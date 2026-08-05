# Agent 资料与项目验证工具

本目录的脚本只使用 Python 标准库。将整个资料包复制到目标插件项目的 `agent-dev/` 后，从插件项目根目录运行：

```text
python agent-dev/tools/<脚本>.py ...
```

所有下载归档、解包资料、清单和查询结果写入 `agent-dev/state/`；不要把它们打进插件 JAR 或提交到版本控制。首次使用前填写 `agent-dev/state/environment.json` 的 `gradleUserHomes`，记录本机实际 Gradle 缓存目录；每次恢复任务先读取该文件。

## `api_evidence.py`

用于同步、查询和比较 Spigot/Paper API 的 sources/Javadoc。

```text
python agent-dev/tools/api_evidence.py sync --api spigot --minecraft <用户原样版本>
python agent-dev/tools/api_evidence.py sync --api paper --minecraft <用户原样版本>
python agent-dev/tools/api_evidence.py query --api spigot --minecraft <用户原样版本> --symbol <类名或成员关键词>
python agent-dev/tools/api_evidence.py query --api spigot --minecraft <用户原样版本> --type PlayerInventory --member addItem
python agent-dev/tools/api_evidence.py compare --api spigot --from <旧原样版本> --to <新原样版本> --symbol <类名或成员>
python agent-dev/tools/api_evidence.py status
```

`--symbol` 是不区分大小写的文本搜索，适合先发现候选类型或成员。若已知接收者类型，优先使用 `--type <完整或简单类型名> --member <成员片段>`：工具会搜索该类型及其已解析的 `extends`/`implements` 链，并报告成员实际声明类型和继承距离。例如 `PlayerInventory` 本身不声明 `addItem`，但可从 `Inventory` 继承。`--minecraft` 是用户提供的 Minecraft 版本原样文本。工具不会将 `1.21.11` 改为 `1.21.1`，也不会将 `26.2` 补成其它旧式格式。若精确 Maven 构件版本与默认 `<minecraft>-R0.1-SNAPSHOT` 不同，显式传入 `--artifact-version`；映射依据必须写入证据记录。

同步顺序是：项目 `state/` 已有资料、显式 `--gradle-user-home`、`state/environment.json` 的 `gradleUserHomes`、注册表 Maven 仓库。只有不存在 `environment.json` 时，才回退到 `GRADLE_USER_HOME` 与默认 Gradle 用户目录；配置文件存在但路径为空/无效时会停止，绝不隐式搜索默认 C 盘目录。每个归档都会记录来源、`SHA-256` 与解包文件数。

## `pluginbase_evidence.py`

用于按模块同步、查询和比较 PluginBase 资料。

```text
python agent-dev/tools/pluginbase_evidence.py modules
python agent-dev/tools/pluginbase_evidence.py sync --version <PluginBase版本> --module library
python agent-dev/tools/pluginbase_evidence.py query --version <PluginBase版本> --module library --symbol BukkitPlugin
python agent-dev/tools/pluginbase_evidence.py compare --from <旧版本> --to <新版本> --module library --symbol valueOr
```

PluginBase 资料默认从 Maven Central 的 `top.mrxiaom.pluginbase` 坐标下载。Central 的 Javadoc 为控制每月发布大小而只保留 HTML；工具直接查询源码和 HTML，不依赖被排除的 JavaScript、CSS、字体或搜索索引。

若 Central 无法取得**完整的 sources 与 Javadoc 资料集**，工具才会整体回退到 JitPack。JitPack 对全部模块统一使用精确 group `top.mrxiaom.PluginBase`；其中 `PluginBase` 的大小写不可改变。

## `dependency_index.py`

用于从**目标项目自己的 Gradle Wrapper**取得真实的多模块解析结果，并在 `state/indexes/dependency-index.sqlite3` 建立依赖、JAR 类名、公开 Java API 签名与继承关系索引。它不解析 `build.gradle.kts` 文本来猜测依赖，也不会修改目标构建文件；临时 Gradle init script 在命令结束后删除。

```text
python agent-dev/tools/dependency_index.py sync --project .
python agent-dev/tools/dependency_index.py status --project .
python agent-dev/tools/dependency_index.py modules --project .
python agent-dev/tools/dependency_index.py dependencies --project . --module :
python agent-dev/tools/dependency_index.py classes --project . <类名或包关键词>
python agent-dev/tools/dependency_index.py members --project . <类型、方法、字段或签名关键词>
python agent-dev/tools/dependency_index.py members --project . addItem --type PlayerInventory
python agent-dev/tools/dependency_index.py show --project . --artifact <GAV或哈希前缀>
```

`sync` 对每个可解析 Gradle 配置记录解析后的构件、项目/传递依赖边和失败项；Gradle 还会按项目实际仓库、镜像、认证与缓存策略解析同版本 `sources.jar`、`javadoc.jar`。Python 不扫描 Gradle 缓存猜测资料，也不自行联网下载；它只流式读取 Gradle 返回的本机归档，索引公开 Java 类型、构造器、方法、字段、继承关系与短文档摘要。第 `1/4` 阶段实时转发 Gradle 日志，并在首次解析资料变体时显示 `解析资料构件 N：<GAV>:sources|javadoc`；机器索引 JSON 不会输出到终端。缺少源码时，工具会直接解析二进制 `.class` 的公开类型、字段、构造器、方法描述符与直接继承关系，而不是只保留类名。类名和公开 API 都以每批 `2,000` 条写入 SQLite；类名显示 `类名 N/M`，源码 API 显示 `公开 API 文件 N/M`，字节码回退显示 `字节码结构 N/M`。所有构件完成后才一次性重建 SQLite `FTS5` 类名与 API 索引，避免逐条维护全文索引；归档和二进制 JAR 哈希会按文件状态复用。同步还会实时显示 Gradle 解析、构件计数、资料处理和最终写入进度。`--no-api` 可只同步依赖与类名，并通知 Gradle 跳过资料变体；字节码签名没有参数名、泛型、注解、异常、源码行或 Javadoc，不能替代版本敏感调用的资料复核。

查询默认最多输出 `8` 条，格式紧凑；`dependencies` 默认只列已解析构件，传递依赖边需显式加 `--transitive`。`classes` 和未限定的 `members` 都是模糊搜索；已知调用者类型时使用 `members <成员> --type <类型>`，它会沿已索引 `extends`/`implements` 链定位成员声明，并标注继承距离。使用 `--limit`、`--offset` 分页，使用 `--verbose` 查看路径、哈希与来源，使用 `--json` 供自动化工具调用。索引过期、缺失或解析失败时，查询不会静默重同步；先执行 `sync`，再根据 `sources`/Javadoc 命中复核版本敏感调用的签名、弃用、线程与语义。

该工具同样遵守 `state/environment.json`：未传 `--gradle-user-home` 时，环境文件存在就只使用其中的 `gradleUserHomes`，不会扫描默认 C 盘缓存。

### Zoo Code 工具

从项目 `.roo/skills/minecraft-pluginbase-development/` 运行初始化脚本时，安装器会自动创建 `./.roo/tools/pluginbase-dependency-index.js`，并在该工具目录安装 `zod@3.25.76`。Zoo 对 `.js` 工具直接加载，避免项目目录缺少扩展内部 `@roo-code/types` 时的 esbuild 解析失败；参数仍使用真实 Zod schema。已有同名 `.js` 工具会保留，不自动覆盖。随后在 Zoo Code 的 Experimental 设置启用 Custom Tools，并按官方提示执行 `Refresh Custom Tools` 或重载窗口。

Zoo Custom Tools 启用后会**自动批准**执行，因此只应启用已审查的项目工具。适配器只接受固定查询参数，以数组方式调用本 CLI，不提供任意 Shell 命令入口；它只返回紧凑字符串 JSON。`install-zoo` 子命令仅保留给非 `.roo/skills/` 安装路径的维护或修复场景。

## 通用外部依赖资料

`api_evidence.py` 只接受 Spigot/Paper，`pluginbase_evidence.py` 只接受 PluginBase 模块；不要用它们同步 `ItemPacketModifier`、`EvalEx-j8` 或其它通用 Java 库。对于这些库：

1. 从项目 `build.gradle.kts` 读取锁定的完整 GAV；
2. 参照 `agent-dev/registry/artifacts.json` 从 Gradle 缓存或 Maven Central 取得同版本 POM、`sources.jar`、`javadoc.jar`；
3. 按 `agent-dev/docs/evidence/query-playbook.md` 的人工查询流程检查精确类、成员、线程和传递依赖；
4. 将来源、哈希、命中路径与适用边界写入证据记录；
5. 阅读 `agent-dev/docs/external-libraries/item-packet-modifier.md` 或 `agent-dev/docs/external-libraries/evalex-j8.md`，完成相应生命周期、输入与 JAR 验证。

## `verify_plugin_project.py`

用于静态检查一个目标插件项目：

```text
python agent-dev/tools/verify_plugin_project.py --project .
python agent-dev/tools/verify_plugin_project.py --project . --jar build/libs/<插件JAR>.jar
python agent-dev/tools/verify_plugin_project.py --project . --json
```

它检查 `build.gradle.kts`、`plugin.yml`、主类、自动注册、Shadow 重定位、`META-INF/PluginBaseHolders`、服务器 API 打包、`PaperFactory` 接入以及不安全的 `Enum.valueOf(...)`/`Material.valueOf(...)` 解析。

退出码：`0` 表示未发现静态问题，`1` 表示仅警告，`2` 表示存在阻断错误或无法分析。该工具不替代 Gradle 构建、JAR 人工审查和目标服务端启动验证。

## 安全边界

- 工具仅解包 JAR/ZIP 的安全相对路径，拒绝路径逃逸；
- 下载和缓存不会修改插件 `src/`、`build.gradle.kts` 或 `plugin.yml`；
- 查询无命中时会输出“未证明符号存在”，不能把无命中解释成可猜测接口；
- 对陌生 Minecraft 版本，先遵守 `docs/server-api/minecraft-version-integrity.md`；需要确认命名时使用原样版本号访问 Wiki，而不是修改输入。
