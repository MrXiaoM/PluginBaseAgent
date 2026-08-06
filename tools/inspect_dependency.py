#!/usr/bin/env python3
"""按依赖索引给出的本机归档路径，临时查看单个依赖实现源码。"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any


GITHUB_RELEASES = "https://api.github.com/repos/Vineflower/vineflower/releases/latest"
USER_AGENT = "PluginBaseAgent-dependency-inspector"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="直接读取 sources JAR，或临时下载 Vineflower 反编译主 JAR 中的单个类。"
    )
    commands = result.add_subparsers(dest="command", required=True)
    source = commands.add_parser("source", help="从 sources JAR 直接输出一个 Java 源文件")
    source.add_argument("--sources", type=Path, required=True, help="依赖索引 show --verbose 返回的 sources 路径")
    source.add_argument("--class", dest="class_name", required=True, help="完整二进制类名，例如 example.api.Sample")
    decompile = commands.add_parser("decompile", help="临时下载 Vineflower 并反编译主 JAR 中的一个类")
    decompile.add_argument("--jar", type=Path, required=True, help="依赖索引 show --verbose 返回的 file 路径")
    decompile.add_argument("--class", dest="class_name", required=True, help="完整二进制类名，例如 example.api.Sample")
    return result


def source_entry(class_name: str) -> str:
    normalized = class_name.strip().replace(".", "/")
    if not normalized or normalized.startswith("/") or ".." in normalized:
        raise ValueError("类名必须是非空的完整二进制类名")
    return normalized.split("$", 1)[0] + ".java"


def read_java(archive: Path, class_name: str) -> tuple[str, str]:
    if not archive.is_file():
        raise RuntimeError(f"归档不存在：{archive}")
    expected = source_entry(class_name)
    try:
        with zipfile.ZipFile(archive) as source:
            try:
                data = source.read(expected)
                return expected, data.decode("utf-8", errors="replace")
            except KeyError:
                simple = expected.rsplit("/", 1)[-1]
                candidates = [entry.filename for entry in source.infolist() if entry.filename.endswith("/" + simple) or entry.filename == simple]
    except zipfile.BadZipFile as error:
        raise RuntimeError(f"不是可读取的 JAR/ZIP：{archive}") from error
    if len(candidates) == 1:
        with zipfile.ZipFile(archive) as source:
            return candidates[0], source.read(candidates[0]).decode("utf-8", errors="replace")
    if candidates:
        raise RuntimeError(f"sources 中存在多个同名候选，拒绝猜测：{', '.join(candidates[:8])}")
    raise RuntimeError(f"sources 中没有 {expected}")


def github_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            value = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as error:
        raise RuntimeError(f"无法读取 Vineflower GitHub Releases：{error}") from error
    if not isinstance(value, dict):
        raise RuntimeError("Vineflower GitHub Releases 返回了无效数据")
    return value


def download_vineflower(destination: Path) -> tuple[str, str]:
    release = github_json(GITHUB_RELEASES)
    tag = str(release.get("tag_name") or "未知版本")
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise RuntimeError("Vineflower 最新发布没有可用资产列表")
    candidates = [
        asset
        for asset in assets
        if isinstance(asset, dict)
        and str(asset.get("name", "")).endswith(".jar")
        and "-sources" not in str(asset.get("name", ""))
        and "-javadoc" not in str(asset.get("name", ""))
    ]
    if len(candidates) != 1:
        names = [str(asset.get("name")) for asset in candidates]
        raise RuntimeError(f"无法唯一确定 Vineflower JAR 资产：{names}")
    url = str(candidates[0].get("browser_download_url") or "")
    if not url.startswith("https://"):
        raise RuntimeError("Vineflower 发布资产没有安全下载 URL")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)
    except urllib.error.URLError as error:
        raise RuntimeError(f"无法下载 Vineflower {tag}：{error}") from error
    try:
        with zipfile.ZipFile(destination) as archive:
            if "META-INF/MANIFEST.MF" not in archive.namelist():
                raise RuntimeError("下载的 Vineflower 资产不是有效 JAR")
    except zipfile.BadZipFile as error:
        raise RuntimeError("下载的 Vineflower 资产不是有效 JAR") from error
    return tag, url


def locate_decompiled_java(output: Path, class_name: str) -> tuple[str, str]:
    expected = source_entry(class_name)
    archives = sorted(path for path in output.rglob("*") if path.is_file() and path.suffix.lower() in {".jar", ".zip"})
    for archive in archives:
        try:
            return read_java(archive, class_name)
        except RuntimeError:
            continue
    direct = output / expected
    if direct.is_file():
        return expected, direct.read_text(encoding="utf-8", errors="replace")
    raise RuntimeError(f"Vineflower 未生成目标源码：{expected}")


def command_source(arguments: argparse.Namespace) -> int:
    entry, text = read_java(arguments.sources, arguments.class_name)
    print(f"来源：sources JAR {arguments.sources} | 条目：{entry}", file=sys.stderr)
    print(text, end="" if text.endswith("\n") else "\n")
    return 0


def command_decompile(arguments: argparse.Namespace) -> int:
    if not arguments.jar.is_file():
        raise RuntimeError(f"主 JAR 不存在：{arguments.jar}")
    with tempfile.TemporaryDirectory(prefix="pluginbase-agent-vineflower-") as temporary:
        root = Path(temporary)
        vineflower = root / "vineflower.jar"
        output = root / "output"
        tag, url = download_vineflower(vineflower)
        print(f"临时下载 Vineflower {tag}：{url}", file=sys.stderr)
        result = subprocess.run(
            ["java", "-jar", str(vineflower), "-dgs=1", str(arguments.jar), str(output)],
            text=True,
            capture_output=True,
            check=False,
            timeout=120,
        )
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(f"Vineflower 反编译失败：{detail or '没有输出'}")
        entry, text = locate_decompiled_java(output, arguments.class_name)
        print(f"来源：Vineflower {tag} 临时反编译 {arguments.jar} | 条目：{entry}", file=sys.stderr)
        print(text, end="" if text.endswith("\n") else "\n")
    return 0


def main() -> int:
    arguments = parser().parse_args()
    try:
        if arguments.command == "source":
            return command_source(arguments)
        return command_decompile(arguments)
    except (RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"错误：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
