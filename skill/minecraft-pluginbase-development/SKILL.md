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
2. 缺失时，执行本 Skill 的 `scripts/install_kit.py --project <目标插件项目根目录>`，一次完成 `assets/agent-dev-kit.zip` 释放、由目标项目 Gradle Wrapper 报告并写入 `agent-dev/state/environment.json`、以及首次依赖索引同步。
3. 安装器优先保留既有 `gradleUserHomes`；首次配置从 Gradle 实际 `gradleUserHomeDir` 写入，而不是猜测默认 C 盘目录。只有 Wrapper 无法启动时才可用 `--gradle-user-home` 作为显式诊断覆盖。该文件是本地持久环境信息，必须保持忽略且不进入插件 JAR。
4. 从 `.roo/skills/` 入口安装时，安装器还会自动创建 `.roo/tools/pluginbase-dependency-index.js`，并在同目录安装所需 `zod@3.25.76`；已有同名 `.js` 工具不自动覆盖。用户仅需在 Zoo Code Experimental 设置启用 Custom Tools，并执行 Refresh Custom Tools。
5. 每次任务开始、上下文压缩后恢复、重新连接或交接给新 Agent 时，先读取 `agent-dev/state/environment.json`；资料同步仅搜索其中配置的路径，不得自行改查默认 C 盘 Gradle 目录。只有文件不存在时才允许工具回退到环境变量或默认目录。
6. 已存在时，不要覆盖；只有用户明确要求升级或重置时，执行 `scripts/install_kit.py --project <目标插件项目根目录> --force`。可先附加 `--dry-run` 预览；即使使用 `--force`，安装器仍保留已有 `environment.json` 和同名 Zoo 工具。
7. 阅读项目内 `agent-dev/README.md`、`agent-dev/docs/01-agent-contract.md` 与任务对应的专题文档。不要在日常开发中修改此 Skill 目录；文档、工具、注册表和缓存均在项目内 `agent-dev/`。

## 强制工作流

1. 先读取 `agent-dev/state/environment.json`，确认 `gradleUserHomes`；在上下文恢复后不得因丢失临时环境信息改查默认 C 盘缓存。需要单次诊断时才显式传入 `--gradle-user-home`。
2. 原样记录用户指定的 Minecraft 版本；不得将 `1.21.11` 改为 `1.21.1`，不得把 `26.2` 改为旧式版本格式。若对版本命名有疑问，按 `agent-dev/docs/server-api/minecraft-version-integrity.md` 使用原样版本号查询 Wiki。
3. 默认选择 Spigot API。只有用户明确选择 Paper，或目标项目已验证需要 Paper 专有能力时才进入 Paper 路径；PluginBase 的 `paper` 模块用于 Spigot/Paper 双端物品/库存工厂回退，不等于可直接调用 Paper API。
4. 初始化或查询 PluginBase 资料时，读取 `build.gradle.kts` 中 `top.mrxiaom:LibrariesResolver-Gradle` 的精确版本；它是全部 PluginBase 模块的统一版本锚点。从 `pluginBaseModules` 识别实际启用模块，并只用该统一版本同步这些模块。不得逐个猜测、探测或预先获取未启用模块的版本。
5. 遇到陌生 Gradle 依赖时，先检查 `agent-dev/tools/dependency_index.py status --project .`；索引缺失或过期时显式运行 `sync --project .`。它以 SQLite/FTS 按需查询，流式处理 Gradle 缓存中的 sources/Javadoc 且实时显示阶段/构件进度，不复制或解包完整归档。再查询模块、构件、类和公开签名；已知接收者类型时，优先使用 `members <成员> --type <类型>`，使搜索沿 `extends`/`implements` 链报告真实声明处，不要反复执行 `javap`。
6. 在使用版本敏感的 Bukkit、Spigot、Paper、PluginBase、外部插件或 NMS 符号前，先运行项目内资料工具并记录证据：
    - `python agent-dev/tools/api_evidence.py sync/query ...`
    - `python agent-dev/tools/pluginbase_evidence.py sync/query ...`
