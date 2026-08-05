"""面向 Minecraft 插件资料的纯标准库证据处理工具。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as element_tree
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

TEXT_SUFFIXES = {".java", ".html", ".htm", ".txt", ".js", ".css", ".xml", ".properties", ".json"}
USER_AGENT = "PluginBaseAgentEvidence/1.0"


class EvidenceError(RuntimeError):
    pass


def print_error(message: str) -> None:
    print(f"错误：{message}", file=sys.stderr)


def load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as stream:
            value = json.load(stream)
    except FileNotFoundError as error:
        raise EvidenceError(f"找不到配置文件 {path}") from error
    except json.JSONDecodeError as error:
        raise EvidenceError(f"配置文件不是有效 JSON：{path}：{error}") from error
    if not isinstance(value, dict):
        raise EvidenceError(f"配置文件根节点必须是对象：{path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    temporary.replace(path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)


def normalize_maven_path(group: str, artifact: str, version: str) -> str:
    return "/".join([group.replace(".", "/"), artifact, version])


def configured_gradle_homes(state_root: Path) -> list[Path] | None:
    """读取项目持久环境配置；文件存在时不允许隐式回退到默认 Gradle 目录。"""
    path = state_root / "environment.json"
    if not path.is_file():
        return None
    environment = load_json(path)
    homes = environment.get("gradleUserHomes")
    if not isinstance(homes, list) or not all(isinstance(value, str) and value.strip() for value in homes):
        raise EvidenceError(
            f"环境配置 `{path}` 的 gradleUserHomes 必须是非空路径字符串数组；"
            "为避免误查默认 Gradle 目录，工具已停止。"
        )
    if not homes:
        raise EvidenceError(
            f"环境配置 `{path}` 尚未填写 gradleUserHomes；"
            "请填入实际 Gradle 缓存目录，或为本次命令显式传入 --gradle-user-home。"
        )
    return [Path(value).expanduser() for value in homes]


def default_gradle_homes(explicit: str | None, state_root: Path) -> list[Path]:
    """按显式参数、项目环境文件、环境变量、默认目录的顺序取得 Gradle 缓存。"""
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    else:
        configured = configured_gradle_homes(state_root)
        if configured is not None:
            candidates.extend(configured)
        else:
            environment = os.environ.get("GRADLE_USER_HOME")
            if environment:
                candidates.append(Path(environment).expanduser())
            candidates.append(Path.home() / ".gradle")
    unique: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve() if candidate.exists() else candidate
        if resolved not in unique:
            unique.append(resolved)
    return unique


def find_cached_artifacts(
    gradle_homes: Iterable[Path], group: str, artifact: str, version: str, classifier: str
) -> list[Path]:
    filename = f"{artifact}-{version}-{classifier}.jar"
    matches: list[Path] = []
    for home in gradle_homes:
        base = home / "caches" / "modules-2" / "files-2.1" / group / artifact / version
        if not base.is_dir():
            continue
        for path in base.glob(f"*/{filename}"):
            if path.is_file():
                matches.append(path)
    return sorted(matches, key=lambda item: item.stat().st_mtime, reverse=True)


def request_bytes(url: str, timeout: int = 30) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        reason = getattr(error, "reason", None) or str(error) or error.__class__.__name__
        raise EvidenceError(f"下载失败：{url}：{reason}") from error


def parse_snapshot_value(metadata: bytes, version: str, classifier: str, extension: str) -> str | None:
    try:
        root = element_tree.fromstring(metadata)
    except element_tree.ParseError:
        return None
    for node in root.findall(".//snapshotVersion"):
        found_extension = node.findtext("extension")
        found_classifier = node.findtext("classifier") or ""
        value = node.findtext("value")
        if found_extension == extension and found_classifier == classifier and value:
            return value
    timestamp = root.findtext(".//snapshot/timestamp")
    build_number = root.findtext(".//snapshot/buildNumber")
    if timestamp and build_number and version.endswith("-SNAPSHOT"):
        return f"{version[:-9]}-{timestamp}-{build_number}"
    return None


def download_artifact(
    repositories: Iterable[str], group: str, artifact: str, version: str, classifier: str, destination: Path
) -> tuple[str, str]:
    base_path = normalize_maven_path(group, artifact, version)
    errors: list[str] = []
    for repository in repositories:
        root = repository.rstrip("/")
        resolved_version = version
        if version.endswith("-SNAPSHOT"):
            metadata_url = f"{root}/{base_path}/maven-metadata.xml"
            try:
                metadata = request_bytes(metadata_url)
                resolved = parse_snapshot_value(metadata, version, classifier, "jar")
                if resolved:
                    resolved_version = resolved
            except EvidenceError as error:
                errors.append(str(error))
        filename = f"{artifact}-{resolved_version}-{classifier}.jar"
        url = f"{root}/{base_path}/{filename}"
        try:
            body = request_bytes(url)
        except EvidenceError as error:
            errors.append(str(error))
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(body)
        return url, resolved_version
    joined = "\n".join(f"- {error}" for error in errors)
    raise EvidenceError(f"无法下载 {group}:{artifact}:{version}:{classifier}\n{joined}")


def copy_or_download(
    *, gradle_homes: Iterable[Path], group: str, artifact: str, version: str, classifier: str,
    repositories: Iterable[str], destination: Path
) -> dict[str, Any]:
    cached = find_cached_artifacts(gradle_homes, group, artifact, version, classifier)
    if cached:
        source = cached[0]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return {"origin": "gradle-cache", "source": str(source), "resolvedVersion": version}
    url, resolved_version = download_artifact(repositories, group, artifact, version, classifier, destination)
    return {"origin": "maven", "source": url, "resolvedVersion": resolved_version}


def safe_extract(archive: Path, destination: Path) -> int:
    destination.mkdir(parents=True, exist_ok=True)
    count = 0
    try:
        with zipfile.ZipFile(archive) as source:
            for member in source.infolist():
                relative = PurePosixPath(member.filename)
                if relative.is_absolute() or ".." in relative.parts:
                    raise EvidenceError(f"归档包含不安全路径：{member.filename}")
                target = destination.joinpath(*relative.parts)
                resolved_root = destination.resolve()
                resolved_target = target.resolve()
                if resolved_root != resolved_target and resolved_root not in resolved_target.parents:
                    raise EvidenceError(f"归档路径逃逸：{member.filename}")
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open(member) as input_stream, target.open("wb") as output_stream:
                    shutil.copyfileobj(input_stream, output_stream)
                count += 1
    except zipfile.BadZipFile as error:
        raise EvidenceError(f"不是有效 JAR/ZIP：{archive}") from error
    return count


def artifact_root(state_root: Path, ecosystem: str, version: str) -> Path:
    return state_root / "evidence" / ecosystem / version


def manifest_path(state_root: Path, ecosystem: str, version: str) -> Path:
    return artifact_root(state_root, ecosystem, version) / "manifest.json"


def sync(
    *, state_root: Path, ecosystem: str, user_minecraft_version: str | None, group: str, artifact: str,
    version: str, repositories: Iterable[str], gradle_user_home: str | None, classifiers: Iterable[str],
    metadata: dict[str, Any] | None = None
) -> dict[str, Any]:
    root = artifact_root(state_root, ecosystem, version)
    downloads = state_root / "downloads" / ecosystem / version
    homes = default_gradle_homes(gradle_user_home, state_root)
    artifact_entries: list[dict[str, Any]] = []
    for classifier in classifiers:
        archive = downloads / f"{artifact}-{version}-{classifier}.jar"
        copied = copy_or_download(
            gradle_homes=homes, group=group, artifact=artifact, version=version, classifier=classifier,
            repositories=repositories, destination=archive,
        )
        extracted = root / classifier
        if extracted.exists():
            shutil.rmtree(extracted)
        file_count = safe_extract(archive, extracted)
        artifact_entries.append({
            "classifier": classifier,
            "archive": str(archive.relative_to(state_root)),
            "sha256": sha256(archive),
            "origin": copied["origin"],
            "source": copied["source"],
            "resolvedVersion": copied["resolvedVersion"],
            "extracted": str(extracted.relative_to(state_root)),
            "fileCount": file_count,
        })
    manifest: dict[str, Any] = {
        "schemaVersion": 1,
        "ecosystem": ecosystem,
        "userMinecraftVersion": user_minecraft_version,
        "coordinate": {"group": group, "artifact": artifact, "version": version},
        "synchronizedAtEpoch": int(time.time()),
        "artifacts": artifact_entries,
    }
    if metadata:
        manifest["metadata"] = metadata
    write_json(manifest_path(state_root, ecosystem, version), manifest)
    return manifest


def iter_text_files(root: Path) -> Iterable[Path]:
    if not root.is_dir():
        return []
    return (path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES)


def find_matches(root: Path, query: str, context: int = 2, limit: int = 80) -> list[dict[str, Any]]:
    try:
        pattern = re.compile(re.escape(query), re.IGNORECASE)
    except re.error as error:
        raise EvidenceError(f"无效查询：{query}：{error}") from error
    matches: list[dict[str, Any]] = []
    for path in iter_text_files(root):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for index, line in enumerate(lines):
            if not pattern.search(line):
                continue
            start = max(0, index - context)
            end = min(len(lines), index + context + 1)
            matches.append({
                "path": str(path.relative_to(root)),
                "line": index + 1,
                "context": lines[start:end],
                "contextStartLine": start + 1,
            })
            if len(matches) >= limit:
                return matches
    return matches


def print_matches(root: Path, query: str, limit: int = 80) -> int:
    matches = find_matches(root, query, limit=limit)
    if not matches:
        print(f"未证明符号存在：在 {root} 中未找到 `{query}`")
        return 1
    print(f"查询 `{query}`：{len(matches)} 个命中（根目录：{root}）")
    for match in matches:
        print(f"\n{match['path']}:{match['line']}")
        for number, line in enumerate(match["context"], start=match["contextStartLine"]):
            marker = ">" if number == match["line"] else " "
            print(f"{marker} {number:5d} | {line}")
    return 0


def load_manifest(state_root: Path, ecosystem: str, version: str) -> dict[str, Any]:
    return load_json(manifest_path(state_root, ecosystem, version))


def compare_text_roots(old_root: Path, new_root: Path, symbol: str) -> int:
    old = find_matches(old_root, symbol, context=0, limit=200)
    new = find_matches(new_root, symbol, context=0, limit=200)
    old_keys = {(item["path"], item["context"][0]) for item in old}
    new_keys = {(item["path"], item["context"][0]) for item in new}
    print(f"比较符号 `{symbol}`")
    print(f"旧版本命中：{len(old)}；新版本命中：{len(new)}")
    removed = old_keys - new_keys
    added = new_keys - old_keys
    if removed:
        print("\n旧版本存在、新版本未找到的文本：")
        for path, line in sorted(removed):
            print(f"- {path}: {line}")
    if added:
        print("\n新版本新增或变化的文本：")
        for path, line in sorted(added):
            print(f"+ {path}: {line}")
    if not removed and not added:
        print("未发现基础文本差异；这不等于完整 ABI 或运行时兼容证明。")
    return 0
