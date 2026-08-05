# Gradle 依赖索引

`agent-dev/tools/dependency_index.py` 为当前插件项目建立本地依赖索引，用于减少反复检查陌生 JAR 的成本。它是**定位工具**，不是对版本兼容、运行时语义或 API 可用性的替代证明。

## 同步范围

从目标项目根目录运行：

```text
python agent-dev/tools/dependency_index.py sync --project .
```

工具必须找到项目自己的 `gradlew` 或 `gradlew.bat`，并临时注入 Gradle init script，收集所有 Gradle 子项目及每个可解析配置的真实解析结果。它不读取 `build.gradle.kts` 文本来推测依赖，也不会写入项目构建文件。

索引保存于本机 `agent-dev/state/indexes/dependency-index.sqlite3`，包括：

- Gradle 模块、可解析配置、解析后的构件、依赖边与失败项；
- 实际 JAR 的 `SHA-256`、类名与二进制内部类名；
- 对有精确 GAV 的构件，匹配版本 `sources.jar` 与 `javadoc.jar` 的来源和哈希；
- Java sources 中可识别的公开类型、构造器、方法、字段、继承关系、source 行号，以及最多 `420` 字符的类/成员 Javadoc 摘要。

同步使用 Python 标准库 `sqlite3` 批量写入，类与成员使用 SQLite `FTS5` 按需检索；查询只读取匹配的受限结果，不会将整份索引 JSON 载入内存。终端会持续显示 `1/4` 至 `4/4` 阶段、当前构件序号，并在单个 sources 归档中每处理 `200` 个 Java 文件刷新 `公开 API 文件 N/M` 进度，避免长时间无输出。

默认同步公开 API。工具直接从 Gradle 缓存原地流式读取 `sources.jar` 和 `javadoc.jar`；缓存未命中时只下载到临时文件，处理后立即删除。它不会复制归档、解包 HTML/JS/CSS/图片，也不会把完整 Javadoc 保存到 `state/`。若只需先查看依赖/类名，可使用 `--no-api`；此时成员查询不会有完整结果。没有 Java sources、只有 Javadoc、或源语言/文档结构不适合可靠解析时，索引会显示资料不足，不得把无结果解释为成员不存在。

## 缓存与安全边界

SQLite 索引属于 `agent-dev/state/`，不提交、不分发、不参与插件构建或 Shadow。`state/environment.json` 存在时，工具只使用其中的 `gradleUserHomes`；未填写或无效时停止，绝不自行扫描默认 C 盘缓存。`--gradle-user-home` 仅为单次覆盖。

同步先原地复用实际 Gradle 缓存中的匹配 `sources.jar`/`javadoc.jar`，再按目标项目仓库与 Maven Central 临时下载。每个归档和二进制 JAR 均记录哈希，但原始归档不会进入索引状态。对没有有效 Maven 坐标的项目/文件依赖，工具仍可索引实际 JAR 类名，但无法猜测或下载相应 sources/Javadoc。首次 SQLite 同步会自动清理旧版 `dependency-index.json` 和 `indexes/artifacts/` 中由旧工具遗留的归档/解包内容。

构建脚本、设置脚本、版本目录、锁文件或 Wrapper 内容变化会使索引过期。查询不会自动执行 Gradle；先显式重新运行 `sync`，避免在一次小查询中意外解析、下载或变更环境。

## 紧凑查询

```text
python agent-dev/tools/dependency_index.py status --project .
python agent-dev/tools/dependency_index.py modules --project .
python agent-dev/tools/dependency_index.py dependencies --project . --module :
python agent-dev/tools/dependency_index.py dependencies --project . --module :feature --transitive
python agent-dev/tools/dependency_index.py classes --project . ItemStack
python agent-dev/tools/dependency_index.py members --project . getDisplayName
python agent-dev/tools/dependency_index.py members --project . addItem --type PlayerInventory
python agent-dev/tools/dependency_index.py show --project . --artifact top.mrxiaom:EvalEx-j8
```

默认输出只有一行摘要和最多 `8` 条记录：类查询显示类名与 GAV；成员查询显示公开声明、所属类型、GAV 与 source 位置；依赖查询默认只显示实际构件。需要更多结果时使用 `--limit`、`--offset`，需要来源、哈希和本机路径时使用 `--verbose`；自动化调用使用 `--json`。无索引、索引过期、解析失败或资料不足都会输出短错误，不输出堆栈。

`classes` 和未限定的 `members` 是不区分大小写的模糊搜索。已知接收者类型时，使用 `members <成员关键词> --type <完整或简单类型名>`；索引会沿已记录的 `extends`/`implements` 链搜索该类型可见成员，并明确输出“声明于 <父类型> | 继承 N”。例如 `PlayerInventory` 可见的 `addItem` 实际声明于 `Inventory`。关系仅来自对应 sources 中的类型声明，遇到无法解析、未索引或歧义的父类型时不会猜测。

`members` 的命中只能说明索引到对应版本的公开声明。写入版本敏感调用前，仍须依据返回的 GAV、归档哈希、sources 行号/Javadoc 页面，按 `query-playbook.md` 复核完整重载、弃用、注解、线程和语义。

## Zoo Code 适配器

从项目 `.roo/skills/minecraft-pluginbase-development/` 运行初始化脚本时，安装器自动创建 `./.roo/tools/pluginbase-dependency-index.ts`；已有同名文件保留，不自动覆盖。模板使用 Zoo 官方 `defineCustomTool` 与参数 schema，限定固定索引查询动作，不接受任意命令；返回受限大小的字符串 JSON。

Zoo Code Custom Tools 是实验性功能，启用后自动批准工具执行。用户只需在 Zoo Code 的 Experimental 设置启用 Custom Tools，并在工具变更后执行 `Refresh Custom Tools` 或重载窗口。核心 CLI 不依赖 Zoo；`install-zoo` 子命令仅用于非 `.roo/skills/` 安装路径的维护或修复。
