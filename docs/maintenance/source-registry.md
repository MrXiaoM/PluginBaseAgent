# 构件来源注册表契约

项目内 `agent-dev/registry/` 保存 Spigot、Paper、PluginBase 与必要配套构件的资料获取策略。注册表让工具按项目声明的版本可复现地定位 sources/Javadoc，而不是依赖 Agent 记忆、开发机目录或网页搜索结果。

当前实现使用 `artifacts.json` 管理 Spigot/Paper API 与已登记的通用外部依赖，使用 `pluginbase.json` 管理 PluginBase 模块、Maven Central 优先与 JitPack 回退；工具命令见 `../../tools/README.md`。

## 注册表位置

```text
agent-dev/
  registry/
    artifacts.json      # 服务端 API 与通用外部构件策略
    pluginbase.json     # PluginBase 模块、版本与资料策略
```

注册表属于开发包版本的一部分，建议提交到插件项目。下载到 `agent-dev/state/` 的实际归档和索引不属于注册表，不应提交。

## 每个构件必须记录的字段

| 字段 | 含义 |
| --- | --- |
| `ecosystem` | `spigot`、`paper`、`pluginbase` 或其它明确生态标签。 |
| `group`、`artifact`、`version` | Maven 坐标；不可只写 Minecraft 大版本。 |
| `repositories` | 按优先顺序列出的公开仓库基础 URL。 |
| `sourcesClassifier` | 通常为 `sources`；例外必须记录。 |
| `javadocClassifier` | 通常为 `javadoc`；例外必须记录。 |
| `packaging` | 预期归档类型，如 `jar`。 |
| `module` | PluginBase 时的模块名与包前缀。 |
| `apiKind` | Spigot/Paper 时的 API 类型与兼容说明。 |
| `snapshot` | 是否可能在同版本字符串下变更内容。 |
| `licenseOrNotice` | 资料获取/使用时需保留的来源或许可证提示。 |
| `notes` | 版本特殊性、缺少某种资料时的已知限制。 |

当前 JSON 结构由工具读取；字段语义不得被简化为只有 URL 的无版本列表。新增字段需保持向后兼容，或与工具版本一同升级。

## 解析与下载规则

工具应：

1. 优先依据目标插件 `build.gradle.kts` 的真实依赖，确认构件版本；
2. 用注册表补全仓库、分类器和模块策略，不覆盖项目锁定版本；
3. 先查本地 `state/` 中同坐标同哈希资料，再查 Gradle 缓存；
4. 必要时按注册表仓库顺序下载；
5. 对每个归档记录 URL、HTTP/元数据版本、时间、大小和 `SHA-256`；
6. 不下载注册表中未被当前任务/项目需要的无关构件；
7. 下载失败时输出已尝试仓库与原因，不隐式改用另一个版本。

## Snapshot 规则

Snapshot 构件必须额外记录：

- 请求的版本字符串；
- 解析到的实际文件名或元数据时间戳（若仓库提供）；
- 下载时间；
- SHA-256；
- sources/Javadoc 是否来自同一解析版本。

同一个 Snapshot 坐标但 SHA-256 不同，视为不同资料状态。旧索引和基于旧内容写出的新开发结论需重新核验。

## PluginBase 模块规则

PluginBase 注册表除了 Maven 坐标，还应维护：

- 版本可用模块清单；
- 模块到包前缀的映射；
- `library`、`misc` 等基线模块关系；
- `paper` 模块用于 Spigot/Paper 双端工厂回退的说明；
- sources/Javadoc 是否按模块单独发布；
- LibrariesResolver 相关构件与 PluginBase 版本关系。

工具不能因为项目在 `pluginBaseModules` 中有一个模块，就假定其它模块的 class 也随之存在。

## 通用外部依赖规则

`artifacts.json` 中的 `item-packet-modifier`、`evalex-j8` 等 `external-library` 条目可提供 Maven Central、sources/Javadoc 与默认版本元数据，但现有 `api_evidence.py` 只接受 `spigot`、`paper`，不得假定它能自动同步通用库。查询通用库时，按 `../evidence/query-playbook.md` 的人工流程从项目锁定坐标、Gradle 缓存或 Maven Central 取得证据。

通用库条目应明确其运行期风险与专题文档；它们不是 PluginBase 模块，不能依据 `LibrariesResolver-Gradle` 的统一版本锚点推导版本。

## 注册表变更审查

修改注册表时必须检查：

- 新坐标是否能与项目实际 Gradle 依赖对应；
- 仓库是否公开、稳定且符合上游要求；
- sources/Javadoc 分类器是否真实存在；
- 是否引入许可证、认证或私有仓库限制；
- 是否影响已缓存资料的失效判断；
- 文档中的示例命令、资料路径和兼容性说明是否同步更新。

注册表不是依赖版本管理器；它不能替代项目的 Gradle 依赖声明、锁定策略和构建验证。
