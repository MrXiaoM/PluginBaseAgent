#!/usr/bin/env python3
"""从当前文档真源构建 Skill 内的 agent-dev 文档资源包。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SKILL_NAME = "minecraft-pluginbase-development"
OUTPUT_PATH = PROJECT_ROOT / "skill" / SKILL_NAME / "assets" / "agent-dev-kit.zip"
KIT_SOURCES = (
    Path("README.md"),
    Path("QUICKSTART.md"),
    Path(".gitignore"),
    Path("docs"),
    Path("tools"),
    Path("state/README.md"),
)
EXCLUDED_PARTS = {"__pycache__", ".git", "state"}
EXCLUDED_SUFFIXES = {".pyc"}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="构建 minecraft-pluginbase-development Skill 的 agent-dev 资源包。"
    )
    result.add_argument("--output", type=Path, default=OUTPUT_PATH, help="资源 ZIP 输出路径")
    result.add_argument("--dry-run", action="store_true", help="只列出将写入资源包的文件")
    return result


def is_distributable(relative: Path) -> bool:
    if relative == Path("state/README.md"):
        return True
    return not any(part in EXCLUDED_PARTS for part in relative.parts) and relative.suffix not in EXCLUDED_SUFFIXES


def source_files() -> list[tuple[Path, Path]]:
    entries: list[tuple[Path, Path]] = []
    for relative in KIT_SOURCES:
        source = PROJECT_ROOT / relative
        if not source.exists():
            raise RuntimeError(f"找不到分发源：{source}")
        if source.is_file():
            entries.append((source, relative))
            continue
        for file in sorted(path for path in source.rglob("*") if path.is_file()):
            relative_file = file.relative_to(PROJECT_ROOT)
            if is_distributable(relative_file):
                entries.append((file, relative_file))
    return entries


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)


def build(output: Path, entries: list[tuple[Path, Path]]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip", dir=output.parent) as temporary:
        temporary_path = Path(temporary.name)
    try:
        manifest = {
            "schemaVersion": 1,
            "contentRoot": "agent-dev",
            "files": [
                {"path": str(destination).replace("\\", "/"), "sha256": sha256(source)}
                for source, destination in entries
            ],
        }
        with zipfile.ZipFile(temporary_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for source, destination in entries:
                archive.write(source, str(destination).replace("\\", "/"))
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        temporary_path.replace(output)
    finally:
        temporary_path.unlink(missing_ok=True)


def main() -> int:
    arguments = parser().parse_args()
    try:
        entries = source_files()
    except RuntimeError as error:
        print(f"错误：{error}", file=sys.stderr)
        return 2
    if arguments.dry_run:
        for _, destination in entries:
            print(destination.as_posix())
        print(f"预览完成：共 {len(entries)} 个文件。")
        return 0
    output = arguments.output.resolve()
    build(output, entries)
    print(f"已构建 Skill 资源包：{output}")
    print(f"包含 {len(entries)} 个 agent-dev 源文件；不含 state 缓存。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
