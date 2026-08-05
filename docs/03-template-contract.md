# 模板项目契约

本文件描述 `template-site` 生成的 `PluginBase` 插件项目基线。已有项目可能随生成时间存在版本差异，因此修改前必须读取项目自身的 `build.gradle.kts`、`plugin.yml` 和 Gradle Wrapper；不要用本文件盲目覆盖已验证配置。

## 基线结构

模板项目的核心结构如下：

```text
<plugin-project>/
  build.gradle.kts
  settings.gradle.kts
  gradle.properties
  gradle/wrapper/gradle-wrapper.properties
  gradlew
  gradlew.bat
  src/main/java/<插件包名>/<主类>.java
  src/main/java/<插件包名>/func/AbstractModule.java
  src/main/java/<插件包名>/func/AbstractPluginHolder.java
  src/main/java/<插件包名>/commands/CommandMain.java       # 选择命令时生成
  src/main/resources/plugin.yml
  src/main/resources/config.yml                            # 按选项生成
  src/main/resources/database.yml                          # 启用数据库时生成
```

业务功能按职责继续在包根下扩展 `config/`、`data/`、`func/`、`manager/`、`api/`、`event/`、`depend/` 与 `commands/`。不要为了贴合模板而把所有业务代码放进主类。

## Java 与 Gradle 约束

当前模板基线使用 Java `25` 运行 Gradle/编译器，同时将 `targetJavaVersion` 设为 Java `8`。实际含义是：

- 开发环境中的项目 SDK、Gradle JVM 应设为 Java `25`，并满足当前模板与依赖的要求；
- 生产字节码目标由 `LibraryHelper.initJava(...)` 和项目设置控制；Java `25` 的构建环境不等于插件必须以 Java `25` 在服务端运行；
- 升级 Java、Gradle、Shadow 或插件 API 时，先完成构建和运行环境兼容性验证；
- 不得把开发机的 JDK 版本当作服务端运行兼容性证明。

## 构建脚本的核心角色

模板使用 Kotlin DSL，并引入 `LibraryHelper`：

```kotlin
import top.mrxiaom.gradle.LibraryHelper

val base = LibraryHelper(project)
val targetJavaVersion = 8
val pluginBaseModules = base.modules.run { listOf(library, misc) }
val shadowGroup = "<插件私有包>.libs"
```

`LibraryHelper` 由构建脚本中的 `top.mrxiaom:LibrariesResolver-Gradle:<版本>` 提供，负责对齐 PluginBase 相关依赖、初始化 Java 设置和发布设置。该构件的**精确版本**是当前项目所有 PluginBase 模块的统一版本锚点：`base.modules` 中的 `library`、`misc`、`paper` 等模块均应使用这一版本，不应逐个查询、猜测或手写不同版本的模块坐标。

新增或删除框架能力时，应调整 `pluginBaseModules`，而不是手写不受版本管理的模块坐标。初始化资料环境时，先读取 `LibrariesResolver-Gradle` 的精确版本，再从 `pluginBaseModules` 收集项目实际启用的模块，并仅同步这些模块的 sources/Javadoc；未启用模块既不随插件打包，也不需要预先同步资料。

模板基线模块为 `library` 与 `misc`。可根据需求加入：

| 模块 | 选择时机 |
| --- | --- |
| `paper` | 插件需同时兼容 Spigot 与 Paper，并希望由框架按运行环境选择 Paper 或 Bukkit 的物品/库存实现 |
| `actions` | 使用配置化 Action 系统 |
| `gui` | 使用框架 GUI 系统 |
| `l10n` | 使用语言管理和消息 Holder |
| `commands` | 使用框架命令参数工具 |
| `temporaryData` | 使用临时数据模块 |
| `magic` | 使用 Magic 模块的已验证能力 |

模块的准确功能、版本和公共符号以对应版本的 PluginBase 资料为准，详见 `pluginbase/modules-and-capabilities.md`。

## 依赖范围

### 服务端 API

Spigot 或 Paper API 必须使用 `compileOnly`：

```kotlin
compileOnly("org.spigotmc:spigot-api:<版本>")
// 或在明确选择 Paper 后：
compileOnly("io.papermc.paper:paper-api:<版本>")
```

服务端在运行时提供 API，因此不得将该 API 打入插件 JAR。模板会为 Paper 仓库按需添加 `repo.papermc.io`；不要在选用 Paper 坐标后遗漏其仓库。

### PluginBase 与实现依赖

