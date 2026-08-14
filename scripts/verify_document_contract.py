#!/usr/bin/env python3
"""离线检查 Agent 文档的关键安全与路由契约。"""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def read(relative: str) -> str:
    path = PROJECT_ROOT / relative
    if not path.is_file():
        raise RuntimeError(f"缺少文档：{relative}")
    return path.read_text(encoding="utf-8")


def require(document: str, *fragments: str) -> None:
    for fragment in fragments:
        if fragment not in document:
            raise RuntimeError(f"文档缺少关键契约：{fragment}")


def reject(document: str, *fragments: str) -> None:
    for fragment in fragments:
        if fragment in document:
            raise RuntimeError(f"文档仍含已废弃的路由规则：{fragment}")


def main() -> int:
    item_nbt = read("docs/external-libraries/item-nbt-api.md")
    require(
        item_nbt,
        "NBT.get(itemStack, ...)",
        "NBT.modify(itemStack, ...)",
        "## 禁止的旧 `NBTItem` 路径",
        "`new NBTItem(...)`",
        "`applyNBT(...)`",
        "`mergeNBT(...)`",
        "`@Deprecated` Javadoc",
        "up to 400% faster",
        "`ItemMeta` 的安全顺序",
        "`NBT.modifyMeta(...)`",
        "Minecraft `1.20.5+`",
        "`custom_data` component",
        "`my_plugin_schema`",
        "键名仅使用小写字母、数字与下划线",
    )
    reject(item_nbt, "my-plugin:", "<plugin-id>:")

    contract = read("docs/01-agent-contract.md")
    workflow = read("docs/02-development-workflow.md")
    skill = read("skill/minecraft-pluginbase-development/SKILL.md")
    query_playbook = read("docs/evidence/query-playbook.md")
    require(
        contract,
        "不读取、不推断、不记录 `LibrariesResolver-Gradle` 的隐式 PluginBase 版本",
        "`@Deprecated` 的成员必须先读取弃用描述与替代项",
    )
    require(
        workflow,
        "只确认 `pluginBaseModules` 是否声明所需能力",
        "`item-nbt-api` 必须使用 `NBT.get(...)`/`NBT.modify(...)`",
    )
    require(
        skill,
        "不得为了重复确认而读取 `AbstractPluginHolder`、`AbstractModule`",
        "不读取、不推断、不记录 `LibrariesResolver-Gradle` 的隐式 PluginBase 版本",
        "不得使用已弃用的 `NBTItem` 路径",
    )
    require(
        query_playbook,
        "先阅读任务对应的 `agent-dev/docs/` 设计文档",
        "不得为重复确认这些结论而阅读框架实现源码或查询依赖资料",
        "若成员带有 `@Deprecated`，必须读取弃用描述和替代项",
    )

    all_markdown = "\n".join(
        path.read_text(encoding="utf-8")
        for path in PROJECT_ROOT.rglob("*.md")
        if ".git" not in path.parts
    )
    reject(
        all_markdown,
        "取得 PluginBase 的统一精确版本",
        "读取 PluginBase 统一精确版本",
        "它是模块版本锚点",
    )

    print("通过：文档具备 NBT 新 API 示例、弃用防护、设计文档优先和依赖索引事实优先契约。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
