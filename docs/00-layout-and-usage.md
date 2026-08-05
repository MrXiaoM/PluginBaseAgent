# 资料包布局与使用方式

本资料包最终复制到目标插件项目根目录下的 `agent-dev/`。它不是插件运行时的一部分，不应被打进插件 JAR；它是项目内 Agent 的开发依据。

## 最终项目布局

```text
<plugin-project>/
  build.gradle.kts                 # 插件构建定义
  settings.gradle.kts              # Gradle 项目名称或多模块设置
  gradle.properties                # 组名与版本等项目属性
  gradle/                          # Gradle Wrapper 文件
  gradlew
  gradlew.bat
  src/
    main/
      java/                        # 插件生产代码
      resources/                   # plugin.yml、配置与内置资源
    test/                          # 可选测试代码
  agent-dev/                       # 本资料包，供 Agent 开发时使用
    README.md
    docs/
    tools/                         # 后续加入；不参与插件构建
    registry/                      # 后续加入；资料坐标与获取策略
    state/                         # 本地环境、缓存与取证记录；不提交
```

## 目录分类

| 路径 | 归属 | 可写性 | 是否参与插件构建 | Git 建议 |
| --- | --- | --- | --- | --- |
| `src/main/java/` | 插件业务代码 | Agent 与开发者可写 | 是 | 提交 |
| `src/main/resources/` | 插件资源 | Agent 与开发者可写 | 是 | 提交 |
| `build.gradle.kts` | 插件构建契约 | 审慎修改 | 是 | 提交 |
| `gradle/`、`gradlew*` | 构建基础设施 | 通常不修改 | 是 | 提交 |
| `agent-dev/docs/` | 开发规范快照 | 升级资料包时更新 | 否 | 提交 |
| `agent-dev/tools/` | 开发辅助工具 | 升级资料包时更新 | 否 | 提交 |
| `agent-dev/registry/` | 资料来源和版本策略 | 升级资料包时更新 | 否 | 提交 |
| `agent-dev/state/` | 持久本地环境、下载资料、索引和临时记录 | 工具可写 | 否 | 忽略 |

## 复制规则

1. 复制整个资料包到 `<plugin-project>/agent-dev/`，保留本文件的相对结构。
2. 不要把 `agent-dev/` 放进 `src/`、资源目录或 Gradle 构建输出目录。
3. 不要通过 `shadowJar`、`processResources` 或 `jar` 任务将资料包写入插件产物。
4. 文档和未来的工具可随插件项目提交，以便不同 Agent 使用同一版本的开发规范。
5. `agent-dev/state/` 仅存放使用者本地生成的资料，必须添加到项目根 `.gitignore`：

```gitignore
# Agent 开发资料的本地缓存，不进入插件源码仓库
agent-dev/state/
```

6. 首次安装后填写 `agent-dev/state/environment.json` 的 `gradleUserHomes`，使任何 Agent 在上下文恢复后都能从项目内读取实际 Gradle 缓存目录；该本地文件必须保持忽略。
7. 若团队希望保留某次 API 取证结论，应将简短证据记录复制到项目正式文档或提交记录中；不要提交整个第三方源码/Javadoc 缓存。

## 日常使用入口

| 任务 | 先读 | 然后读 |
| --- | --- | --- |
| 新建插件或重建构建脚本 | `03-template-contract.md` | `pluginbase/packaging-and-relocation.md` |
| 新增 Bukkit/Spigot 功能 | `01-agent-contract.md` | `server-api/spigot-first-rules.md`、`evidence/evidence-policy.md` |
| 新增 Paper 专有功能 | `server-api/api-selection.md` | `server-api/paper-extension-rules.md` |
| 使用 PluginBase 的模块或主类 | `pluginbase/overview.md` | 相关模块、生命周期和自动注册文档 |
| 修改配置、数据库、动态库 | `pluginbase/configuration-database-and-libraries.md` | `quality/review-checklist.md` |
| 构建、发布或排查启动失败 | `quality/build-and-artifact-checklist.md` | `pluginbase/packaging-and-relocation.md` |
| 升级 Minecraft、API、PluginBase 或模板 | `maintenance/update-policy.md` | `server-api/version-compatibility.md` |

## 与未来 Skill 的关系

未来安装的 Skill 只承担入口和流程引导，不存放需要频繁更新的资料。Skill 应引导 Agent 在当前插件项目内读取 `agent-dev/README.md` 与对应专题文档；资料、工具和缓存保持在普通目录，以避免受保护的 Skill 目录成为日常写入目标。
