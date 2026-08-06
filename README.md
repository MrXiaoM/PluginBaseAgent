# PluginBase Agent 开发文档

使用者从零创建项目、安装 Skill 与释放项目内资料包时，请先阅读 [`QUICKSTART.md`](QUICKSTART.md)。

这是面向 Agent 的 Minecraft 服务端插件开发规范包，服务于使用 `PluginBase` 的 Gradle 插件项目。

目标是让 Agent 在开发、修复、审查和升级插件时，能够依据项目内的文档与可复核资料完成工作：默认使用 Spigot API；仅在用户明确选择或已验证需要时使用 Paper API；在写出版本敏感代码前查询目标版本的源码或 Javadoc，而不是凭经验猜测接口。

> 当前阶段：先交付文档。用于同步、解包、索引与查询 API 资料的工具，以及安装后的 Skill 入口，会在文档审阅完成后补充。

## 这份文档放在哪里

完成后，应将整个文档包复制到每个目标插件项目的 `agent-dev/` 目录：

```text
<目标插件项目>/
  build.gradle.kts
  src/
  gradle/
  agent-dev/
    README.md
    docs/
```

`agent-dev/` 是插件项目的一部分，不依赖开发者本机的其它目录。Agent 应优先读取项目内 `agent-dev/` 的内容；不得假设存在本仓库调研时使用的本机 `PluginBase`、模板站点、示例插件或 Gradle 缓存路径。

配套工具位于 `agent-dev/tools/`，本地下载的归档、解包资料、索引和查询记录位于 `agent-dev/state/`。`state/environment.json` 专门保存本项目机器的持久环境信息，例如实际 Gradle 缓存目录；它使 Agent 在上下文压缩、重新连接或交接后无需猜测或扫描默认 C 盘路径。`state/` 不应提交到插件的版本控制仓库；文档、注册表和工具应随项目提交，以固定该项目使用的开发规范版本。

## 目录导航

| 路径 | 内容 | 何时阅读 |
| --- | --- | --- |
| `docs/00-layout-and-usage.md` | 目录分类、复制规则、版本控制边界与使用入口 | 首次接入或迁移项目时 |
| `docs/01-agent-contract.md` | Agent 的强制规则：先取证、禁止猜测、停止条件 | 每个任务开始前 |
| `docs/02-development-workflow.md` | 从需求到构建验证的完整流程 | 开发、修复和评审时 |
| `docs/03-template-contract.md` | `template-site` 生成项目的结构与构建约定 | 新建项目或改构建脚本时 |
| `docs/gui/` | 硬编码与配置驱动的 Minecraft 箱子容器菜单、图标、交互与重载边界 | 设计或修改 `Inventory` 菜单时 |
| `docs/external-libraries/` | `ItemPacketModifier` 客户端虚拟 Lore、`EvalEx-j8` 配置公式及其接入、重定位、生命周期和验证边界 | 引入这两项嵌入式外部依赖时 |
| `docs/pluginbase/` | `PluginBase` 主类、生命周期、模块、配置与打包规范 | 使用或修改 `PluginBase` 相关代码时 |
| `docs/server-api/` | Spigot 优先、Paper 扩展、版本兼容与 NMS 边界 | 使用服务端 API 前 |
| `docs/evidence/` | API 资料查询与证据记录要求 | 使用版本敏感接口前 |
| `docs/quality/` | 代码风格、评审清单、构建与产物检查 | 提交改动前 |
| `docs/maintenance/` | 文档、工具、资料与依赖升级规则 | 升级版本或维护资料时 |
| `tools/README.md` | Gradle 依赖索引、API/PluginBase 资料同步、查询、比较与项目静态验证命令 | 使用陌生依赖、版本敏感接口或提交构建改动前 |
| `registry/` | Spigot/Paper、PluginBase 与已登记外部依赖的构件坐标、仓库和资料策略 | 排查资料下载或更新来源规则时 |

## 推荐阅读顺序