`PluginBase` 模块和需要随插件发布的库使用 `implementation`，然后通过 Shadow 打包。注解库与已由服务器/其它插件提供的可选 API 使用 `compileOnly`。

动态下载的库由模板中的 resolver、`base.library(...)`、`base.doResolveLibraries()`、`BuildConstants.RESOLVED_LIBRARIES` 与 `plugin.yml` 的 libraries 配置共同构成。启用或移除动态库解析时必须整体检查，而不能只删其中一行。

### 可选依赖插件

可选外部插件的 API 使用 `compileOnly`，并在 `plugin.yml` 中按真实运行时关系声明：

- 缺失时不能启用：`depend`；
- 缺失时仍能运行、但可用时提供兼容：`softdepend`；
- 代码中必须隔离可选 API 的类加载与调用，避免未安装时主类加载失败。

## Shadow 与重定位

PluginBase 的设计要求将其嵌入最终 JAR 并重定位到当前插件私有包：

```kotlin
tasks {
    shadowJar {
        configurations.add(project.configurations.runtimeClasspath.get())
        mapOf(
            "top.mrxiaom.pluginbase" to "base",
        ).forEach { (original, target) ->
            relocate(original, "$shadowGroup.$target")
        }
        append("META-INF/PluginBaseHolders")
    }
}
```

必须遵守：

1. `shadowGroup` 仅属于当前插件，通常为插件主包下的 `.libs`；不能与其它插件共享。
2. `top.mrxiaom.pluginbase` 必须重定位；PluginBase 会在运行时检查未重定位情形并拒绝启动。
3. 任何随 JAR 打入、且可能与其它插件冲突的实现依赖也应使用私有包重定位；准确原包名以依赖资料为准。
4. `META-INF/PluginBaseHolders` 必须通过 `append(...)` 合并，以保留自动注册预扫描索引。
5. 不得重定位服务器 API、其它运行时前置插件的 API，或已明确需要保持原包名的服务加载接口；这种例外必须有依赖文档证据。

详见 `pluginbase/packaging-and-relocation.md`。

## 主类基线

模板主类继承 `BukkitPlugin`，并在构造器中配置 Options。典型选项对应：

- `bungee(...)`：BungeeCord 插件消息通道；
- `adventure(...)`：Adventure 支持；
- `database(...)` 与 `reconnectDatabaseWhenReloadConfig(...)`：数据库能力；
- `economy(...)`：经济接口策略；
- `scanIgnore(...)`：忽略 Shadow 私有包，避免自动扫描嵌入依赖。

若启用 resolver，模板会在构造器中处理 `LinkageError`、下载库并向类加载器添加 URL。不要在不理解 `BuildConstants`、`plugin.yml` libraries 配置和 resolver 行为的情况下删改该逻辑。

主类初始化物品编辑器、物品栏工厂或 NBT API 时，应遵从模板中已选择的模块/API 组合。严禁覆写 Bukkit 的 `onLoad()`、`onEnable()` 和 `onDisable()`，框架生命周期详见 `pluginbase/lifecycle-and-main-class.md`。

## plugin.yml 契约

`src/main/resources/plugin.yml` 必须与构建和源码同步，至少包含：

```yaml
name: <插件名>
version: '${version}'
main: <完整主类名>
api-version: <最低 API 版本>
depend: []
softdepend: []
authors: [ <作者> ]
folia-supported: true
```

模板按选项增加命令和 resolver libraries 配置。修改时检查：

- `main` 与 Java 主类包名一致；
- `api-version` 与真正支持的最小 API 一致，不以编译 API 版本机械替代；
- `depend`、`softdepend` 与实际类加载/功能策略一致；
- 命令名、别名和描述与 `CommandMain` 的注册一致；
- 声明 `folia-supported: true` 前，必须确保所有新增调度/实体/世界访问符合框架和目标服务端的线程模型。

## 模板变更处理

模板站点和 PluginBase 都会演进。升级或重新生成项目时，先比较：

- Gradle、Shadow、PluginBase 和 LibrariesResolver 版本；
- 仓库和依赖坐标；
- Java 初始化和 `targetJavaVersion`；
- `shadowJar` 的重定位、重复文件和 `PluginBaseHolders` 配置；
- `plugin.yml` 字段与动态 libraries 配置；
- 主类构造器、Options 和生命周期扩展点。

不要把新模板完整覆盖已有业务项目；应将基础设施变更拆分、取证并逐项验证。
