#!/usr/bin/env python3
"""按 Gradle 模块建立 SQLite 依赖、类与公开 Java API 索引。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Iterable, Iterator

SCRIPT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_ROOT))

from common.evidence import (  # noqa: E402
    EvidenceError,
    default_gradle_homes,
    download_artifact,
    find_cached_artifacts,
    print_error,
    sha256,
)

PROJECT_ROOT = SCRIPT_ROOT.parent
STATE_ROOT = PROJECT_ROOT / "state"
INDEX_SCHEMA_VERSION = 3
TOOL_VERSION = "3"
DEFAULT_REPOSITORIES = ("https://repo.maven.apache.org/maven2/",)
DEFAULT_LIMIT = 8
MAX_LIMIT = 100
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
            def output = [schemaVersion: 1, gradleVersion: gradle.gradleVersion, projects: []]
            root.allprojects.sort { it.path }.each { current ->
                def repositories = current.repositories.findAll { repository -> repository.hasProperty("url") }
                    .collect { repository -> repository.url.toString() }.unique()
                def projectData = [path: current.path, name: current.name, repositories: repositories, configurations: []]
                current.configurations.findAll { configuration -> configuration.canBeResolved }.sort { it.name }.each { configuration ->
                    def configData = [name: configuration.name, status: "ok", artifacts: [], dependencies: [], failures: []]
                    try {
                        configuration.resolvedConfiguration.resolvedArtifacts.toList().sort { it.file.absolutePath }.each { artifact ->
                            def id = artifact.moduleVersion.id
                            configData.artifacts << [
                                group: id.group ?: "", artifact: id.name ?: "", version: id.version ?: "",
                                classifier: artifact.classifier ?: "", extension: artifact.extension ?: "",
                                file: artifact.file.absolutePath, type: artifact.type ?: ""
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
    command.add_argument("--verbose", action="store_true", help="显示来源、路径、哈希等详情")


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


def run_gradle(project: Path, state_root: Path, explicit_home: str | None) -> dict[str, Any]:
    homes = default_gradle_homes(explicit_home, state_root)
    environment = os.environ.copy()
    if homes:
        environment["GRADLE_USER_HOME"] = str(homes[0])
    with tempfile.TemporaryDirectory(prefix="pluginbase-agent-index-") as temporary:
        init_file = Path(temporary) / "dependency-index.init.gradle"
        init_file.write_text(INIT_SCRIPT, encoding="utf-8", newline="\n")
        command = gradle_command(project, ["--no-daemon", "--console=plain", "--init-script", str(init_file), "pluginBaseAgentDependencyIndex"])
        try:
            result = subprocess.run(command, cwd=project, env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8", errors="replace", timeout=300, check=False)
        except OSError as error:
            raise IndexError(f"无法启动 Gradle Wrapper：{error}") from error
        except subprocess.TimeoutExpired as error:
            raise IndexError("Gradle 依赖解析超过 300 秒；请检查网络、仓库或配置。") from error
    output = result.stdout or ""
    start = output.find(MARKER_START)
    end = output.find(MARKER_END, start + len(MARKER_START))
    if start < 0 or end < 0:
        raise IndexError(f"Gradle 未输出索引 JSON（退出码 {result.returncode}）：{compact_text(output, 800)}")
    try:
        parsed = json.loads(output[start + len(MARKER_START):end].strip())
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


def repositories_for(project_data: dict[str, Any]) -> list[str]:
    values = [str(value).rstrip("/") + "/" for value in project_data.get("repositories", []) if str(value).startswith(("http://", "https://"))]
    return list(dict.fromkeys([*values, *DEFAULT_REPOSITORIES]))


def reference_archive(classifier: str, coordinate: tuple[str, str, str], repositories: Iterable[str], homes: Iterable[Path]) -> tuple[Path, dict[str, str], Path | None] | None:
    """优先原地读取 Gradle 缓存；远程构件仅使用临时文件。"""
    group, artifact, version = coordinate
    cached = find_cached_artifacts(homes, group, artifact, version, classifier)
    if cached:
        archive = cached[0]
        return archive, {"sha256": sha256(archive), "origin": "gradle-cache", "source": str(archive), "resolvedVersion": version}, None
    with tempfile.NamedTemporaryFile(prefix=f"pluginbase-agent-{classifier}-", suffix=".jar", delete=False) as temporary:
        destination = Path(temporary.name)
    try:
        url, resolved_version = download_artifact(repositories, group, artifact, version, classifier, destination)
        return destination, {"sha256": sha256(destination), "origin": "maven", "source": url, "resolvedVersion": resolved_version}, destination
    except EvidenceError:
        destination.unlink(missing_ok=True)
        return None


def iter_class_names(archive: Path) -> Iterator[tuple[str, str]]:
    try:
        with zipfile.ZipFile(archive) as source:
            for entry in source.namelist():
                if not entry.endswith(".class") or entry.startswith("META-INF/") or entry.endswith("module-info.class"):
                    continue
                binary = entry[:-6].replace("/", ".")
                if binary.rsplit(".", 1)[-1].isdigit():
                    continue
                yield binary.replace("$", "."), binary
    except zipfile.BadZipFile:
        return


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


def html_text(value: str) -> str:
    value = re.sub(r"<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>", "", value, flags=re.IGNORECASE | re.DOTALL)
    return compact_text(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value)).strip(), 420)


def add_javadoc_summaries(records: list[dict[str, Any]], source: zipfile.ZipFile) -> None:
    by_owner: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_owner.setdefault(str(record["owner"]), []).append(record)
    for owner, owner_records in by_owner.items():
        path = owner.replace(".", "/") + ".html"
        try:
            document = source.read(path).decode("utf-8", errors="replace")
        except KeyError:
            continue
        blocks = re.findall(r'<div class="block">(.*?)</div>', document, flags=re.IGNORECASE | re.DOTALL)
        summary = html_text(blocks[0]) if blocks else ""
        for record in owner_records:
            record["javadoc"] = path
            if record["kind"] == "type":
                record["documentation"] = summary or None
                continue
            name = re.escape(str(record["name"]))
            found = re.search(rf'id="[^"]*{name}[^"]*".*?<div class="block">(.*?)</div>', document, flags=re.IGNORECASE | re.DOTALL)
            if found:
                record["documentation"] = html_text(found.group(1)) or None


def iter_public_api(source_archive: Path, javadoc_archive: Path | None, progress_prefix: str) -> Iterator[dict[str, Any]]:
    """顺序读取归档；每次只保留一个 Java 文件及其对应类型页面。"""
    try:
        with zipfile.ZipFile(source_archive) as sources:
            java_count = sum(1 for info in sources.infolist() if not info.is_dir() and info.filename.endswith(".java"))
            javadocs = zipfile.ZipFile(javadoc_archive) if javadoc_archive else None
            processed = 0
            try:
                for info in sources.infolist():
                    if info.is_dir() or not info.filename.endswith(".java"):
                        continue
                    processed += 1
                    if processed == 1 or processed % 200 == 0 or processed == java_count:
                        print(f"{progress_prefix}公开 API 文件 {processed}/{java_count}", flush=True)
                    lines = sources.read(info).decode("utf-8", errors="replace").splitlines()
                    package = ""
                    imports: dict[str, str] = {}
                    for line in lines[:200]:
                        found = re.match(r"\s*package\s+([\w.]+)\s*;", line)
                        if found:
                            package = found.group(1)
                        imported = re.match(r"\s*import\s+(?:static\s+)?([\w.]+)\s*;", line)
                        if imported and not imported.group(1).endswith(".*"):
                            qualified = imported.group(1)
                            imports[qualified.rsplit(".", 1)[-1]] = qualified
                    records = java_public_declarations(lines, package, imports, info.filename)
                    if javadocs and records:
                        add_javadoc_summaries(records, javadocs)
                    yield from records
            finally:
                if javadocs:
                    javadocs.close()
    except zipfile.BadZipFile:
        return


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
        CREATE INDEX classes_artifact_idx ON classes(artifact_id);
        CREATE INDEX api_owner_idx ON api(owner);
        CREATE INDEX api_artifact_idx ON api(artifact_id);
        CREATE INDEX edges_parent_idx ON type_edges(parent_owner);
        CREATE INDEX configurations_module_idx ON configurations(module_path);
        CREATE VIRTUAL TABLE class_search USING fts5(name, binary_name, artifact_id UNINDEXED, class_id UNINDEXED, tokenize='unicode61', prefix='2 3 4');
        CREATE VIRTUAL TABLE api_search USING fts5(owner, name, declaration, documentation, api_id UNINDEXED, tokenize='unicode61', prefix='2 3 4');
    """)


