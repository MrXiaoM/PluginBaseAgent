# 可安装 Skill 分发目录

`minecraft-pluginbase-development/` 是给**具体 Minecraft 插件项目**安装的 Skill，不是当前文档项目自身的 `.roo/skills/` 配置。

## 结构

```text
skill/
  minecraft-pluginbase-development/
    SKILL.md
    scripts/
      install_kit.py
    assets/
      agent-dev-kit.zip
```

- `SKILL.md`：稳定、简短的 Agent 入口和强制工作流。
- `assets/agent-dev-kit.zip`：从当前项目根目录的 `README.md`、`QUICKSTART.md`、`docs/`、`tools/`、`.gitignore` 和 `state/README.md` 构建的项目内开发包。
- `scripts/install_kit.py`：Skill 安装后，将资源 ZIP 安全释放为目标插件项目的 `agent-dev/`。

资源 ZIP 是由当前项目文档真源生成的构建产物，不在 `assets/` 维护第二份可编辑文档。不要手工修改 ZIP 内文件；应修改当前项目根目录的真源后重新构建。

## 重建资源包

在当前文档项目根目录执行：

```text
python scripts/build_skill_package.py
```

该命令重新生成 `skill/minecraft-pluginbase-development/assets/agent-dev-kit.zip`，并排除 `state/` 中的本机 Gradle 环境、可重建索引、依赖笔记以及 Python 字节码。ZIP 中的 `manifest.json` 记录每个资源文件的 `SHA-256`，供追溯当前构建内容。

预览将包含的文件：

```text
python scripts/build_skill_package.py --dry-run
```

## 安装到目标插件项目

将整个 `skill/minecraft-pluginbase-development/` 目录安装到目标插件项目所使用 AI 开发工具的**项目级 Skill 目录**。目录内的 `SKILL.md`、`scripts/` 与 `assets/` 均须保留，且 `SKILL.md` 必须位于该 Skill 目录根部。

| AI 开发工具 | 项目级安装路径 | 释放项目内资料包的命令 |
| --- | --- | --- |
| Roo Code | `<插件项目>/.roo/skills/minecraft-pluginbase-development/` | `python .roo/skills/minecraft-pluginbase-development/scripts/install_kit.py --project .` |
| Claude Code | `<插件项目>/.claude/skills/minecraft-pluginbase-development/` | `python .claude/skills/minecraft-pluginbase-development/scripts/install_kit.py --project .` |
| Codex | `<插件项目>/.agents/skills/minecraft-pluginbase-development/` | `python .agents/skills/minecraft-pluginbase-development/scripts/install_kit.py --project .` |
| OpenCode | `<插件项目>/.opencode/skills/minecraft-pluginbase-development/` | `python .opencode/skills/minecraft-pluginbase-development/scripts/install_kit.py --project .` |

安装后，首次使用该 Skill 时执行对应命令：

```text
python <该工具的项目级 Skill 路径>/scripts/install_kit.py --project .
```

它会创建：

```text
<插件项目>/agent-dev/
  README.md
  QUICKSTART.md
  docs/
  tools/
  state/README.md
  manifest.json
```

默认不会覆盖已有的 `agent-dev/` 文件。用户明确要求升级或重置时才加 `--force`；可先使用 `--dry-run` 预览。`agent-dev/state/` 保存本机 Gradle 环境、可重建索引和依赖笔记，必须保持在版本控制和插件 JAR 之外。
