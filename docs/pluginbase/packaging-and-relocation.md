# 打包、重定位与插件产物

PluginBase 的运行模型要求每个插件携带自己的框架副本，并将其重定位到该插件独有的私有包。打包规则不是优化建议，而是避免多个插件在同一服务端发生类冲突、自动扫描异常和运行时拒绝启动的必要条件。

## 产物模型

```text
<plugin>.jar
  plugin.yml
  <插件业务包>/...
  <插件私有包>.libs.base/...              # 重定位后的 PluginBase
  <插件私有包>.libs.<其它依赖>/...        # 重定位后的实现依赖
  META-INF/PluginBaseHolders              # 合并后的自动注册索引
```

服务端 API 与其它已安装前置插件的 API 通常不应进入此 JAR；它们作为 `compileOnly` 或外部运行时依赖存在。

## 必须重定位的基础包

至少包含：

```kotlin
relocate("top.mrxiaom.pluginbase", "$shadowGroup.base")
```

其中 `shadowGroup` 必须是当前插件专属包，例如 `<插件主包>.libs`。不要使用 `top.mrxiaom.pluginbase` 原包，也不要与另一个插件复用相同私有包。

PluginBase 主类包含未重定位检查。若它以原始框架包名运行，会抛出异常以提示构建错误；不要禁用、捕获并吞掉这项检查。

## 其它实现依赖

需要被打进 JAR 的第三方实现库应逐项判断：

| 依赖类别 | 通常处理 | 说明 |
| --- | --- | --- |
| PluginBase 模块 | `implementation` + 重定位 | 必需。 |
| 物品 NBT、表达式、连接池等实现库 | `implementation` + 通常重定位 | 防止不同插件携带不同版本时冲突。 |
| 动态下载库 | 不一定打入 JAR；按 resolver/libraries 策略 | 由配置、生成清单和运行期加载方式决定。 |
| Spigot/Paper API | `compileOnly`，不重定位、不打包 | 服务端提供。 |
| Vault、PlaceholderAPI、MythicMobs 等插件 API | `compileOnly`，不重定位、不打包 | 由目标插件提供。 |
| 注解库 | 以模板和构建实际解析结果为准 | 不能仅凭名称猜测是否打包。 |

“通常重定位”不代表可以无条件搬移。服务加载器、反射类名、资源路径、序列化标识和第三方许可证可能要求额外配置。对每个非框架依赖，应查询其文档和最终 JAR 内容。

## Shadow 任务基线

模板的关键要素：

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

项目可按依赖增加重定位映射，但不得删除或覆盖 PluginBase 映射与 Holder 索引合并。若 Shadow 版本改变 API、任务名或默认分类器，必须先查看项目实际 Gradle 配置和插件文档再调整。

## 自动注册索引

`META-INF/PluginBaseHolders` 是框架的预扫描类名索引。`append(...)` 的用途是把参与打包的索引资源合并到最终 JAR，而不是选择其中任意一个覆盖其它文件。

构建后检查：

- 最终 JAR 有该资源；
- 文件非空且包含预期项目/模块 Holder 的可解析类名；
- 类名与 Shadow 后路径相容；
- 插件启用时，所需模块被正确实例化。

索引缺失时框架可能退回 class 扫描；这不应被视为正常构建结果。

## `scanIgnore` 与重定位一致性

主类 Options 中应排除 `$shadowGroup` 或足以覆盖其所有子包的路径：

```java
.scanIgnore("example.plugin.libs")
```

该值必须与 Shadow 的真实目标包同步。常见错误是更改 `shadowGroup` 后忘记更新 `scanIgnore`，导致自动扫描进入嵌入依赖并出现无关类加载、性能或错误注册问题。

## 构建后归档检查

不依赖专用工具时，也应以归档查看工具检查最终 JAR：

1. `plugin.yml` 位于 JAR 根目录；
2. `main` 指向的主类在 JAR 中；
3. 原始 `top/mrxiaom/pluginbase/` 路径不存在；
4. 私有 `.libs.base/` 下存在重定位后的 PluginBase；
5. `META-INF/PluginBaseHolders` 存在；
6. 没有意外打入 `org/bukkit/`、`io/papermc/paper/` 或外部插件 API；
7. 被打入的其它实现依赖要么已重定位，要么有文档化例外；
8. 没有将 `agent-dev/`、开发文档、源码归档、测试数据或本机缓存打入 JAR。

检查命令、产物文件名和目标路径以当前 Gradle 项目为准。未来的项目内验证工具将自动化部分静态检查，但不会替代真实 JAR 内容审阅。

## 启动验证

归档结构正确仍不足以证明可运行。目标服务端启动时还需观察：

- PluginBase 未触发未重定位异常；
- 插件主类成功实例化；
- 自动注册模块没有构造器、依赖或类加载错误；
- `plugin.yml` 的依赖与命令被正确识别；
- 动态库、数据库或可选依赖按预期处理；
- Spigot/Paper/Folia 的实际目标环境符合声明。

运行环境不可用时，必须报告“仅完成静态归档检查”，不能宣称已通过启动验证。
