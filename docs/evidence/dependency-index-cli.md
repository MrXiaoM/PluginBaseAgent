# 无 Zoo Code 时的依赖索引 CLI 规程

本规程仅适用于当前会话未提供 `pluginbase_dependency_index` Zoo 自定义工具的项目。若该工具可调用，必须改用 `dependency-index-zoo-tool.md`，不得用本规程的 CLI 查询替代工具调用。

## 强制规则

- 不执行 `status` 预检。Skill 初始化器已在安装时构建首次索引；需要资料时直接运行具体查询命令。
- 使用 CLI 查询不会自动同步。查询缺失、过期、无命中或资料不足时，不得因此自行运行 `sync`；停止猜测并报告结果。
- CLI `sync` 仅在以下任一条件满足时允许：Agent 已实际添加、删除或变更 Gradle 依赖坐标、版本或所属配置；或用户明确要求同步/重建依赖索引。
- 不能因“可能有新依赖”“想确认状态”“查询失败”或“准备写代码”执行 `sync`。
- 索引仅用于定位实际 GAV、运行字节码签名、继承关系、源码位置和短文档摘要。版本敏感调用仍按项目证据规则复核完整资料。

## 直接查询

从项目根目录执行具体查询，不先运行 `status`：

```text
python agent-dev/tools/dependency_index.py modules --project .
python agent-dev/tools/dependency_index.py dependencies --project . --module :
python agent-dev/tools/dependency_index.py dependencies --project . --module :feature --transitive
python agent-dev/tools/dependency_index.py classes --project . ItemStack
python agent-dev/tools/dependency_index.py members --project . getDisplayName
python agent-dev/tools/dependency_index.py members --project . addItem --type PlayerInventory
python agent-dev/tools/dependency_index.py show --project . --artifact top.mrxiaom:EvalEx-j8 --verbose
```

默认最多输出 `8` 条。需要更多匹配时使用 `--limit`、`--offset`；对 `show` 使用 `--verbose` 取得本机主 JAR、sources/Javadoc 路径与哈希。随后按 `query-playbook.md` 优先直接读取 sources；sources 缺失时才临时 Vineflower 反编译主 JAR。自动化调用使用 `--json`。

## 推荐顺序

1. 用 `classes` 找到陌生库的实际类与 GAV。
2. 用 `members` 查方法、字段、构造器或类型；已知接收者类型时必须加 `--type`，使索引沿继承链报告真实声明处。
3. 用 `show` 和 `dependencies` 核对构件、解析来源或传递依赖；需要实现细节时对 `show` 使用 `--verbose`，再按 `query-playbook.md` 检查目标源码。
4. 结果不足时，停止猜测；不要以 `javap` 反复试探，也不要自动同步。

## 允许同步的唯一常规场景

在 Agent 完成改变依赖集合的构建修改后，执行一次全量重建：

```text
python agent-dev/tools/dependency_index.py sync --project .
```

这里的依赖集合变更包括新增、删除或修改 `build.gradle.kts`、版本目录、锁文件或等效输入中的依赖坐标、版本或配置。同步会删除旧 SQLite 索引并完整重建；完成后再运行上方具体查询。用户也可以明确要求同步或重建，此时允许执行同一命令。
