# 本地资料状态目录

本目录是未来 API/PluginBase 资料工具的运行期工作区。它随 `agent-dev/` 复制到目标插件项目，但其中除本文件外的内容默认不进入版本控制，也不参与插件构建或 Shadow 打包。

## 持久本地环境配置

`state/environment.json` 是本项目开发环境的持久本地配置。它专门保存上下文压缩、重新连接或更换 Agent 后仍必须保留的机器相关信息；它和下载缓存一样只留在本机，不得提交、分发或打进插件 JAR。

首次通过 Skill 安装资料包时，安装器会调用目标项目自己的 Gradle Wrapper，读取 Gradle 实际报告的 `gradleUserHomeDir` 并自动写入如下配置；Windows 路径使用正斜杠。已有有效配置会保留。只有 Wrapper 无法启动时才使用 `--gradle-user-home` 作为显式诊断覆盖：

```json
{
  "schemaVersion": 1,
  "gradleUserHomes": [
    "I:/gradle-cache"
  ]
}
```

- `gradleUserHomes` 是按优先顺序搜索的非空路径数组，可填写多个专用缓存目录。
- 取证工具未收到 `--gradle-user-home` 时，发现此文件就**只**搜索其中列出的路径；不会再回退到 `GRADLE_USER_HOME` 或默认 `C:` 用户目录。
- 空数组或无效 JSON 是配置错误，工具会停止并提示修复，而不是继续误查默认目录。
- `--gradle-user-home <目录>` 是单次命令的最高优先级覆盖，可用于临时诊断；它不会修改 `environment.json`。
- 每个恢复、压缩后继续的 Agent 任务都先读取此文件，再执行资料同步。路径不存在时可下载资料，但仍不会改去扫描其它盘符。

## 运行期子目录

```text
state/
  environment.json # 机器本地环境配置；首次安装创建，不分发、不提交
  downloads/       # 取证工具专用的原始 sources/Javadoc 归档
  evidence/        # 取证工具安全解包后的源码与 Javadoc
  indexes/         # 紧凑 SQLite 依赖、类名、公开 API 与继承关系索引
  records/         # 本地查询输出和临时证据记录
```

## 使用边界

- 只保存当前插件项目开发所需的第三方资料和机器本地环境配置；
- 不保存服务端世界、生产数据库、密码、令牌或私有仓库凭据；
- 不把任何内容打进插件 JAR；
- 不提交 `state/` 的下载归档、解包资料、索引或临时记录；
- 需要长期保留的结论，应转写成精简 Markdown 证据记录，包含坐标、版本、哈希和必要签名，而不是提交整份第三方归档；
- `indexes/dependency-index.sqlite3` 可随 Gradle 构建输入、Wrapper、锁文件或归档哈希变化重建，不应提交；依赖索引会流式读取 Gradle 缓存或临时下载的归档，只保存签名和短文档摘要，不保存 sources/Javadoc 副本或解包树。

项目根 `.gitignore` 应包含：

```gitignore
agent-dev/state/
```

若本资料包尚未复制到项目内，则对应忽略规则为未来目标项目的规则；不要将本目录错误放入插件的 `src/`、`resources/` 或 `build/`。
