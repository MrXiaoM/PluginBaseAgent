# Zoo Code 依赖索引工具规程

本规程适用于当前 Zoo Code 会话已提供 `pluginbase_dependency_index` 自定义工具的项目。该工具已由 Skill 初始化器创建并加载；首次依赖索引已在安装时建立。

## 强制规则

- 只要当前会话可调用 `pluginbase_dependency_index`，所有依赖索引查询必须调用该工具；不得为 `status`、`modules`、`dependencies`、`classes`、`members` 或 `show` 执行 `agent-dev/tools/dependency_index.py` CLI。
- 不执行 `status` 预检。初始化器已建立索引；需要资料时直接发起具体查询。
- 查询无命中、资料不足、索引缺失或索引过期时，不得因此自动执行 CLI `sync`。应根据结果停止猜测并报告缺少的证据。
- CLI `sync` 仅在以下任一条件满足时允许：Agent 已实际添加、删除或变更 Gradle 依赖坐标、版本或所属配置；或用户明确要求同步/重建依赖索引。即使满足条件，也只执行一次同步，然后继续使用 Zoo 工具查询。
- 工具结果只用于定位实际 GAV、运行字节码签名、继承关系、源码位置和短文档摘要；版本敏感调用仍须按任务要求复核完整 sources/Javadoc、弃用、线程与语义。

## 调用映射

| 目标 | 工具参数 |
| --- | --- |
| 列出 Gradle 模块 | `action: "modules"` |
| 查询模块直接依赖 | `action: "dependencies"`、`module: ":"` 或实际模块路径 |
| 查询模块传递依赖 | `action: "dependencies"`、`module`、`transitive: true` |
| 按类名或包关键词找类 | `action: "classes"`、`query` |
| 查询方法、字段、类型或签名 | `action: "members"`、`query` |
| 查看成员已确认的 Javadoc 页面与摘要 | `action: "members"`、`query`、`verbose: true` |
| 沿继承链查接收者可见成员 | `action: "members"`、`query`、`type: "完整或简单类型名"` |
| 查看构件摘要 | `action: "show"`、`query: "GAV 或哈希前缀"` |
| 查看主 JAR、sources/Javadoc 路径与哈希 | `action: "show"`、`query: "GAV 或哈希前缀"`、`verbose: true` |

`members` 的 `verbose: true` 返回 SQLite 已保存且唯一确认的 `javadoc` 页面条目路径和 `documentation` 短摘要，不重新读取 Javadoc 归档；资料有歧义或缺失时不猜测。`limit` 只在结果较多时设置，范围为 `1` 至 `20`。`dependencies` 可使用 `configuration` 限定 Gradle 配置。

## 推荐顺序

1. 陌生库先查询 `classes`，定位实际类和 GAV。
2. 再用 `members` 查目标方法、字段或构造器；需要成员说明时同时提供 `verbose: true`。已知接收者类型时必须提供 `type`，让索引沿 `extends`/`implements` 关系定位真实声明处。
3. 需要确认依赖来源或 Shadow/重定位影响时，用 `show` 或 `dependencies` 查询；需要实现细节时，以 `show` 的 `verbose: true` 取得主 JAR 与 `sources.jar` 路径，再按 `query-playbook.md` 直接读取 sources 或临时反编译。
4. 结果不足时，不用 `javap` 反复试探，不自动同步；记录阻塞并按项目证据规则继续处理。

## 需要同步的唯一常规场景

Agent 修改 `build.gradle.kts`、版本目录、锁文件或等效构建输入并实际改变依赖集合后，索引不再代表新的解析结果。此时允许通过 CLI 执行一次：

```text
python agent-dev/tools/dependency_index.py sync --project .
```

同步完成后，后续查询立即回到 `pluginbase_dependency_index`，不得继续用 CLI 查询。
