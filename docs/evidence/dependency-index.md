# Gradle 依赖索引

`agent-dev/tools/dependency_index.py` 为当前插件项目建立本地依赖索引，用于减少反复检查陌生 JAR 的成本。它是**定位工具**，不是对版本兼容、运行时语义或 API 可用性的替代证明。

## 调用通道与同步权限

首次索引由 Skill 初始化器建立。日常查询必须先按当前会话选择唯一通道：可调用 `pluginbase_dependency_index` 时，遵循 `dependency-index-zoo-tool.md` 且只调用该工具；未提供该工具时，遵循 `dependency-index-cli.md` 并直接运行具体 CLI 查询。两条通道都禁止 `status` 预检。

`sync` 不是查询前置步骤。只有 Agent 已实际添加、删除或变更 Gradle 依赖坐标、版本或所属配置，或用户明确要求同步/重建时，才允许从项目根目录运行：

```text
python agent-dev/tools/dependency_index.py sync --project .
```

工具必须找到项目自己的 `gradlew` 或 `gradlew.bat`，并临时注入 Gradle init script，收集所有 Gradle 子项目及每个可解析配置的真实解析结果。它不读取 `build.gradle.kts` 文本来推测依赖，也不会写入项目构建文件。同步完成后，若 Zoo 工具可用，查询立即回到 Zoo 工具。

索引保存于本机 `agent-dev/state/indexes/dependency-index.sqlite3`，包括：

- Gradle 模块、可解析配置、解析后的构件、依赖边与失败项；
- 实际 JAR 的 `SHA-256`、类名与二进制内部类名；
- 由目标项目 Gradle 解析的同版本 `sources.jar` 与 `javadoc.jar` 的本机路径和哈希；
- 实际运行 JAR 的二进制 `.class` 中可解析的公开类型、字段、构造器、方法描述符与直接继承关系；这也是所有索引签名与所属类型的唯一权威来源；
- 由 sources/Javadoc 唯一确认的源码位置、类型/成员摘要，最多 `420` 字符；它们只补全资料，不会新增、删除或改写字节码签名。

同步按构件依次执行清晰阶段：扫描类名、读取运行字节码、读取源码、读取说明页面、连接资料与写入完整公开成员记录。Gradle 返回全部唯一构件的位置和资料路径后，默认使用不超过 `8` 个工作线程并行读取、解压和分析不同构件；工作线程只产生纯内存结果，绝不访问 SQLite。主线程通过有界结果队列逐个接收完成构件，并独占 SQLite 连接、事务和构件写入。可用 `sync --workers N` 在 `1` 到 `8` 间覆盖线程数；结果按完成顺序写入，索引内容不依赖写入顺序。类名和公开 API 均以每批 `2,000` 条写入基础表；运行字节码每处理 `200` 个 `.class` 刷新一次 `字节码结构 N/M`，并行阶段显示工作线程数和 `已写入构件 N/M`。资料关联在首次写入 `api` 前完成，源码位置、说明页面和短摘要随同一条公开成员记录一次写入，不会执行第二次成员更新。全部构件的基础数据写完后，才在 `4/4` 阶段一次性创建普通查询索引、重建两份全文索引；因此方法签名仍可查询到对应的 Javadoc 路径和摘要，同时避免每个 `.class` 或公开签名插入时维护索引。二进制 JAR 与资料归档的 `SHA-256` 会按路径、大小和修改时间复用，避免重复顺序读取。

默认同步公开 API。目标项目自己的 Gradle Wrapper 会使用项目已声明的仓库、镜像、认证、缓存与网络策略解析 `sources.jar`、`javadoc.jar`；索引器不扫描缓存猜测文件，也不会自行联网下载。第一阶段会实时转发 Gradle 输出，并在首次解析每个资料变体时显示 `解析资料构件 N：<GAV>:sources|javadoc`；索引 JSON 标记区保持静默，不会刷出大段机器数据。Python 只读取 Gradle 返回归档中有机会关联的单个条目，不复制归档、不解包 HTML/JS/CSS/图片，也不会把完整 Javadoc 保存到 `state/`。资料文件优先由完整运行类名直接定位；只有完整路径不存在时，才一次性建立源码简单文件名目录并且仅接受唯一候选，供重定位场景回退。每个命中的源码文件和说明页面在当前构件中最多读取、分析一次；说明页面顺序解析后按成员名保存候选，成员不会重复扫描完整页面。即使 sources 存在，所有类结构和签名仍从最终运行 JAR 读取，因此可正确处理不规范构件、Shadow 合并和重定位。资料补全仅在成员种类、名称、参数数量、数组维度、基本类型和可稳定比较的引用类型结构均唯一对应时写入；有重载、多个候选、解析失败或任何歧义时不附加资料，绝不猜测。若只需先查看依赖/类名，可使用 `--no-api`；该模式会要求 Gradle 跳过资料变体解析，此时成员查询不会有完整结果。

