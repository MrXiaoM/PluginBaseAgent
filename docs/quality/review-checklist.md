# 代码审查清单

本清单用于新功能、缺陷修复、兼容性改动和依赖升级的审查。按风险优先，不能以“能编译”替代未完成的项目级检查。

## 需求与边界

- [ ] 需求目标、非目标、用户可观察行为清楚。
- [ ] Minecraft 目标版本、最低兼容版本和已验证版本已记录；用户给出的版本号保持原样，没有被擅自截断、补段或改写。
- [ ] 对陌生/前沿版本如有疑问，已按 `server-api/minecraft-version-integrity.md` 使用原样 Wiki URL 核验，且核验失败没有被解释为可自动改用其它版本。
- [ ] Spigot/Paper 选择符合用户要求；未明确时没有引入 Paper-only API。
- [ ] NMS/CraftBukkit/反射使用已经得到明确许可并有版本证据。
- [ ] 改动范围没有夹带无关重构、依赖升级或格式化噪声。

## API 与证据

- [ ] 新增的服务端、PluginBase、外部插件类型和成员已按精确版本查询。
- [ ] 证据记录包含坐标/版本、来源、相对路径或锚点、实际签名和适用边界。
- [ ] 已检查弃用、实验性、线程、取消语义和最低版本存在性。
- [ ] 没有用旧项目代码、网络摘要或 AI 记忆作为唯一依据。
- [ ] 证据缺失处没有通过猜测方法名、反射字符串或宽泛异常处理掩盖。

## PluginBase

- [ ] 主类继承 `BukkitPlugin`，没有覆写 `onLoad`、`onEnable`、`onDisable`。
- [ ] Options 与实际使用的数据库、Adventure、Bungee、经济、动态库能力一致。
- [ ] 功能模块使用正确的项目 Holder/Module 基类。
- [ ] `@AutoRegister` 类具备正确继承关系和主类构造器。
- [ ] `requirePlugins`、`priority` 与 `plugin.yml` 依赖声明一致。
- [ ] `paper` 模块若被引入，原因是 Spigot/Paper 双端物品/库存兼容或已验证的对应框架能力。
- [ ] 主类按需覆写 `initItemEditor()`、`initInventoryFactory()` 并调用 `PaperFactory`。
- [ ] 调度、重载、数据库和停用路径符合框架生命周期。

## 业务结构与状态

- [ ] 主类只负责项目级编排，业务逻辑位于职责清晰的包和模块。
- [ ] 可选插件 API 被隔离，缺失时核心功能不会类加载失败。
- [ ] 配置键、默认值、类型、错误和迁移行为完整。
- [ ] Bukkit 枚举或注册表类型没有使用 `Enum.valueOf(...)`/`Material.valueOf(...)` 解析；已使用 `Util.valueOr(...)`、`Util.valueOrNull(...)` 或相应 `Util.parse*` 包装方法，并处理默认值/`null`。
- [ ] 构建脚本已安装 `item-nbt-api` 时，物品自定义数据没有使用 `PersistentDataContainer`、`PersistentDataType` 或 `ItemMeta#getPersistentDataContainer()`；同一物品数据只通过 `item-nbt-api` 读写。
- [ ] 玩家/实体/世界/库存对象在延迟或异步操作前重新验证。
- [ ] 任务、监听器、连接、文件和缓存有明确清理责任。
- [ ] 重载不会保留旧任务、旧监听器、旧配置或已关闭资源的引用。
- [ ] 高频事件和任务有性能边界，不执行无界扫描或阻塞 I/O。

## 交付信息

- [ ] 构建命令和真实结果已记录。
- [ ] 未执行的服务端启动、跨版本或外部依赖测试已明确标出。
- [ ] 已知兼容性边界、风险和回退行为写入交付说明。
