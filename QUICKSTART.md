# 快速上手

用这份资料从零创建一个 `PluginBase` 插件项目，并让 AI 开发工具具备项目内开发文档与资料查询能力。

## 1. 生成插件项目

访问 https://bukkit.mcio.dev/ ，填写插件名、包名、最低 API 版本等信息后下载并解压项目。

默认使用 Spigot API。只有明确需要 Paper 专有 API 时才选择 Paper API；页面中的 `paper` 模块用于 Spigot/Paper 双端物品与库存兼容，不等于可以直接调用 Paper API。

## 2. 打开并构建

用 Java `25` 作为 IDE 项目 SDK 与 Gradle JVM 打开项目，然后在项目根目录执行：

```shell
./gradlew build
```

Windows 原生命令行可执行：

```batch
gradlew.bat build
```

`targetJavaVersion` 决定最终字节码兼容级别，不要因为构建使用 Java `25` 就擅自修改它。

## 3. 安装 Skill

将发行包中的整个 `skill/minecraft-pluginbase-development/` 目录复制到所用 AI 开发工具的项目级目录：

| AI 开发工具 | 安装目录 |
| --- | --- |
| Roo Code | `.roo/skills/minecraft-pluginbase-development/` |
| Claude Code | `.claude/skills/minecraft-pluginbase-development/` |
| Codex | `.agents/skills/minecraft-pluginbase-development/` |
| OpenCode | `.opencode/skills/minecraft-pluginbase-development/` |

## 4. 释放项目内开发包

在插件项目根目录，按实际安装路径执行对应命令：

```text
# Roo Code
python .roo/skills/minecraft-pluginbase-development/scripts/install_kit.py --project .

# Claude Code
python .claude/skills/minecraft-pluginbase-development/scripts/install_kit.py --project .

# Codex
python .agents/skills/minecraft-pluginbase-development/scripts/install_kit.py --project .

# OpenCode
python .opencode/skills/minecraft-pluginbase-development/scripts/install_kit.py --project .
```

它会生成项目内 `agent-dev/`，其中包含 Agent 规范、资料查询工具、构件注册表和本地缓存目录。

## 5. 开始开发

将 `agent-dev/state/` 加入项目根 `.gitignore`；它保存本地下载和解包缓存，不能提交或打进插件 JAR。

然后向已安装的 AI 工具发送一次以下提示词，完成项目资料环境初始化：

```text
请读取本项目的 agent-dev/README.md 和 agent-dev/docs/01-agent-contract.md，检查 build.gradle.kts、plugin.yml 与当前 PluginBase 配置；将 build.gradle.kts 中 top.mrxiaom:LibrariesResolver-Gradle 的精确版本作为所有 PluginBase 模块的统一版本锚点，从 pluginBaseModules 收集实际启用的模块，仅同步这些模块的资料，不要逐个猜测或获取其它模块版本。以项目中声明的 Minecraft 版本原样同步所需的 Spigot 或 Paper API 资料。不要修改项目代码或构建配置；完成后报告 API 与 PluginBase 的精确构件版本、已同步模块、同步来源、缓存位置和未能取得的资料。
```

发送前，请先在项目配置或提示词中明确目标 Minecraft 版本；用户指定的版本必须原样保留，不能自行改写。首次涉及版本敏感 API 或 PluginBase 符号时，AI 仍会先用 `agent-dev/tools/` 查询已同步资料。
