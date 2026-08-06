# Agent 开发契约

本文件规定 Agent 在本项目中开发 Minecraft 服务端插件时必须遵守的最低规则。若任务与其它文档冲突，优先遵守用户明确要求、目标项目现有构建约束和已验证的目标版本资料；不能以经验替代证据。

## 任务开始时必须确认的事实

在改动代码、构建脚本或资源前，确认并记录：

1. `agent-dev/state/environment.json` 中的持久本地环境信息，特别是 `gradleUserHomes`。上下文压缩后恢复、重新连接或交接任务时也必须重新读取；该文件存在时不得扫描默认 C 盘 Gradle 目录。
2. 目标 Minecraft 版本及最低兼容版本；用户明确给出的版本号必须逐字保留，不得因知识库、旧版命名模式或资料查询失败而擅自改写。
3. 服务器 API 选择：未特别指定时为 **Spigot**；Paper 必须由用户明确选择，或由已验证的需求证明不可替代。
4. 是否允许 NMS、CraftBukkit 或版本包代码；未明确允许时，按不允许处理。
5. `build.gradle.kts` 中现有的 API 坐标、`top.mrxiaom:LibrariesResolver-Gradle` 精确版本、`PluginBase` 模块、可选依赖、Java 目标版本和 Shadow 配置。
6. `LibrariesResolver-Gradle` 的精确版本是全部 PluginBase 模块的统一版本锚点；只从 `pluginBaseModules` 识别实际启用模块，并以该统一版本同步其资料，不得为未启用模块逐个猜测或探测版本。
7. 功能是否需要配置、数据库、GUI、Action、命令、富文本、调度、BungeeCord、动态库、外部插件兼容或嵌入式外部依赖。
8. 若使用 `ItemPacketModifier` 或 `EvalEx-j8`，从项目锁定的 Maven Central GAV 取得 POM、sources/Javadoc，核对实际包名、公开签名、传递依赖、许可证、重定位与运行期线程边界；不得用本资料包示例版本替代项目版本。
9. 涉及已有依赖、PluginBase 模块、服务端 API 或 Shadow 重定位时，先读取相关 `agent-dev/state/notes/*.md`；只采用已验证笔记，版本、依赖或封装改变后立即使相应笔记失效。
10. 遇到陌生 Gradle 依赖时，按 `evidence/dependency-index-zoo-tool.md` 或 `evidence/dependency-index-cli.md` 直接查询实际模块依赖、类、公开字节码签名和继承关系，不执行 `status` 预检。只有 Agent 已实际改变依赖集合或用户明确要求时才允许 `sync`；查询失败、索引过期和资料不足不能触发同步。已知接收者类型时，用类型限定成员搜索沿 `extends`/`implements` 链定位实际声明，不能因实现类型本身未声明成员就误判 API 不存在。

若这些事实影响实现而无法从用户需求和当前项目中确定，先提出最少必要的问题；不得擅自选用 Paper 或 NMS。对陌生或前沿的用户版本号，可按 `server-api/minecraft-version-integrity.md` 使用 Wiki 原样 URL 核验，但不得改写该输入。

## API 选择规则

1. 默认只引用目标 Spigot API 中可证明存在的类型与成员。
2. 选择 Paper 后，仍优先使用兼容的 Bukkit/Spigot 表面；仅把没有等价替代的 Paper 调用隔离在小范围适配层。
3. 不得因为 Paper 继承 Bukkit API 就认定任意 Paper 代码可在 Spigot 服务端运行。
4. 不得把网络帖子、记忆中的方法名、其它版本的编译结果或 IDE 自动补全当作目标版本存在性的证明。
5. 不得把编译 `compileOnly` 成功误认为运行时兼容；仍需核实服务器实现、版本与线程要求。

详见 `server-api/api-selection.md`。

## 证据优先规则

下列情形必须先查询目标版本的源码、Javadoc、Gradle 元数据或已验证的框架资料：

- 服务端 API 的类、方法、构造器、事件、枚举值和常量；
- 事件触发时机、是否可取消、线程要求和弃用状态；
- Paper 专用 API；
- NMS、CraftBukkit 或反射目标；
- `PluginBase` 的模块、Options、生命周期、自动注册、调度器、配置、物品栏和物品编辑行为；
- 外部插件 API、可选依赖和嵌入式外部库的类名；优先用本地依赖索引定位实际 GAV、类、公开签名、继承声明和本机归档路径，再按 `evidence/query-playbook.md` 直接读取 sources，缺少 sources 时才临时反编译主 JAR；
- 依赖坐标、传递依赖、重定位包名和产物资源路径；
- `ItemPacketModifier` 的包回调线程、客户端回传还原与监听器释放；
- `EvalEx-j8` 的表达式 API、可变实例/副本并发语义及数值精度策略。

证据必须能说明**精确版本**、**来源类型**、**构件哈希**、**归档内文件或锚点**与**实际签名/描述**。运行签名以最终 JAR 字节码为准；sources/Javadoc 用于补充语义，Vineflower 临时反编译只能说明实现阅读来源。查询完成后，至少将证据保留在开发记录、改动说明或提交说明中；可复用的项目习惯按 `evidence/dependency-notes.md` 精简写入 `state/notes/`。格式见 `evidence/evidence-record-format.md`。

## 禁止猜测与停止条件

出现以下任一情况时，停止编造实现并报告阻塞项：

- 未取得目标 API 或 PluginBase 的对应版本资料；
- 查不到被计划调用的符号；
- 已找到的符号版本不匹配、弃用、实验性或线程限制与需求冲突；
- 缺少外部插件 API、NMS 映射或必要运行环境；
- 无法判断 Paper 专有代码的 Spigot 回退方案；
- 构建、重定位或启动检查已经显示事实与假设不一致。

报告应包含：已确认的信息、已查询的来源、未能证明的部分、可选的后续动作。不得用看似合理的占位类名、反射字符串或宽泛 `try/catch` 掩盖未知接口。

## PluginBase 强制规则

1. 插件主类继承 `top.mrxiaom.pluginbase.BukkitPlugin`，并使用其构造器 `options()` 设定能力。
2. 不得覆写 `onLoad()`、`onEnable()`、`onDisable()`；使用 `beforeLoad()`、`beforeEnable()`、`afterEnable()`、`beforeDisable()` 等框架扩展点。
3. 必须将 `PluginBase` 打入插件 JAR，并将 `top.mrxiaom.pluginbase` 重定位到插件私有包；不把它作为要求服务器额外安装的前置插件。
4. 若使用自动注册模块，必须遵守 `@AutoRegister`、Holder 基类、构造器和 `META-INF/PluginBaseHolders` 的规则。
5. 使用调度、物品栏和物品编辑时，先使用框架抽象；不能直接假设 Bukkit 调度或某个版本的物品 API 满足 Folia/Paper 兼容需求。

详见 `pluginbase/`。

## 修改后的最低验证

每次完成实际改动后，至少执行与变更相符的检查：

1. 检查构建脚本、主类、资源和依赖声明的一致性。
2. 运行项目 Gradle Wrapper 的相关构建任务。
3. 审查 Shadow 产物中 `PluginBase` 与实现依赖的重定位结果。
4. 审查 `plugin.yml` 的主类、`api-version`、依赖、软依赖、命令和 Folia 声明。
5. 若有服务端测试环境，使用目标 API/版本启动并观察插件启用日志。
6. 报告执行过的检查与未能执行的检查，不能把未运行的检查写成已通过。

详细清单见 `quality/build-and-artifact-checklist.md`。
