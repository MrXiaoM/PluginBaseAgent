#!/usr/bin/env python3
"""同步并查询目标 Spigot/Paper API 的 sources 与 Javadoc 证据。"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_ROOT))

from common.evidence import (  # noqa: E402
    EvidenceError,
    artifact_root,
    compare_text_roots,
    load_json,
    load_manifest,
    print_error,
    print_matches,
    sync,
)

PROJECT_ROOT = SCRIPT_ROOT.parent
REGISTRY_PATH = PROJECT_ROOT / "registry" / "artifacts.json"
STATE_ROOT = PROJECT_ROOT / "state"


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="同步、查询和比较 Spigot/Paper API 的本地 sources/Javadoc 证据。"
    )
    subcommands = root.add_subparsers(dest="command", required=True)

    sync_parser = subcommands.add_parser("sync", help="同步 sources 与 Javadoc 到 state 目录")
    sync_parser.add_argument("--api", choices=("spigot", "paper"), required=True)
    sync_parser.add_argument(
        "--minecraft", required=True,
        help="用户指定的 Minecraft 版本原样文本；工具绝不自动改写。"
    )
    sync_parser.add_argument(
        "--artifact-version", help="精确 Maven 构件版本；未指定时使用 <minecraft>-R0.1-SNAPSHOT。"
    )
    sync_parser.add_argument("--gradle-user-home", help="优先复用的 Gradle 用户目录")
    sync_parser.add_argument("--state", type=Path, default=STATE_ROOT, help="本地状态目录")

    query_parser = subcommands.add_parser("query", help="在已同步资料中查询符号")
    query_parser.add_argument("--api", choices=("spigot", "paper"), required=True)
    query_parser.add_argument("--minecraft", required=True, help="同步时使用的原样 Minecraft 版本文本")
    query_parser.add_argument("--artifact-version", help="精确 Maven 构件版本；默认 <minecraft>-R0.1-SNAPSHOT")
    query_parser.add_argument("--symbol", help="全文搜索的完整类名、简单类名或成员名")
    query_parser.add_argument("--type", dest="type_name", help="类型限定搜索：完整/简单类型名，可沿继承关系查成员")
    query_parser.add_argument("--member", help="与 --type 配合的成员名或片段")
    query_parser.add_argument("--limit", type=int, default=8, help="最大命中数，默认 8")
    query_parser.add_argument("--state", type=Path, default=STATE_ROOT, help="本地状态目录")

    compare_parser = subcommands.add_parser("compare", help="比较两个已同步版本中的符号文本")
    compare_parser.add_argument("--api", choices=("spigot", "paper"), required=True)
    compare_parser.add_argument("--from", dest="old_minecraft", required=True, help="旧版本原样文本")
    compare_parser.add_argument("--to", dest="new_minecraft", required=True, help="新版本原样文本")
    compare_parser.add_argument("--from-artifact-version", help="旧精确 Maven 构件版本")
    compare_parser.add_argument("--to-artifact-version", help="新精确 Maven 构件版本")
    compare_parser.add_argument("--symbol", required=True)
    compare_parser.add_argument("--state", type=Path, default=STATE_ROOT, help="本地状态目录")

    status_parser = subcommands.add_parser("status", help="列出已同步的 API 资料")
    status_parser.add_argument("--state", type=Path, default=STATE_ROOT, help="本地状态目录")
    return root


def artifact_version(minecraft: str, explicit: str | None) -> str:
    return explicit if explicit else f"{minecraft}-R0.1-SNAPSHOT"


def command_sync(arguments: argparse.Namespace) -> int:
    registry = load_json(REGISTRY_PATH)
    entry = registry.get("artifacts", {}).get(arguments.api)
    if not isinstance(entry, dict):
        raise EvidenceError(f"注册表中没有 API `{arguments.api}`")
    version = artifact_version(arguments.minecraft, arguments.artifact_version)
    manifest = sync(
        state_root=arguments.state,
        ecosystem=arguments.api,
        user_minecraft_version=arguments.minecraft,
        group=str(entry["group"]),
        artifact=str(entry["artifact"]),
        version=version,
        repositories=[str(value) for value in entry["repositories"]],
        gradle_user_home=arguments.gradle_user_home,
        classifiers=(str(entry.get("sourcesClassifier", "sources")), str(entry.get("javadocClassifier", "javadoc"))),
        metadata={"api": arguments.api, "registry": str(REGISTRY_PATH.relative_to(PROJECT_ROOT))},
    )
    print(f"已同步 {arguments.api} API：用户 Minecraft 版本 `{arguments.minecraft}`，构件 `{version}`")
    for item in manifest["artifacts"]:
        print(
            f"- {item['classifier']}：{item['origin']}，SHA-256 {item['sha256']}，"
            f"解包 {item['fileCount']} 个文件"
        )
    print(f"清单：{arguments.state / 'evidence' / arguments.api / version / 'manifest.json'}")
    return 0


def command_query(arguments: argparse.Namespace) -> int:
    version = artifact_version(arguments.minecraft, arguments.artifact_version)
    manifest = load_manifest(arguments.state, arguments.api, version)
    original = manifest.get("userMinecraftVersion")
    if original != arguments.minecraft:
        raise EvidenceError(
            f"已同步资料记录的用户 Minecraft 版本为 `{original}`，与本次输入 `{arguments.minecraft}` 不同；"
            "工具不会将两个版本视为同一版本。"
        )
    root = artifact_root(arguments.state, arguments.api, version)
    if arguments.type_name or arguments.member:
        if not arguments.type_name or not arguments.member:
            raise EvidenceError("类型限定查询必须同时传入 --type 与 --member。")
        return query_member_with_inheritance(root / "sources", arguments.type_name, arguments.member, arguments.limit)
    if not arguments.symbol:
        raise EvidenceError("查询必须传入 --symbol，或同时传入 --type 与 --member。")
    print(f"证据：用户 Minecraft 版本 `{original}`；构件 `{version}`")
    source_code = print_matches(root / "sources", arguments.symbol, arguments.limit)
    javadoc_code = print_matches(root / "javadoc", arguments.symbol, arguments.limit)
    return 0 if source_code == 0 or javadoc_code == 0 else 1


def java_types(source_root: Path) -> tuple[dict[str, dict[str, object]], dict[str, set[str]]]:
    """取得可公开检索的 Java 类型及其直接父类/接口关系。"""
    types: dict[str, dict[str, object]] = {}
    simple_names: dict[str, set[str]] = {}
    pattern = re.compile(
        r"\b(?:public\s+)?(?:abstract\s+|final\s+)?(?:class|interface|enum|record)\s+"
        r"(\w+)(?:\s+extends\s+([^\{]+?))?(?:\s+implements\s+([^\{]+?))?\s*\{"
    )
    for source in sorted(source_root.rglob("*.java")):
        try:
            lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        package = ""
        imports: dict[str, str] = {}
        for line in lines[:200]:
            package_match = re.match(r"\s*package\s+([\w.]+)\s*;", line)
            if package_match:
                package = package_match.group(1)
            import_match = re.match(r"\s*import\s+([\w.]+)\s*;", line)
            if import_match and not import_match.group(1).endswith(".*"):
                imported = import_match.group(1)
                imports[imported.rsplit(".", 1)[-1]] = imported
        for line_number, line in enumerate(lines, start=1):
            match = pattern.search(line)
            if not match:
                continue
            simple = match.group(1)
            qualified = f"{package}.{simple}" if package else simple
            parents: list[str] = []
            for clause in (match.group(2), match.group(3)):
                if not clause:
                    continue
                for parent in clause.split(","):
                    name = re.sub(r"<.*?>", "", parent).strip().split()[0]
                    if not name:
                        continue
                    parents.append(name if "." in name else imports.get(name, f"{package}.{name}" if package else name))
            types[qualified] = {"path": source.relative_to(source_root).as_posix(), "line": line_number, "parents": parents}
            simple_names.setdefault(simple, set()).add(qualified)
    return types, simple_names


def query_member_with_inheritance(source_root: Path, type_name: str, member: str, limit: int) -> int:
    types, simple_names = java_types(source_root)
    seeds = {type_name} if "." in type_name else simple_names.get(type_name, set())
    if not seeds:
        print(f"未找到类型：{type_name}")
        return 1
    visible: dict[str, int] = {}
    pending = [(item, 0) for item in seeds]
    while pending:
        current, distance = pending.pop(0)
        if current in visible and visible[current] <= distance:
            continue
        visible[current] = distance
        pending.extend((parent, distance + 1) for parent in types.get(current, {}).get("parents", []))
    hits: list[tuple[int, str, str, int, str]] = []
    member_pattern = re.compile(rf"\b{re.escape(member)}\s*\(", re.IGNORECASE)
    for owner, distance in visible.items():
        data = types.get(owner)
        if not data:
            continue
        path = source_root / str(data["path"])
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line_number, line in enumerate(lines, start=1):
            if member_pattern.search(line):
                hits.append((distance, owner, str(data["path"]), line_number, " ".join(line.split())))
    hits.sort()
    shown = hits[:max(1, limit)]
    print(f"{type_name} 可见成员 `{member}`：{len(hits)}")
    for distance, owner, path, line_number, declaration in shown:
        inherited = "" if distance == 0 else f" | 继承 {distance}"
        print(f"声明于 {owner}{inherited} | {declaration} | {path}:{line_number}")
    if len(hits) > len(shown):
        print(f"其余 {len(hits) - len(shown)} 条；使用更精确成员名或提高 --limit")
    return 0 if hits else 1


def command_compare(arguments: argparse.Namespace) -> int:
    old_version = artifact_version(arguments.old_minecraft, arguments.from_artifact_version)
    new_version = artifact_version(arguments.new_minecraft, arguments.to_artifact_version)
    old_manifest = load_manifest(arguments.state, arguments.api, old_version)
    new_manifest = load_manifest(arguments.state, arguments.api, new_version)
    if old_manifest.get("userMinecraftVersion") != arguments.old_minecraft:
        raise EvidenceError("旧资料的用户 Minecraft 版本与 --from 输入不同；拒绝近似匹配。")
    if new_manifest.get("userMinecraftVersion") != arguments.new_minecraft:
        raise EvidenceError("新资料的用户 Minecraft 版本与 --to 输入不同；拒绝近似匹配。")
    print(
        f"版本完整性：旧 `{arguments.old_minecraft}` -> 构件 `{old_version}`；"
        f"新 `{arguments.new_minecraft}` -> 构件 `{new_version}`"
    )
    return compare_text_roots(
        artifact_root(arguments.state, arguments.api, old_version) / "sources",
        artifact_root(arguments.state, arguments.api, new_version) / "sources",
        arguments.symbol,
    )


def command_status(arguments: argparse.Namespace) -> int:
    evidence_root = arguments.state / "evidence"
    if not evidence_root.is_dir():
        print("尚未同步任何 API 资料。")
        return 0
    found = False
    for manifest_file in sorted(evidence_root.glob("*/*/manifest.json")):
        manifest = load_json(manifest_file)
        coordinate = manifest.get("coordinate", {})
        user_version = manifest.get("userMinecraftVersion")
        version_text = f"用户 Minecraft `{user_version}`" if user_version is not None else "无用户 Minecraft 版本（框架资料）"
        print(
            f"{manifest.get('ecosystem')}：{version_text}；"
            f"构件 `{coordinate.get('group')}:{coordinate.get('artifact')}:{coordinate.get('version')}`"
        )
        found = True
    if not found:
        print("尚未同步任何 API 资料。")
    return 0


def main() -> int:
    arguments = parser().parse_args()
    try:
        if arguments.command == "sync":
            return command_sync(arguments)
        if arguments.command == "query":
            return command_query(arguments)
        if arguments.command == "compare":
            return command_compare(arguments)
        if arguments.command == "status":
            return command_status(arguments)
        raise EvidenceError(f"未知命令：{arguments.command}")
    except EvidenceError as error:
        print_error(str(error))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
