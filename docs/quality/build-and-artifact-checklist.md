# 构建与产物检查

本清单用于构建前后检查。项目实际任务名、JAR 文件名和 Gradle 版本以当前项目为准。

## 构建前

- [ ] `build.gradle.kts` 的 API 坐标与目标服务器选择一致。
- [ ] Spigot/Paper API 使用 `compileOnly`。
- [ ] PluginBase 所需模块使用 `implementation` 并加入模块列表。
- [ ] 外部插件 API 使用正确范围，并与 `depend`/`softdepend` 一致。
- [ ] Java 构建环境与目标字节码配置已确认。
- [ ] 仓库、Gradle Wrapper 和插件版本没有被无意改动。
- [ ] `shadowGroup` 为当前插件独有的私有包。
- [ ] `shadowJar` 重定位 `top.mrxiaom.pluginbase`。
- [ ] 打入 JAR 的冲突性实现依赖具有重定位规则或已记录例外。
- [ ] `shadowJar` 使用 `append("META-INF/PluginBaseHolders")`。
- [ ] `scanIgnore` 与实际重定位目标一致。
- [ ] `plugin.yml` 的主类、版本、API 版本、依赖、软依赖、命令和 Folia 声明正确。
- [ ] `agent-dev/` 不会被任何 JAR 任务打包。

## 构建执行

- [ ] 使用项目自带 `gradlew` 或 `gradlew.bat`，避免绕过 Wrapper 使用未知 Gradle 版本。
- [ ] 至少运行编译任务和 Shadow JAR 任务；若任务不存在，记录实际替代任务。
- [ ] 构建日志中没有未处理的编译错误、警告性链接错误或依赖解析失败。
- [ ] 若依赖网络或动态库，记录网络不可用时的实际结果。

## JAR 归档

- [ ] 目标插件 JAR 已生成且文件大小合理。
- [ ] `plugin.yml` 位于归档根目录。
- [ ] `main` 指向的类存在。
- [ ] 原始 `top/mrxiaom/pluginbase/` 路径不存在。
- [ ] 重定位后的 PluginBase 私有路径存在。
- [ ] `META-INF/PluginBaseHolders` 存在且非空或符合项目无 Holder 的明确情况。
- [ ] 没有打包 `org/bukkit/`、`io/papermc/paper/`、外部插件 API 或开发资料。
- [ ] 需打包的实现依赖存在，且包名、服务文件、反射路径和资源路径经过审查。
- [ ] 没有打包源代码归档、Javadoc、`agent-dev/`、Gradle 缓存或测试数据。

## 运行验证

- [ ] 在最低承诺版本启动成功。
- [ ] 在每个承诺的 Spigot/Paper 服务端启动成功。
- [ ] 自动注册模块没有构造器、类加载、优先级或依赖警告。
- [ ] `paper` 模块在 Spigot 环境回退到 Bukkit 工厂，在 Paper 环境按预期使用 Paper 工厂。
- [ ] 命令、监听器、配置重载、数据库、动态库和核心业务路径至少执行一次。
- [ ] Folia 支持声明已在 Folia 环境验证；未验证则不宣称通过。

## 不能完成时

如果构建或运行验证受环境限制，交付说明必须区分：

- 已完成的静态检查；
- 已完成的构建任务；
- 已检查的 JAR 内容；
- 未能启动或测试的服务器版本；
- 剩余风险和需要的环境。
