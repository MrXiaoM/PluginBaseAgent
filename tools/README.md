# Agent 资料与项目验证工具

本目录的脚本只使用 Python 标准库。将整个资料包复制到目标插件项目的 `agent-dev/` 后，从插件项目根目录运行：

```text
python agent-dev/tools/<脚本>.py ...
```

所有下载归档、解包资料、清单和查询结果写入 `agent-dev/state/`；不要把它们打进插件 JAR 或提交到版本控制。

## `api_evidence.py`

用于同步、查询和比较 Spigot/Paper API 的 sources/Javadoc。

```text
python agent-dev/tools/api_evidence.py sync --api spigot --minecraft <用户原样版本>
python agent-dev/tools/api_evidence.py sync --api paper --minecraft <用户原样版本>
python agent-dev/tools/api_evidence.py query --api spigot --minecraft <用户原样版本> --symbol <类名或成员>
python agent-dev/tools/api_evidence.py compare --api spigot --from <旧原样版本> --to <新原样版本> --symbol <类名或成员>
python agent-dev/tools/api_evidence.py status
```

`--minecraft` 是用户提供的 Minecraft 版本原样文本。工具不会将 `1.21.11` 改为 `1.21.1`，也不会将 `26.2` 补成其它旧式格式。若精确 Maven 构件版本与默认 `<minecraft>-R0.1-SNAPSHOT` 不同，显式传入 `--artifact-version`；映射依据必须写入证据记录。

同步顺序是：项目 `state/` 已有资料、显式 `--gradle-user-home`、`GRADLE_USER_HOME`、默认 Gradle 用户目录、注册表 Maven 仓库。每个归档都会记录来源、`SHA-256` 与解包文件数。

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
