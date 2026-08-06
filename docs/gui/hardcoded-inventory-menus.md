# 硬编码箱子容器菜单

本文中的“菜单”是 Minecraft 服务端通过 `Inventory` 打开的**箱子容器界面**，不是客户端原生图形界面，也不是浏览器/桌面 GUI。它由服务端库存、`ItemStack`、格子索引和库存事件组成；玩家客户端只显示服务端创建并打开的容器。

本页讨论菜单结构、格子语义和交互逻辑由 Java 代码定义的场景。对 YAML 定义布局和图标的菜单，改读 `config-driven-inventory-menus.md`。

## 适用条件与选择

优先选择硬编码菜单的情况：

- 格子、物品、可见性或标题依赖复杂的运行期状态；
- 交互包含临时输入、事务确认、异步查询、分页、父菜单返回或细粒度权限判断；
- 菜单的行为是稳定业务逻辑，不应交给服主通过 YAML 任意改写；
- 配置仅用于文字、物品外观或少量业务参数，而不承担完整菜单模型。

不要因为菜单“看起来只有几格”就跳过设计。每个菜单仍要明确：顶部箱子容器的大小和 slot 语义、玩家背包是否可操作、每种点击类型的处理、刷新时机、关闭行为和异步结果失效条件。

## 实现前必须取证

计划阶段先读取当前项目的 `build.gradle.kts`：

1. 从 `top.mrxiaom:LibrariesResolver-Gradle` 取得 PluginBase 的统一精确版本。
2. 确认 `pluginBaseModules` 已包含 `gui`；同时确认是否需要 `paper` 提供 Spigot/Paper 双端库存工厂回退。
3. 按 `../evidence/dependency-index-zoo-tool.md` 或 `../evidence/dependency-index-cli.md` 查询项目实际解析的 GUI 构件，定位 `IGuiHolder`、`GuiManager` 和计划调用的成员；需要完整实现语义时，再按 `../evidence/query-playbook.md` 直接读取其 `sources.jar`。
4. 若菜单会使用 `ItemEditor`、`InventoryFactory`、物品 NBT、Action 或语言消息，确认实际已解析的对应模块构件；不要因 `gui` 已引入就假定这些能力存在。
5. 阅读目标项目已有的 Holder、菜单和 `plugin.yml`。框架源码证明能力边界，不是可直接复制的完整业务菜单示例。

若找不到实际解析的 `gui` 构件或计划调用的符号，不得根据其它版本、其它插件或记忆猜测签名；查询失败本身不允许自动同步。

## 框架职责与每玩家实例

`IGuiHolder` 是箱子菜单实例的核心接口：它同时是顶部库存的 `InventoryHolder`，提供目标玩家、`newInventory()`、点击、拖拽和关闭回调。`GuiManager` 通过**顶部库存**的 Holder 识别本框架菜单，并将库存事件路由给该实例。

因此遵守以下边界：

- 每次为玩家打开菜单时创建独立实例；不要将可变的玩家、分页、选择项、点击锁或异步请求状态保存到共享单例菜单对象。
- `newInventory()` 创建顶部 `Inventory` 时，必须将当前 `IGuiHolder` 作为 Holder，并将创建结果保存给 `getInventory()`；否则 `GuiManager` 会拒绝打开该菜单。
- 用 `open()` 或 `GuiManager.inst().openGui(...)` 打开菜单，让框架调度器处理打开操作；不要在不明线程中直接调用 Bukkit 打开库存。
- `GuiManager` 已统一转发 `InventoryClickEvent`、`InventoryDragEvent`、`InventoryCloseEvent` 和 `PlayerQuitEvent`。菜单仍必须实现自身的状态清理、事务取消和异步结果失效策略。
- 只根据框架传入的顶层 `InventoryViewAccessor` 和 slot 判断菜单操作；不能因玩家当前打开任意容器就处理事件。

当前项目实际解析的 GUI 构件中 `GuiManager`、`IGuiHolder` 的字节码签名与同版本资料是生命周期和事件路由的依据；项目具体的库存创建、标题处理和兼容工厂仍以当前版本资料与项目已有基线为准。

## 推荐结构

将菜单代码放在项目的 `gui/` 包，业务状态和数据访问保留在对应的 `manager/`、`data/` 或服务层。一个典型结构是：

```text
src/main/java/<主包名>/
  gui/
    RewardMenu.java              # 仅负责箱子菜单实例和 slot 路由
  manager/
    RewardManager.java           # 领域查询、领取/事务边界
  data/
    RewardState.java             # 菜单显示需要的稳定数据快照
```

菜单类应承担：

- 保存玩家、当前领域数据快照、父菜单引用和一次打开会话所需状态；
- 创建顶部库存并填充物品；
- 将顶部 slot 映射为明确的业务动作；
- 在点击后取消不允许的库存操作；
- 在需要时刷新当前实例，或安全打开新的父/子菜单。

菜单类不应承担：

- 长时间数据库或网络 I/O；
- 无边界的全服扫描；
- 通过静态全局变量复用某个玩家的会话状态；
- 把所有奖励、交易、权限和配置解析塞入 `onClick(...)`。

## 创建、刷新与交互

### 硬编码图标创建

