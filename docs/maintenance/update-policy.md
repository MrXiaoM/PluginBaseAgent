# 文档、资料与依赖更新策略

本资料包要随着模板、PluginBase、Spigot/Paper 和工具演进而维护，但更新不能让“文档版本”“资料版本”“项目依赖版本”彼此脱节。所有更新遵循先锁定、再同步、后比较、最后验证的顺序。

## 三类版本

| 类别 | 位置 | 含义 |
| --- | --- | --- |
| 项目依赖版本 | `build.gradle.kts`、`gradle.properties` | 当前插件实际编译/打包的 API、PluginBase、Shadow 和其它依赖。 |
| 开发包版本 | `agent-dev/docs/`、未来 `agent-dev/tools/`、`agent-dev/registry/` | 当前项目采用的规范、工具协议和资料来源策略。 |
| 本地资料版本 | `agent-dev/state/` 清单 | 实际下载/缓存的 sources、Javadoc、元数据、哈希和索引。 |

三类版本需要可追溯对应，但不要求每次任务都更新。只有依赖、资料或规则变化影响结论时才更新相关层。

## 更新 PluginBase

更新 PluginBase 或模块时：

1. 记录升级前的版本、模块列表、构建结果和已知运行环境；
2. 同步新版本的模块 sources/Javadoc；
3. 对 `BukkitPlugin`、Options、自动注册、调度、工厂、配置与实际使用的模块符号重新查询；
4. 审查模板依赖助手、LibrariesResolver 和 Shadow 规则是否需同步；
5. 检查 `paper` 模块的工厂回退行为没有变化；
6. 重新构建、检查重定位和 `PluginBaseHolders`；
7. 在承诺环境启动，检查生命周期、模块加载、配置重载和停用；
8. 更新证据记录与兼容说明。

不得只提升版本号后依靠旧文档继续推断框架行为。

## 更新 Spigot/Paper

升级 API 时：

1. 明确是编译 API、最低运行版本还是已验证服务器版本变化；
2. 同步前后版本资料，记录 Snapshot 哈希；
3. 检查全部版本敏感调用，尤其 Material、ItemMeta、Inventory、事件、声音、实体、调度和资料对象；
4. 检查 Paper-only 适配层不向 Spigot 主路径泄漏；
5. 构建并分别在承诺的服务端启动；
6. 更新 `plugin.yml` 的 `api-version` 仅在真实最低 API 变化时进行；
7. 更新发布说明中的已验证/未验证范围。

## 更新模板与构建基础设施

模板、Gradle、Shadow、LibrariesResolver 或 Java 设置变化时，比较而非覆盖：

- 插件和构建插件版本；
- Maven 仓库；
- 依赖范围与排除规则；
- Java 初始化与字节码目标；
- `shadowJar` 的运行时 classpath、重定位、重复文件、服务资源和 Holder 索引；
- `plugin.yml` libraries 配置及 BuildConstants 生成；
- 主类 resolver、Options 与 PaperFactory 初始化骨架。

将基础设施升级与业务功能改动分开提交，便于定位回归。

## 更新文档包

当本资料包复制到项目 `agent-dev/` 后：

- 文档、工具和注册表建议一同提交；
- 更新时保留变更说明，特别是 API 选择、PluginBase 模块、工具命令和缓存布局变化；
- 不让文档声称超出当前工具/资料能力的自动化行为；
- 将频繁变化的归档和索引保留在 `state/`，不改动受保护的未来 Skill 目录；
- 更新后运行内部链接、路径和示例命令检查；
- 若文档规则被项目刻意例外，记录例外原因、证据和复审条件。

## 资料失效规则

以下情况使相关资料或记录需要重新同步/复核：

- 构件版本变化；
- Snapshot 坐标的 SHA-256 变化；
- Maven 仓库或来源策略变化；
- PluginBase 模块增删；
- Java、Gradle、Shadow 或解析器升级影响构建行为；
- API 文档出现弃用、实验性或线程语义变化；
- 发现已有记录使用了错误生态、错误版本或不完整签名。

失效不等于立刻删除旧资料：保留清单可用于追溯，但不能继续作为新代码的当前版本证明。