7. 无法取得资料或查询不到符号时，停止猜测，报告已尝试来源与阻塞项；不得编造 API、反射字符串或近似版本。
8. 使用 PluginBase 时：继承 `BukkitPlugin`，不覆写 `onLoad()`、`onEnable()`、`onDisable()`；将框架打入 Shadow JAR 并重定位；保持 `scanIgnore` 与 `shadowGroup` 一致；保留 `META-INF/PluginBaseHolders` 合并。
9. 计划或修改箱子容器菜单时，先按统一版本同步并查询 `gui` 模块；不能把其源码当作完整业务菜单示例。按实现方式阅读 `agent-dev/docs/gui/hardcoded-inventory-menus.md` 或 `agent-dev/docs/gui/config-driven-inventory-menus.md`；配置点击动作或语言时只在模块已启用的前提下继续查询 `actions`、`l10n`。
10. 箱子容器菜单必须以每玩家独立 `IGuiHolder`/会话实例管理可变状态，明确顶部 Holder、slot、点击、拖拽、关闭、玩家退出、重载、点击锁与异步回调失效。YAML 模型、Action 和 L10n 不得绕过 Java 业务权限、事务或数据校验。
11. 创建或编辑硬编码物品图标时，优先使用 `AdventureItemStack`；对非 Adventure 既有路径及发光/模型等辅助操作使用 `ItemStackUtil` 的已验证方法。不得在业务菜单中重复散落裸 `ItemMeta` 读改写流程。
12. 使用 `ItemPacketModifier` 时，先读 `agent-dev/docs/external-libraries/item-packet-modifier.md`，从项目锁定的 Maven Central GAV 查询 POM、sources/Javadoc 与 `PacketEvents` 边界；它只用于客户端虚拟展示，必须幂等追加、准确还原客户端回传内容，并在重载/停用调用 `dispose()` 释放包监听器。
13. 使用 `EvalEx-j8` 时，先读 `agent-dev/docs/external-libraries/evalex-j8.md`，从项目锁定的 Maven Central GAV 查询资料；配置公式必须限制变量、输入/结果类型、范围和 `BigDecimal` 精度/舍入，解析失败不得触发业务副作用，缓存表达式不得跨玩家或线程共享可变变量。
14. 解析 Bukkit 枚举或注册表类型时使用 `Util.valueOr(...)`、`Util.valueOrNull(...)` 或对应 `Util.parse*` 方法；不要使用 `Enum.valueOf(...)` 或 `Material.valueOf(...)`。
15. 构建脚本已安装 `item-nbt-api` 时，物品自定义数据必须用该依赖读写；不得对 `ItemStack`/`ItemMeta` 使用 `PersistentDataContainer`、`PersistentDataType` 或 `getPersistentDataContainer()` 作为替代方案。
16. 修改后执行 `python agent-dev/tools/verify_plugin_project.py --project .`、项目 Gradle Wrapper 构建，并按 `agent-dev/docs/quality/build-and-artifact-checklist.md` 审查最终 JAR。

## 文档导航

- 布局和复制边界：`agent-dev/docs/00-layout-and-usage.md`
- 硬编码箱子容器菜单：`agent-dev/docs/gui/hardcoded-inventory-menus.md`
- 配置驱动箱子容器菜单：`agent-dev/docs/gui/config-driven-inventory-menus.md`
- 外部依赖总览：`agent-dev/docs/external-libraries/README.md`
- `ItemPacketModifier` 客户端虚拟 Lore：`agent-dev/docs/external-libraries/item-packet-modifier.md`
- `EvalEx-j8` 配置公式：`agent-dev/docs/external-libraries/evalex-j8.md`
- 开发总流程：`agent-dev/docs/02-development-workflow.md`
- 模板和构建：`agent-dev/docs/03-template-contract.md`
- PluginBase：`agent-dev/docs/pluginbase/overview.md`
- Spigot/Paper 选择：`agent-dev/docs/server-api/api-selection.md`
- 用户版本号完整性：`agent-dev/docs/server-api/minecraft-version-integrity.md`
- 证据规程：`agent-dev/docs/evidence/query-playbook.md`
- Gradle 依赖、类与继承索引：`agent-dev/docs/evidence/dependency-index.md`
- 工具命令：`agent-dev/tools/README.md`
- 审查与产物：`agent-dev/docs/quality/review-checklist.md`、`agent-dev/docs/quality/build-and-artifact-checklist.md`

对每个任务只读取解决当前决策所需的最少专题文档；完整索引位于 `agent-dev/docs/README.md`。
