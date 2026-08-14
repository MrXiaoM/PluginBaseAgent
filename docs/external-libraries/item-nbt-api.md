# item-nbt-api：物品自定义数据

`item-nbt-api` 用于读写**服务端真实 `ItemStack`** 的自定义数据。它适合保存物品标识、业务类型、数量、状态、绑定信息和迁移版本等随物品流转的领域数据；它不是显示名称、Lore、材质或自定义模型数据的替代物，也不应承担玩家档案、数据库记录或可由配置推导的状态。

当项目构建脚本已引入 `item-nbt-api` 时，同一用途的物品自定义数据必须统一通过此依赖读写；不得同时用 `PersistentDataContainer`、`PersistentDataType` 或 `ItemMeta#getPersistentDataContainer()` 保存镜像字段，也不得在 NBT 读取失败时静默回退到 PDC。

## 使用前的文档与资料顺序

1. 先阅读本文件、`README.md` 与 `../quality/coding-style.md`，再阅读目标项目已有的物品数据适配层、数据键和调用点。它们已规定数据归属、封装和 PDC 禁止边界。
2. 设计文档足以回答常规选型时，不得为了重复确认而阅读无关框架源码。
3. 仅在需要确认当前构件的实际类名、方法签名、弃用说明、嵌套容器、组件语义或线程限制时，按 `../evidence/dependency-index-zoo-tool.md` 或 `../evidence/dependency-index-cli.md` 查询实际解析的构件。
4. 索引或 Javadoc 显示拟调用成员带有 `@Deprecated` 时，必须停止编码，读取弃用描述与替代项；只有替代项不满足需求且已取得明确证据时才能继续评估旧路径。不得知道替代 API 后仍沿用弃用 API。
5. 需要完整语义时，再按 `../evidence/query-playbook.md` 直接读取同一构件的 `sources.jar` 或 Javadoc；不要把资料包示例当作项目构件签名。

## 唯一常规读写路径：`NBT.get` 与 `NBT.modify`

对真实 `ItemStack` 的常规自定义数据读写，使用静态 `NBT.get(itemStack, ...)` 与 `NBT.modify(itemStack, ...)`。`get` 是只读查询；`modify` 在受控写入作用域中修改数据。将调用集中在项目专属适配层，业务菜单、命令、监听器和 Packet 回调不得散布数据键或直接调用库 API。

下列示例表达已经核验的 API 形态；写入项目代码前仍要以依赖索引中实际解析构件的运行签名为准。

### 示例：集中写入领域数据

```java
import de.tr7zw.changeme.nbtapi.NBT;
import org.bukkit.inventory.ItemStack;

import java.util.UUID;

public final class ItemDataAccess {
    private static final String KEY_SCHEMA = "my_plugin_schema";
    private static final String KEY_TYPE = "my_plugin_type";
    private static final String KEY_ID = "my_plugin_id";

    private ItemDataAccess() {
    }

    public static void write(ItemStack item, String type, UUID id) {
        NBT.modify(item, nbt -> {
            nbt.setInteger(KEY_SCHEMA, 1);
            nbt.setString(KEY_TYPE, type);
            nbt.setUUID(KEY_ID, id);
        });
    }
}
```

只写入已经校验过的领域值；业务层应先验证 `type`、`id` 和数值范围。每个物品模型都应有最小必要字段及明确的 `schema`/`data_version`。键名仅使用小写字母、数字与下划线，并以插件私有前缀隔开，例如 `my_plugin_schema`；不要使用宽泛的 `id`、`type`、`data` 等易冲突键名。

### 示例：只读查询与缺失值处理

```java
import de.tr7zw.changeme.nbtapi.NBT;
import org.bukkit.inventory.ItemStack;

public final class ItemDataAccess {
    private static final String KEY_TYPE = "my_plugin_type";

    public static String readType(ItemStack item) {
        return NBT.get(item, nbt -> nbt.getOrDefault(KEY_TYPE, ""));
    }

    public static boolean isReward(ItemStack item) {
        return "reward".equals(readType(item));
    }
}
```

读取结果不是可信输入。适配层必须处理键缺失、错误类型、非法范围、旧 `schema` 与不再支持的物品类型，返回明确的无效结果或完成可验证迁移；不要因交易、旧存档或其它插件修改就假定字段一定存在。

### 示例：`ItemMeta` 的安全顺序

官方 Wiki 明确警告：不要混用 `ItemMeta` 与 NBT 写入顺序。对物品调用 `setItemMeta(...)` 会覆盖此前对该物品做出的 NBT 修改。因此先完成 NBT 修改，再取得并写回 `ItemMeta`：

```java
import de.tr7zw.changeme.nbtapi.NBT;
import org.bukkit.inventory.ItemStack;
import org.bukkit.inventory.meta.ItemMeta;

public final class RewardIconFactory {
    public static void markAndName(ItemStack item) {
        NBT.modify(item, nbt -> nbt.setBoolean("my_plugin_reward", true));

        ItemMeta meta = item.getItemMeta();
        meta.setDisplayName("Reward");
        item.setItemMeta(meta);
    }
}
```

如果名称或其它元数据必须与同一 NBT 作用域中的值保持一致，使用 `NBT.modifyMeta(...)`，避免在外部交错写回：

