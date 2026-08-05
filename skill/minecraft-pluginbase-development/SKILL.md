---
name: minecraft-pluginbase-development
description: Guides development, maintenance, review, and version upgrades of Gradle Minecraft server plugins using PluginBase. Use when working with Spigot, Paper, BukkitPlugin, PluginBase modules, Shadow relocation, plugin.yml, Minecraft API evidence, or server-version compatibility.
---

# PluginBase Minecraft 插件开发

## When to use

在当前项目开发、修复、审查或升级基于 `PluginBase` 的 Minecraft 服务端插件时使用，包括 `Spigot`、`Paper`、`BukkitPlugin`、`plugin.yml`、PluginBase 模块、Shadow 重定位、自动注册、Folia、版本兼容和 API 资料查询。

## When NOT to use

不要用于非 Minecraft 插件项目、未使用 `PluginBase` 的通用 Java 项目，或与构建/服务端 API 无关的纯文本任务。此类任务应遵循项目自己的规范。

## 项目内开发包

1. 在目标插件项目根目录检查 `agent-dev/README.md` 是否存在。
2. 缺失时，执行本 Skill 的 `scripts/install_kit.py --project <目标插件项目根目录>`，将 `assets/agent-dev-kit.zip` 安全释放为项目内 `agent-dev/`。
3. 已存在时，不要覆盖；只有用户明确要求升级或重置时，执行 `scripts/install_kit.py --project <目标插件项目根目录> --force`。可先附加 `--dry-run` 预览。
4. 阅读项目内 `agent-dev/README.md`、`agent-dev/docs/01-agent-contract.md` 与任务对应的专题文档。不要在日常开发中修改此 Skill 目录；文档、工具、注册表和缓存均在项目内 `agent-dev/`。

## 强制工作流

1. 原样记录用户指定的 Minecraft 版本；不得将 `1.21.11` 改为 `1.21.1`，不得把 `26.2` 改为旧式版本格式。若对版本命名有疑问，按 `agent-dev/docs/server-api/minecraft-version-integrity.md` 使用原样版本号查询 Wiki。
2. 默认选择 Spigot API。只有用户明确选择 Paper，或目标项目已验证需要 Paper 专有能力时才进入 Paper 路径；PluginBase 的 `paper` 模块用于 Spigot/Paper 双端物品/库存工厂回退，不等于可直接调用 Paper API。
3. 初始化或查询 PluginBase 资料时，读取 `build.gradle.kts` 中 `top.mrxiaom:LibrariesResolver-Gradle` 的精确版本；它是全部 PluginBase 模块的统一版本锚点。从 `pluginBaseModules` 识别实际启用模块，并只用该统一版本同步这些模块。不得逐个猜测、探测或预先获取未启用模块的版本。
4. 在使用版本敏感的 Bukkit、Spigot、Paper、PluginBase、外部插件或 NMS 符号前，先运行项目内资料工具并记录证据：
   - `python agent-dev/tools/api_evidence.py sync/query ...`
   - `python agent-dev/tools/pluginbase_evidence.py sync/query ...`
5. 无法取得资料或查询不到符号时，停止猜测，报告已尝试来源与阻塞项；不得编造 API、反射字符串或近似版本。
6. 使用 PluginBase 时：继承 `BukkitPlugin`，不覆写 `onLoad()`、`onEnable()`、`onDisable()`；将框架打入 Shadow JAR 并重定位；保持 `scanIgnore` 与 `shadowGroup` 一致；保留 `META-INF/PluginBaseHolders` 合并。
7. 解析 Bukkit 枚举或注册表类型时使用 `Util.valueOr(...)`、`Util.valueOrNull(...)` 或对应 `Util.parse*` 方法；不要使用 `Enum.valueOf(...)` 或 `Material.valueOf(...)`。
8. 修改后执行 `python agent-dev/tools/verify_plugin_project.py --project .`、项目 Gradle Wrapper 构建，并按 `agent-dev/docs/quality/build-and-artifact-checklist.md` 审查最终 JAR。

## 文档导航

- 布局和复制边界：`agent-dev/docs/00-layout-and-usage.md`
- 开发总流程：`agent-dev/docs/02-development-workflow.md`
- 模板和构建：`agent-dev/docs/03-template-contract.md`
- PluginBase：`agent-dev/docs/pluginbase/overview.md`
- Spigot/Paper 选择：`agent-dev/docs/server-api/api-selection.md`
- 用户版本号完整性：`agent-dev/docs/server-api/minecraft-version-integrity.md`
- 证据规程：`agent-dev/docs/evidence/query-playbook.md`
- 工具命令：`agent-dev/tools/README.md`
- 审查与产物：`agent-dev/docs/quality/review-checklist.md`、`agent-dev/docs/quality/build-and-artifact-checklist.md`

对每个任务只读取解决当前决策所需的最少专题文档；完整索引位于 `agent-dev/docs/README.md`。
