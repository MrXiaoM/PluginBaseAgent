# 模块与能力选择

PluginBase 按模块拆分能力。项目应只引入确实使用的模块，并将“选择模块的理由、引用的公共类型和实际解析构件证据”写入改动说明。模块名称只能说明大致领域，不能替代对具体类和方法的查询。

## 选择流程

1. 写明需求需要的能力，而不是先挑模块；例如“可重载语言消息”“跨 Spigot/Paper 的物品编辑”“配置驱动的 Action”。
2. 从 `pluginBaseModules` 确认已声明能力；确实需要新能力时只修改该列表，不读取、不推断、不记录 `LibrariesResolver-Gradle` 的隐式版本。
3. 模块集合实际变化并已获准同步后，查询依赖索引返回的实际解析构件，确认计划调用的模块和符号存在。
4. 检查该模块是否需要额外的服务端 API、动态库、可选依赖或主类覆写。
5. 构建 Shadow JAR，确认模块被重定位并不会被自动注册扫描误处理。

## 模块边界

| 模块 | 可解决的问题 | 接入提示 |
| --- | --- | --- |
| `library` | `BukkitPlugin`、基础接口、通用数据结构、默认 Bukkit 实现、基础工具 | 通常为必需基线。 |
| `misc` | Folia/Bukkit 调度选择、Bungee 通道、配置更新等扩展 | 通常与 `library` 一同使用；所需能力按符号验证。 |
| `paper` | 在同一插件 JAR 中优先使用 Paper 物品/库存实现、不可用时回退 Bukkit 实现 | 用于同时兼容 Spigot 与 Paper；主类覆写两项工厂方法，见 `lifecycle-and-main-class.md`。 |
| `actions` | Action 接口、动作提供器和内建动作 | 配置解释为动作时使用；注册自定义动作前核对提供器 API。它不替代菜单权限、事务或点击锁。 |
| `gui` | 箱子容器菜单管理、Holder、模型、图标、页面等 | 使用框架 `Inventory` 菜单时加入；计划阶段必须查询当前版本 `IGuiHolder`、`GuiManager`、`AbstractGuiModule`/`AbstractGuisModule` 与 `LoadedIcon`，同时确认物品/库存工厂策略。 |
| `l10n` | 语言管理、语言 Holder、消息对象与处理器 | 需要可重载本地化消息时加入；明确消息资源与加载时机。它不管理菜单 slot 或菜单会话状态。 |
| `commands` | 命令参数、命令注入等工具 | 需要其公共能力时加入；普通 Bukkit 命令不因存在该模块而强制迁移。 |
| `temporary-data` | 临时数据相关能力 | 仅在目标版本资料验证后按需要加入。 |
| `magic` | Magic 领域能力 | 仅在确有需求且查证 API 后加入。 |
| `config` | PluginBase 的配置实现 | 仅在代码或依赖明确采用时引入；不要与 Bukkit 配置模型混用而不说明。 |

## Spigot/Paper 双端兼容模式

该模式由 `paper` 模块和 `PaperFactory` 提供，适用条件是：

- 产物希望同时在 Spigot 与 Paper 上运行；
- 项目使用 `ItemEditor`、`InventoryFactory` 或由其支撑的 GUI/物品能力；
- 项目愿意在运行时由框架检测并选择最佳实现。

正确接入包括模块声明和主类覆写两部分：

```kotlin
val pluginBaseModules = base.modules.run { listOf(library, misc, paper) }
```

```java
@Override
public @NotNull ItemEditor initItemEditor() {
    return PaperFactory.createItemEditor();
}

@Override
public @NotNull InventoryFactory initInventoryFactory() {
    return PaperFactory.createInventoryFactory();
}
```

`PaperFactory` 会优先创建 Paper 实现，异常或环境探测不满足时回退 Bukkit 兼容实现。由此得到的兼容性只覆盖其包装的工厂能力；业务代码自己导入的 Paper 专有类型仍必须按 `server-api/paper-extension-rules.md` 隔离和取证。

## 能力与项目层的映射

| 需求 | 建议检查的层 | 额外注意 |
| --- | --- | --- |
| 创建可跨端显示的库存 | `library`、可选 `paper`、可选 `gui` | 通过 `InventoryFactory`；不能直接假设标题或视图 API 一致。 |
| 编辑跨版本物品属性 | `library`、可选 `paper` | 通过 `ItemEditor`；具体属性仍取证。 |
| 多语言消息 | `l10n` | 语言 Holder 注册时机与配置重载顺序。 |
| 配置触发动作 | `actions` | 动作参数、目标选择和异步语义。 |
| Java 硬编码箱子容器菜单 | `gui`、可选 `paper` | 每玩家 `IGuiHolder` 实例、顶层容器 Holder、点击/拖拽/关闭、异步回调和返回链；见 `../gui/hardcoded-inventory-menus.md`。 |
| YAML 配置驱动箱子容器菜单 | `gui`、可选 `actions`、可选 `l10n`、可选 `paper` | 字符布局与图标是共享模型，玩家状态在运行期实例；重载时处理旧界面；见 `../gui/config-driven-inventory-menus.md`。 |
| 重载命令 | `commands` 或普通 Bukkit 命令 | `plugin.yml`、权限和补全一致性。 |
| 可选外部插件支持 | `library` 工具与项目 `depend/` 适配层 | API 保持 `compileOnly`，类加载隔离。 |
| 数据库 | `library` 与项目依赖 | Options、配置、连接生命周期和线程边界。 |

## 不应以模块取代的判断

- `paper` 不等于项目可以编译或运行任意 Paper 专用业务代码；
- `misc` 不等于每种线程或调度任务都自动安全；
- `actions` 不等于任意 YAML 都能安全执行外部命令，也不替代菜单业务前置校验；
- `gui` 不等于无需处理玩家下线、关闭、拖拽、重复点击、重载和数据一致性；
- `l10n` 不等于配置重载无需测试，也不替代菜单模型或 slot 路由；
- `library` 不等于可以绕过目标 Spigot/Paper 版本资料。

只有设计文档未覆盖、当前调用需要精确签名或运行语义时，才通过依赖索引查询实际解析构件的签名、Javadoc 与依赖关系；不将隐式 PluginBase 版本字符串作为 Agent 的查询对象。
