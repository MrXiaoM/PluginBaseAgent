# 自动注册与 Holder 模块

PluginBase 使用 Holder 体系组织项目功能，并可在插件启用时自动发现和实例化模块。它不是“对全部 class 反射构造”的机制：候选类必须满足继承关系和注解条件，且构造器、优先级、可选依赖与 Shadow 索引都有明确约束。

## 基础类型

- `AbstractPluginHolder<T extends BukkitPlugin>`：持有主类实例的基础功能类，可参与配置重载、模块加载完成通知、停用通知、事件/命令注册等。
- `AbstractModule<T extends BukkitPlugin>`：强制注册到 Holder 注册表的基础功能模块；其构造器会使用 `register = true`。
- 本项目 `func/AbstractPluginHolder` 与 `func/AbstractModule`：模板生成的泛型适配层，将 `T` 固定为当前插件主类。项目业务类优先继承这两个本地基类。
- `@AutoRegister`：运行期注解。框架扫描到符合 Holder 继承关系的类后，只有带此注解的类型才会进入项目自动加载列表。

## 标准模块形态

```java
@AutoRegister
public final class CommandMain extends AbstractModule
        implements CommandExecutor, TabCompleter, Listener {

    public CommandMain(ExamplePlugin plugin) {
        super(plugin);
        registerCommand("example", this);
        registerEvents();
    }
}
```

构造器接收当前项目主类；通过本项目 `AbstractModule` 继承链保存为 `plugin` 字段。命令、监听器和项目功能初始化应在模块职责内完成，而不是把同一逻辑复制到主类。

## 发现与实例化流程

插件启用时，框架按下列方式处理项目模块：

1. 优先读取 JAR 内 `META-INF/PluginBaseHolders`；存在时按其中类名加载，避免完整 JAR 扫描。
2. 若索引不存在，则从 `scanPackage` 或主类包扫描 class；`scanIgnore` 中的私有 Shadow 包会被排除。
3. 忽略接口、注解和枚举；只保留 `AbstractPluginHolder` 的子类。
4. 只有带 `@AutoRegister` 的类被加入自动加载列表。
5. 加载时先检查 `@AutoRegister.requirePlugins()`；任一指定插件未启用则跳过该模块。
6. 框架尝试构造器：先查找参数为 `BukkitPlugin` 的构造器，失败后查找参数为当前项目主类类型的构造器。
7. 按 `@AutoRegister.priority()` 升序构造，数值越小越早；默认优先级为 `1000`。
8. 构造过程异常会由框架记录警告，不能据此假定模块已经可用。

准确行为应随目标 PluginBase 版本重新核验。

## `@AutoRegister` 的选项

```java
@AutoRegister(
    requirePlugins = {"PlaceholderAPI"},
    priority = 500
)
```

| 属性 | 作用 | 规则 |
| --- | --- | --- |
| `requirePlugins` | 模块必须依赖且已启用的插件名 | 仅用于该模块无法在依赖缺失时安全加载的情形；同时使 `plugin.yml` 的 `depend`/`softdepend` 与实际策略一致。 |
| `priority` | 模块实例化、模块加载完成、配置重载和停用通知的排序依据 | 数值越小越先执行；只有明确依赖顺序时才改变默认值。 |

`requirePlugins` 不会自动解决 JVM 类加载问题。若类字段、父类、静态初始化或主路径导入了可选插件 API，仍可能在框架检查前触发 `NoClassDefFoundError`。可选依赖适配必须隔离到安全边界，见项目 `depend/` 规范和 `quality/review-checklist.md`。

## Holder 生命周期回调

Holder 已注册后，可按职责覆写：

| 方法 | 时机 | 用途 |
| --- | --- | --- |
| `reloadConfig(MemoryConfiguration)` | 主类完成 `beforeReloadConfig(...)` 后 | 读取、验证并替换模块配置状态。 |
| `onModulesLoaded()` | 项目自动模块都已构造后 | 建立模块间协作；不要假设配置已经重载。 |
| `onDisable()` | 主类 `beforeDisable()` 后的框架清理阶段 | 停止模块专属资源、保存必要状态。 |
| `receiveBungee(...)` | 已注册 Bungee 接收 Holder 时 | 处理已验证的插件消息；仅在已启用 Bungee 支持时使用。 |

这些回调的执行顺序同样遵循 `priority()`。不要在 Holder 回调中绕开主类关闭流程，或对已经被框架关闭的基础设施继续操作。

## 注册表与实例访问

- `AbstractModule` 默认将自身注册为 Holder；只继承 `AbstractPluginHolder` 的类需按需要使用其受保护注册机制。
- 需要查找已注册模块时，使用框架公开的查询方式并处理不存在情形；不要另建不可控全局单例。
- 动态注册模块可使用主类提供的 `registerModules(...)`，但应先确认插件是否已启用及该模块的生命周期预期。
- 注解扫描/索引只负责构造，不取代配置校验、依赖适配、线程安排和停用清理。

### Holder 单例访问风格

对自动注册且必须唯一的 Holder，项目采用接近 Kotlin `object` 的静态 `inst()` 访问风格：

```java
@AutoRegister
public final class FeatureManager extends AbstractModule {
    public FeatureManager(ExamplePlugin plugin) {
        super(plugin);
    }

    public static FeatureManager inst() {
        return instanceOf(FeatureManager.class);
    }
}
```

`instanceOf(...)` 从当前已注册 Holder 中取得实例；目标类型尚未注册时会抛出异常。因此该风格表达的是“此模块在当前生命周期阶段必须已存在”的强约束，而不是可空查询。

使用规则：

- 仅用于由 PluginBase 注册表管理、设计上唯一且必需的模块；
- 只能在该 Holder 已自动/动态注册完成之后调用；构造器、过早生命周期或可选模块路径不能假设 `inst()` 一定成功；
- 可选模块、依赖条件不满足时可能跳过加载的模块，使用可空/`Optional` 查询并处理缺失，而非调用 `inst()`；
- 不手工维护第二个静态实例字段，避免与框架注册表、重载和停用状态脱节；
- 停用后或模块注销后不得继续保存并使用 `inst()` 得到的旧引用。

## Shadow 索引要求

模板通过：

```kotlin
append("META-INF/PluginBaseHolders")
```

将各依赖中的 Holder 索引合并到最终 JAR。不得删除这一配置。缺失时框架会退回 JAR 扫描，可能导致性能、扫描范围或依赖类加载行为与预期不同。

索引中类名必须仍能在重定位后的产物中正确解析。构建后应检查最终 JAR 存在该资源，并在目标服务端观察模块加载日志。

## 常见错误

- 给普通类添加 `@AutoRegister`，但它不继承 `AbstractPluginHolder`；不会被作为模块加载。
- 模块构造器参数不是 `BukkitPlugin` 或当前项目主类；框架无法构造。
- 忘记继承本项目 `func/AbstractModule`，导致泛型、注册或项目约定丢失。
- 在 `@AutoRegister` 模块的静态字段中直接引用可选依赖 API，导致依赖检查之前类加载失败。
- 使用无理由的极低/极高优先级掩盖模块耦合，应改为明确的职责和生命周期设计。
- 忘记 `scanIgnore`，使 Shadow 的私有库被扫描为候选类。
- 删除 `PluginBaseHolders` 合并后仍假定所有模块按预扫描路径加载。
