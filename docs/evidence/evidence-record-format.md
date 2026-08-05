# 证据记录格式

证据记录把“为什么使用此接口”从隐含经验变成可复查事实。记录应足够短，以便在开发说明、PR、任务日志或项目文档中保存；但不能省略版本、来源与签名。

## 最小记录模板

```markdown
- 结论：<采用或拒绝的技术结论>
- 用户指定 Minecraft 版本：`<原样文本>`
- 目标：<Spigot/Paper/PluginBase>；<精确构件或服务端版本>
- 版本映射依据：<构建脚本、仓库元数据、用户明确说明或原样 Wiki URL>
- 来源：<sources/Javadoc/元数据/锁定源码>
- 位置：<项目内相对路径或归档内路径>#<类/成员/锚点>
- 证据：<实际签名、注解、Javadoc 摘要或必要实现行为>
- 适用性：<为何满足需求；线程、弃用、最低版本等边界>
- 回退：<低版本、Spigot、依赖缺失或失败时的处理；无则写不适用>
```

## Spigot API 示例

```markdown
- 结论：使用 `<事件类>` 处理 `<行为>`。
- 目标：Spigot API；`<精确版本>`。
- 来源：sources。
- 位置：`agent-dev/state/evidence/spigot/<版本>/sources/<归档内路径>`#`<成员签名>`。
- 证据：`<实际类声明、可取消接口或方法签名>`。
- 适用性：在最低支持版本中存在；`<线程/取消语义>` 已按资料处理。
- 回退：不适用。
```

## PluginBase 双端工厂示例

```markdown
- 结论：插件在 Spigot/Paper 双端使用 `PaperFactory` 初始化物品编辑和库存工厂。
- 目标：PluginBase；`<精确版本>`。
- 来源：sources。
- 位置：`agent-dev/state/evidence/pluginbase-paper/<版本>/sources/.../PaperFactory.java`#`createItemEditor`、`createInventoryFactory`。
- 证据：工厂优先构造 Paper 实现，异常或探测失败时回退 Legacy/Bukkit 实现。
- 适用性：业务代码只依赖 `ItemEditor`/`InventoryFactory` 抽象，不直接加载 Paper-only 类型。
- 回退：Spigot 环境由工厂回退；直接 Paper API 功能不属于此结论。
```

## 被拒绝方案示例

```markdown
- 结论：不在最低支持版本使用 `<方法>`。
- 目标：Spigot API；`<最低版本>`。
- 来源：sources 与 Javadoc。
- 位置：`agent-dev/state/evidence/spigot/<版本>/...`#`<类>`。
- 证据：目标版本不存在该成员；它只在 `<更高版本>` 出现。
- 适用性：避免最低版本 `NoSuchMethodError` 或无法编译。
- 回退：使用 `<已证实替代>`，或提高最低支持版本并由用户确认。
```

## 记录质量检查

一条合格记录必须能回答：

1. 用的是什么精确版本？
2. 资料在哪里？别人能否在当前项目的 `agent-dev/state/` 或明确 URL 复查？
3. 实际调用的签名/行为是什么？
4. 它为什么适合本次任务？
5. 它在哪些版本、服务器或线程条件下不适用？

以下记录不合格：

- “Bukkit 有这个方法”；
- “Paper 应该支持”；
- “参考其它插件”；
- “IDE 能补全”；
- 只写链接而没有版本、路径、签名或结论；
- 只写代码片段，未说明最低版本与回退。
