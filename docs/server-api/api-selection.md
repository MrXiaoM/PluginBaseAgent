# 服务端 API 选择

本资料包以 **Spigot API 优先** 为默认策略。这里的“优先”指业务代码的编译表面与接口选择，不等于拒绝在 Paper 服务端运行；使用 Spigot API 编译的插件通常可以运行在兼容的 Paper 服务端。只有需求明确需要 Paper 专有能力时，才进入 Paper API 路径。

## 决策表

| 情形 | 编译/API 策略 | 代码策略 |
| --- | --- | --- |
| 用户未指定服务端，仅要求常规插件功能 | Spigot API | 只使用目标版本可证明存在的 Bukkit/Spigot API。 |
| 要在 Spigot 与 Paper 都运行，涉及物品/库存兼容 | Spigot API + PluginBase `paper` 模块 | 覆写两项工厂方法，交给 `PaperFactory` 运行时选择/回退；业务代码仍保持 Spigot 表面。 |
| 用户明确只支持 Paper，且功能依赖 Paper API | Paper API | 记录 Paper-only 范围，隔离 Paper 调用，仍优先使用通用 Bukkit 表面。 |
| 同时支持 Spigot/Paper，但某项功能只有 Paper API | Spigot API 为主 | 提供经验证的 Spigot 回退或明确禁用该增强功能；不能让主路径加载 Paper 类型。 |
| 需要 NMS/CraftBukkit | 由用户明确批准 | 锁定实现、映射与版本，隔离版本层并准备每版本验证。 |

## Spigot 优先的理由

- 模板默认可生成 Spigot 项目；
- 业务 API 表面更小，跨服务端可用范围更清晰；
- PluginBase 的 `paper` 模块能对特定物品/库存工厂在运行时提供 Paper 优先、Bukkit 回退，不需要将整个业务项目改为 Paper-only；
- 避免 Agent 因 Paper 提供更多便利方法而无意引入 Spigot 无法加载的符号。

## 选择 Paper API 的前提

以下条件必须全部满足：

1. 用户明确选择 Paper，或需求中存在没有可接受 Spigot 替代的已验证能力；
2. 目标 Minecraft/Paper API 精确版本已确定；
3. 已同步并查询该版本源码或 Javadoc，确认要用的类型、成员、弃用标记和线程要求；
4. `build.gradle.kts` 改为或已经使用 Paper API 坐标与正确仓库；
5. `plugin.yml`、README 或发布说明明确运行环境边界；
6. 业务代码将 Paper 依赖限制在可审查边界，避免无意扩散。

“Paper 兼容 Bukkit”不是满足这些条件的证明。

## `paper` 模块与 Paper API 的区别

| 项目 | PluginBase `paper` 模块 | Paper API 依赖 |
| --- | --- | --- |
| 目的 | 在同一插件中为物品编辑/库存工厂优先选择 Paper 实现，并能回退 Bukkit | 调用 Paper 服务端公开的专有 API |
| 是否能在 Spigot 运行 | 能；不可用时回退 Bukkit 工厂 | 通常不能；类型加载或方法调用可能失败 |
| 是否要求项目 Paper-only | 否 | 是，除非有经过验证的隔离与回退设计 |
| 主类接入 | 覆写 `initItemEditor()`、`initInventoryFactory()` | 依具体 Paper 功能设计适配层 |
| 是否免除 API 查询 | 否 | 否 |

不能以“项目引入了 `paper` 模块”为理由，在业务类直接导入 `io.papermc.paper.*`。

## 依赖坐标和仓库

实际版本以目标项目和资料注册表为准。模板形态为：

```kotlin
repositories {
    maven("https://hub.spigotmc.org/nexus/content/repositories/snapshots/")
    // 使用 Paper API 时再加入：
    maven("https://repo.papermc.io/repository/maven-public/")
}

dependencies {
    compileOnly("org.spigotmc:spigot-api:<Minecraft>-R0.1-SNAPSHOT")
    // 或明确选择 Paper：
    compileOnly("io.papermc.paper:paper-api:<Minecraft>-R0.1-SNAPSHOT")
}
```

API 都应保持 `compileOnly`，不打入 Shadow JAR。Snapshot 构件可能在同一版本字符串下变化；资料同步时必须记录获取时间和内容哈希，见 `evidence/evidence-policy.md`。

## API 选择后的复核

- 检查所有导入是否符合选定 API；
- 检查转接层、反射和静态字段没有提前加载 Paper-only 类；
- 检查 Paper-only 功能的失败/禁用路径；
- 检查 `paper` 模块只承担其工厂回退职责；
- 分别在承诺支持的 Spigot/Paper 版本上构建和启动验证；
- 没有目标环境验证时，不得宣称双端运行已通过。
