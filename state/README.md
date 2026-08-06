# 本地状态目录

`agent-dev/state/` 是当前插件项目的本机工作状态目录。除本文件外，所有内容均不提交、不分发、不参与插件构建或 Shadow 打包。

本目录只保存三类轻量本地状态：机器 Gradle 环境、可重建依赖索引和项目依赖使用笔记。它不保存第三方 sources/Javadoc 归档或完整解包资料。

## 持久 Gradle 环境

`state/environment.json` 保存项目实际使用的 Gradle 用户目录，使恢复会话或更换 Agent 后仍能定位同一份本机缓存。

首次通过 Skill 初始化时，安装器会调用目标项目自己的 Gradle Wrapper，读取 Gradle 实际报告的 `gradleUserHomeDir` 并写入配置。已有有效配置会保留。只有 Wrapper 无法启动时才使用 `--gradle-user-home` 作为显式诊断覆盖。

```json
{
  "schemaVersion": 1,
  "gradleUserHomes": [
    "I:/gradle-cache"
  ]
}
```

- `gradleUserHomes` 是按优先顺序搜索的非空路径数组，可填写多个专用缓存目录。
- 未传 `--gradle-user-home` 时，环境文件存在就只使用其中的路径；不会回退到 `GRADLE_USER_HOME` 或默认 `C:` 用户目录。
- 空数组或无效 JSON 是配置错误，工具会停止并提示修复，而不是误查默认目录。
- `--gradle-user-home <目录>` 是单次命令的最高优先级覆盖，不会修改 `environment.json`。

## 运行期目录

```text
state/
  environment.json # 本机 Gradle 环境配置；初始化创建，不提交
  indexes/         # 可重建 SQLite 依赖、类名、公开 API 与继承关系索引
  notes/           # 本机项目依赖使用习惯与已验证边界的轻量 Markdown 笔记
```

`indexes/dependency-index.sqlite3` 由项目 Gradle 的真实解析结果完整重建。它只保存紧凑索引数据和必要摘要；第三方二进制 JAR、sources/Javadoc 仍由 Gradle 管理的本机缓存保存，资料包不会复制、下载或解包它们。

`notes/` 用于跨会话保留本项目的依赖使用习惯，例如实际 GAV、重定位目标、适配层、线程/生命周期边界、已拒绝方案和失效条件。具体格式与禁止内容见 `../docs/evidence/dependency-notes.md`。

## 使用边界

- 只保存当前项目开发所需的本地环境、可重建索引与轻量笔记；
- 不保存第三方归档、完整源码/Javadoc、反编译文本、大段命令输出或网页副本；
- 不保存服务端世界、生产数据库、密码、令牌、私有仓库凭据或真实生产连接串；
- 不把任何状态内容打进插件 JAR；
- 依赖笔记不能替代当前版本的索引查询和必要资料复核；
- 需要团队共享的稳定结论，应写入项目正式文档、提交说明或代码注释，而非提交本机 `state/`。

项目根 `.gitignore` 应包含：

```gitignore
agent-dev/state/
```

不要将本目录放入插件的 `src/`、`resources/` 或 `build/`。