```java
NBT.modify(item, nbt -> {
    nbt.setInteger("my_plugin_kills", nbt.getOrDefault("my_plugin_kills", 0) + 1);
    nbt.modifyMeta((readOnlyNbt, meta) -> {
        int kills = readOnlyNbt.getOrDefault("my_plugin_kills", 0);
        meta.setDisplayName("Kills: " + kills);
    });
});
```

`ItemMeta`、展示名称与 Lore 的具体跨版本处理仍使用项目已验证的 `AdventureItemStack`、`ItemStackUtil` 或适配层；不要把上述示例扩展为对任意版本可用重载的猜测。

## 禁止的旧 `NBTItem` 路径

不得使用 `new NBTItem(...)`，包括 `NBTItem(ItemStack)` 与 `NBTItem(ItemStack, boolean)`。两者均已弃用。也不得为普通物品数据读写使用旧路线的 `applyNBT(...)`、`clearCustomNBT()`、`mergeCustomNBT(...)`、`mergeNBT(...)`、`convertItemtoNBT(...)`、`convertNBTtoItem(...)` 或相关数组转换方法。

这是明确的迁移规则，不是风格偏好：官方 `NBTItem(ItemStack)` 的 `@Deprecated` Javadoc 明确要求改用 `NBT`，并说明新路线“up to 400% faster and provides less ways to mess up code”。该效率表述来自弃用 Javadoc；在没有读取此证据时，不得把它当成凭记忆得出的性能结论，也不得以它为由继续编写已弃用的 `NBTItem` 代码。

## Minecraft `1.20.5+` 的范围

在 Minecraft `1.20.5+`，运行期 `ItemStack` 不再以旧式 vanilla NBT 持有全部物品数据。`NBT.get` 与 `NBT.modify` 面向物品的 `custom_data` component，正是本文件所定义的项目自定义业务数据边界。

仅在业务确实需要访问 vanilla item component，且已通过依赖索引核验当前构件成员和目标 Minecraft 版本时，才评估 `NBT.getComponents(...)` 或 `NBT.modifyComponents(...)`。不能因其名称相近就用它们取代一般的 `NBT.get`/`NBT.modify`，也不能把组件 API 当作跨版本默认实现。

## 数据模型、封装与线程边界

适配层应至少提供：

- `read(...)`：读取并验证 NBT，返回不可变领域快照或明确无效结果；
- `write(...)`：只写入已验证领域状态，并维护 `schema`；
- `matches(...)`：安全判定物品是否属于该业务类型；
- `remove(...)`：仅删除本插件拥有的键；
- `migrate(...)`：集中处理旧版本格式。

只存可稳定校验的基本值、短字符串、UUID、有限列表或明确编码的紧凑结构；不要将玩家名、长文本、完整配置、序列化对象图或无界集合塞入物品数据。持久格式不能依赖 Java 类名、反射名或实现细节，因为 Shadow 重定位、重构和升级会使其不可读。

`ItemStack` 是可变对象。读写必须位于当前任务已验证的 Bukkit/PluginBase 线程边界内；不要跨异步任务、玩家会话或重载周期共享同一 `ItemStack` 或 NBT 包装对象。异步 I/O 前在合适线程取得并验证普通领域快照，异步路径不持有 Bukkit 对象；回到合适线程后再次确认物品和会话仍有效。

## 与 PDC、显示与客户端包的边界

本约束只针对**物品**自定义数据。实体、方块、世界或其它非物品对象是否使用 Bukkit PDC，必须按其自身 API、版本和项目要求另行审查。

- 不新增 PDC 与 NBT 的镜像字段，也不把 PDC 双写视为迁移方案；迁移只在 NBT 适配层中以可验证的 `schema` 完成。
- 显示名称、Lore、材质、模型与组件文本不是本库的职责，依旧走物品展示适配层。
- `ItemPacketModifier` 只生成客户端临时展示；真实业务数据仍只由本适配层通过 `item-nbt-api` 读写，不能信任或写回客户端虚拟 Lore。

## 依赖、打包与最低验证

常见发布坐标属于 `de.tr7zw:item-nbt-api`，但以项目实际 Gradle 解析结果为准；不得擅自修改版本、补加仓库或把本文代码示例当成版本声明。若它作为运行实现依赖进入插件 JAR，沿用项目既有的 `implementation`、Shadow 与重定位策略；不将 Spigot/Paper API 一并打入 JAR。

完成物品数据改动后至少验证：

1. 依赖索引中的实际解析构件、运行签名、弃用状态、归档哈希及所需 sources/Javadoc；
2. 首次写入、正常读取、键缺失、错误类型、非法值、旧 `schema` 和迁移失败；
3. `ItemMeta` 写回不会覆盖 NBT，或 `NBT.modifyMeta(...)` 路径按预期同时更新数据与展示；
4. 复制、堆叠拆分、交易、菜单移动、掉落/拾取、重载和插件停用后的业务行为；
5. 与 `ItemPacketModifier` 共用时，客户端虚拟展示不会覆盖真实物品数据；
6. Shadow JAR 的重定位、`plugin.yml` 和目标服务端启动；
7. 将可复用的键空间、`schema` 与迁移边界精简写入 `state/notes/`，但不记录物品实例、玩家数据或完整 NBT 输出。
