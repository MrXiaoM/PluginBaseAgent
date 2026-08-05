#!/usr/bin/env python3
"""将 Skill 资源中的 agent-dev 文档包安全释放到目标插件项目。"""

from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path, PurePosixPath


SCRIPT_ROOT = Path(__file__).resolve().parent
KIT_ARCHIVE = SCRIPT_ROOT.parent / "assets" / "agent-dev-kit.zip"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="释放 PluginBase Agent 项目内开发包。")
    result.add_argument("--project", type=Path, required=True, help="目标插件项目根目录")
    result.add_argument("--force", action="store_true", help="覆盖 agent-dev 中已有的受管文件")
    result.add_argument("--dry-run", action="store_true", help="只显示将释放或跳过的文件")
    return result


def safe_destination(root: Path, member_name: str) -> Path:
    relative = PurePosixPath(member_name)
    if relative.is_absolute() or ".." in relative.parts:
        raise RuntimeError(f"资源包包含不安全路径：{member_name}")
    destination = root.joinpath(*relative.parts)
    resolved_root = root.resolve()
    resolved_destination = destination.resolve()
    if resolved_root != resolved_destination and resolved_root not in resolved_destination.parents:
        raise RuntimeError(f"资源包路径逃逸：{member_name}")
    return destination


def install(project: Path, force: bool, dry_run: bool) -> tuple[int, int]:
    if not KIT_ARCHIVE.is_file():
        raise RuntimeError(f"Skill 资源不完整：找不到 {KIT_ARCHIVE}")
    target = project / "agent-dev"
    installed = 0
    skipped = 0
    try:
        with zipfile.ZipFile(KIT_ARCHIVE) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                destination = safe_destination(target, member.filename)
                if destination.exists() and not force:
                    print(f"跳过已有文件：{destination}")
                    skipped += 1
                    continue
                action = "覆盖" if destination.exists() else "释放"
                print(f"{action}：{destination}")
                if not dry_run:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as source, destination.open("wb") as output:
                        shutil.copyfileobj(source, output)
                installed += 1
    except zipfile.BadZipFile as error:
        raise RuntimeError(f"Skill 资源不是有效 ZIP：{KIT_ARCHIVE}") from error
    return installed, skipped


def main() -> int:
    arguments = parser().parse_args()
    project = arguments.project.resolve()
    if not project.is_dir():
        print(f"错误：目标插件项目不存在或不是目录：{project}", file=sys.stderr)
        return 2
    try:
        installed, skipped = install(project, arguments.force, arguments.dry_run)
    except RuntimeError as error:
        print(f"错误：{error}", file=sys.stderr)
        return 2
    result = "预览完成" if arguments.dry_run else "释放完成"
    print(f"{result}：处理 {installed} 个文件，跳过 {skipped} 个已有文件。")
    if not arguments.dry_run:
        print(f"项目内开发包：{project / 'agent-dev'}")
        print("提示：agent-dev/state/ 是本地缓存，不应提交版本控制或打进插件 JAR。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
