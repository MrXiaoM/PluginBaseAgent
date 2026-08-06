#!/usr/bin/env python3
"""按 Gradle 模块建立 SQLite 依赖、类与公开 Java API 索引。"""

from __future__ import annotations

import argparse
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import queue
import time
import zipfile
import struct
from pathlib import Path
from typing import Any, Iterable, Iterator

SCRIPT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_ROOT))

from common.evidence import (  # noqa: E402
    EvidenceError,
    default_gradle_homes,
    print_error,
    sha256,
)

PROJECT_ROOT = SCRIPT_ROOT.parent
STATE_ROOT = PROJECT_ROOT / "state"
INDEX_SCHEMA_VERSION = 12
TOOL_VERSION = "12"
DEFAULT_LIMIT = 8
MAX_ARTIFACT_WORKERS = 8
MAX_LIMIT = 100
CLASS_INSERT_BATCH_SIZE = 2_000
API_INSERT_BATCH_SIZE = 2_000
ZOO_ZOD_VERSION = "3.25.76"
MARKER_START = "__PLUGIN_BASE_AGENT_DEPENDENCY_INDEX_START__"
MARKER_END = "__PLUGIN_BASE_AGENT_DEPENDENCY_INDEX_END__"

INIT_SCRIPT = r'''import groovy.json.JsonOutput

allprojects { project ->
    tasks.register("pluginBaseAgentDependencyIndex") {
        group = "plugin base agent"
        description = "Writes resolved dependency metadata for PluginBase Agent."
        doLast {
            def root = project.rootProject
            if (project != root) return
            def output = [schemaVersion: 2, gradleVersion: gradle.gradleVersion, projects: []]
            def includeApi = gradle.startParameter.projectProperties.get("pluginBaseAgentIncludeApi") != "false"
            def documentationArchives = [:]
            root.allprojects.sort { it.path }.each { current ->
                def documentationArchive = { artifact, classifierValue ->
                    def id = artifact.moduleVersion.id
                    def key = "${id.group}:${id.name}:${id.version}:${classifierValue}"
                    if (documentationArchives.containsKey(key)) return documentationArchives[key]
                    try {
                        if (!id.group || !id.name || !id.version) return documentationArchives[key] = [file: "", failure: "构件没有完整 GAV"]
                        println("[PluginBase Agent] 解析资料构件 ${documentationArchives.size() + 1}：${key}")
                        def dependency = current.dependencies.create("${id.group}:${id.name}:${id.version}")
                        dependency.transitive = false
                        dependency.artifact {
                            name = id.name
                            type = "jar"
                            extension = "jar"
                            classifier = classifierValue
                        }
                        def detached = current.configurations.detachedConfiguration(dependency)
                        detached.transitive = false
                        def files = detached.resolve().findAll { it.isFile() }.sort { it.absolutePath }
                        def selected = files.find { it.name.endsWith("-${classifierValue}.jar") } ?: files.find { it.name.endsWith(".jar") }
                        return documentationArchives[key] = (selected ? [file: selected.absolutePath, failure: ""] : [file: "", failure: "Gradle 未解析到 ${classifierValue}.jar"])
                    } catch (Throwable error) {
                        return documentationArchives[key] = [file: "", failure: error.class.name + ": " + (error.message ?: "")]
                    }
                }
                def projectData = [path: current.path, name: current.name, configurations: []]
                current.configurations.findAll { configuration -> configuration.canBeResolved }.sort { it.name }.each { configuration ->
                    def configData = [name: configuration.name, status: "ok", artifacts: [], dependencies: [], failures: []]
                    try {
                        configuration.resolvedConfiguration.resolvedArtifacts.toList().sort { it.file.absolutePath }.each { artifact ->
                            def id = artifact.moduleVersion.id
                            configData.artifacts << [
                                group: id.group ?: "", artifact: id.name ?: "", version: id.version ?: "",
                                classifier: artifact.classifier ?: "", extension: artifact.extension ?: "",
                                file: artifact.file.absolutePath, type: artifact.type ?: "",
                                sources: includeApi ? documentationArchive(artifact, "sources") : [file: "", failure: "未请求 API 索引"],
                                javadoc: includeApi ? documentationArchive(artifact, "javadoc") : [file: "", failure: "未请求 API 索引"]
                            ]
                        }
                        configuration.incoming.resolutionResult.allDependencies.each { dependency ->
                            def requested = dependency.requested?.displayName ?: ""
                            def from = dependency.from?.id?.displayName ?: ""
                            if (dependency instanceof org.gradle.api.artifacts.result.ResolvedDependencyResult) {
                                configData.dependencies << [kind: "resolved", from: from, requested: requested, selected: dependency.selected?.id?.displayName ?: ""]
                            } else if (dependency instanceof org.gradle.api.artifacts.result.UnresolvedDependencyResult) {
                                configData.dependencies << [kind: "unresolved", from: from, requested: requested, selected: ""]
                                configData.failures << (dependency.failure?.message ?: requested)
                            } else {
                                configData.dependencies << [kind: "other", from: from, requested: requested, selected: ""]
                            }
                        }
                    } catch (Throwable error) {
                        configData.status = "failed"
                        configData.failures << (error.class.name + ": " + (error.message ?: ""))
                    }
                    projectData.configurations << configData
                }
                output.projects << projectData
            }
            println("''' + MARKER_START + '''")
            println(JsonOutput.toJson(output))
            println("''' + MARKER_END + '''")
        }
    }
}
gradle.rootProject { root ->
    root.tasks.matching { it.name == "pluginBaseAgentDependencyIndex" }.configureEach { task -> task.outputs.upToDateWhen { false } }
}
'''


class IndexError(EvidenceError):
    """索引构建或读取失败。"""


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="按 Gradle 模块查询 SQLite 依赖、类和公开 Java API 索引。")
    root.add_argument("--state", type=Path, default=STATE_ROOT, help="agent-dev 本地状态目录")
    subcommands = root.add_subparsers(dest="command", required=True)

    sync_parser = subcommands.add_parser("sync", help="同步 Gradle 模块、依赖、类与公开 API 到 SQLite")
    add_project_argument(sync_parser)
    sync_parser.add_argument("--gradle-user-home", help="单次 Gradle/资料缓存目录覆盖")
    sync_parser.add_argument("--configuration", action="append", default=[], help="只同步名称匹配的可解析配置，可重复")
    sync_parser.add_argument("--no-api", action="store_true", help="只索引依赖与类名，不读取 sources/Javadoc")
    sync_parser.add_argument("--workers", type=int, help=f"并行处理构件的工作线程数，默认按 CPU 自动选择，最大 {MAX_ARTIFACT_WORKERS}")

    status_parser = subcommands.add_parser("status", help="显示 SQLite 索引摘要与是否过期")
    add_project_argument(status_parser)
    status_parser.add_argument("--json", action="store_true", help="输出紧凑 JSON")

    modules_parser = subcommands.add_parser("modules", help="列出已索引 Gradle 模块")
    add_project_argument(modules_parser)
    add_output_arguments(modules_parser)

    dependencies_parser = subcommands.add_parser("dependencies", help="列出模块依赖")
    add_project_argument(dependencies_parser)
    dependencies_parser.add_argument("--module", required=True, help="Gradle 模块路径，例如 : 或 :feature")
    dependencies_parser.add_argument("--configuration", help="只查询一个配置")
    dependencies_parser.add_argument("--transitive", action="store_true", help="同时显示传递依赖边")
    add_output_arguments(dependencies_parser)

    classes_parser = subcommands.add_parser("classes", help="按类名、简单名或包前缀搜索类")
    add_project_argument(classes_parser)
    classes_parser.add_argument("query", help="类名关键词")
    add_output_arguments(classes_parser)

    members_parser = subcommands.add_parser("members", help="搜索公开类型、方法、字段或签名；可沿继承关系查成员")
    add_project_argument(members_parser)
    members_parser.add_argument("query", help="成员、类型或签名关键词")
    members_parser.add_argument("--type", dest="type_name", help="限定为该类型可见的成员，自动沿 extends/implements 回溯")
    add_output_arguments(members_parser)

    show_parser = subcommands.add_parser("show", help="显示一个构件的索引摘要")
    add_project_argument(show_parser)
    show_parser.add_argument("--artifact", required=True, help="GAV、文件名或构件哈希前缀")
    add_output_arguments(show_parser)

    zoo_parser = subcommands.add_parser("install-zoo", help="显式安装 Zoo Code 查询工具（维护/修复用途）")
    add_project_argument(zoo_parser)
    zoo_parser.add_argument("--force", action="store_true", help="覆盖同名 Zoo 工具")
    zoo_parser.add_argument("--dry-run", action="store_true", help="只显示将创建或跳过的文件")
    return root


def add_project_argument(command: argparse.ArgumentParser) -> None:
    command.add_argument("--project", type=Path, default=Path("."), help="目标 Gradle 插件项目根目录，默认当前目录")


def add_output_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"最大结果数，默认 {DEFAULT_LIMIT}")
    command.add_argument("--offset", type=int, default=0, help="跳过前 N 条结果")
    command.add_argument("--json", action="store_true", help="输出紧凑 JSON")
    command.add_argument("--verbose", action="store_true", help="显示来源、路径、哈希及已确认的资料摘要等详情")


def index_path(state_root: Path) -> Path:
    return state_root / "indexes" / "dependency-index.sqlite3"


def normalize_project(project: Path) -> Path:
    resolved = project.resolve()
    if not resolved.is_dir():
        raise IndexError(f"目标项目不存在或不是目录：{project}")
    return resolved


def project_files(project: Path) -> list[Path]:
    names = ("settings.gradle", "settings.gradle.kts", "build.gradle", "build.gradle.kts", "gradle.properties", "gradle.lockfile")
    files = [project / name for name in names if (project / name).is_file()]
    files.extend(path for path in project.rglob("*.versions.toml") if ".gradle" in path.parts)
    files.extend(path for path in project.rglob("*.lockfile") if ".gradle" in path.parts)
    wrapper = project / "gradle" / "wrapper"
    if wrapper.is_dir():
        files.extend(path for path in wrapper.iterdir() if path.is_file())
    files.extend(project / name for name in ("gradlew", "gradlew.bat") if (project / name).is_file())
    return sorted(set(files))


