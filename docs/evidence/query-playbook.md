# 资料查询操作规程

本规程规定 Agent 如何取得、查询和使用 Spigot、Paper 与 PluginBase 的本地资料。项目内 Python 工具已实现同步、解包、查询、基础文本比较和清单生成；它们只使用标准库，命令见 `../../tools/README.md`。

## 目标目录

资料包安装到插件项目后，约定使用：

```text
agent-dev/
  registry/                         # 坐标、仓库与回退策略
  state/
    environment.json                # 本机 Gradle 缓存等持久环境信息；忽略
    downloads/                      # 原始归档；忽略
    evidence/
      spigot/<版本>/
      paper/<版本>/
      pluginbase-<模块>/<版本>/
    indexes/                        # 为未来扩展保留的全文索引目录；忽略
    records/                        # 本地查询记录；忽略
```

所有记录使用相对路径；不得写入开发者绝对盘符，也不得假设存在任何调研机器上的私有目录。

## 查询前准备

1. 从项目 `build.gradle.kts` 读取实际 API 坐标、PluginBase 版本和模块；
2. 先读取 `agent-dev/state/environment.json`；上下文恢复、重新连接或新 Agent 接手时也必须先做此步，确认 `gradleUserHomes` 的实际非 C 盘缓存目录；
3. 确认需求对应的 Minecraft 版本、最低版本与 Spigot/Paper 选择；
4. 从 `agent-dev/state/` 查找是否已有相同构件、相同哈希的资料；
5. 缓存不存在或版本/哈希不同，则优先从 `environment.json` 配置的 Gradle 用户目录复用；
6. 仍不存在时，再从官方/配置的 Maven 仓库获取 sources 和 Javadoc；
7. 将归档、来源 URL、获取时间、哈希和解包路径写入清单。

Gradle 缓存的位置不能硬编码。`state/environment.json` 存在时，工具只读取其 `gradleUserHomes`，不会扫描 `GRADLE_USER_HOME` 或默认 C 盘用户目录；空值或无效配置会停止。显式 `--gradle-user-home` 可单次覆盖该配置，未配置环境文件时才依次读取 `GRADLE_USER_HOME` 与运行环境默认目录。

## 人工查询方式

工具不可用、资料来源需要人工核验时，可安全地：

- 用 ZIP/JAR 查看工具列出 `sources.jar` 内 Java 路径；
- 解包到 `agent-dev/state/evidence/<生态>/<版本>/sources/`；
- 在 `.java` 文件中按完整类名、成员名和注解搜索；
- 解包或浏览 `javadoc.jar`，确认公开描述和弃用信息；
- 保存来源坐标、归档哈希和命中路径；
- 以 `evidence-record-format.md` 写下结论。

不得只查看二进制 JAR 后猜测源码签名。没有 `sources.jar` 时可以使用 Javadoc，但要标明资料类型不足以证明的实现细节。

## 可用工具命令

工具使用 Python 标准库，在项目内运行：

```text
python agent-dev/tools/api_evidence.py sync --api spigot --minecraft <版本>
python agent-dev/tools/api_evidence.py sync --api paper --minecraft <版本>
python agent-dev/tools/api_evidence.py query --api spigot --minecraft <版本> --symbol <完整类名或成员>
python agent-dev/tools/api_evidence.py compare --api spigot --from <版本> --to <版本> --symbol <类型>
python agent-dev/tools/pluginbase_evidence.py sync --version <版本> --module <模块>
python agent-dev/tools/pluginbase_evidence.py query --version <版本> --module <模块> --symbol <完整类名或成员>
python agent-dev/tools/verify_plugin_project.py --project .
```

工具输出精确坐标、来源、哈希、命中文件相对路径、行号或 Javadoc 上下文。`api_evidence.py` 将 `--minecraft` 作为用户原样版本文本写入清单，拒绝混用不同原样版本的缓存；具体规则见 `../server-api/minecraft-version-integrity.md`。

## 查询策略

### 查服务端类型或成员

1. 以完整类名查 sources；
2. 在类内查精确成员名和重载；
3. 读取相关 Javadoc、注解、父类型和事件接口；
4. 若需要最低版本兼容，同时在最低版本和编译版本查询；
5. 记录存在性、签名、语义与线程边界；
6. 若无法确认，停止使用该成员。

### 查 PluginBase 能力

1. 先确认项目锁定的 PluginBase 版本和已引入模块；
2. 查模块源码/Javadoc 中的完整包名；
3. 从公共入口向具体类型核对，特别是 `BukkitPlugin`、Options、Holder、Factory、Scheduler；
4. 查模块间引用，不假设仅引入一个模块即可使用其它模块类；
5. 将框架行为与实际主类 Options、Shadow 和资源配置对应起来。

### 查版本差异

1. 同步前后两个精确版本；
2. 先比较类型是否存在；
3. 再比较构造器/成员签名、注解和 Javadoc；
4. 最后检查调用点、配置名、反射字符串和测试环境；
5. 复杂行为变化必须通过源码阅读和服务端测试确认，不把文本比较当作完整兼容证明。

## 查询失败处理

| 失败 | 正确处理 |
| --- | --- |
| 找不到构件 | 核对坐标、仓库、Snapshot 元数据和项目实际依赖；报告阻塞。 |
| 只有二进制 JAR | 尝试同版本 Javadoc 或上游源码；记录资料不足，避免推断实现。 |
| sources/Javadoc 与项目版本不同 | 不混用；同步精确版本或由用户确认版本调整。 |
| Snapshot 哈希变化 | 旧索引/记录标记失效，重新解包与查询。 |
| 只找到高版本符号 | 不作为低版本证明；设计回退、提高最低版本或放弃该调用。 |
| 资料显示弃用/实验性 | 查询替代和稳定性说明，记录风险并取得必要确认。 |

查询的目标是证明“现在要写的这行代码在这个项目承诺的环境中成立”，不是收集看似相关的网页或类名。
