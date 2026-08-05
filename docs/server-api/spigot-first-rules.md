# Spigot 优先开发规则

未明确选择 Paper API 时，插件业务代码以目标版本的 Spigot API 为编译和实现基线。Spigot API 的公开包大量使用 `org.bukkit.*`，但类型在某个版本存在、可用或未弃用，都必须由该精确版本资料确认。

## 编码前的 API 检查

每次引入新的服务端类型或成员前，至少确认：

1. 完整类名与导入包；
2. 目标版本中的成员签名、参数、返回值和异常；
3. 事件是否可取消、何时触发、是否已有更合适事件；
4. 弃用、实验性或替代 API 标记；
5. 调用线程和对象生命周期限制；
6. 最低兼容版本是否包含该符号；
7. 是否存在 PluginBase 已封装的跨版本能力。

不要仅搜索类名后就调用记忆中的重载。特别是 Material、ItemMeta、Inventory、玩家资料、事件构造器、声音、粒子和实体接口跨版本容易变动。

## 事件处理

- 监听器实现 `Listener`，由框架 Holder 或项目明确注册；
- 事件类型和优先级以目标 Spigot API 签名为准；
- 若监听取消事件，明确是否应处理 `ignoreCancelled`；
- 不在高频事件中执行阻塞 I/O、全服线性扫描或未经限流的日志；
- 不依赖事件触发顺序的经验；有顺序需求时查询事件优先级语义并设计可容错状态；
- 可取消事件的取消、修改和后续状态应在目标版本服务器上验证。

事件注册不替代停用清理：PluginBase 在主类停用中会注销与插件相关的监听，但模块仍应处理自身的任务、缓存和资源。

## 命令与 plugin.yml

命令应同时满足：

- `plugin.yml` 中声明命令、描述、别名和所需权限；
- 项目模块在启用期间注册 `CommandExecutor`、`TabCompleter`；
- 注册标签与 `plugin.yml` 命令名一致；
- 参数处理、权限检查、控制台/玩家差异与补全结果稳定；
- 重载类命令不会在未验证的线程或不完整状态下修改配置。

框架 Holder 的 `registerCommand(...)` 找不到声明时只会记录无法注册信息；不能把它当作 `plugin.yml` 自动生成机制。

## 玩家、实体、世界与库存

这些对象均受服务器状态、线程和版本 API 约束：

- 玩家可能离线、切换世界、死亡或断开；每次延迟操作前重新验证状态；
- 实体可能已无效或处于不同区域；不要跨线程/跨区域假设引用恒定有效；
- 世界、区块和方块访问可能触发加载或昂贵操作；在高频路径加边界和缓存策略；
- Inventory、InventoryView、ItemStack、ItemMeta 的可变行为以当前 API 和实现为准；修改后按已验证方式写回；
- 标题、组件、物品数据和显示名跨版本差异较大，优先使用 PluginBase 的抽象或查证后的兼容层。

## 物品自定义数据

当项目已安装 `item-nbt-api`，对 `ItemStack`、`ItemMeta` 及其物品标记的自定义数据读写必须使用该依赖，不得使用 Bukkit 的 `PersistentDataContainer`、`PersistentDataType` 或 `getPersistentDataContainer()` 作为同一用途的替代方案。

PDC 在此场景不符合本项目的运行效率和开发效率要求；不要因为它是 Bukkit API 就默认选择它。先以构建脚本中声明的 `item-nbt-api` 精确版本查询资料，并将物品数据访问集中在适配层，避免业务代码混用两套存储方式。此规则只针对物品自定义数据；实体、方块或其它非物品容器的 PDC 使用需按各自需求和证据另行审查。

## 配置序列化

- 只把目标 API 明确支持序列化的 Bukkit 类型写入 YAML；
- 自定义数据使用已验证的 `ConfigurationSerializable` 或项目自己的稳定映射；
- 配置值不可信：对缺失、错误类型、越界数字、无效枚举和无效 Material 给出可诊断错误；
- 所有 Bukkit 枚举或注册表类型的配置解析，使用 `Util.valueOr(...)`、`Util.valueOrNull(...)` 或基于它们的框架包装方法；不要使用 `Enum.valueOf(...)`、`Material.valueOf(...)`；
- 配置文件中保存的 API 名称需与最低兼容版本匹配，并计划升级迁移。

### 枚举与 Bukkit Registry 兼容解析

高版本或 Paper 中，某些原本表现为枚举的 Bukkit 类型会改为由 Bukkit Registry 提供的接口。直接使用 `Enum.valueOf(...)` 或 `Material.valueOf(...)` 既不能覆盖这种变化，也会把大小写、别名和回退策略散落到业务代码中。

PluginBase 的 `Util.valueOr(Class<T>, String, T)` 是项目标准解析入口：目标类型仍是枚举时，它会忽略大小写匹配枚举常量；目标类型不是枚举时，它会查询 Bukkit Registry；找不到或输入为空时返回调用者提供的默认值。`Util.valueOrNull(Class<T>, String...)` 可按顺序尝试多个候选名称，全部失败时返回 `null`。

```java
Material material = Util.valueOr(Material.class, input, Material.STONE);
Sound sound = Util.valueOrNull(Sound.class, configuredName, legacyName);
```

对常见类型，可优先使用基于同一机制的 `Util.parseMaterial(...)`、`Util.parseSound(...)`、`Util.parseEnchant(...)` 和 `Util.parsePotion(...)`；它们在找不到时返回 `null`。调用者仍须为 `null` 或默认值提供清楚的配置错误与业务回退，不能把解析失败静默忽略。

## 版本差异高风险区

下列主题必须特别取证：

| 主题 | 常见风险 |
| --- | --- |
| `Material` 与物品数据 | 名称变更、遗留数据值、版本不存在的材料。 |
| 物品元数据 | 方法签名、组件化数据、显示名/描述格式变化。 |
| 声音、粒子、实体类型 | 枚举常量增删和客户端行为差异。 |
| 玩家资料/皮肤 | 资料对象、异步更新和实现差异。 |
| Inventory/View | 标题、slot、holder、关闭和点击语义变化。 |
| 配方、标签、注册表 | Key、迭代器、注册/移除 API 变化。 |
| 调度/线程 | Bukkit、Paper、Folia 实现差异。 |
| 事件 | 构造器、取消语义、触发阶段和弃用。 |

找到一个更高版本的调用示例不代表其可用于项目最低版本。必要时使用版本比较资料、兼容适配层或缩小支持范围。

## 不可用时的处理

若某符号不在最低版本资料中：

1. 寻找该版本可用且语义等价的 API；
2. 若功能可选，隔离并仅在已验证环境启用；
3. 若无安全替代，向用户说明最低版本需要提高或功能需要缩减；
4. 不通过猜测反射、硬编码版本包名或捕获 `Throwable` 伪造兼容性。

更详细的资料要求见 `../evidence/evidence-policy.md`，版本升级流程见 `version-compatibility.md`。
