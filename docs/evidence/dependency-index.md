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
- 由目标项目 Gradle 解析的同版本 `sources.jar` 与 `javadoc.jar` 的本机路径和哈希；
- Java sources 中可识别的公开类型、构造器、方法、字段、继承关系、source 行号，以及最多 `420` 字符的类/成员 Javadoc 摘要；
- 缺少 `sources.jar` 时，二进制 `.class` 中可解析的公开类型、字段、构造器、方法描述符与直接继承关系。

同步使用 Python 标准库 `sqlite3` 批量写入，类与成员使用 SQLite `FTS5` 按需检索；查询只读取匹配的受限结果，不会将整份索引 JSON 载入内存。类名和公开 API 均以每批 `2,000` 条写入基础表；类名会输出当前构件的 `类名 N/M` 进度，公开 API 在来源归档中每处理 `200` 个 Java 文件刷新 `公开 API 文件 N/M`，字节码回退每处理 `200` 个 class 文件刷新 `字节码结构 N/M`。全部构件落盘后才在 `4/4` 阶段一次性从基础表重建两份全文索引，避免每个 `.class` 或公开签名都同步维护一次 FTS。二进制 JAR 与资料归档的 `SHA-256` 会按路径、大小和修改时间复用，避免重复顺序读取。

默认同步公开 API。目标项目自己的 Gradle Wrapper 会使用项目已声明的仓库、镜像、认证、缓存与网络策略解析 `sources.jar`、`javadoc.jar`；索引器不扫描缓存猜测文件，也不会自行联网下载。第一阶段会实时转发 Gradle 输出，并在首次解析每个资料变体时显示 `解析资料构件 N：<GAV>:sources|javadoc`；索引 JSON 标记区保持静默，不会刷出大段机器数据。Python 只流式读取 Gradle 返回的本机归档，不复制归档、不解包 HTML/JS/CSS/图片，也不会把完整 Javadoc 保存到 `state/`。缺少源码时自动改读二进制 JAR 的 class 结构，输出可检索的公开签名和继承关系，但没有参数名、泛型、注解、异常、源码行或 Javadoc；这些记录会在摘要中标为 `字节码回退`。若只需先查看依赖/类名，可使用 `--no-api`；该模式会要求 Gradle 跳过资料变体解析，此时成员查询不会有完整结果。

## 缓存与安全边界

SQLite 索引属于 `agent-dev/state/`，不提交、不分发、不参与插件构建或 Shadow。`state/environment.json` 存在时，工具只使用其中的 `gradleUserHomes`；未填写或无效时停止，绝不自行扫描默认 C 盘缓存。`--gradle-user-home` 仅为单次覆盖。

资料归档只由 Gradle 解析，因而与项目实际仓库、镜像、认证、版本替换和缓存策略一致；资料归档解析失败只影响该构件的源码/Javadoc 丰富信息，不会中断整次同步。每个归档和二进制 JAR 均记录哈希，但原始归档不会进入索引状态。没有有效 GAV、没有资料变体或 Gradle 解析资料失败的构件仍会从实际二进制 JAR 提取公开结构，绝不猜测源码或文档。首次 SQLite 同步会自动清理旧版 `dependency-index.json` 和 `indexes/artifacts/` 中由旧工具遗留的归档/解包内容。

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

`classes` 和未限定的 `members` 是不区分大小写的模糊搜索。已知接收者类型时，使用 `members <成员关键词> --type <完整或简单类型名>`；索引会沿已记录的 `extends`/`implements` 链搜索该类型可见成员，并明确输出“声明于 <父类型> | 继承 N”。例如 `PlayerInventory` 可见的 `addItem` 实际声明于 `Inventory`。关系来自 sources 类型声明或字节码直接父类/接口；遇到无法解析、未索引或歧义的父类型时不会猜测。

`members` 的命中只能说明索引到对应版本的公开声明。写入版本敏感调用前，仍须依据返回的 GAV、归档哈希、sources 行号/Javadoc 页面，按 `query-playbook.md` 复核完整重载、弃用、注解、线程和语义。

## Zoo Code 适配器

从项目 `.roo/skills/minecraft-pluginbase-development/` 运行初始化脚本时，安装器自动创建 `./.roo/tools/pluginbase-dependency-index.ts`；已有同名文件保留，不自动覆盖。模板使用 Zoo 官方 `defineCustomTool` 与参数 schema，限定固定索引查询动作，不接受任意命令；返回受限大小的字符串 JSON。

Zoo Code Custom Tools 是实验性功能，启用后自动批准工具执行。用户只需在 Zoo Code 的 Experimental 设置启用 Custom Tools，并在工具变更后执行 `Refresh Custom Tools` 或重载窗口。核心 CLI 不依赖 Zoo；`install-zoo` 子命令仅用于非 `.roo/skills/` 安装路径的维护或修复。
