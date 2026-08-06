# 资料查询与实现查阅规程

本规程规定 Agent 如何用当前项目的 Gradle 依赖索引取得证据、查看依赖实现并记录可复核结论。资料包不保存第三方归档副本、完整解包资料或反编译文本；这些归档由目标项目 Gradle 管理，索引只保存定位所需的路径、哈希、公开字节码签名和短摘要。

## 本地状态边界

```text
agent-dev/
  state/
    environment.json                # 本机 Gradle 环境信息；忽略
    indexes/dependency-index.sqlite3 # 可完整重建的紧凑索引；忽略
    notes/                           # 项目依赖使用习惯与已验证边界；忽略
```

不得把第三方 JAR、`sources.jar`、Javadoc、完整解包内容、Vineflower 或反编译输出写入 `state/`。本机 Gradle 缓存路径只存在于 `environment.json`；不得写入文档、项目源码或笔记。

## 查询前准备

1. 从目标项目实际构建输入确认 Minecraft 版本、Spigot/Paper 选择、模块和依赖边界。
2. 读取 `agent-dev/state/environment.json`；恢复上下文、重新连接或交接时也必须重读。文件存在时只能使用其中 `gradleUserHomes`，不得扫描默认 C 盘缓存。
3. 涉及已有依赖、PluginBase 模块、服务端 API 或 Shadow 重定位时，读取相关 `agent-dev/state/notes/*.md`。
4. 按 `dependency-index-zoo-tool.md` 或 `dependency-index-cli.md` 选择唯一索引查询通道；不执行 `status` 预检。
5. 只有 Agent 已实际改变依赖集合，或用户明确要求时，才允许一次 `dependency_index.py sync --project .`。索引缺失、过期、无命中或资料不足均不授权同步。

## 定位签名与构件

依赖索引的运行 JAR `.class` 字节码是公开类型、字段、构造器、方法签名和继承关系的唯一权威来源。使用 `classes`、`members`、`dependencies` 和 `show` 定位实际 GAV、声明处、重定位后名称与资料路径；已知接收者类型时必须给 `members` 提供 `type`，让索引沿继承关系定位真实声明。

版本敏感调用不能只凭模糊搜索结果写入。还要根据返回的精确 GAV、哈希、源码位置或 Javadoc 摘要核对完整重载、弃用、注解、线程与语义。sources/Javadoc 与字节码不一致或重定位关联有歧义时，保留字节码签名并停止猜测。

## 查看依赖实现

### 1. 取得主 JAR 与资料路径

先以构件 GAV 调用 `show` 的详细模式：

- Zoo 工具：`action: "show"`、`query: "<GAV>"`、`verbose: true`；
- 无 Zoo 工具时：

```text
python agent-dev/tools/dependency_index.py show --project . --artifact <GAV> --verbose
```

结果中的字段含义：

- `file`：目标项目实际解析并运行的主 JAR 本机路径；
- `sources`：同版本 `sources.jar` 本机路径，可能为空；
- `javadoc`：同版本 Javadoc JAR 本机路径，可能为空；
- `sha256`：主 JAR 内容哈希。

这些路径来自已建索引，查询本身不扫描缓存、不联网且不触发同步。

### 2. 有 `sources.jar` 时直接读取

`sources` 非空时优先直接读取其中的一个目标 Java 条目：

```text
python agent-dev/tools/inspect_dependency.py source --sources <sources 路径> --class <完整类名>
```

工具先按完整二进制类名定位；只有同简单文件名候选唯一时才回退，多个候选会停止。不得将整个 `sources.jar` 解包到 `state/`，也不得以 sources 改写索引中由运行字节码得到的签名。

### 3. 没有 `sources.jar` 时临时反编译

仅当 `sources` 字段为空，且确实需要理解实现原理时，才运行：

```text
python agent-dev/tools/inspect_dependency.py decompile --jar <file 路径> --class <完整类名>
```

工具会：

1. 通过官方 `Vineflower/vineflower` GitHub Releases API 查询最新正式发布；
2. 只接受唯一的 HTTPS JAR 资产；
3. 在系统临时目录下载该 JAR，并执行 `java -jar` 反编译索引给出的主 JAR；
4. 只输出请求的一个 Java 条目；
5. 退出时删除 Vineflower JAR 和全部反编译输出。

反编译仅用于理解控制流、内部封装与实现约束。它不能取代运行字节码签名、目标版本 sources/Javadoc、线程语义或兼容性证据；无法唯一定位、下载失败或反编译失败时应报告阻塞，不得猜测。

## 记录结论与笔记

证据记录应包含精确 GAV、构件哈希、来源类型、归档内路径或 Javadoc 锚点、实际签名/描述和适用边界。位置可写为：`<GAV> | SHA-256 <哈希> | sources.jar:<归档内路径>#<成员>`；没有 sources 时明确写为临时 Vineflower 反编译，并将其限制为实现理解来源。

如果结论会反复影响这个项目的实现选择，把精简、已验证的使用习惯、生命周期、重定位边界或已拒绝方案更新到 `state/notes/`。不要保存完整源码、Javadoc、反编译文本、大段输出、凭据或未经验证的猜测。格式见 `dependency-notes.md` 和 `evidence-record-format.md`。

## 查询失败处理

| 情形 | 正确处理 |
| --- | --- |
| 索引没有构件或符号 | 核对当前构建输入；停止猜测，不因失败自动同步。 |
| 索引过期或不存在 | 报告结果；仅在已实际改变依赖集合或用户明确要求时同步。 |
| 有主 JAR、没有 `sources` | 签名以字节码为准；需要实现细节时才临时 Vineflower 反编译。 |
| sources/Javadoc 与运行签名不一致 | 不让资料覆盖字节码；记录不一致并停止依赖不确定部分。 |
| 找到多个同简单类名候选 | 提供完整类名或停止；不得按名称猜测。 |
| Vineflower 下载或运行失败 | 报告 GitHub Releases/Java/反编译错误；不得伪造实现结论。 |
| 只找到高版本符号 | 不作为低版本证明；设计回退、提高最低版本或放弃调用。 |

查询的目标是证明“现在要写的代码在当前项目承诺的环境中成立”，而不是积累第三方归档副本或看似相关的类名。
