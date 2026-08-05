# 开发规范索引

本目录应位于目标插件项目的 `agent-dev/docs/`。本文按开发决策分类导航；先从 `agent-dev/README.md` 和 `00-layout-and-usage.md` 开始。

## 通用入口

| 文件 | 解决的问题 |
| --- | --- |
| `00-layout-and-usage.md` | 文档包如何复制到项目、哪些目录可写/可提交、工具和缓存应放在哪里。 |
| `01-agent-contract.md` | Agent 的强制约束：默认 Spigot、先取证、不猜测、生命周期与最低验证。 |
| `02-development-workflow.md` | 从需求、证据、设计到构建和交付的完整执行顺序。 |
| `03-template-contract.md` | `template-site` 生成项目的构建、模块、依赖、资源和 Shadow 基线。 |

## 箱子容器菜单

| 文件 | 解决的问题 |
| --- | --- |
| `gui/hardcoded-inventory-menus.md` | Java 硬编码的 `Inventory` 箱子容器菜单：每玩家 Holder、slot、点击、拖拽、关闭、异步与返回链。 |
| `gui/config-driven-inventory-menus.md` | YAML 配置驱动的箱子容器菜单：字符布局、图标模型、重载、多菜单，以及 `gui`/`actions`/`l10n` 的组合边界。 |

## PluginBase

| 文件 | 解决的问题 |
| --- | --- |
| `pluginbase/overview.md` | PluginBase 的嵌入模型、模块边界和全局使用原则。 |
| `pluginbase/lifecycle-and-main-class.md` | `BukkitPlugin` 主类、Options、生命周期、Spigot/Paper 双端工厂覆写。 |
| `pluginbase/modules-and-capabilities.md` | 各模块的选择条件，特别是 `paper` 双端兼容层的正确用途。 |
| `pluginbase/auto-register-and-holders.md` | `@AutoRegister`、Holder 构造器、优先级、预扫描索引和 `inst()` 访问风格。 |
| `pluginbase/configuration-database-and-libraries.md` | 配置重载、数据库、经济、resolver 与动态库加载。 |
| `pluginbase/concurrency-and-folia.md` | 调度、线程、异步、任务停用和 Folia 声明边界。 |
| `pluginbase/packaging-and-relocation.md` | Shadow、私有包重定位、`scanIgnore`、Holder 索引和最终 JAR 检查。 |

## 服务端 API

| 文件 | 解决的问题 |
| --- | --- |
| `server-api/api-selection.md` | 何时选 Spigot、Paper 或 PluginBase `paper` 模块，以及三者区别。 |
| `server-api/spigot-first-rules.md` | 默认 Spigot 路径下的事件、命令、对象生命周期、配置和版本风险。 |
| `server-api/paper-extension-rules.md` | Paper-only 功能的前提、隔离、回退、类加载与线程规则。 |
| `server-api/version-compatibility.md` | Minecraft/API/PluginBase 升级与最低版本承诺。 |
| `server-api/minecraft-version-integrity.md` | 用户版本号原样保留、陌生版本的 Wiki 核验与 API 构件映射边界。 |
| `server-api/nms-boundary.md` | NMS、CraftBukkit 和反射的显式许可与版本隔离边界。 |

## 证据与资料

| 文件 | 解决的问题 |
| --- | --- |
| `evidence/evidence-policy.md` | 哪些结论必须取证、可接受来源、精确版本和停止条件。 |
| `evidence/evidence-record-format.md` | 记录接口或框架结论的标准模板。 |
| `evidence/query-playbook.md` | 资料同步、缓存、人工查询与当前工具命令协议。 |

## 质量与维护

| 文件 | 解决的问题 |
| --- | --- |
| `quality/coding-style.md` | 包职责、代码风格、空值/异常、兼容层和资源管理。 |
| `quality/review-checklist.md` | 功能修改的审查清单。 |
| `quality/build-and-artifact-checklist.md` | Gradle、Shadow、JAR 和服务端启动验证清单。 |
| `maintenance/update-policy.md` | PluginBase/API/模板/资料包的更新流程和失效规则。 |
| `maintenance/source-registry.md` | 未来资料注册表的字段、下载和 Snapshot 校验契约。 |
| `maintenance/distribution-boundary.md` | 分发内容、缓存、版权、Git 和未来 Skill 的边界。 |

## 任务到文档的最短路径

| 任务 | 必读文件 |
| --- | --- |
| 新建模板项目 | `03-template-contract.md`、`pluginbase/packaging-and-relocation.md` |
| 新增命令/监听器 | `01-agent-contract.md`、`server-api/spigot-first-rules.md`、`pluginbase/auto-register-and-holders.md` |
| 新增 Java 硬编码箱子容器菜单 | `gui/hardcoded-inventory-menus.md`、`pluginbase/modules-and-capabilities.md`、`evidence/query-playbook.md` |
| 新增 YAML 配置驱动箱子容器菜单 | `gui/config-driven-inventory-menus.md`、`pluginbase/modules-and-capabilities.md`、`pluginbase/configuration-database-and-libraries.md` |
| 新增 GUI/物品功能且需 Spigot/Paper 双端支持 | `pluginbase/modules-and-capabilities.md`、`pluginbase/lifecycle-and-main-class.md`、`server-api/api-selection.md` |
| 增加 Paper-only 功能 | `server-api/api-selection.md`、`server-api/paper-extension-rules.md`、`evidence/evidence-policy.md` |
| 增加配置、数据库或动态库 | `pluginbase/configuration-database-and-libraries.md`、`quality/review-checklist.md` |
| 修改构建、发布和依赖 | `03-template-contract.md`、`pluginbase/packaging-and-relocation.md`、`quality/build-and-artifact-checklist.md` |
| 用户给出陌生、前沿或非传统 Minecraft 版本号 | `server-api/minecraft-version-integrity.md`；保留原样版本并按 Wiki URL 核验，绝不自动改写。 |
| 升级服务端/API/PluginBase | `server-api/version-compatibility.md`、`maintenance/update-policy.md`、`evidence/query-playbook.md` |
| 想使用 NMS 或反射 | `server-api/nms-boundary.md`；未获明确许可时停止。 |
