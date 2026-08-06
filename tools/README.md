# Agent 依赖资料与项目验证工具

将资料包释放到目标插件项目的 `agent-dev/` 后，从插件项目根目录运行：

```text
python agent-dev/tools/<脚本>.py ...
```

工具不会把第三方二进制 JAR、`sources.jar`、Javadoc 或反编译文本复制到 `agent-dev/state/`。项目 Gradle 管理实际构件；`state/` 只保存 `environment.json`、可重建 SQLite 索引和本地依赖使用笔记。每次恢复任务先读取 `agent-dev/state/environment.json`。

## `dependency_index.py`

从**目标项目自己的 Gradle Wrapper**取得真实多模块解析结果，在 `state/indexes/dependency-index.sqlite3` 建立模块、构件、依赖边、运行 JAR 类名、公开字节码签名与继承关系索引。Gradle 同时按项目实际仓库、镜像、认证和缓存策略解析同版本 `sources.jar`、`javadoc.jar`；索引记录它们的本机路径与哈希，不复制或解包归档。

日常查询通道由 `../docs/evidence/dependency-index-zoo-tool.md` 和 `../docs/evidence/dependency-index-cli.md` 规定：Zoo 工具可用时只能调用 `pluginbase_dependency_index`；未提供 Zoo 工具时才可直接运行 CLI 具体查询。两条通道均禁止 `status` 预检。`sync` 只在 Agent 已实际改变依赖集合或用户明确要求时允许：

```text
python agent-dev/tools/dependency_index.py sync --project .
python agent-dev/tools/dependency_index.py sync --project . --workers 4
```

`sync` 默认以最多 `8` 个工作线程并行读取不同构件的运行 JAR、源码和说明资料；SQLite 仍由主线程单独写入，避免跨线程数据库访问。可用 `--workers 1` 到 `--workers 8` 覆盖线程数；机械硬盘、内存较小或需排查问题时可使用 `--workers 1`。

无 Zoo 工具时的常用查询：

```text
python agent-dev/tools/dependency_index.py modules --project .
python agent-dev/tools/dependency_index.py dependencies --project . --module :
python agent-dev/tools/dependency_index.py classes --project . ItemStack
python agent-dev/tools/dependency_index.py members --project . addItem --type PlayerInventory
python agent-dev/tools/dependency_index.py members --project . echo --type example.api.Sample --verbose
python agent-dev/tools/dependency_index.py show --project . --artifact top.mrxiaom:EvalEx-j8 --verbose
```

全部类型、字段、构造器、方法签名和继承关系都从最终运行 JAR 的 `.class` 字节码获取；多个工作线程会先读取不同构件，并按已发现类型关联必要的 `sources.jar` 与 Javadoc 页面，主线程首次写入公开成员时同时写入唯一可确认的源码位置和短摘要。建立流程不会再次更新同一成员，绝不会新增、删除或改写运行签名。全部基础数据写完后才创建普通查询索引和全文索引；因此方法签名查询仍可返回对应 Javadoc 路径和摘要。对成员查询加 `--verbose`，即可像 IDE 悬停一样在签名下显示已确认的 `Javadoc 页面` 与 `摘要`；自动化 JSON 结果同时给出 `javadoc` 与 `documentation` 字段。无法唯一关联的成员不会显示或猜测资料。同步进度会显示工作线程数、已写入构件数，以及运行字节码、源码、说明页面和资料连接；同一构件内每个命中的源码文件与说明页面最多读取一次。`show --verbose` 返回主 JAR 的 `file`、资料构件的 `sources`/`javadoc` 本机路径与哈希。详细规则见 `../docs/evidence/dependency-index.md`。

### Zoo Code 工具

Skill 初始化器会创建 `./.roo/tools/pluginbase-dependency-index.js`，并在同目录安装 `zod@3.25.76`。Zoo 对 `.js` 工具直接加载，参数是固定 Zod schema，不提供任意 Shell 命令入口。`show` 可设置 `verbose: true`，以返回主 JAR 与 `sources.jar` 路径；`members` 设置 `verbose: true` 时返回已确认的成员 Javadoc 页面路径与摘要。工具加载后必须遵循 `../docs/evidence/dependency-index-zoo-tool.md`，不得改用本 CLI 查询。

## `inspect_dependency.py`

只在已经由依赖索引定位到构件和路径后，用于选择性阅读一个依赖类的实现：

```text
python agent-dev/tools/inspect_dependency.py source --sources <show 返回的 sources 路径> --class <完整类名>
python agent-dev/tools/inspect_dependency.py decompile --jar <show 返回的 file 路径> --class <完整类名>
```

先使用 `source`：它直接从现有 `sources.jar` 读取单个 `.java` 条目，不解包。只有索引显示没有 `sources` 路径时才使用 `decompile`。后者通过 `https://api.github.com/repos/Vineflower/vineflower/releases/latest` 取得最新 Vineflower 正式发布的唯一 JAR 资产，在系统临时目录运行 `java -jar`，只输出目标类，然后自动删除 Vineflower JAR 与反编译输出。

反编译结果只能帮助理解实现，不能覆盖索引的字节码签名，也不能单独证明版本可用性、线程语义或兼容性。不能唯一定位目标源码时工具会停止，拒绝按简单类名猜测。完整规程见 `../docs/evidence/query-playbook.md`。

## `verify_plugin_project.py`

静态检查一个目标插件项目：

```text
python agent-dev/tools/verify_plugin_project.py --project .
python agent-dev/tools/verify_plugin_project.py --project . --jar build/libs/<插件JAR>.jar
python agent-dev/tools/verify_plugin_project.py --project . --json
```

它检查 `build.gradle.kts`、`plugin.yml`、主类、自动注册、Shadow 重定位、`META-INF/PluginBaseHolders`、服务器 API 打包、`PaperFactory` 接入以及不安全的 `Enum.valueOf(...)`/`Material.valueOf(...)` 解析。退出码 `0` 表示未发现静态问题，`1` 表示仅警告，`2` 表示阻断错误或无法分析。

## 安全边界

- 索引查询不会自动同步 Gradle，也不会因无命中、过期或资料不足而猜测 API。
- `inspect_dependency.py` 只读取指定归档中的一个条目；反编译仅接受索引给出的现有主 JAR。
- Vineflower 只从官方 GitHub Releases API 的 HTTPS 资产链接临时下载；不会写入 `state/`、插件源码、`build.gradle.kts` 或 `plugin.yml`。
- 所有依赖使用习惯、重定位结论和已拒绝方案应按 `../docs/evidence/dependency-notes.md` 写入轻量 `state/notes/`，不要保存完整来源或工具输出。