## 缓存与安全边界

SQLite 索引属于 `agent-dev/state/`，不提交、不分发、不参与插件构建或 Shadow。`state/environment.json` 存在时，工具只使用其中的 `gradleUserHomes`；未填写或无效时停止，绝不自行扫描默认 C 盘缓存。`--gradle-user-home` 仅为单次覆盖。

资料归档只由 Gradle 解析，因而与项目实际仓库、镜像、认证、版本替换和缓存策略一致；资料归档解析失败只影响该构件的源码/Javadoc 丰富信息，不会中断整次同步。每个归档和二进制 JAR 均记录哈希，但原始归档不会进入索引状态。没有有效 GAV、没有资料变体或 Gradle 解析资料失败的构件仍会从实际二进制 JAR 提取公开结构；资料未能唯一匹配时保留准确字节码签名并省略文档，绝不猜测。每次 `sync` 都会在复用完归档哈希后删除旧 SQLite 索引，并由空临时库完整重建；因此移除的依赖、旧 API 与垃圾数据不会残留。同步失败时不保留可查询的旧索引，修复问题后重新运行 `sync`。首次 SQLite 同步还会自动清理旧版 `dependency-index.json` 和 `indexes/artifacts/` 中由旧工具遗留的归档/解包内容。

构建脚本、设置脚本、版本目录、锁文件或 Wrapper 内容变化会使索引过期。查询不会自动执行 Gradle，也不得因发现过期而自行同步；仅在本节定义的依赖修改或用户明确要求条件满足时重建。

## 查询规则

具体 Zoo 参数映射见 `dependency-index-zoo-tool.md`，无 Zoo 时的 CLI 示例见 `dependency-index-cli.md`。默认结果最多 `8` 条：类查询显示类名与 GAV；成员查询显示公开声明、所属类型、GAV 与 source 位置；依赖查询默认只显示实际构件。需要更多结果时使用通道对应的 `limit`/`--limit`、`offset`/`--offset`。成员查询使用 Zoo `verbose: true` 或 CLI `--verbose` 时，会像 IDE 悬停一样附加 SQLite 中唯一确认的 Javadoc 页面条目路径和短摘要；无资料或关联有歧义时不猜测。需要来源、哈希和主 JAR、sources/Javadoc 本机路径时，对 `show` 使用 Zoo `verbose: true`，或 CLI `--verbose`。无索引、索引过期、解析失败或资料不足都会输出短错误，不输出堆栈；这些结果本身不授权同步。

`classes` 和未限定的 `members` 是不区分大小写的模糊搜索。已知接收者类型时，使用 `members <成员关键词> --type <完整或简单类型名>`；索引会沿已记录的 `extends`/`implements` 链搜索该类型可见成员，并明确输出“声明于 <父类型> | 继承 N”。例如 `PlayerInventory` 可见的 `addItem` 实际声明于 `Inventory`。关系来自 sources 类型声明或字节码直接父类/接口；遇到无法解析、未索引或歧义的父类型时不会猜测。

`members` 的命中只能说明索引到对应版本的公开声明。写入版本敏感调用前，仍须依据返回的 GAV、归档哈希、sources 行号/Javadoc 页面，按 `query-playbook.md` 复核完整重载、弃用、注解、线程和语义。

## Zoo Code 适配器

从项目 `.roo/skills/minecraft-pluginbase-development/` 运行初始化脚本时，安装器自动创建 `./.roo/tools/pluginbase-dependency-index.js`，并在同目录自动安装 Zoo 参数校验所需的 `zod@3.25.76`。Zoo 对 `.js` 工具直接加载，避免项目工具经 esbuild 打包时解析不到扩展内部 `@roo-code/types`；模板导出普通工具对象与真实 Zod schema，限定固定索引查询动作，不接受任意命令，返回受限大小的字符串 JSON。`show` 的 `verbose: true` 转发索引 CLI 的 `--verbose`，返回数据库已记录的主 JAR、sources/Javadoc 路径与哈希；`members` 的 `verbose: true` 同样转发该开关，返回已确认的成员 Javadoc 页面条目路径和短摘要。两者均不扫描缓存、不联网、不触发同步。已有同名 `.js` 工具始终保留，不自动覆盖。

Zoo Code Custom Tools 是实验性功能，启用后自动批准工具执行。用户只需在 Zoo Code 的 Experimental 设置启用 Custom Tools，并在工具变更后执行 `Refresh Custom Tools` 或重载窗口。工具已加载的会话必须遵循 `dependency-index-zoo-tool.md`，不得改用 CLI 查询。核心 CLI 不依赖 Zoo；`install-zoo` 子命令仅用于非 `.roo/skills/` 安装路径的维护或修复。
