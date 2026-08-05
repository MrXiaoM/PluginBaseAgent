# ItemPacketModifier：客户端侧虚拟 Lore

`ItemPacketModifier` 用于在**不修改服务端真实物品**的前提下，经网络包向客户端临时展示物品 Lore 或其它已验证的物品显示变化。它适合频繁变化、仅用于展示的信息，例如灵魂绑定状态或实时属性描述；不应将它误当作物品持久化、权限判定或服务端业务状态的实现。

使用前先阅读 `README.md`，并遵守 `../server-api/spigot-first-rules.md` 的物品数据规则。若项目已经使用 `item-nbt-api` 存储物品自定义数据，真实数据仍只通过 `item-nbt-api` 读写；本库仅依据这些真实数据生成客户端显示结果。

## 依赖与打包

在项目的 `build.gradle.kts` 锁定实际发布版本。Maven Central 为唯一默认仓库：

```kotlin
repositories {
    mavenCentral()
}

dependencies {
    implementation("top.mrxiaom.packets:item-modifier:1.0.0")
}
```

`1.0.0` 是本资料包登记的默认 Maven Central 版本；项目升级后必须以 `build.gradle.kts` 中实际锁定、且已由构建解析的版本为准，不得由 Agent 猜测版本。该库以网络包对象工作，依赖 `PacketEvents` API；其传递依赖、服务端平台接入方式、是否需要在 `plugin.yml` 声明外部插件，以及对应版本兼容性，必须按锁定版本 POM、sources/Javadoc 和当前项目实际安装方式核验。

它是实现依赖，若要打入插件 JAR，必须随 Shadow 重定位。以项目自己的私有 `shadowGroup` 为根，至少覆盖库自身包；`PacketEvents` 的打包或 `compileOnly` 边界必须按已核验的依赖模型决定，不能因为示例中出现其类型就擅自塞入 JAR：

```kotlin
tasks.shadowJar {
    relocate(
        "top.mrxiaom.packet",
        "$shadowGroup.libs.packet"
    )
}
```

重定位会影响最终类名。若项目有服务加载、反射、配置中类名或跨插件公开 API，先确认这些路径不会引用重定位前名称。构建后按 `../quality/build-and-artifact-checklist.md` 审查最终 JAR。

## 生命周期与职责

将本库封装在一个具有明确生命周期的项目适配器中，例如 `manager/ClientItemDisplayManager`。适配器负责：

1. 取得已经初始化且与目标版本兼容的 `PacketEventsAPI<?>`；
2. 通过 `ItemPacketModifier.register(api).setItemModifier(...)` 注册一次物品包修改器；
3. 在 `applyToClient(...)` 读取服务端物品的真实状态，生成客户端虚拟显示；
4. 在 `restoreToServer(...)` 删除该插件添加的虚拟内容，避免创造模式等客户端回传路径把展示 Lore 写回服务端；
5. 在插件停用、模块替换或重载前调用 `modifier.dispose()` 注销网络包监听器。

不要在每次点击、打开箱子容器菜单或配置重载时重复注册修改器。若显示策略可重载，应替换适配器读取的不可变规则或显式销毁旧实例；不能遗留多个监听器让同一 Lore 被重复追加。

## 虚拟 Lore 的安全模型

`ItemModifier` 的目标是对网络包中的物品表示进行修改，核心回调为：

```java
@Override
public @Nullable ItemStack applyToClient(
        User user,
        PacketWrapper<?> wrapper,
        ItemStack serverItem
) {
    // 返回 null：不修改；返回已修改的 serverItem：发送给客户端。
}

@Override
public @Nullable ItemStack restoreToServer(
        User user,
        PacketWrapper<?> wrapper,
        ItemStack clientItem
) {
    // 删除此前仅展示给客户端的内容，避免客户端回传污染真实物品。
}
```

具体参数类型、可用辅助方法与返回语义必须以项目锁定版本的 `ItemModifier` 和 `ItemPacketModifier` sources/Javadoc 为准。实现时遵守以下边界：

- 只依据服务端已验证的数据生成展示；不信任客户端传回的 Lore、名称、NBT 或标记来授予物品效果、奖励或权限。
- 对库添加的每一条 Lore 使用项目专有、稳定的隐藏标记。上游示例使用 Adventure `Component#insertion(...)` 作为标记载体；是否沿用及其具体签名必须按锁定版本核验。
- `applyToClient(...)` 必须具有幂等性：重复发送、物品栏刷新、菜单更新或多个观察路径都不能无限叠加相同 Lore。
- `restoreToServer(...)` 只能删除本插件以自身标记识别的虚拟内容；不得按文本模糊删除管理员或其它插件的真实 Lore。
- 不要通过虚拟 Lore 储存唯一 ID、数值或反作弊状态。需要持久化的数据应留在项目数据层或已选定的物品数据 API。
- 任何玩家、物品、配置和展示变量都可能在网络包到达前发生变化；读取状态时处理缺失、过期和权限变化，不能假定对象始终有效。

## 性能、线程与兼容

网络包回调是高频路径。先从 `PacketEvents` 与本库的锁定版本资料确认回调线程及 Bukkit 对象访问约束；未证实可访问 Bukkit 状态时，不直接读取世界、实体、库存或非线程安全的玩家数据。

回调内仅执行有界、无阻塞的查表和文本组装：

- 不进行数据库、文件、HTTP 或同步等待；
- 不扫描全部在线玩家、完整背包或无界配置；
- 不在每个包中反复解析复杂公式或构建大量可缓存对象；
- 对缺失状态返回不修改，而不是抛出异常中断数据包流程；
- 将异步取得的数据先发布为可安全读取的快照，再由回调使用；异步结果不得在玩家离线、物品变化、重载或停用后继续套用。

客户端虚拟展示不是跨版本 API 回退。不同 Minecraft、Spigot/Paper、PacketEvents 或物品数据格式版本均须按目标构件资料验证；资料不足时停止引入该显示能力。

## 最低验证

1. Gradle 能从 Maven Central 解析项目锁定的构件；检查版本、传递依赖与许可证。
2. Shadow JAR 只包含必要实现依赖，`top.mrxiaom.packet` 已重定位，且没有误打入 Spigot/Paper API 或不应嵌入的外部插件 API。
3. 插件启用后只注册一个修改器；执行物品栏、手持物品与箱子容器菜单等实际发送路径，Lore 会显示且不会改写服务端真实物品。
4. 重复刷新、菜单重开和配置重载不会重复叠加 Lore；物品状态变化后旧 Lore 会按设计消失或更新。
5. 在创造模式或任何会将物品由客户端发回服务端的已验证路径中，虚拟 Lore 会被准确还原，不会删除真实 Lore。
6. 停用、重载和玩家退出后没有遗留包监听器、异常刷屏或继续处理旧配置的回调。

交付说明必须写明锁定版本、`PacketEvents` 接入证据、重定位结果、实际测试的服务端版本与未验证路径。