1. 新建项目或首次接入时，先阅读工作区根 `QUICKSTART.md`，完成模板项目、Skill 与 `agent-dev/` 的安装。
2. 填写并在每次任务恢复后阅读 `state/environment.json`，确认本机 `gradleUserHomes`；该文件存在时不得自行扫描默认 C 盘 Gradle 目录。
3. 阅读 `docs/00-layout-and-usage.md`，确认当前项目中资料包的位置和可写目录。
4. 阅读 `docs/01-agent-contract.md`，确认目标 Minecraft 版本、服务器 API 与兼容边界。
5. 根据任务读取 `docs/02-development-workflow.md` 和对应专题文档。
6. 遇到陌生 Gradle 依赖时，按 `docs/evidence/dependency-index-zoo-tool.md` 或 `docs/evidence/dependency-index-cli.md` 选择唯一查询通道：Zoo 工具存在时只调用工具，不执行依赖索引 CLI；否则直接执行具体 CLI 查询，不做 `status` 预检。初始化器已建立首次索引；仅在 Agent 实际修改依赖集合或用户明确要求时才允许 `sync`。索引只负责定位，不替代 sources/Javadoc 复核。
7. 使用 `tools/api_evidence.py` 或 `tools/pluginbase_evidence.py` 同步并查询目标版本资料，再实现版本敏感代码。
8. 修改完成后按 `docs/quality/build-and-artifact-checklist.md` 执行构建与产物检查。

## 适用范围

- Java 与 Gradle Kotlin DSL 的 Minecraft 服务端插件。
- 由 `template-site` 生成，或能对齐其项目约定的插件项目。
- 使用 `PluginBase` 作为嵌入式库并通过 Shadow 重定位的项目。
- 默认面向 Spigot API；可选使用 Paper API。
- 默认使用 Java `25` 作为项目 SDK 与 Gradle JVM；目标字节码兼容级别仍以项目的 `targetJavaVersion` 和 `build.gradle.kts` 为准。

## 不在本包中分发的内容

本包不包含 Spigot、Paper、PluginBase 或其它第三方库的源码归档与 Javadoc 归档。它们体积大、版本会变动且受各自许可证约束。工具只会在当前插件项目的 `agent-dev/state/` 中按需复用 Gradle 缓存或下载、解包和查询这些资料。

## 关键原则

- **Spigot 优先**：未明确选择 Paper 时，不能调用 Paper 专用 API。
- **证据优先**：类、方法、事件、弃用状态、线程要求和版本可用性必须以目标版本资料为准。
- **PluginBase 优先**：框架已提供的生命周期、模块、调度、物品栏、物品编辑、配置和依赖处理能力，应先查框架资料再决定是否自行实现。
- **构建即验证**：依赖范围、Shadow 打包、重定位、`PluginBaseHolders` 索引和 `plugin.yml` 都是可运行性的一部分。
- **不猜测**：证据不足时，记录阻塞原因和需要同步的资料，而不是伪造 API 或框架行为。

## Skill 分发

可安装的 Skill 位于 `skill/minecraft-pluginbase-development/`，它包含简短的 `SKILL.md`、安全释放脚本和由当前文档真源生成的 `assets/agent-dev-kit.zip`。分发与重建步骤见 `skill/README.md`：修改本项目文档、工具或注册表后，执行 `python scripts/build_skill_package.py` 重新生成资源包。

将整个 `minecraft-pluginbase-development/` 目录安装到目标插件项目中所用 AI 开发工具的**项目级 Skill 目录**；目录内的 `SKILL.md` 必须保持在对应目录根部：

| AI 开发工具 | 项目级安装路径 |
| --- | --- |
| Neko/Roo/Zoo Code | `<插件项目>/.roo/skills/minecraft-pluginbase-development/` |
| Claude Code | `<插件项目>/.claude/skills/minecraft-pluginbase-development/` |
| Codex | `<插件项目>/.agents/skills/minecraft-pluginbase-development/` |
| OpenCode | `<插件项目>/.opencode/skills/minecraft-pluginbase-development/` |

安装后，在相应目录下运行一次 `scripts/install_kit.py --project <插件项目>`，将资料释放到统一的 `<插件项目>/agent-dev/`，由目标项目 Gradle Wrapper 写入实际 Gradle 缓存配置，并同步首次依赖索引。不同工具的 Skill 安装位置不同，但 `agent-dev/` 的布局、工具命令和开发规则完全一致。