def fingerprint(project: Path) -> dict[str, Any]:
    entries = []
    digest = hashlib.sha256()
    for file in project_files(project):
        relative = file.relative_to(project).as_posix()
        value = sha256(file)
        entries.append({"path": relative, "sha256": value})
        digest.update(relative.encode("utf-8"))
        digest.update(value.encode("ascii"))
    return {"sha256": digest.hexdigest(), "files": entries}


def gradle_command(project: Path, arguments: list[str]) -> list[str]:
    batch = project / "gradlew.bat"
    shell = project / "gradlew"
    if sys.platform == "win32" and batch.is_file():
        return [str(batch), *arguments]
    if shell.is_file():
        if sys.platform == "win32":
            bash = shutil.which("bash")
            if not bash:
                raise IndexError("目标项目只有 gradlew，但当前 Windows 环境找不到 bash；请使用带 gradlew.bat 的模板项目。")
            return [bash, str(shell), *arguments]
        return [str(shell), *arguments]
    if batch.is_file():
        return [str(batch), *arguments]
    raise IndexError(f"找不到 Gradle Wrapper：{shell} 或 {batch}")


def compact_text(value: str, limit: int) -> str:
    normalized = " ".join(value.split())
    return normalized[:limit] + ("…" if len(normalized) > limit else "")


