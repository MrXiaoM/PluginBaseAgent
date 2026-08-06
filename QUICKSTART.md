# 快速上手

这份指南帮助你把 `minecraft-pluginbase-development` Skill 安装到一个现有的 Gradle Minecraft 插件项目，并完成项目内资料包初始化。

## 1.准备条件

开始前请确认：

- 已有一个可正常打开的 Gradle 插件项目，并安装 PluginBase 相关构件；
- 如果没有，可以到 https://bukkit.mcio.dev/ 生成一个模板项目；
- 项目根目录包含 `gradlew` 或 `gradlew.bat`；
- 已安装项目所需的 Java 与 Python；
- 使用的 AI 开发工具支持项目级 Skill。

建议先在项目根目录执行一次构建，确认项目本身没有配置错误：

```shell
./gradlew build
```

在 Windows 原生命令行中可使用：

```shell
gradlew.bat build
```

## 2.安装 Skill

将发行包中的整个 `skill/minecraft-pluginbase-development/` 目录复制到项目对应的 Skill 目录。

| AI 开发工具 | 项目内安装目录 |
| --- | --- |
| Zoo Code | `.roo/skills/minecraft-pluginbase-development/` |
| Roo Code | `.roo/skills/minecraft-pluginbase-development/` |
| Claude Code | `.claude/skills/minecraft-pluginbase-development/` |
| Codex | `.agents/skills/minecraft-pluginbase-development/` |
| OpenCode | `.opencode/skills/minecraft-pluginbase-development/` |

需要确保上述安装目录内存在 `SKILL.md` 文件。

## 3.初始化项目资料

在插件项目根目录执行与 Skill 安装位置对应的一条命令：

```shell
# Zoo Code / Roo Code
python .roo/skills/minecraft-pluginbase-development/scripts/install_kit.py --project .

# Claude Code
python .claude/skills/minecraft-pluginbase-development/scripts/install_kit.py --project .

# Codex
python .agents/skills/minecraft-pluginbase-development/scripts/install_kit.py --project .

# OpenCode
python .opencode/skills/minecraft-pluginbase-development/scripts/install_kit.py --project .
```

初始化器会：

- 在项目根目录创建 `agent-dev/` 开发资料包；
- 读取项目 Gradle 的实际本地缓存位置；
- 建立首次依赖索引；
- 为 Zoo Code / Roo Code 项目安装可选的依赖索引工具。

初始化完成后，确保项目根 `.gitignore` 包含：

```gitignore
agent-dev/state/
```

> **可选启用项目工具**
> 
> 若使用 Zoo Code，初始化完成后，项目工具位于 `.roo/tools/`。
> 
> 按以下步骤来启用这个工具，便于 Agent 去查询索引：
> 
> 1. 打开 Zoo Code 的 “实验性” 设置；
> 2. 勾选 “启用自定义工具”；
> 3. 执行该选项右侧的 “刷新”，或重载 VS Code 窗口。
> 

## 4.开始使用

现在可以直接开始插件开发、维护或审查工作。项目内 `agent-dev/` 包含开发规范、PluginBase 资料、服务端 API 规则、依赖索引工具与构建检查清单。

常用入口：

| 需要查看的内容 | 位置 |
| --- | --- |
| 开发资料总览 | `agent-dev/README.md` |
| 开发规则 | `agent-dev/docs/01-agent-contract.md` |
| PluginBase 与服务端 API 文档 | `agent-dev/docs/README.md` |
| 构建与产物检查 | `agent-dev/docs/quality/build-and-artifact-checklist.md` |

## 常见问题

### 初始化器找不到 Gradle Wrapper

确认命令是在插件项目根目录执行，并且根目录中存在 `gradlew` 或 `gradlew.bat`。

### 初始化过程中 Gradle 失败

先修复项目本身的 Gradle 配置、仓库或依赖问题，再重新执行同一条初始化命令。已创建的 `agent-dev/` 会保留。

### Zoo Code 中看不到项目工具

确认 Skill 位于 `.roo/skills/minecraft-pluginbase-development/`，重新执行初始化命令后，在 Experimental 设置中启用 Custom Tools，并执行 `Refresh Custom Tools` 或重载窗口。

### 想重新安装资料包

在原初始化命令末尾添加 `--force`：

```text
python .roo/skills/minecraft-pluginbase-development/scripts/install_kit.py --project . --force
```

`--force` 会更新资料包受管文件；本机资料状态仍保留在 `agent-dev/state/`，不应提交到插件仓库。
