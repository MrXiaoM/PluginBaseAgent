# 资料包布局与使用方式

本资料包安装在目标插件项目的 `agent-dev/`，与插件源码并列。它提供可提交的规范与工具，以及不提交的本机状态。

## 最终项目布局

```text
<插件项目>/
  build.gradle.kts
  src/
  agent-dev/
    README.md
    QUICKSTART.md
    docs/
    tools/
    state/
      README.md
      environment.json
      indexes/
      notes/
```

`agent-dev/` 不依赖维护者的绝对路径、示例项目或预置 Gradle 缓存。目标项目的 Gradle Wrapper 是依赖构件与资料变体的唯一解析入口。

## 目录分类

| 目录 | 用途 | 可写性 | 是否提交 |
| --- | --- | --- | --- |
| `agent-dev/docs/` | 开发契约、专题规范、资料规程与维护说明 | 升级资料包时更新 | 是 |
| `agent-dev/tools/` | 依赖索引、选择性源码检查和项目验证工具 | 升级资料包时更新 | 是 |
| `agent-dev/state/environment.json` | 当前机器实际 Gradle 用户目录 | 初始化器与诊断工具写入 | 否 |
| `agent-dev/state/indexes/` | Gradle 实际解析结果的可重建 SQLite 索引 | 索引同步写入 | 否 |
| `agent-dev/state/notes/` | 项目依赖使用习惯、已验证边界与失效条件 | Agent 按规程维护 | 否 |

`state/` 禁止保存第三方二进制 JAR、`sources.jar`、Javadoc、完整解包资料或反编译文本。它们由 Gradle 缓存管理，或由临时检查工具在系统临时目录处理后立即清理。

## 复制规则

1. 将资源包内容完整释放到目标项目的 `agent-dev/`。
2. 保留项目根 `.gitignore` 对 `agent-dev/state/` 的忽略；不要把本机缓存或笔记提交到插件仓库。
3. 文档和工具之间只使用相对路径、公开 GAV 与归档内路径；不得记录盘符、用户名、令牌或私有仓库凭据。
4. 升级资料包时覆盖文档和工具；保留目标项目已有的 `state/environment.json`、`state/indexes/` 与 `state/notes/`，除非用户明确要求重置。

## 日常使用入口

1. 每次任务开始先读 `README.md`、`docs/01-agent-contract.md` 与 `state/environment.json`。
2. 涉及依赖、服务端 API、PluginBase 模块或重定位时，先读相关 `state/notes/*.md`。
3. 按 `docs/evidence/dependency-index-zoo-tool.md` 或 `docs/evidence/dependency-index-cli.md` 查询真实 Gradle 索引。
4. 需要实现细节时，按 `docs/evidence/query-playbook.md` 从 `show --verbose` 的路径直接读取 sources；缺少 sources 才临时 Vineflower 反编译。
5. 将之后仍会影响实现选择的已验证结论精简写回 `state/notes/`。

## 与 Skill 的关系

Skill 只负责安装入口、首次初始化和强制工作流。所有日常资料查询、笔记和验证均在目标项目的普通 `agent-dev/` 目录中完成，避免把运行态数据写入受保护的 Skill 目录。