def metadata(connection: sqlite3.Connection) -> dict[str, str]:
    return {row["key"]: row["value"] for row in connection.execute("SELECT key, value FROM metadata")}


def fts_query(query: str) -> str:
    terms = re.findall(r"[\w.$]+", query, flags=re.UNICODE)
    if not terms:
        raise IndexError("查询文本不包含可搜索字符。")
    return " AND ".join(f'"{term.replace("\"", "")}"*' for term in terms)


def artifact_id(raw: dict[str, Any]) -> str:
    path = native_path(str(raw.get("file", "")))
    return sha256(path) if path.is_file() else "missing:" + re.sub(r"[^A-Za-z0-9_.-]+", "_", str(path))


def insert_artifact(connection: sqlite3.Connection, raw: dict[str, Any], homes: list[Path], repositories: list[str], include_api: bool, position: int, total: int) -> None:
    path = native_path(str(raw.get("file", "")))
    identifier = artifact_id(raw)
    if not path.is_file():
        connection.execute("INSERT INTO artifacts(id, file_name, file_path, api_status) VALUES (?, ?, ?, ?)", (identifier, path.name, str(path), "missing"))
        return
    coordinate = valid_coordinate(raw)
    label = ":".join(coordinate) if coordinate else path.name
    prefix = f"[3/4] 构件 {position}/{total} {label}："
    print(prefix + "扫描类名", flush=True)
    source_reference = reference_archive("sources", coordinate, repositories, homes) if coordinate and include_api else None
    javadoc_reference = reference_archive("javadoc", coordinate, repositories, homes) if coordinate and include_api else None
    sources_info = source_reference[1] if source_reference else None
    javadoc_info = javadoc_reference[1] if javadoc_reference else None
    api_status = "not-requested" if not include_api else ("sources" if source_reference and javadoc_reference else "sources-only" if source_reference else "javadoc-only" if javadoc_reference else "unavailable")
    connection.execute("""
        INSERT INTO artifacts(id, group_name, artifact_name, version, classifier, extension, file_name, file_path, sha256, sources_sha256, sources_origin, sources_source, javadoc_sha256, javadoc_origin, javadoc_source, api_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (identifier, *(coordinate or (None, None, None)), str(raw.get("classifier", "")), str(raw.get("extension", "")), path.name, str(path), sha256(path), *(sources_info[key] if sources_info else None for key in ("sha256", "origin", "source")), *(javadoc_info[key] if javadoc_info else None for key in ("sha256", "origin", "source")), api_status))
    for name, binary in iter_class_names(path):
        cursor = connection.execute("INSERT INTO classes(artifact_id, name, binary_name) VALUES (?, ?, ?)", (identifier, name, binary))
        connection.execute("INSERT INTO class_search(name, binary_name, artifact_id, class_id) VALUES (?, ?, ?, ?)", (name, binary, identifier, cursor.lastrowid))
    if source_reference:
        source_archive, _, source_temporary = source_reference
        javadoc_archive = javadoc_reference[0] if javadoc_reference else None
        print(prefix + ("读取 sources 与 Javadoc 摘要" if javadoc_archive else "读取 sources"), flush=True)
        try:
            for record in iter_public_api(source_archive, javadoc_archive, prefix):
                cursor = connection.execute("INSERT INTO api(artifact_id, kind, owner, name, declaration, source_path, source_line, javadoc_path, documentation) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (identifier, record["kind"], record["owner"], record["name"], record["declaration"], record["source"], record["line"], record["javadoc"], record["documentation"]))
                connection.execute("INSERT INTO api_search(owner, name, declaration, documentation, api_id) VALUES (?, ?, ?, ?, ?)", (record["owner"], record["name"], record["declaration"], record["documentation"] or "", cursor.lastrowid))
                if record["kind"] == "type":
                    connection.executemany("INSERT OR IGNORE INTO type_edges(child_owner, parent_owner) VALUES (?, ?)", ((record["owner"], parent) for parent in record["supertypes"]))
        finally:
            if source_temporary:
                source_temporary.unlink(missing_ok=True)
    if javadoc_reference and javadoc_reference[2]:
        javadoc_reference[2].unlink(missing_ok=True)


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
    raw = selected_configurations(run_gradle(project, state_root, arguments.gradle_user_home), arguments.configuration)
    homes = default_gradle_homes(arguments.gradle_user_home, state_root)
    unique: dict[str, tuple[dict[str, Any], list[str]]] = {}
    for project_data in raw["projects"]:
        repositories = repositories_for(project_data)
        for config in project_data.get("configurations", []):
            for artifact in config.get("artifacts", []):
                unique.setdefault(artifact_id(artifact), (artifact, repositories))
    print(f"[2/4] 已发现 {len(raw['projects'])} 个模块、{len(unique)} 个唯一构件；开始流式建立 SQLite 索引…", flush=True)
    remove_legacy_index_state(state_root)
    temporary = database.with_suffix(database.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    connection = open_database(temporary, writable=True)
    try:
        create_schema(connection)
        connection.execute("BEGIN")
        for project_data in raw["projects"]:
            connection.execute("INSERT INTO modules(path, name) VALUES (?, ?)", (str(project_data.get("path", "")), str(project_data.get("name", ""))))
            for config in project_data.get("configurations", []):
                cursor = connection.execute("INSERT INTO configurations(module_path, name, status) VALUES (?, ?, ?)", (str(project_data.get("path", "")), str(config.get("name", "")), str(config.get("status", "unknown"))))
                config_id = cursor.lastrowid
                for dependency in config.get("dependencies", []):
                    connection.execute("INSERT INTO dependencies(configuration_id, kind, requested, selected, failure) VALUES (?, ?, ?, ?, NULL)", (config_id, str(dependency.get("kind", "")), str(dependency.get("requested", "")), str(dependency.get("selected", ""))))
                for failure in config.get("failures", []):
                    connection.execute("INSERT INTO dependencies(configuration_id, kind, requested, selected, failure) VALUES (?, 'failed', '', '', ?)", (config_id, compact_text(str(failure), 500)))
                for artifact in config.get("artifacts", []):
                    identifier = artifact_id(artifact)
                    if connection.execute("SELECT 1 FROM artifacts WHERE id = ?", (identifier,)).fetchone() is None:
                        raw_artifact, repositories = unique[identifier]
                        insert_artifact(connection, raw_artifact, homes, repositories, not arguments.no_api, connection.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] + 1, len(unique))
                    connection.execute("INSERT OR IGNORE INTO configuration_artifacts(configuration_id, artifact_id) VALUES (?, ?)", (config_id, identifier))
        current_fingerprint = fingerprint(project)
        metadata_entries = {
            "schemaVersion": str(INDEX_SCHEMA_VERSION), "toolVersion": TOOL_VERSION, "projectPath": str(project),
            "fingerprint": current_fingerprint["sha256"], "fingerprintFiles": json.dumps(current_fingerprint["files"], ensure_ascii=False, separators=(",", ":")),
            "gradleVersion": str(raw.get("gradleVersion", "")), "createdAtEpoch": str(int(time.time())),
        }
        connection.executemany("INSERT INTO metadata(key, value) VALUES (?, ?)", metadata_entries.items())
        print("[4/4] 正在完成 SQLite 索引写入…", flush=True)
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
        missing = connection.execute("SELECT COUNT(*) FROM artifacts WHERE api_status IN ('unavailable', 'javadoc-only')").fetchone()[0]
        failed = connection.execute("SELECT COUNT(*) FROM configurations WHERE status != 'ok'").fetchone()[0]
    finally:
        connection.close()
    print(f"已同步：模块 {counts['modules']}，配置 {counts['configurations']}，构件 {counts['artifacts']}，类 {counts['classes']}，公开签名 {counts['api']}，资料缺失 {missing}，失败 {failed}")
    return 0


def command_status(arguments: argparse.Namespace) -> int:
    connection = load_database(arguments)
    try:
        reason = stale_reason(connection, normalize_project(arguments.project))
        data = {"status": "stale" if reason else "ready", "reason": reason, "modules": connection.execute("SELECT COUNT(*) FROM modules").fetchone()[0], "artifacts": connection.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0], "classes": connection.execute("SELECT COUNT(*) FROM classes").fetchone()[0], "members": connection.execute("SELECT COUNT(*) FROM api").fetchone()[0], "withoutSources": connection.execute("SELECT COUNT(*) FROM artifacts WHERE api_status NOT IN ('sources', 'sources-only')").fetchone()[0]}
    finally:
        connection.close()
    print(json.dumps(data, ensure_ascii=False, separators=(",", ":")) if arguments.json else f"SQLite 索引 {data['status']}：模块 {data['modules']}，构件 {data['artifacts']}，类 {data['classes']}，公开签名 {data['members']}，无源码资料 {data['withoutSources']}{'；' + reason if reason else ''}")
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
        rows = connection.execute("SELECT c.name, c.binary_name, a.group_name, a.artifact_name, a.version FROM class_search s JOIN classes c ON c.id=s.class_id JOIN artifacts a ON a.id=c.artifact_id WHERE class_search MATCH ? ORDER BY c.name LIMIT ? OFFSET ?", (search, limit, offset)).fetchall()
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
            rows = connection.execute("SELECT a.*, r.group_name, r.artifact_name, r.version FROM api_search s JOIN api a ON a.id=s.api_id JOIN artifacts r ON r.id=a.artifact_id WHERE api_search MATCH ? ORDER BY a.owner, a.declaration LIMIT ? OFFSET ?", (search, limit, offset)).fetchall()
        else:
            placeholders = ",".join("?" for _ in visible)
            values = [search, *visible.keys()]
            total = connection.execute(f"SELECT COUNT(*) FROM api_search s JOIN api a ON a.id=s.api_id WHERE api_search MATCH ? AND a.owner IN ({placeholders})", values).fetchone()[0]
            rows = connection.execute(f"SELECT a.*, r.group_name, r.artifact_name, r.version FROM api_search s JOIN api a ON a.id=s.api_id JOIN artifacts r ON r.id=a.artifact_id WHERE api_search MATCH ? AND a.owner IN ({placeholders}) ORDER BY a.owner, a.declaration LIMIT ? OFFSET ?", (*values, limit, offset)).fetchall()
        items = []
        for row in rows:
            gav = f"{row['group_name']}:{row['artifact_name']}:{row['version']}" if row['group_name'] else "未知构件"
            distance = visible.get(row["owner"], 0) if visible else 0
            inherited = "" if distance == 0 else f" | 继承 {distance}"
            item = {"kind": row["kind"], "owner": row["owner"], "declaration": row["declaration"], "artifact": gav, "source": row["source_path"], "line": row["source_line"], "inheritanceDistance": distance, "text": f"{row['kind']} | 声明于 {row['owner']}{inherited} | {row['declaration']} | {gav} | {row['source_path']}:{row['source_line']}"}
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
    return SCRIPT_ROOT / "zoo" / "dependency-index.ts.template"


def command_install_zoo(arguments: argparse.Namespace) -> int:
    project = normalize_project(arguments.project)
    source = zoo_template()
    destination = project / ".roo" / "tools" / "pluginbase-dependency-index.ts"
    if not source.is_file():
        raise IndexError(f"找不到 Zoo 工具模板：{source}")
    if destination.exists() and not arguments.force:
        print(f"保留已有 Zoo 工具：{destination}")
        return 0
    print(f"{'预览' if arguments.dry_run else ''}{'覆盖' if destination.exists() else '创建'} Zoo 工具：{destination}")
    if not arguments.dry_run:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
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
