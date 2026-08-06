# 分发、版权与本地状态边界

本资料包让每个插件项目拥有可提交的 Agent 开发规范和工具，但不分发第三方 API 归档，也不依赖维护者机器的私有目录。

## 应分发的内容

复制到 `<plugin-project>/agent-dev/` 并建议随插件项目提交：

- `README.md`、`QUICKSTART.md` 与 `docs/` 中的规范；
- `tools/` 中的 Python 标准库工具；
- `state/README.md`；
- 版本、变更说明和必要的证据/笔记模板。

这些内容只引用相对路径、公开 GAV、归档内路径和公开 URL，不包含盘符、用户名、缓存绝对路径或本机服务端位置。

## 不应分发或提交的内容

| 内容 | 原因 | 位置 |
| --- | --- | --- |
| Spigot/Paper/PluginBase/第三方的主 JAR、sources/Javadoc 归档 | 体积、许可证、版本漂移 | 目标项目 Gradle 用户目录，不复制 |
| 完整源码/Javadoc、反编译文本 | 许可证、体积、可由路径重新读取 | 系统临时目录，工具退出即删除 |
| Gradle 依赖、类名、公开 API 与继承关系索引 | 可重建、可能随工具版本变化 | `agent-dev/state/indexes/` |
| 本机 Gradle 环境与依赖使用笔记 | 机器/项目局部状态 | `agent-dev/state/environment.json`、`notes/` |
| 服务端运行目录、世界数据、日志、数据库 | 项目外运行数据或敏感信息 | 服务端环境，不进入资料包 |
| 密码、令牌、私有仓库凭据和真实生产连接串 | 安全敏感 | 仅安全配置渠道 |

项目根 `.gitignore` 至少应包含：

```gitignore
agent-dev/state/
```

若团队决定提交某个证据结论，只提交精简 Markdown、精确 GAV、哈希和归档内位置，不提交第三方归档或完整资料。

## Gradle 与临时检查边界

1. 目标项目 Gradle Wrapper 按项目实际仓库、镜像、认证、版本替换和缓存策略解析主 JAR、sources 与 Javadoc。
2. `dependency_index.py` 记录这些构件的路径、哈希和从运行字节码提取的签名；它不扫描缓存猜测文件，也不复制归档。
3. 需要实现细节时，优先从索引 `show --verbose` 返回的 `sources` 路径直接读取一个 Java 条目。
4. `sources` 不存在时，`inspect_dependency.py decompile` 才会通过官方 Vineflower GitHub Releases API 临时下载唯一 JAR 资产、反编译索引返回的主 JAR，并在退出时清理全部临时文件。
5. 不得将 Vineflower、反编译结果或资料归档改存到 `state/`；不得把临时反编译作为字节码签名、兼容性或线程语义的唯一证据。

`environment.json` 一旦存在但为空或无效，工具必须停止，绝不改为扫描默认 C 盘缓存。工具不得把某台开发机的缓存路径写进文档、构建脚本或项目源码。

## Skill 的边界

Skill 只提供简要入口、资源包释放、首次索引和工作流引导：

- Skill 不存放本地构件、索引或任务笔记；
- Skill 引导 Agent 进入当前项目 `agent-dev/`；
- 日常查询、笔记和验证都使用普通项目目录；
- 文档/工具升级通过更新并重建 `agent-dev` 资源包完成；
- Skill 仅在入口协议或强制工作流变化时升级。

## 许可证与来源尊重

- 获取、使用和再分发每个第三方归档时遵循其许可证、仓库条款和上游要求；
- 只解析当前项目开发所需构件，不批量镜像无关版本；
- 记录来源时保留 GAV、哈希、归档内路径和必要归属；
- 不将上游 Javadoc/源码或反编译内容大段复制进资料包或本地笔记；只记录为当前结论必要的签名与短摘要。
