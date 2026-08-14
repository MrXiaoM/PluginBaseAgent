# 外部依赖库使用向导

本目录说明不属于 `PluginBase` 的、可嵌入 Minecraft 服务端插件 JAR 的通用 Java 依赖。它们不能替代 Spigot、Paper 或 PluginBase 的版本取证；每次引入仍须符合 `../01-agent-contract.md`、`../02-development-workflow.md` 与 `../quality/build-and-artifact-checklist.md`。

| 库 | 用途 | 专题向导 |
| --- | --- | --- |
| `ItemPacketModifier` | 经网络包在客户端侧临时显示物品 Lore，不改写服务端真实物品 | `item-packet-modifier.md` |
| `EvalEx-j8` | 解析、校验并执行可配置的数学/布尔表达式 | `evalex-j8.md` |
| `item-nbt-api` | 真实 `ItemStack` 自定义数据、迁移、`ItemMeta` 安全次序与 PDC 禁止边界 | `item-nbt-api.md` |

## 通用接入流程

1. 从目标项目的 `build.gradle.kts` 读取并锁定实际 GAV；不以本向导中的示例版本替代项目声明。
2. 按 `../evidence/dependency-index-zoo-tool.md` 或 `../evidence/dependency-index-cli.md` 从项目实际 Gradle 解析结果确认依赖、传递依赖、公开签名与哈希；需要完整资料时按 `../evidence/query-playbook.md` 直接读取目标版本的 `sources.jar`、Javadoc 或临时反编译实现。
3. 判断依赖范围：插件运行时直接调用且服务端不提供时通常使用 `implementation`；仅编译外部插件 API 时使用 `compileOnly`，并在 `plugin.yml` 维护 `depend` 或 `softdepend`。不要把这两个场景混淆。
4. 对会进入 Shadow JAR 的实现依赖，按项目私有 `shadowGroup` 重定位其 Java 包；同时检查服务描述、配置、反射字符串、序列化类型名和资源路径。不得把 Spigot/Paper API 打入 JAR。
5. 将第三方库调用集中在业务适配层或 `depend/`、`manager/` 等职责明确的类中；不让其类型无边界传播到命令、配置和持久化模型。
6. 为注册、重载和停用设计配对的释放路径；监听器、缓存、表达式实例和异步任务都不得跨越旧配置或插件停用继续使用。
7. 运行项目 Gradle Wrapper，审查 Shadow JAR，并在目标服务端执行对应关键路径。构建通过不代表包监听、客户端同步、公式精度或异常处理已正确。

## 版本与资料边界

- `ItemPacketModifier`、`EvalEx-j8` 与 `item-nbt-api` 均按 Maven Central 构件处理；仓库配置应优先使用 `mavenCentral()`，不额外加入来源不明的仓库。
- 版本、包名、方法签名、线程安全性、传递依赖和许可证都以项目锁定版本的实际 Gradle 解析、运行 JAR 字节码、官方 POM、sources/Javadoc 为准。无法取得资料时，停止添加或调用未证明的类型。
- 查询这些通用依赖时，按 `../evidence/query-playbook.md` 通过依赖索引定位 GAV、运行签名和资料路径；sources 存在时直接读取，缺少 sources 才临时反编译，并按证据格式记录结论。
- `item-nbt-api` 的物品数据只使用 `NBT.get(...)`/`NBT.modify(...)`；索引或 Javadoc 显示成员 `@Deprecated` 时，必须阅读替代项，禁止使用已弃用的 `NBTItem` 路径。
- 不把第三方库的业务输入视为可信：客户端数据、物品、配置公式、变量值和管理员可编辑文本都必须在项目边界验证。

## 打包与运行期审查

引入本目录的库后，除通用 JAR 检查外，还须确认：

- 最终 JAR 包含需要的实现依赖及其重定位后的包路径；
- 原始依赖包不会与其它插件或服务端库冲突；
- `plugin.yml`、可选插件检测和实际类加载路径一致；
- 库的初始化、使用、重载与停用顺序均有明确责任；
- 每个库专题中列出的业务边界和回归场景已验证。
