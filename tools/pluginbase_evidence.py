#!/usr/bin/env python3
"""同步并查询目标 PluginBase 模块的 sources 与 Javadoc 证据。"""

from __future__ import annotations

import argparse
import shutil
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
REGISTRY_PATH = PROJECT_ROOT / "registry" / "pluginbase.json"
STATE_ROOT = PROJECT_ROOT / "state"


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="同步、查询和比较 PluginBase 模块资料。")
    subcommands = root.add_subparsers(dest="command", required=True)

    sync_parser = subcommands.add_parser("sync", help="同步一个 PluginBase 模块的 sources 与 Javadoc")
    sync_parser.add_argument("--version", required=True, help="目标项目实际锁定的 PluginBase 版本")
    sync_parser.add_argument("--module", required=True, help="PluginBase 模块名，例如 library、misc、paper")
    sync_parser.add_argument("--gradle-user-home", help="优先复用的 Gradle 用户目录")
    sync_parser.add_argument("--state", type=Path, default=STATE_ROOT)

    query_parser = subcommands.add_parser("query", help="在已同步模块资料中查询符号")
    query_parser.add_argument("--version", required=True)
    query_parser.add_argument("--module", required=True)
    query_parser.add_argument("--symbol", required=True)
    query_parser.add_argument("--limit", type=int, default=80)
    query_parser.add_argument("--state", type=Path, default=STATE_ROOT)

    compare_parser = subcommands.add_parser("compare", help="比较同一模块的两个已同步版本")
    compare_parser.add_argument("--from", dest="old_version", required=True)
    compare_parser.add_argument("--to", dest="new_version", required=True)
    compare_parser.add_argument("--module", required=True)
    compare_parser.add_argument("--symbol", required=True)
    compare_parser.add_argument("--state", type=Path, default=STATE_ROOT)

    modules_parser = subcommands.add_parser("modules", help="列出注册表支持的模块")
    modules_parser.add_argument("--json", action="store_true", help="输出原始 JSON")
    return root


def registry_module(registry: dict, module: str) -> dict:
    modules = registry.get("modules", {})
    entry = modules.get(module)
    if not isinstance(entry, dict):
        available = ", ".join(sorted(modules))
        raise EvidenceError(f"未知 PluginBase 模块 `{module}`；可用模块：{available}")
    return entry


def ecosystem(module: str) -> str:
    return f"pluginbase-{module}"


def command_sync(arguments: argparse.Namespace) -> int:
    registry = load_json(REGISTRY_PATH)
    entry = registry_module(registry, arguments.module)
    classifiers = (str(registry.get("sourcesClassifier", "sources")), str(registry.get("javadocClassifier", "javadoc")))
    candidates = [{
        "name": "Maven Central",
        "group": str(registry["group"]),
        "repositories": [str(value) for value in registry["repositories"]],
    }]
    for fallback in registry.get("fallbackCoordinates", []):
        candidates.append({
            "name": "JitPack 回退",
            "group": str(fallback["group"]),
            "repositories": [str(value) for value in fallback["repositories"]],
        })

    errors: list[str] = []
    manifest = None
    chosen = None
    state_artifact_root = artifact_root(arguments.state, ecosystem(arguments.module), arguments.version)
    state_download_root = arguments.state / "downloads" / ecosystem(arguments.module) / arguments.version
    for candidate in candidates:
        shutil.rmtree(state_artifact_root, ignore_errors=True)
        shutil.rmtree(state_download_root, ignore_errors=True)
        try:
            manifest = sync(
                state_root=arguments.state,
                ecosystem=ecosystem(arguments.module),
                user_minecraft_version=None,
                group=candidate["group"],
                artifact=arguments.module,
                version=arguments.version,
                repositories=candidate["repositories"],
                gradle_user_home=arguments.gradle_user_home,
                classifiers=classifiers,
                metadata={
                    "module": arguments.module,
                    "moduleDescription": entry.get("description"),
                    "packagePrefixes": entry.get("packagePrefixes", []),
                    "registry": str(REGISTRY_PATH.relative_to(PROJECT_ROOT)),
                    "coordinateSource": candidate["name"],
                },
            )
            chosen = candidate
            break
        except EvidenceError as error:
            errors.append(f"{candidate['name']}：{error}")
    if manifest is None or chosen is None:
        raise EvidenceError("无法同步 PluginBase 资料：\n" + "\n".join(f"- {error}" for error in errors))
    print(
        f"已同步 PluginBase `{arguments.module}` 模块，版本 `{arguments.version}`；"
        f"来源 `{chosen['name']}`，坐标组 `{chosen['group']}`"
    )
    for item in manifest["artifacts"]:
        print(f"- {item['classifier']}：{item['origin']}，SHA-256 {item['sha256']}，解包 {item['fileCount']} 个文件")
    print(f"清单：{arguments.state / 'evidence' / ecosystem(arguments.module) / arguments.version / 'manifest.json'}")
    return 0


def command_query(arguments: argparse.Namespace) -> int:
    registry = load_json(REGISTRY_PATH)
    registry_module(registry, arguments.module)
    manifest = load_manifest(arguments.state, ecosystem(arguments.module), arguments.version)
    coordinate = manifest.get("coordinate", {})
    if coordinate.get("artifact") != arguments.module or coordinate.get("version") != arguments.version:
        raise EvidenceError("已同步资料与指定模块/版本不一致；拒绝近似查询。")
    root = artifact_root(arguments.state, ecosystem(arguments.module), arguments.version)
    print(f"证据：PluginBase 模块 `{arguments.module}`；版本 `{arguments.version}`")
    source_code = print_matches(root / "sources", arguments.symbol, arguments.limit)
    javadoc_code = print_matches(root / "javadoc", arguments.symbol, arguments.limit)
    return 0 if source_code == 0 or javadoc_code == 0 else 1


def command_compare(arguments: argparse.Namespace) -> int:
    registry = load_json(REGISTRY_PATH)
    registry_module(registry, arguments.module)
    old_manifest = load_manifest(arguments.state, ecosystem(arguments.module), arguments.old_version)
    new_manifest = load_manifest(arguments.state, ecosystem(arguments.module), arguments.new_version)
    if old_manifest.get("coordinate", {}).get("artifact") != arguments.module:
        raise EvidenceError("旧资料不属于指定模块。")
    if new_manifest.get("coordinate", {}).get("artifact") != arguments.module:
        raise EvidenceError("新资料不属于指定模块。")
    print(f"比较 PluginBase `{arguments.module}`：`{arguments.old_version}` -> `{arguments.new_version}`")
    return compare_text_roots(
        artifact_root(arguments.state, ecosystem(arguments.module), arguments.old_version) / "sources",
        artifact_root(arguments.state, ecosystem(arguments.module), arguments.new_version) / "sources",
        arguments.symbol,
    )


def command_modules(arguments: argparse.Namespace) -> int:
    registry = load_json(REGISTRY_PATH)
    modules = registry.get("modules", {})
    if arguments.json:
        import json
        print(json.dumps(modules, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    for name, entry in sorted(modules.items()):
        print(f"{name}: {entry.get('description', '')}")
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
        if arguments.command == "modules":
            return command_modules(arguments)
        raise EvidenceError(f"未知命令：{arguments.command}")
    except EvidenceError as error:
        print_error(str(error))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