硬编码菜单中的图标优先复用 PluginBase 的物品工具，不要在每个菜单业务类中重复编写裸 `ItemMeta` 的取得、修改和写回流程。

- 使用 Adventure 文本、MiniMessage 或需要跨 Spigot/Paper 统一处理名称与 Lore 时，优先使用 `AdventureItemStack`。它通过主类初始化的 `ItemEditor` 处理组件文本；基础图标可用 `AdventureItemStack.buildItem(...)` 创建，再按当前版本已验证的接口补充其它元数据。
- 例如，当前资料中的 `AdventureItemStack.buildItem(Material, Integer, String, List<String>)` 会创建物品、设置名称和 MiniMessage Lore，并在指定时写入自定义模型数据：

  ```java
  ItemStack icon = AdventureItemStack.buildItem(
      Material.CHEST,
      1001,
      "<gold>领取奖励",
      List.of("<gray>点击领取当前可用奖励")
  );
  ```

- 对不使用 Adventure 的既有项目、原始颜色文本，或发光、模型数据、物品模型等辅助操作，使用 `ItemStackUtil` 的已验证方法，例如 `setItemDisplayName(...)`、`setItemLore(...)`、`setGlow(...)`、`setCustomModelData(...)` 与 `setItemModel(...)`；不要因方便直接散落 `ItemMeta` 操作。
- 图标需要保留或附加物品自定义数据时，构建脚本已安装 `item-nbt-api` 就使用该依赖；不得改用 `PersistentDataContainer` 作为同一用途的替代方案。
- `Material`、自定义模型、物品模型和具体工具方法都必须以目标 Minecraft/PluginBase 版本资料为准。当前文档的示例表达工具分层，不允许跳过依赖索引定位与同版本资料复核后猜测重载或版本可用性。

### 创建和填充

`newInventory()` 应创建符合布局的顶部箱子容器，并立即填充初始物品。动态物品生成应接受当前玩家和当前会话状态；不要把另一个玩家的 `ItemStack`、Placeholder 或权限结果复用给当前玩家。

刷新已有菜单时，只更新当前实例的顶部库存。刷新前重新确认：玩家仍在线、当前打开的顶部 Holder 仍是本实例、所依赖业务数据仍有效。需要客户端同步时使用当前框架版本已验证的库存更新路径。

### 点击与拖拽

在 `onClick(...)` 内：

1. 先取消默认操作，除非该 slot 被设计为允许玩家放入/取出物品；
2. 只处理顶部菜单的有效 slot 和已定义图标；
3. 区分左键、右键、Shift、数字键、双击、丢弃键等会影响业务语义的操作；不支持的操作保持取消；
4. 对提交、购买、领取等非幂等操作设定每实例点击锁或事务状态，防止双击重入；
5. 将耗时工作交给合适的异步路径，完成后通过 PluginBase 调度器回到可操作库存的上下文；
6. 异步回调执行前再次确认玩家、菜单实例、业务版本和关闭状态，过期结果不得刷新已关闭或已切换的菜单。

`onDrag(...)` 默认应拒绝拖拽。若业务需要输入槽，必须依据原始 slot 集合精确允许目标顶部格，不能仅靠“拖拽发生时刷新”掩盖物品复制、移动或丢失问题。

### 关闭、退出与跳转

`onClose(...)` 和玩家退出都可能结束菜单会话。关闭时释放临时引用、取消可取消任务、使异步结果失效，并定义输入物品的返还/保存/丢弃策略。不要假定点击后必然仍处于打开状态。

父/子菜单跳转应保存**实例级**父菜单引用或可重新创建菜单所需的稳定参数；返回前确认父实例仍适用。异步操作完成后需要重开菜单时，应在调度器上重新验证玩家在线和权限。

## 物品数据与兼容

- 物品展示和跨 Spigot/Paper 兼容优先使用 `AdventureItemStack`、`ItemStackUtil` 与项目已接入的 `ItemEditor`、`InventoryFactory` 或 `paper` 模块工厂；`paper` 模块不允许直接导入 Paper-only 业务 API。
- 构建脚本已安装 `item-nbt-api` 时，菜单物品的自定义数据只能使用该依赖；不得用 `PersistentDataContainer` 作为同一用途的替代方案。
- 不把显示名称、Lore、材质或自定义模型数据的跨版本行为当作常识；按目标 API 和框架版本查询资料。

## 最低验证

提交前至少检查：

- 菜单模块、`gui` 模块和可选 `paper` 模块已按项目统一版本声明；
- 顶部库存 Holder 是当前菜单实例；
- 图标通过 `AdventureItemStack` 或 `ItemStackUtil` 的已验证方法创建/编辑，没有在菜单业务代码重复散落裸 `ItemMeta` 写入；
- 点击、拖拽、关闭、玩家退出、重复点击和异步回写都有明确处理；
- 玩家背包、输入槽和顶部库存的允许/取消策略经人工走查；
- `python agent-dev/tools/verify_plugin_project.py --project .`、Gradle Wrapper 构建和最终 JAR 检查已执行；
- 在目标服务端手工验证打开、常用点击、关闭、重开、异常路径和至少一条异步/刷新路径。未执行的服务端验证必须如实记录。