def run_gradle(project: Path, state_root: Path, explicit_home: str | None, include_api: bool) -> dict[str, Any]:
    """实时转发 Gradle 日志，仅保留标记区间中的索引 JSON。"""
    homes = default_gradle_homes(explicit_home, state_root)
    environment = os.environ.copy()
    if homes:
        environment["GRADLE_USER_HOME"] = str(homes[0])
    with tempfile.TemporaryDirectory(prefix="pluginbase-agent-index-") as temporary:
        init_file = Path(temporary) / "dependency-index.init.gradle"
        init_file.write_text(INIT_SCRIPT, encoding="utf-8", newline="\n")
        arguments = ["--no-daemon", "--console=plain", "--init-script", str(init_file)]
        if not include_api:
            arguments.append("-PpluginBaseAgentIncludeApi=false")
        command = gradle_command(project, [*arguments, "pluginBaseAgentDependencyIndex"])
        try:
            process = subprocess.Popen(command, cwd=project, env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8", errors="replace", bufsize=1)
        except OSError as error:
            raise IndexError(f"无法启动 Gradle Wrapper：{error}") from error
        assert process.stdout is not None
        lines: queue.Queue[str | None] = queue.Queue()

        def read_output() -> None:
            try:
                for line in process.stdout:
                    lines.put(line)
            finally:
                lines.put(None)

        reader = threading.Thread(target=read_output, name="pluginbase-agent-gradle-output", daemon=True)
        reader.start()
        started = time.monotonic()
        index_lines: list[str] = []
        diagnostics: deque[str] = deque(maxlen=200)
        in_index = False
        while True:
            remaining = 300 - (time.monotonic() - started)
            if remaining <= 0:
                process.kill()
                process.wait()
                raise IndexError("Gradle 依赖解析超过 300 秒；请检查网络、仓库或配置。")
            try:
                line = lines.get(timeout=min(1.0, remaining))
            except queue.Empty:
                continue
            if line is None:
                break
            text = line.rstrip("\r\n")
            if text == MARKER_START:
                in_index = True
                continue
            if text == MARKER_END:
                in_index = False
                continue
            if in_index:
                index_lines.append(line)
                continue
            diagnostics.append(line)
            if text:
                print(f"[Gradle] {text}", flush=True)
        process.wait()
        reader.join(timeout=1)
    if in_index or not index_lines:
        raise IndexError(f"Gradle 未输出完整索引 JSON（退出码 {process.returncode}）：{compact_text(''.join(diagnostics), 800)}")
    try:
        parsed = json.loads("".join(index_lines).strip())
    except json.JSONDecodeError as error:
        raise IndexError(f"Gradle 输出的索引 JSON 无效：{error}") from error
    if not isinstance(parsed, dict) or not isinstance(parsed.get("projects"), list):
        raise IndexError("Gradle 输出的索引结构无效。")
    return parsed


def selected_configurations(raw: dict[str, Any], names: list[str]) -> dict[str, Any]:
    if not names:
        return raw
    wanted = set(names)
    result = dict(raw)
    result["projects"] = [
        {**project, "configurations": [item for item in project.get("configurations", []) if item.get("name") in wanted]}
        for project in raw.get("projects", [])
    ]
    return result


def native_path(value: str) -> Path:
    """将 Git Bash/MSYS 的 /c/... Gradle 路径转换为原生 Windows 可访问路径。"""
    if os.name == "nt":
        match = re.match(r"^/([A-Za-z])/(.*)$", value)
        if match:
            return Path(f"{match.group(1)}:/{match.group(2)}")
    return Path(value)


def valid_coordinate(artifact: dict[str, Any]) -> tuple[str, str, str] | None:
    group, name, version = (str(artifact.get(key, "")).strip() for key in ("group", "artifact", "version"))
    if not group or not name or not version or group == "unspecified" or version == "unspecified":
        return None
    return group, name, version


def coordinate_text(row: sqlite3.Row) -> str:
    if row["group_name"] and row["artifact_name"] and row["version"]:
        return f"{row['group_name']}:{row['artifact_name']}:{row['version']}"
    return row["file_name"] or "未知文件"


class ArchiveHashCache:
    """按归档路径、大小与修改时间复用 SHA-256，避免每次同步重读大型缓存归档。"""

    def __init__(self, entries: dict[str, tuple[int, int, str]] | None = None):
        self.entries = entries or {}

    def digest(self, path: Path) -> str:
        resolved = path.resolve()
        key = str(resolved)
        status = resolved.stat()
        current = (status.st_size, status.st_mtime_ns)
        cached = self.entries.get(key)
        if cached and cached[:2] == current:
            return cached[2]
        digest = sha256(resolved)
        self.entries[key] = (*current, digest)
        return digest

    def rows(self) -> Iterable[tuple[str, int, int, str]]:
        return ((path, size, modified, digest) for path, (size, modified, digest) in self.entries.items())


def load_archive_hashes(database: Path) -> ArchiveHashCache:
    if not database.is_file():
        return ArchiveHashCache()
    try:
        connection = sqlite3.connect(database)
        try:
            rows = connection.execute("SELECT path, size, modified_ns, sha256 FROM archive_hashes").fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return ArchiveHashCache()
    return ArchiveHashCache({str(path): (int(size), int(modified), str(digest)) for path, size, modified, digest in rows})


def reference_archive(raw: dict[str, Any], classifier: str, hashes: ArchiveHashCache) -> tuple[Path, dict[str, str]] | None:
    """只读取目标项目 Gradle 已解析的资料归档；索引器绝不自行联网下载。"""
    value = raw.get(classifier)
    if not isinstance(value, dict):
        return None
    archive = native_path(str(value.get("file", "")))
    if not archive.is_file():
        return None
    return archive, {"sha256": hashes.digest(archive), "origin": "gradle", "source": str(archive), "resolvedVersion": str(raw.get("version", ""))}


def is_indexable_class_entry(entry: zipfile.ZipInfo) -> bool:
    name = entry.filename
    if entry.is_dir() or not name.endswith(".class") or name.startswith("META-INF/") or name.endswith("module-info.class"):
        return False
    binary = name[:-6].replace("/", ".")
    return not binary.rsplit(".", 1)[-1].isdigit()


def insert_class_names(connection: sqlite3.Connection, archive: Path, identifier: str, progress_prefix: str) -> None:
    """分批写入类名；FTS 在全部构件写完后从 classes 一次性重建。"""
    try:
        with zipfile.ZipFile(archive) as source:
            entries = source.infolist()
            total = sum(1 for entry in entries if is_indexable_class_entry(entry))
            if not total:
                print(f"{progress_prefix}类名 0/0", flush=True)
                return
            batch: list[tuple[str, str, str]] = []
            processed = 0
            for entry in entries:
                if not is_indexable_class_entry(entry):
                    continue
                binary = entry.filename[:-6].replace("/", ".")
                batch.append((identifier, binary.replace("$", "."), binary))
                if len(batch) < CLASS_INSERT_BATCH_SIZE:
                    continue
                connection.executemany("INSERT INTO classes(artifact_id, name, binary_name) VALUES (?, ?, ?)", batch)
                processed += len(batch)
                print(f"{progress_prefix}类名 {processed}/{total}", flush=True)
                batch.clear()
            if batch:
                connection.executemany("INSERT INTO classes(artifact_id, name, binary_name) VALUES (?, ?, ?)", batch)
                processed += len(batch)
                print(f"{progress_prefix}类名 {processed}/{total}", flush=True)
    except zipfile.BadZipFile:
        print(f"{progress_prefix}类名归档无效，已跳过", flush=True)


BYTECODE_PUBLIC = 0x0001
BYTECODE_PRIVATE = 0x0002
BYTECODE_PROTECTED = 0x0004
BYTECODE_STATIC = 0x0008
BYTECODE_FINAL = 0x0010
BYTECODE_SYNCHRONIZED = 0x0020
BYTECODE_INTERFACE = 0x0200
BYTECODE_BRIDGE = 0x0040
BYTECODE_VARARGS = 0x0080
BYTECODE_NATIVE = 0x0100
BYTECODE_ABSTRACT = 0x0400
BYTECODE_SYNTHETIC = 0x1000
BYTECODE_ANNOTATION = 0x2000
BYTECODE_ENUM = 0x4000


def bytecode_u1(data: bytes, offset: int) -> tuple[int, int]:
    if offset >= len(data):
        raise ValueError("意外结束的 class 文件")
    return data[offset], offset + 1


def bytecode_u2(data: bytes, offset: int) -> tuple[int, int]:
    if offset + 2 > len(data):
        raise ValueError("意外结束的 class 文件")
    return struct.unpack_from(">H", data, offset)[0], offset + 2


def bytecode_u4(data: bytes, offset: int) -> tuple[int, int]:
    if offset + 4 > len(data):
        raise ValueError("意外结束的 class 文件")
    return struct.unpack_from(">I", data, offset)[0], offset + 4


def bytecode_skip_attributes(data: bytes, offset: int) -> int:
    count, offset = bytecode_u2(data, offset)
    for _ in range(count):
        _, offset = bytecode_u2(data, offset)
        length, offset = bytecode_u4(data, offset)
        offset += length
        if offset > len(data):
            raise ValueError("意外结束的 class 属性")
    return offset


def bytecode_constant_pool(data: bytes, offset: int) -> tuple[list[Any], int]:
    count, offset = bytecode_u2(data, offset)
    values: list[Any] = [None] * count
    index = 1
    while index < count:
        tag, offset = bytecode_u1(data, offset)
        if tag == 1:
            length, offset = bytecode_u2(data, offset)
            end = offset + length
            if end > len(data):
                raise ValueError("意外结束的 UTF-8 常量")
            values[index] = (tag, data[offset:end].decode("utf-8", errors="replace"))
            offset = end
        elif tag in {3, 4}:
            offset += 4
            values[index] = (tag, None)
        elif tag in {5, 6}:
            offset += 8
            values[index] = (tag, None)
            index += 1
        elif tag in {7, 8, 16, 19, 20}:
            value, offset = bytecode_u2(data, offset)
            values[index] = (tag, value)
        elif tag in {9, 10, 11, 12, 17, 18}:
            first, offset = bytecode_u2(data, offset)
            second, offset = bytecode_u2(data, offset)
            values[index] = (tag, first, second)
        elif tag == 15:
            kind, offset = bytecode_u1(data, offset)
            reference, offset = bytecode_u2(data, offset)
            values[index] = (tag, kind, reference)
        else:
            raise ValueError(f"不支持的常量池标签：{tag}")
        if offset > len(data):
            raise ValueError("意外结束的常量池")
        index += 1
    return values, offset


def bytecode_utf8(pool: list[Any], index: int) -> str:
    value = pool[index] if 0 < index < len(pool) else None
    return str(value[1]) if value and value[0] == 1 else ""


def bytecode_class_name(pool: list[Any], index: int) -> str:
    value = pool[index] if 0 < index < len(pool) else None
    return bytecode_utf8(pool, int(value[1])).replace("/", ".").replace("$", ".") if value and value[0] == 7 else ""


def bytecode_type(descriptor: str, offset: int = 0) -> tuple[str, int]:
    primitives = {"B": "byte", "C": "char", "D": "double", "F": "float", "I": "int", "J": "long", "S": "short", "Z": "boolean", "V": "void"}
    arrays = 0
    while offset < len(descriptor) and descriptor[offset] == "[":
        arrays += 1
        offset += 1
    if offset >= len(descriptor):
        raise ValueError("无效的类型描述符")
    marker = descriptor[offset]
    if marker == "L":
        end = descriptor.find(";", offset)
        if end < 0:
            raise ValueError("无效的对象描述符")
        value = descriptor[offset + 1:end].replace("/", ".").replace("$", ".")
        offset = end + 1
    elif marker in primitives:
        value = primitives[marker]
        offset += 1
    else:
        raise ValueError("未知的类型描述符")
    return value + "[]" * arrays, offset


def bytecode_method_types(descriptor: str) -> tuple[list[str], str]:
    if not descriptor.startswith("("):
        raise ValueError("无效的方法描述符")
    offset = 1
    arguments: list[str] = []
    while offset < len(descriptor) and descriptor[offset] != ")":
        value, offset = bytecode_type(descriptor, offset)
        arguments.append(value)
    if offset >= len(descriptor):
        raise ValueError("无效的方法描述符")
    result, offset = bytecode_type(descriptor, offset + 1)
    if offset != len(descriptor):
        raise ValueError("无效的方法描述符尾部")
    return arguments, result


def bytecode_modifiers(access: int, member: bool = False) -> str:
    values = []
    if access & BYTECODE_PUBLIC:
        values.append("public")
    elif access & BYTECODE_PROTECTED:
        values.append("protected")
    elif access & BYTECODE_PRIVATE:
        values.append("private")
    if access & BYTECODE_STATIC:
        values.append("static")
    if access & BYTECODE_FINAL:
        values.append("final")
    if member and access & BYTECODE_ABSTRACT:
        values.append("abstract")
    if member and access & BYTECODE_NATIVE:
        values.append("native")
    if member and access & BYTECODE_SYNCHRONIZED:
        values.append("synchronized")
    return " ".join(values)


def bytecode_member_records(data: bytes, entry_name: str) -> list[dict[str, Any]]:
    """从单个 class 文件提取可见类型、字段、方法与直接继承关系。"""
    if len(data) < 10 or data[:4] != b"\xca\xfe\xba\xbe":
        return []
    try:
        offset = 8
        pool, offset = bytecode_constant_pool(data, offset)
        access, offset = bytecode_u2(data, offset)
        this_class, offset = bytecode_u2(data, offset)
        super_class, offset = bytecode_u2(data, offset)
        owner = bytecode_class_name(pool, this_class)
        if not owner or not (access & BYTECODE_PUBLIC) or access & BYTECODE_SYNTHETIC:
            return []
        interfaces_count, offset = bytecode_u2(data, offset)
        interfaces = []
        for _ in range(interfaces_count):
            interface, offset = bytecode_u2(data, offset)
            resolved = bytecode_class_name(pool, interface)
            if resolved:
                interfaces.append(resolved)
        supertypes = [value for value in [bytecode_class_name(pool, super_class), *interfaces] if value]
        simple_name = owner.rsplit(".", 1)[-1]
        if access & BYTECODE_ANNOTATION:
            type_kind = "@interface"
        elif access & BYTECODE_INTERFACE:
            type_kind = "interface"
        elif access & BYTECODE_ENUM:
            type_kind = "enum"
        else:
            type_kind = "class"
        source = "bytecode:" + entry_name
        type_modifiers = bytecode_modifiers(access)
        records: list[dict[str, Any]] = [{"kind": "type", "owner": owner, "name": simple_name, "declaration": f"{type_modifiers} {type_kind} {simple_name}".strip(), "source": source, "line": 0, "supertypes": supertypes, "javadoc": None, "documentation": None}]
        fields_count, offset = bytecode_u2(data, offset)
        for _ in range(fields_count):
            field_access, offset = bytecode_u2(data, offset)
            name_index, offset = bytecode_u2(data, offset)
            descriptor_index, offset = bytecode_u2(data, offset)
            offset = bytecode_skip_attributes(data, offset)
            if not field_access & BYTECODE_PUBLIC or field_access & BYTECODE_SYNTHETIC:
                continue
            field_name = bytecode_utf8(pool, name_index)
            try:
                field_type, _ = bytecode_type(bytecode_utf8(pool, descriptor_index))
            except ValueError:
                continue
            records.append({"kind": "field", "owner": owner, "name": field_name, "declaration": f"{bytecode_modifiers(field_access, True)} {field_type} {field_name}".strip(), "source": source, "line": 0, "supertypes": [], "javadoc": None, "documentation": None})
        methods_count, offset = bytecode_u2(data, offset)
        for _ in range(methods_count):
            method_access, offset = bytecode_u2(data, offset)
            name_index, offset = bytecode_u2(data, offset)
            descriptor_index, offset = bytecode_u2(data, offset)
            offset = bytecode_skip_attributes(data, offset)
            if not method_access & BYTECODE_PUBLIC or method_access & (BYTECODE_SYNTHETIC | BYTECODE_BRIDGE):
                continue
            method_name = bytecode_utf8(pool, name_index)
            if method_name == "<clinit>":
                continue
            try:
                arguments, result = bytecode_method_types(bytecode_utf8(pool, descriptor_index))
            except ValueError:
                continue
            parameters = ", ".join(arguments)
            if method_name == "<init>":
                kind, name, declaration = "constructor", simple_name, f"{bytecode_modifiers(method_access, True)} {simple_name}({parameters})".strip()
            else:
                kind, name, declaration = "method", method_name, f"{bytecode_modifiers(method_access, True)} {result} {method_name}({parameters})".strip()
            records.append({"kind": kind, "owner": owner, "name": name, "declaration": declaration, "source": source, "line": 0, "supertypes": [], "javadoc": None, "documentation": None})
        return records
    except (IndexError, ValueError, struct.error):
        return []


def iter_bytecode_api(archive: Path, progress_prefix: str, report: bool = True) -> Iterator[dict[str, Any]]:
    """从缺失源码的二进制 JAR 流式提取可见 API；不加载或执行任何类。"""
    try:
        with zipfile.ZipFile(archive) as source:
            entries = [entry for entry in source.infolist() if is_indexable_class_entry(entry)]
            total = len(entries)
            if not total:
                if report:
                    print(f"{progress_prefix}字节码结构 0/0", flush=True)
                return
            for processed, entry in enumerate(entries, start=1):
                if report and (processed == 1 or processed % 200 == 0 or processed == total):
                    print(f"{progress_prefix}字节码结构 {processed}/{total}", flush=True)
                yield from bytecode_member_records(source.read(entry), entry.filename)
    except zipfile.BadZipFile:
        if report:
            print(f"{progress_prefix}字节码归档无效，已跳过", flush=True)


def strip_java_comments(line: str, in_block: bool) -> tuple[str, bool]:
    result = ""
    index = 0
    while index < len(line):
        if in_block:
            close = line.find("*/", index)
            if close < 0:
                return result, True
            index = close + 2
            in_block = False
        elif line.startswith("/*", index):
            in_block = True
            index += 2
        elif line.startswith("//", index):
            break
        else:
            result += line[index]
            index += 1
    return result, in_block


def declared_supertypes(declaration: str, package: str, imports: dict[str, str]) -> list[str]:
    clauses = re.search(r"\b(?:extends|implements)\b\s+(.+?)(?:\{|$)", declaration)
    if not clauses:
        return []
    result = []
    for raw in re.split(r"\s*,\s*|\bimplements\b", clauses.group(1)):
        value = re.sub(r"<.*?>", "", raw).strip().split()[0] if raw.strip() else ""
        if not value:
            continue
        result.append(value if "." in value else imports.get(value, f"{package}.{value}" if package else value))
    return result


def java_public_declarations(lines: list[str], package: str, imports: dict[str, str], source_path: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    types: list[tuple[str, int, bool]] = []
    depth = 0
    in_block_comment = False
    pending = ""
    type_pattern = re.compile(r"\bpublic\s+(?:abstract\s+|final\s+|static\s+)*(class|interface|enum|record|@interface)\s+(\w+)")
    for line_number, raw in enumerate(lines, start=1):
        line, in_block_comment = strip_java_comments(raw, in_block_comment)
        if not line.strip():
            continue
        opened, closed = line.count("{"), line.count("}")
        found_type = type_pattern.search(line)
        if found_type:
            kind, name = found_type.groups()
            owner = f"{package}.{name}" if package else name
            types.append((name, depth + opened - closed, kind in {"interface", "@interface"}))
            records.append({"kind": "type", "owner": owner, "name": name, "declaration": line.strip(), "source": source_path, "line": line_number, "supertypes": declared_supertypes(line, package, imports), "javadoc": None, "documentation": None})
        if types:
            pending = (pending + " " + line.strip()).strip()
            if len(pending) > 1000:
                pending = ""
            if (";" in line or "{" in line) and ("public" in pending or types[-1][2]):
                declaration = re.sub(r"\s+", " ", pending).strip()
                owner_name, interface = types[-1][0], types[-1][2]
                owner = f"{package}.{owner_name}" if package else owner_name
                method = re.search(r"\b(?:public\s+)?(?:static\s+|final\s+|abstract\s+|synchronized\s+|default\s+|native\s+|strictfp\s+|<[^>]+>\s+)*[\w.$<>?, \[\]]+\s+(\w+)\s*\(([^)]*)\)", declaration)
                constructor = re.search(rf"\bpublic\s+{re.escape(owner_name)}\s*\(([^)]*)\)", declaration)
                field = re.search(r"\b(?:public\s+)?(?:static\s+|final\s+|volatile\s+|transient\s+)*[\w.$<>?, \[\]]+\s+(\w+)\s*(?:=|;|,)", declaration)
                if method:
                    member = method.group(1)
                    records.append({"kind": "method", "owner": owner, "name": member, "declaration": declaration, "source": source_path, "line": line_number, "supertypes": [], "javadoc": None, "documentation": None})
                elif constructor:
                    records.append({"kind": "constructor", "owner": owner, "name": owner_name, "declaration": declaration, "source": source_path, "line": line_number, "supertypes": [], "javadoc": None, "documentation": None})
                elif field:
                    member = field.group(1)
                    records.append({"kind": "field", "owner": owner, "name": member, "declaration": declaration, "source": source_path, "line": line_number, "supertypes": [], "javadoc": None, "documentation": None})
                pending = ""
            elif not line.rstrip().endswith((",", "throws")):
                pending = ""
        depth += opened - closed
        while types and depth < types[-1][1]:
            types.pop()
    return records


PRIMITIVE_TYPES = {"boolean", "byte", "char", "short", "int", "long", "float", "double", "void"}


def split_signature_parameters(value: str) -> list[str]:
    """按泛型嵌套深度分割参数，避免把 Map<K, V> 误切成两个参数。"""
    result: list[str] = []
    start = depth = 0
    for index, character in enumerate(value):
        if character == "<":
            depth += 1
        elif character == ">":
            depth = max(0, depth - 1)
        elif character == "," and not depth:
            result.append(value[start:index].strip())
            start = index + 1
    final = value[start:].strip()
    if final:
        result.append(final)
    return result


def signature_type(value: str, has_parameter_name: bool = False) -> str:
    """把 Java 文本类型缩减为可跨重定位安全比较的结构形状。"""
    value = re.sub(r"@\w+(?:\([^)]*\))?\s*", "", value).strip()
    value = re.sub(r"\b(?:final|volatile|transient)\b\s*", "", value).strip()
    if has_parameter_name:
        parts = re.split(r"\s+", value)
        if len(parts) > 1:
            value = " ".join(parts[:-1])
    value = value.replace("...", "[]")
    dimensions = value.count("[]")
    value = value.replace("[]", "")
    while "<" in value and ">" in value:
        simplified = re.sub(r"<[^<>]*>", "", value)
        if simplified == value:
            break
        value = simplified
    value = re.sub(r"\?\s*(?:extends|super)\s+", "", value).strip()
    value = value.rsplit(".", 1)[-1].strip()
    if value in PRIMITIVE_TYPES:
        return f"primitive:{value}:{dimensions}"
    if re.fullmatch(r"[A-Z]", value):
        return f"reference:*:{dimensions}"
    return f"reference:{value}:{dimensions}"


def declaration_signature(record: dict[str, Any]) -> tuple[str, str, tuple[str, ...], str | None]:
    """返回 kind、名称、参数类型形状及字段/方法返回类型形状。"""
    kind, name, declaration = str(record["kind"]), str(record["name"]), str(record["declaration"])
    if kind in {"method", "constructor"}:
        match = re.search(r"\((.*)\)", declaration)
        parameters = tuple(signature_type(value, has_parameter_name=" " in value.strip()) for value in split_signature_parameters(match.group(1) if match else ""))
        if kind == "constructor":
            return kind, name, parameters, None
        prefix = declaration[:match.start()] if match else declaration
        prefix = re.sub(r"\b(?:public|protected|private|static|final|abstract|synchronized|default|native|strictfp)\b\s*", "", prefix)
        return_type = prefix.rsplit(name, 1)[0].strip().split()[-1] if name in prefix and prefix.rsplit(name, 1)[0].strip() else ""
        return kind, name, parameters, signature_type(return_type)
    if kind == "field":
        prefix = declaration.rsplit(name, 1)[0]
        prefix = re.sub(r"\b(?:public|protected|private|static|final|volatile|transient)\b\s*", "", prefix).strip()
        return kind, name, (), signature_type(prefix.split()[-1] if prefix else "")
    return kind, name, (), None


def types_compatible(left: str | None, right: str | None) -> bool:
    if left is None or right is None or left == right:
        return left == right
    left_kind, left_name, left_dimensions = left.split(":", 2)
    right_kind, right_name, right_dimensions = right.split(":", 2)
    if left_kind != right_kind or left_dimensions != right_dimensions:
        return False
    return left_kind == "reference" and (left_name == "*" or right_name == "*" or left_name == right_name)


def members_compatible(runtime: dict[str, Any], candidate: dict[str, Any], check_result: bool = True) -> bool:
    runtime_kind, runtime_name, runtime_parameters, runtime_result = declaration_signature(runtime)
    candidate_kind, candidate_name, candidate_parameters, candidate_result = declaration_signature(candidate)
    if (runtime_kind, runtime_name) != (candidate_kind, candidate_name) or len(runtime_parameters) != len(candidate_parameters):
        return False
    if not all(types_compatible(left, right) for left, right in zip(runtime_parameters, candidate_parameters)):
        return False
    return not check_result or types_compatible(runtime_result, candidate_result)


def member_lookup_key(record: dict[str, Any]) -> tuple[str, str, int]:
    kind, name, parameters, _ = declaration_signature(record)
    return kind, name, len(parameters)


class JavadocPageParser(HTMLParser):
    """顺序读取一个 Javadoc 类型页；每个页面只分析一次。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.last_identifier: str | None = None
        self.type_summary: str | None = None
        self.member_summaries: dict[str, list[str]] = defaultdict(list)
        self.member_summaries_by_name: dict[str, list[tuple[str, str]]] = defaultdict(list)
        self._capture_identifier: str | None = None
        self._capture_depth = 0
        self._capture_text: list[str] = []

    @staticmethod
    def _attribute(attributes: list[tuple[str, str | None]], name: str) -> str:
        for key, value in attributes:
            if key.casefold() == name:
                return value or ""
        return ""

    def handle_starttag(self, tag: str, attributes: list[tuple[str, str | None]]) -> None:
        identifier = self._attribute(attributes, "id")
        if identifier:
            self.last_identifier = identifier
        classes = self._attribute(attributes, "class").split()
        if tag.casefold() == "div" and "block" in classes and not self._capture_depth:
            self._capture_identifier = self.last_identifier
            self._capture_depth = 1
            self._capture_text = []
        elif self._capture_depth and tag.casefold() == "div":
            self._capture_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if not self._capture_depth or tag.casefold() != "div":
            return
        self._capture_depth -= 1
        if self._capture_depth:
            return
        summary = compact_text(" ".join(" ".join(self._capture_text).split()), 420)
        if summary:
            if self._capture_identifier:
                self.member_summaries[self._capture_identifier].append(summary)
                self.member_summaries_by_name[javadoc_anchor_name(self._capture_identifier)].append((self._capture_identifier, summary))
            elif self.type_summary is None:
                self.type_summary = summary
        self._capture_identifier = None
        self._capture_text = []

    def handle_data(self, data: str) -> None:
        if self._capture_depth:
            self._capture_text.append(data)


def javadoc_anchor_name(identifier: str) -> str:
    end = len(identifier)
    for marker in ("(", ":"):
        position = identifier.find(marker)
        if position >= 0:
            end = min(end, position)
    return identifier[:end]


def javadoc_anchor_parameters(identifier: str) -> str | None:
    start = identifier.find("(")
    end = identifier.rfind(")")
    return identifier[start + 1:end] if start >= 0 and end > start else None


def parse_javadoc_page(document: str) -> JavadocPageParser:
    parser = JavadocPageParser()
    parser.feed(document)
    parser.close()
    return parser


def javadoc_member_summaries(document: str, names: set[str]) -> dict[str, str]:
    """兼容验证工具：从单次页面分析结果中返回指定成员的首个摘要。"""
    page = parse_javadoc_page(document)
    result: dict[str, str] = {}
    for identifier, summaries in page.member_summaries.items():
        name = javadoc_anchor_name(identifier)
        if name in names and name not in result and summaries:
            result[name] = summaries[0]
    return result


def source_tokens(document: str) -> list[tuple[str, int]]:
    """逐字符读取 Java 源码，跳过注释、字符串与字符常量。"""
    result: list[tuple[str, int]] = []
    index = line = 0
    length = len(document)
    while index < length:
        character = document[index]
        if character.isspace():
            line += character == "\n"
            index += 1
            continue
        if document.startswith("//", index):
            end = document.find("\n", index + 2)
            if end < 0:
                break
            line += 1
            index = end + 1
            continue
        if document.startswith("/*", index):
            end = document.find("*/", index + 2)
            end = length if end < 0 else end + 2
            line += document.count("\n", index, end)
            index = end
            continue
        if character in {'"', "'"}:
            quote = character
            index += 1
            while index < length:
                if document[index] == "\\":
                    index += 2
                    continue
                if document[index] == quote:
                    index += 1
                    break
                line += document[index] == "\n"
                index += 1
            continue
        if character.isidentifier() or character in "$_":
            end = index + 1
            while end < length and (document[end].isalnum() or document[end] in "$_"):
                end += 1
            result.append((document[index:end], line + 1))
            index = end
            continue
        if document.startswith("...", index):
            result.append(("...", line + 1))
            index += 3
            continue
        result.append((character, line + 1))
        index += 1
    return result


def source_package_and_type(tokens: list[tuple[str, int]]) -> tuple[str, str, int] | None:
    package = ""
    for index, (value, _) in enumerate(tokens):
        if value == "package":
            parts: list[str] = []
            cursor = index + 1
            while cursor < len(tokens) and tokens[cursor][0] != ";":
                parts.append(tokens[cursor][0])
                cursor += 1
            package = "".join(parts)
            continue
        if value in {"class", "interface", "enum", "record"} and index + 1 < len(tokens):
            name, line = tokens[index + 1]
            return package, name, line
    return None


def source_member_candidates(tokens: list[tuple[str, int]], owner: str, source_path: str) -> list[dict[str, Any]]:
    """只读取类型最外层的声明候选；方法体中的调用绝不作为成员位置。"""
    result: list[dict[str, Any]] = []
    ignored = {"if", "for", "while", "switch", "catch", "new", "return", "throw", "this", "super"}
    modifiers = {"public", "protected", "private", "static", "final", "volatile", "transient"}
    type_start = next((index for index, (value, _) in enumerate(tokens) if value in {"class", "interface", "enum", "record"}), None)
    if type_start is None:
        return result
    opening = next((index for index in range(type_start + 1, len(tokens)) if tokens[index][0] == "{"), None)
    if opening is None:
        return result
    body_depth = 1
    index = opening + 1
    while index < len(tokens) and body_depth:
        name, line = tokens[index]
        if name == "{":
            body_depth += 1
            index += 1
            continue
        if name == "}":
            body_depth -= 1
            index += 1
            continue
        if body_depth != 1:
            index += 1
            continue
        if name not in ignored and index + 1 < len(tokens) and tokens[index + 1][0] in {";", "=", ","}:
            start = index - 1
            while start >= opening and tokens[start][0] not in {";", "{", "}"}:
                start -= 1
            declaration_tokens = [value for value, _ in tokens[start + 1:index] if value not in modifiers]
            field_type = declaration_tokens[-1] if declaration_tokens else ""
            if field_type:
                result.append({"kind": "field", "owner": owner, "name": name, "declaration": f"public {field_type} {name}", "source": source_path, "line": line, "supertypes": [], "javadoc": None, "documentation": None})
            index += 1
            continue
        if name in ignored or index + 1 >= len(tokens) or tokens[index + 1][0] != "(":
            index += 1
            continue
        depth = cursor = 0
        parameters: list[str] = []
        current: list[str] = []
        while index + 1 + cursor < len(tokens):
            value = tokens[index + 1 + cursor][0]
            if value == "(":
                depth += 1
            elif value == ")":
                depth -= 1
                if not depth:
                    if current:
                        parameters.append(" ".join(current))
                    break
            elif value == "," and depth == 1:
                parameters.append(" ".join(current))
                current = []
            elif depth:
                current.append(value)
            cursor += 1
        if depth:
            index += 1
            continue
        next_value = tokens[index + 2 + cursor][0] if index + 2 + cursor < len(tokens) else ""
        if next_value not in {"{", ";", "throws"}:
            index += 1
            continue
        kind = "constructor" if name == owner.rsplit(".", 1)[-1] else "method"
        result.append({"kind": kind, "owner": owner, "name": name, "declaration": f"public void {name}({', '.join(parameters)})", "source": source_path, "line": line, "supertypes": [], "javadoc": None, "documentation": None})
        index += 1
    return result


class SourceApiLookup:
    """在字节码提取完成后，按需读取资料并保守补充既有记录。"""

    def __init__(self, source_archive: Path | None, javadoc_archive: Path | None):
        self.sources = zipfile.ZipFile(source_archive) if source_archive else None
        self.javadocs = zipfile.ZipFile(javadoc_archive) if javadoc_archive else None
        self.by_simple_name: dict[str, list[zipfile.ZipInfo]] | None = None
        self.source_cache: dict[str, tuple[str, str, int, dict[tuple[str, str, int], list[dict[str, Any]]]]] = {}
        self.javadoc_cache: dict[str, JavadocPageParser | None] = {}

    def close(self) -> None:
        if self.javadocs:
            self.javadocs.close()
        if self.sources:
            self.sources.close()

    def source_entry(self, runtime_owner: str) -> zipfile.ZipInfo | None:
        """优先通过 ZIP 目录精确查找；仅重定位回退时枚举一次源码文件名。"""
        if not self.sources:
            return None
        try:
            return self.sources.getinfo(runtime_owner.replace(".", "/") + ".java")
        except KeyError:
            pass
        if self.by_simple_name is None:
            indexed: dict[str, list[zipfile.ZipInfo]] = defaultdict(list)
            for entry in self.sources.infolist():
                if not entry.is_dir() and entry.filename.endswith(".java"):
                    indexed[Path(entry.filename).stem].append(entry)
            self.by_simple_name = indexed
        candidates = self.by_simple_name.get(runtime_owner.rsplit(".", 1)[-1], [])
        return candidates[0] if len(candidates) == 1 else None

    def source_data(self, entry: zipfile.ZipInfo) -> tuple[str, str, int, dict[tuple[str, str, int], list[dict[str, Any]]]] | None:
        cached = self.source_cache.get(entry.filename)
        if cached is not None:
            return cached
        if not self.sources:
            return None
        tokens = source_tokens(self.sources.read(entry).decode("utf-8", errors="replace"))
        parsed = source_package_and_type(tokens)
        if not parsed:
            return None
        package, name, type_line = parsed
        owner = f"{package}.{name}" if package else name
        members_by_key: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
        for member in source_member_candidates(tokens, owner, entry.filename):
            members_by_key[member_lookup_key(member)].append(member)
        data = (owner, entry.filename, type_line, members_by_key)
        self.source_cache[entry.filename] = data
        return data

    def page(self, path: str) -> JavadocPageParser | None:
        if path in self.javadoc_cache:
            return self.javadoc_cache[path]
        if not self.javadocs:
            return None
        try:
            parsed = parse_javadoc_page(self.javadocs.read(path).decode("utf-8", errors="replace"))
        except KeyError:
            parsed = None
        self.javadoc_cache[path] = parsed
        return parsed

    @staticmethod
    def progress(progress_prefix: str, label: str, processed: int, total: int, report: bool) -> None:
        if not report:
            return
        if not total:
            print(f"{progress_prefix}{label} 0/0", flush=True)
        elif processed == 1 or processed % 100 == 0 or processed == total:
            print(f"{progress_prefix}{label} {processed}/{total}", flush=True)

    def enrich(self, records: list[dict[str, Any]], progress_prefix: str, report: bool = True) -> None:
        if not records or not (self.sources or self.javadocs):
            return
        by_owner: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            by_owner[str(record["owner"])].append(record)
        plans = [(owner, owner_records, self.source_entry(owner)) for owner, owner_records in by_owner.items()]

        source_entries = {entry.filename: entry for _, _, entry in plans if entry}
        source_data_by_path: dict[str, tuple[str, str, int, dict[tuple[str, str, int], list[dict[str, Any]]]] | None] = {}
        if self.sources:
            for processed, entry in enumerate(source_entries.values(), start=1):
                self.progress(progress_prefix, "读取源码", processed, len(source_entries), report)
                source_data_by_path[entry.filename] = self.source_data(entry)
            if not source_entries:
                self.progress(progress_prefix, "读取源码", 0, 0, report)

        page_paths: dict[str, None] = {}
        plan_pages: dict[str, str] = {}
        if self.javadocs:
            for runtime_owner, _, entry in plans:
                source_data = source_data_by_path.get(entry.filename) if entry else None
                source_owner = source_data[0] if source_data else runtime_owner
                path = source_owner.replace(".", "/") + ".html"
                plan_pages[runtime_owner] = path
                page_paths[path] = None
            for processed, path in enumerate(page_paths, start=1):
                self.progress(progress_prefix, "读取说明页面", processed, len(page_paths), report)
                self.page(path)
            if not page_paths:
                self.progress(progress_prefix, "读取说明页面", 0, 0, report)

        for processed, (runtime_owner, owner_records, entry) in enumerate(plans, start=1):
            self.progress(progress_prefix, "连接资料", processed, len(plans), report)
            source_data = source_data_by_path.get(entry.filename) if entry else None
            page_path = plan_pages.get(runtime_owner)
            page = self.javadoc_cache.get(page_path) if page_path else None
            for runtime in owner_records:
                if source_data:
                    _, source_path, type_line, members_by_key = source_data
                    runtime["source"] = source_path
                    runtime["line"] = type_line if runtime["kind"] == "type" else 0
                    if runtime["kind"] != "type":
                        matches = [candidate for candidate in members_by_key.get(member_lookup_key(runtime), []) if members_compatible(runtime, candidate, check_result=False)]
                        if len(matches) == 1:
                            runtime["line"] = matches[0]["line"]
                if not page or not page_path:
                    continue
                runtime["javadoc"] = page_path
                if runtime["kind"] == "type":
                    runtime["documentation"] = page.type_summary
                    continue
                summaries: list[str] = []
                for identifier, summary in page.member_summaries_by_name.get(str(runtime["name"]), []):
                    parameters = javadoc_anchor_parameters(identifier)
                    if parameters is None:
                        if runtime["kind"] == "field":
                            summaries.append(summary)
                        continue
                    candidate = {"kind": runtime["kind"], "name": runtime["name"], "declaration": f"public void {runtime['name']}({parameters})"}
                    if members_compatible(runtime, candidate, check_result=False):
                        summaries.append(summary)
                runtime["documentation"] = summaries[0] if len(summaries) == 1 else None


def iter_runtime_api(archive: Path, progress_prefix: str, report: bool = True) -> Iterator[dict[str, Any]]:
    """从运行 JAR 单次提取公开字节码记录；不在该阶段读取资料归档。"""
    yield from iter_bytecode_api(archive, progress_prefix, report)


def open_database(path: Path, writable: bool = False) -> sqlite3.Connection:
    if not writable and not path.is_file():
        raise IndexError(f"尚无 SQLite 依赖索引；先运行 `dependency_index.py sync --project .`。")
    if writable:
        path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript("""
        PRAGMA journal_mode=DELETE;
        PRAGMA synchronous=NORMAL;
        PRAGMA temp_store=MEMORY;
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE modules (path TEXT PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE configurations (id INTEGER PRIMARY KEY, module_path TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL, UNIQUE(module_path, name));
        CREATE TABLE artifacts (id TEXT PRIMARY KEY, group_name TEXT, artifact_name TEXT, version TEXT, classifier TEXT, extension TEXT, file_name TEXT, file_path TEXT, sha256 TEXT, sources_sha256 TEXT, sources_origin TEXT, sources_source TEXT, javadoc_sha256 TEXT, javadoc_origin TEXT, javadoc_source TEXT, api_status TEXT NOT NULL);
        CREATE TABLE configuration_artifacts (configuration_id INTEGER NOT NULL, artifact_id TEXT NOT NULL, PRIMARY KEY(configuration_id, artifact_id));
        CREATE TABLE dependencies (configuration_id INTEGER NOT NULL, kind TEXT NOT NULL, requested TEXT, selected TEXT, failure TEXT);
        CREATE TABLE classes (id INTEGER PRIMARY KEY, artifact_id TEXT NOT NULL, name TEXT NOT NULL, binary_name TEXT NOT NULL);
        CREATE TABLE api (id INTEGER PRIMARY KEY, artifact_id TEXT NOT NULL, kind TEXT NOT NULL, owner TEXT NOT NULL, name TEXT NOT NULL, declaration TEXT NOT NULL, source_path TEXT NOT NULL, source_line INTEGER NOT NULL, javadoc_path TEXT, documentation TEXT);
        CREATE TABLE type_edges (child_owner TEXT NOT NULL, parent_owner TEXT NOT NULL, PRIMARY KEY(child_owner, parent_owner));
        CREATE TABLE archive_hashes (path TEXT PRIMARY KEY, size INTEGER NOT NULL, modified_ns INTEGER NOT NULL, sha256 TEXT NOT NULL);
        CREATE VIRTUAL TABLE class_search USING fts5(name, binary_name, content='classes', content_rowid='id', tokenize='unicode61', prefix='2 3 4');
        CREATE VIRTUAL TABLE api_search USING fts5(owner, name, declaration, documentation, content='api', content_rowid='id', tokenize='unicode61', prefix='2 3 4');
    """)


def metadata(connection: sqlite3.Connection) -> dict[str, str]:
    return {row["key"]: row["value"] for row in connection.execute("SELECT key, value FROM metadata")}


def fts_query(query: str) -> str:
    terms = re.findall(r"[\w.$]+", query, flags=re.UNICODE)
    if not terms:
        raise IndexError("查询文本不包含可搜索字符。")
    return " AND ".join(f'"{term.replace("\"", "")}"*' for term in terms)


def artifact_id(raw: dict[str, Any], hashes: ArchiveHashCache | None = None) -> str:
    path = native_path(str(raw.get("file", "")))
    return (hashes.digest(path) if hashes else sha256(path)) if path.is_file() else "missing:" + re.sub(r"[^A-Za-z0-9_.-]+", "_", str(path))


def insert_public_api(connection: sqlite3.Connection, records: Iterable[dict[str, Any]], identifier: str) -> None:
    """分批写入公开 API 与继承边；FTS 在全部构件完成后统一重建。"""
    api_batch: list[tuple[Any, ...]] = []
    edge_batch: list[tuple[str, str]] = []

    def flush() -> None:
        if api_batch:
            connection.executemany(
                "INSERT INTO api(artifact_id, kind, owner, name, declaration, source_path, source_line, javadoc_path, documentation) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                api_batch,
            )
            api_batch.clear()
        if edge_batch:
            connection.executemany("INSERT OR IGNORE INTO type_edges(child_owner, parent_owner) VALUES (?, ?)", edge_batch)
            edge_batch.clear()

    for record in records:
        api_batch.append((identifier, record["kind"], record["owner"], record["name"], record["declaration"], record["source"], record["line"], record["javadoc"], record["documentation"]))
        if record["kind"] == "type":
            edge_batch.extend((record["owner"], parent) for parent in record["supertypes"])
        if len(api_batch) >= API_INSERT_BATCH_SIZE:
            flush()
    flush()


def create_query_indexes(connection: sqlite3.Connection) -> None:
    """基础数据全部写完后一次创建查询索引，避免插入期间重复维护 B 树。"""
    connection.executescript("""
        CREATE INDEX classes_artifact_idx ON classes(artifact_id);
        CREATE INDEX api_owner_idx ON api(owner);
        CREATE INDEX api_artifact_idx ON api(artifact_id);
        CREATE INDEX edges_parent_idx ON type_edges(parent_owner);
        CREATE INDEX configurations_module_idx ON configurations(module_path);
    """)


def artifact_workers(value: int | None) -> int:
    default = min(MAX_ARTIFACT_WORKERS, max(1, (os.cpu_count() or 2) // 2))
    return min(MAX_ARTIFACT_WORKERS, max(1, value if value is not None else default))


def prepare_artifact_task(raw: dict[str, Any], identifier: str, artifact_sha256: str | None, hashes: ArchiveHashCache, include_api: bool, position: int, total: int) -> dict[str, Any]:
    path = native_path(str(raw.get("file", "")))
    coordinate = valid_coordinate(raw)
    source_reference = reference_archive(raw, "sources", hashes) if include_api else None
    javadoc_reference = reference_archive(raw, "javadoc", hashes) if include_api else None
    sources_info = source_reference[1] if source_reference else None
    javadoc_info = javadoc_reference[1] if javadoc_reference else None
    api_status = "not-requested" if not include_api else ("bytecode-with-sources-and-javadoc" if source_reference and javadoc_reference else "bytecode-with-sources" if source_reference else "bytecode-with-javadoc" if javadoc_reference else "bytecode")
    return {"raw": raw, "identifier": identifier, "sha256": artifact_sha256, "path": path, "coordinate": coordinate, "include_api": include_api, "source_archive": source_reference[0] if source_reference else None, "javadoc_archive": javadoc_reference[0] if javadoc_reference else None, "sources_info": sources_info, "javadoc_info": javadoc_info, "api_status": api_status, "position": position, "total": total}


def process_artifact_task(task: dict[str, Any]) -> dict[str, Any]:
    """工作线程只读取归档并构造纯数据；绝不访问 SQLite。"""
    path = task["path"]
    if not path.is_file():
        return {**task, "class_rows": [], "records": [], "missing": True}
    try:
        with zipfile.ZipFile(path) as archive:
            entries = [entry for entry in archive.infolist() if is_indexable_class_entry(entry)]
            identifier = task["identifier"]
            class_rows = [(identifier, entry.filename[:-6].replace("/", ".").replace("$", "."), entry.filename[:-6].replace("/", ".")) for entry in entries]
            records = [record for entry in entries for record in bytecode_member_records(archive.read(entry), entry.filename)] if task["include_api"] else []
        source_archive = task["source_archive"]
        if source_archive and records:
            lookup = SourceApiLookup(source_archive, task["javadoc_archive"])
            try:
                lookup.enrich(records, "", report=False)
            finally:
                lookup.close()
        return {**task, "class_rows": class_rows, "records": records, "missing": False}
    except zipfile.BadZipFile:
        return {**task, "class_rows": [], "records": [], "missing": False, "invalid": True}


def insert_class_rows(connection: sqlite3.Connection, rows: list[tuple[str, str, str]]) -> None:
    for start in range(0, len(rows), CLASS_INSERT_BATCH_SIZE):
        connection.executemany("INSERT INTO classes(artifact_id, name, binary_name) VALUES (?, ?, ?)", rows[start:start + CLASS_INSERT_BATCH_SIZE])


def write_artifact_result(connection: sqlite3.Connection, result: dict[str, Any]) -> None:
    """仅由主线程写入 SQLite，保持一个连接和一个事务。"""
    raw, identifier, path = result["raw"], result["identifier"], result["path"]
    coordinate = result["coordinate"]
    sources_info, javadoc_info = result["sources_info"], result["javadoc_info"]
    connection.execute("""
        INSERT INTO artifacts(id, group_name, artifact_name, version, classifier, extension, file_name, file_path, sha256, sources_sha256, sources_origin, sources_source, javadoc_sha256, javadoc_origin, javadoc_source, api_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (identifier, *(coordinate or (None, None, None)), str(raw.get("classifier", "")), str(raw.get("extension", "")), path.name, str(path), result["sha256"], *(sources_info[key] if sources_info else None for key in ("sha256", "origin", "source")), *(javadoc_info[key] if javadoc_info else None for key in ("sha256", "origin", "source")), "missing" if result.get("missing") else result["api_status"]))
    if result.get("invalid"):
        return
    insert_class_rows(connection, result["class_rows"])
    records = result["records"]
    if records:
        insert_public_api(connection, records, identifier)


def process_artifact_tasks(tasks: list[dict[str, Any]], workers: int) -> Iterator[dict[str, Any]]:
    """工作线程生产构件数据，调用线程消费结果并负责所有 SQLite 写入。"""
    task_queue: queue.Queue[dict[str, Any] | None] = queue.Queue()
    result_queue: queue.Queue[tuple[dict[str, Any] | None, BaseException | None]] = queue.Queue(maxsize=max(1, workers * 2))
    cancelled = threading.Event()

    def worker() -> None:
        while not cancelled.is_set():
            task = task_queue.get()
            try:
                if task is None:
                    return
                result: dict[str, Any] | None = process_artifact_task(task)
                failure: BaseException | None = None
            except BaseException as error:
                result, failure = None, error
            finally:
                task_queue.task_done()
            while not cancelled.is_set():
                try:
                    result_queue.put((result, failure), timeout=0.1)
                    break
                except queue.Full:
                    continue

    threads = [threading.Thread(target=worker, name=f"pluginbase-agent-artifact-{index + 1}", daemon=True) for index in range(workers)]
    for thread in threads:
        thread.start()
    for task in tasks:
        task_queue.put(task)
    for _ in threads:
        task_queue.put(None)
    try:
        for _ in tasks:
            result, failure = result_queue.get()
            if failure:
                raise failure
            if result is not None:
                yield result
    finally:
        cancelled.set()
        for thread in threads:
            thread.join(timeout=1)


def remove_legacy_index_state(state_root: Path) -> None:
    """仅清理由本工具旧版写入的 JSON、归档副本和解包目录。"""
    legacy_json = state_root / "indexes" / "dependency-index.json"
    legacy_artifacts = state_root / "indexes" / "artifacts"
    if legacy_json.is_file():
        print(f"清理旧 JSON 索引：{legacy_json}", flush=True)
        legacy_json.unlink()
    if legacy_artifacts.is_dir():
        print(f"清理旧索引归档与解包目录：{legacy_artifacts}", flush=True)
        shutil.rmtree(legacy_artifacts)


def build_database(arguments: argparse.Namespace, database: Path) -> None:
    project = normalize_project(arguments.project)
    state_root = arguments.state.resolve()
    print("[1/4] 正在由项目 Gradle Wrapper 解析模块和依赖…", flush=True)
    raw = selected_configurations(run_gradle(project, state_root, arguments.gradle_user_home, not arguments.no_api), arguments.configuration)
    archive_hashes = load_archive_hashes(database)
    unique: dict[str, dict[str, Any]] = {}
    for project_data in raw["projects"]:
        for config in project_data.get("configurations", []):
            for artifact in config.get("artifacts", []):
                unique.setdefault(artifact_id(artifact, archive_hashes), artifact)
    print(f"[2/4] 已发现 {len(raw['projects'])} 个模块、{len(unique)} 个唯一构件；开始流式建立 SQLite 索引…", flush=True)
    remove_legacy_index_state(state_root)
    temporary = database.with_suffix(database.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    if database.is_file():
        print(f"清理旧 SQLite 索引：{database}", flush=True)
        database.unlink()
    connection = open_database(temporary, writable=True)
    try:
        create_schema(connection)
        connection.execute("BEGIN")
        configuration_artifacts: list[tuple[int, str]] = []
        for project_data in raw["projects"]:
            connection.execute("INSERT INTO modules(path, name) VALUES (?, ?)", (str(project_data.get("path", "")), str(project_data.get("name", ""))))
            for config in project_data.get("configurations", []):
                cursor = connection.execute("INSERT INTO configurations(module_path, name, status) VALUES (?, ?, ?)", (str(project_data.get("path", "")), str(config.get("name", "")), str(config.get("status", "unknown"))))
                config_id = cursor.lastrowid
                for dependency in config.get("dependencies", []):
                    connection.execute("INSERT INTO dependencies(configuration_id, kind, requested, selected, failure) VALUES (?, ?, ?, ?, NULL)", (config_id, str(dependency.get("kind", "")), str(dependency.get("requested", "")), str(dependency.get("selected", ""))))
                for failure in config.get("failures", []):
                    connection.execute("INSERT INTO dependencies(configuration_id, kind, requested, selected, failure) VALUES (?, 'failed', '', '', ?)", (config_id, compact_text(str(failure), 500)))
                configuration_artifacts.extend((config_id, artifact_id(artifact, archive_hashes)) for artifact in config.get("artifacts", []))
        tasks: list[dict[str, Any]] = []
        for position, (identifier, raw_artifact) in enumerate(unique.items(), start=1):
            artifact_path = native_path(str(raw_artifact.get("file", "")))
            artifact_sha256 = archive_hashes.digest(artifact_path) if artifact_path.is_file() else None
            tasks.append(prepare_artifact_task(raw_artifact, identifier, artifact_sha256, archive_hashes, not arguments.no_api, position, len(unique)))
        workers = artifact_workers(getattr(arguments, "workers", None))
        print(f"[3/4] 使用 {workers} 个工作线程并行读取 {len(tasks)} 个构件；SQLite 写入保持单线程…", flush=True)
        written = 0
        for result in process_artifact_tasks(tasks, workers):
            write_artifact_result(connection, result)
            written += 1
            label = ":".join(result["coordinate"]) if result["coordinate"] else result["path"].name
            print(f"[3/4] 已写入构件 {written}/{len(tasks)}：{label}（类 {len(result['class_rows'])}，公开成员 {len(result['records'])}）", flush=True)
        connection.executemany("INSERT OR IGNORE INTO configuration_artifacts(configuration_id, artifact_id) VALUES (?, ?)", configuration_artifacts)
        current_fingerprint = fingerprint(project)
        metadata_entries = {
            "schemaVersion": str(INDEX_SCHEMA_VERSION), "toolVersion": TOOL_VERSION, "projectPath": str(project),
            "fingerprint": current_fingerprint["sha256"], "fingerprintFiles": json.dumps(current_fingerprint["files"], ensure_ascii=False, separators=(",", ":")),
            "gradleVersion": str(raw.get("gradleVersion", "")), "createdAtEpoch": str(int(time.time())),
        }
        connection.executemany("INSERT INTO metadata(key, value) VALUES (?, ?)", metadata_entries.items())
        connection.executemany("INSERT INTO archive_hashes(path, size, modified_ns, sha256) VALUES (?, ?, ?, ?)", archive_hashes.rows())
        print("[4/4] 正在建立查询索引与类名、公开 API 全文索引并完成 SQLite 写入…", flush=True)
        create_query_indexes(connection)
        connection.execute("INSERT INTO class_search(class_search) VALUES ('rebuild')")
        connection.execute("INSERT INTO api_search(api_search) VALUES ('rebuild')")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()
    temporary.replace(database)


def load_database(arguments: argparse.Namespace) -> sqlite3.Connection:
    connection = open_database(index_path(arguments.state))
    values = metadata(connection)
    if values.get("schemaVersion") != str(INDEX_SCHEMA_VERSION):
        connection.close()
        raise IndexError("依赖索引版本不兼容；请重新运行 sync。")
    return connection


def stale_reason(connection: sqlite3.Connection, project: Path) -> str | None:
    if metadata(connection).get("fingerprint") != fingerprint(project)["sha256"]:
        return "构建输入已变化，请重新运行 sync"
    return None


def require_fresh(connection: sqlite3.Connection, arguments: argparse.Namespace) -> None:
    reason = stale_reason(connection, normalize_project(arguments.project))
    if reason:
        raise IndexError(f"索引已过期：{reason}。")


def clamp(arguments: argparse.Namespace) -> tuple[int, int]:
    return min(max(1, int(arguments.limit)), MAX_LIMIT), max(0, int(arguments.offset))


def emit(items: list[dict[str, Any]], total: int, arguments: argparse.Namespace) -> None:
    limit, offset = clamp(arguments)
    selected = items[:limit]
    remaining = max(0, total - offset - len(selected))
    if arguments.json:
        print(json.dumps({"count": total, "items": selected, "remaining": remaining}, ensure_ascii=False, separators=(",", ":")))
    else:
        for item in selected:
            print(item["text"])
        if remaining:
            print(f"其余 {remaining} 条；使用更精确关键词或 --offset {offset + limit}")


def command_sync(arguments: argparse.Namespace) -> int:
    build_database(arguments, index_path(arguments.state))
    connection = load_database(arguments)
    try:
        counts = {name: connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in ("modules", "configurations", "artifacts", "classes", "api")}
        without_sources = connection.execute("SELECT COUNT(*) FROM artifacts WHERE api_status NOT IN ('bytecode-with-sources', 'bytecode-with-sources-and-javadoc')").fetchone()[0]
        failed = connection.execute("SELECT COUNT(*) FROM configurations WHERE status != 'ok'").fetchone()[0]
    finally:
        connection.close()
    print(f"已同步：模块 {counts['modules']}，配置 {counts['configurations']}，构件 {counts['artifacts']}，类 {counts['classes']}，公开签名 {counts['api']}（均来自运行字节码），缺少 sources 资料 {without_sources}，失败 {failed}")
    return 0


def command_status(arguments: argparse.Namespace) -> int:
    connection = load_database(arguments)
    try:
        reason = stale_reason(connection, normalize_project(arguments.project))
        data = {"status": "stale" if reason else "ready", "reason": reason, "modules": connection.execute("SELECT COUNT(*) FROM modules").fetchone()[0], "artifacts": connection.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0], "classes": connection.execute("SELECT COUNT(*) FROM classes").fetchone()[0], "members": connection.execute("SELECT COUNT(*) FROM api").fetchone()[0], "withoutSources": connection.execute("SELECT COUNT(*) FROM artifacts WHERE api_status NOT IN ('bytecode-with-sources', 'bytecode-with-sources-and-javadoc')").fetchone()[0], "binarySignatures": connection.execute("SELECT COUNT(*) FROM artifacts WHERE api_status != 'not-requested'").fetchone()[0]}
    finally:
        connection.close()
    print(json.dumps(data, ensure_ascii=False, separators=(",", ":")) if arguments.json else f"SQLite 索引 {data['status']}：模块 {data['modules']}，构件 {data['artifacts']}，类 {data['classes']}，公开签名 {data['members']}（运行字节码），无 sources 资料 {data['withoutSources']}{'；' + reason if reason else ''}")
    return 1 if reason else 0


def command_modules(arguments: argparse.Namespace) -> int:
    connection = load_database(arguments)
    try:
        require_fresh(connection, arguments)
        limit, offset = clamp(arguments)
        total = connection.execute("SELECT COUNT(*) FROM modules").fetchone()[0]
        rows = connection.execute("SELECT m.path, COUNT(c.id) configurations FROM modules m LEFT JOIN configurations c ON c.module_path=m.path GROUP BY m.path ORDER BY m.path LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        emit([{"module": row["path"], "configurations": row["configurations"], "text": f"{row['path']} | 配置 {row['configurations']}"} for row in rows], total, arguments)
    finally:
        connection.close()
    return 0


def command_dependencies(arguments: argparse.Namespace) -> int:
    connection = load_database(arguments)
    try:
        require_fresh(connection, arguments)
        limit, offset = clamp(arguments)
        where = "c.module_path = ?" + (" AND c.name = ?" if arguments.configuration else "")
        params: list[Any] = [arguments.module] + ([arguments.configuration] if arguments.configuration else [])
        artifacts = f"SELECT c.name configuration, 'artifact' kind, COALESCE(a.group_name || ':' || a.artifact_name || ':' || a.version, a.file_name) dependency FROM configurations c JOIN configuration_artifacts ca ON ca.configuration_id=c.id JOIN artifacts a ON a.id=ca.artifact_id WHERE {where}"
        if arguments.transitive:
            edges = f"SELECT c.name configuration, d.kind kind, COALESCE(NULLIF(d.selected,''), NULLIF(d.requested,''), d.failure) dependency FROM configurations c JOIN dependencies d ON d.configuration_id=c.id WHERE {where}"
            union = f"{artifacts} UNION ALL {edges}"
            union_params = [*params, *params]
        else:
            union = artifacts
            union_params = params
        total = connection.execute(f"SELECT COUNT(*) FROM ({union})", union_params).fetchone()[0]
        rows = connection.execute(f"SELECT * FROM ({union}) ORDER BY configuration, dependency, kind LIMIT ? OFFSET ?", (*union_params, limit, offset)).fetchall()
        emit([{"configuration": row["configuration"], "dependency": row["dependency"], "kind": row["kind"], "text": f"{row['configuration']} | {row['dependency']} | {row['kind']}"} for row in rows], total, arguments)
    finally:
        connection.close()
    return 0


def command_classes(arguments: argparse.Namespace) -> int:
    connection = load_database(arguments)
    try:
        require_fresh(connection, arguments)
        limit, offset = clamp(arguments)
        search = fts_query(arguments.query)
        total = connection.execute("SELECT COUNT(*) FROM class_search WHERE class_search MATCH ?", (search,)).fetchone()[0]
        rows = connection.execute("SELECT c.name, c.binary_name, a.group_name, a.artifact_name, a.version FROM class_search s JOIN classes c ON c.id=s.rowid JOIN artifacts a ON a.id=c.artifact_id WHERE class_search MATCH ? ORDER BY c.name LIMIT ? OFFSET ?", (search, limit, offset)).fetchall()
        items = []
        for row in rows:
            gav = f"{row['group_name']}:{row['artifact_name']}:{row['version']}" if row['group_name'] else "未知构件"
            item = {"class": row["name"], "artifact": gav, "text": f"{row['name']} | {gav}"}
            if arguments.verbose:
                item["binaryName"] = row["binary_name"]
            items.append(item)
        emit(items, total, arguments)
    finally:
        connection.close()
    return 0 if total else 1


def ancestor_distances(connection: sqlite3.Connection, requested: str) -> dict[str, int]:
    if "." in requested:
        seeds = [requested]
    else:
        seeds = [row[0] for row in connection.execute("SELECT DISTINCT owner FROM api WHERE kind='type' AND substr(owner, instr(owner, '.') + 1) LIKE ?", (f"%.{requested}",))]
        if not seeds:
            seeds = [row[0] for row in connection.execute("SELECT DISTINCT owner FROM api WHERE kind='type' AND owner LIKE ?", (f"%.{requested}",))]
    found: dict[str, int] = {}
    pending = [(seed, 0) for seed in seeds]
    while pending:
        current, distance = pending.pop(0)
        if current in found and found[current] <= distance:
            continue
        found[current] = distance
        pending.extend((row[0], distance + 1) for row in connection.execute("SELECT parent_owner FROM type_edges WHERE child_owner=?", (current,)))
    return found


def member_text(row: sqlite3.Row, gav: str, inheritance_distance: int, verbose: bool) -> str:
    """格式化成员查询的可读输出；详细模式只显示索引中唯一确认的资料。"""
    inherited = "" if inheritance_distance == 0 else f" | 继承 {inheritance_distance}"
    text = f"{row['kind']} | 声明于 {row['owner']}{inherited} | {row['declaration']} | {gav} | {row['source_path']}:{row['source_line']}"
    if not verbose:
        return text
    details = []
    if row["javadoc_path"]:
        details.append(f"  Javadoc 页面：{row['javadoc_path']}")
    if row["documentation"]:
        details.append(f"  摘要：{row['documentation']}")
    return text if not details else text + "\n" + "\n".join(details)


def command_members(arguments: argparse.Namespace) -> int:
    connection = load_database(arguments)
    try:
        require_fresh(connection, arguments)
        limit, offset = clamp(arguments)
        search = fts_query(arguments.query)
        visible = ancestor_distances(connection, arguments.type_name) if arguments.type_name else None
        if arguments.type_name and not visible:
            raise IndexError(f"索引中未找到类型：{arguments.type_name}")
        if visible is None:
            total = connection.execute("SELECT COUNT(*) FROM api_search WHERE api_search MATCH ?", (search,)).fetchone()[0]
            rows = connection.execute("SELECT a.*, r.group_name, r.artifact_name, r.version FROM api_search s JOIN api a ON a.id=s.rowid JOIN artifacts r ON r.id=a.artifact_id WHERE api_search MATCH ? ORDER BY a.owner, a.declaration LIMIT ? OFFSET ?", (search, limit, offset)).fetchall()
        else:
            placeholders = ",".join("?" for _ in visible)
            values = [search, *visible.keys()]
            total = connection.execute(f"SELECT COUNT(*) FROM api_search s JOIN api a ON a.id=s.rowid WHERE api_search MATCH ? AND a.owner IN ({placeholders})", values).fetchone()[0]
            rows = connection.execute(f"SELECT a.*, r.group_name, r.artifact_name, r.version FROM api_search s JOIN api a ON a.id=s.rowid JOIN artifacts r ON r.id=a.artifact_id WHERE api_search MATCH ? AND a.owner IN ({placeholders}) ORDER BY a.owner, a.declaration LIMIT ? OFFSET ?", (*values, limit, offset)).fetchall()
        items = []
        for row in rows:
            gav = f"{row['group_name']}:{row['artifact_name']}:{row['version']}" if row['group_name'] else "未知构件"
            distance = visible.get(row["owner"], 0) if visible else 0
            item = {"kind": row["kind"], "owner": row["owner"], "declaration": row["declaration"], "artifact": gav, "source": row["source_path"], "line": row["source_line"], "inheritanceDistance": distance, "text": member_text(row, gav, distance, arguments.verbose)}
            if arguments.verbose:
                item["documentation"] = row["documentation"]
                item["javadoc"] = row["javadoc_path"]
            items.append(item)
        emit(items, total, arguments)
    finally:
        connection.close()
    return 0 if total else 1


def command_show(arguments: argparse.Namespace) -> int:
    connection = load_database(arguments)
    try:
        require_fresh(connection, arguments)
        limit, offset = clamp(arguments)
        query = arguments.artifact.casefold()
        rows = connection.execute("SELECT a.*, (SELECT COUNT(*) FROM classes c WHERE c.artifact_id=a.id) classes, (SELECT COUNT(*) FROM api p WHERE p.artifact_id=a.id) members FROM artifacts a WHERE lower(COALESCE(a.group_name || ':' || a.artifact_name || ':' || a.version, a.file_name)) LIKE ? OR lower(a.id) LIKE ? ORDER BY a.group_name, a.artifact_name LIMIT ? OFFSET ?", (f"%{query}%", f"{query}%", limit, offset)).fetchall()
        total = connection.execute("SELECT COUNT(*) FROM artifacts a WHERE lower(COALESCE(a.group_name || ':' || a.artifact_name || ':' || a.version, a.file_name)) LIKE ? OR lower(a.id) LIKE ?", (f"%{query}%", f"{query}%")).fetchone()[0]
        items = []
        for row in rows:
            gav = coordinate_text(row)
            item = {"artifact": gav, "classes": row["classes"], "members": row["members"], "apiStatus": row["api_status"], "sha256": row["sha256"], "text": f"{gav} | 类 {row['classes']} | 公开签名 {row['members']} | {row['api_status']}"}
            if arguments.verbose:
                item["file"] = row["file_path"]
                item["sources"] = row["sources_source"]
                item["javadoc"] = row["javadoc_source"]
            items.append(item)
        emit(items, total, arguments)
    finally:
        connection.close()
    return 0 if total else 1


def zoo_template() -> Path:
    return SCRIPT_ROOT / "zoo" / "dependency-index.js.template"




def install_zoo_runtime(tools: Path, dry_run: bool) -> None:
    package = tools / "node_modules" / "zod" / "package.json"
    if package.is_file():
        try:
            if json.loads(package.read_text(encoding="utf-8")).get("version") == ZOO_ZOD_VERSION:
                return
        except (OSError, json.JSONDecodeError):
            pass
    npm = shutil.which("npm")
    if not npm:
        raise IndexError("Zoo 工具需要 npm 安装 zod，但当前环境找不到 npm。")
    command = [npm, "install", "--no-save", "--no-package-lock", f"zod@{ZOO_ZOD_VERSION}"]
    print(f"{'预览安装' if dry_run else '安装'} Zoo 工具运行时依赖：{' '.join(command)}")
    if dry_run:
        return
    result = subprocess.run(command, cwd=tools, check=False)
    if result.returncode or not package.is_file():
        raise IndexError("Zoo 工具运行时依赖 zod 安装失败；请检查 npm 网络/镜像后重试。")



def command_install_zoo(arguments: argparse.Namespace) -> int:
    project = normalize_project(arguments.project)
    source = zoo_template()
    tools = project / ".roo" / "tools"
    destination = tools / "pluginbase-dependency-index.js"
    if not source.is_file():
        raise IndexError(f"找不到 Zoo 工具模板：{source}")
    if destination.exists() and not arguments.force:
        print(f"保留已有 Zoo 工具：{destination}")
        install_zoo_runtime(tools, arguments.dry_run)
        return 0
    action = "覆盖" if destination.exists() else "创建"
    print(f"{'预览' if arguments.dry_run else ''}{action} Zoo 工具：{destination}")
    if not arguments.dry_run:
        tools.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    install_zoo_runtime(tools, arguments.dry_run)
    return 0

def main() -> int:
    arguments = parser().parse_args()
    try:
        handlers = {"sync": command_sync, "status": command_status, "modules": command_modules, "dependencies": command_dependencies, "classes": command_classes, "members": command_members, "show": command_show, "install-zoo": command_install_zoo}
        return handlers[arguments.command](arguments)
    except EvidenceError as error:
        print_error(str(error))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
