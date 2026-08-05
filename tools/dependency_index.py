#!/usr/bin/env python3
"""按 Gradle 模块建立本地依赖、类与公开 Java API 索引。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Iterable

SCRIPT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_ROOT))

from common.evidence import (  # noqa: E402
    EvidenceError,
    copy_or_download,
    default_gradle_homes,
    print_error,
    sha256,
    write_json,
)

PROJECT_ROOT = SCRIPT_ROOT.parent
STATE_ROOT = PROJECT_ROOT / "state"
INDEX_SCHEMA_VERSION = 1
TOOL_VERSION = "1"
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
                def repositories = current.repositories.findAll { repository ->
                    repository.hasProperty("url")
                }.collect { repository -> repository.url.toString() }.unique()
                def projectData = [path: current.path, name: current.name, repositories: repositories, configurations: []]
                current.configurations.findAll { configuration -> configuration.canBeResolved }.sort { it.name }.each { configuration ->
                    def configData = [name: configuration.name, status: "ok", artifacts: [], dependencies: [], failures: []]
                    try {
                        def artifacts = configuration.resolvedConfiguration.resolvedArtifacts.toList().sort { it.file.absolutePath }
                        artifacts.each { artifact ->
                            def id = artifact.moduleVersion.id
                            configData.artifacts << [
                                group: id.group ?: "",
                                artifact: id.name ?: "",
                                version: id.version ?: "",
                                classifier: artifact.classifier ?: "",
                                extension: artifact.extension ?: "",
                                file: artifact.file.absolutePath,
                                type: artifact.type ?: ""
                            ]
                        }
                        configuration.incoming.resolutionResult.allDependencies.each { dependency ->
                            def requested = dependency.requested?.displayName ?: ""
                            def from = dependency.from?.id?.displayName ?: ""
                            if (dependency instanceof org.gradle.api.artifacts.result.ResolvedDependencyResult) {
                                def selected = dependency.selected?.id?.displayName ?: ""
                                configData.dependencies << [kind: "resolved", from: from, requested: requested, selected: selected]
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
    root.tasks.matching { it.name == "pluginBaseAgentDependencyIndex" }.configureEach { task ->
        task.outputs.upToDateWhen { false }
    }
}
'''


class IndexError(EvidenceError):
    """索引构建或读取失败。"""


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="按 Gradle 模块查询本地依赖、类和公开 Java API 索引。")
    root.add_argument("--state", type=Path, default=STATE_ROOT, help="agent-dev 本地状态目录")
    subcommands = root.add_subparsers(dest="command", required=True)

    sync_parser = subcommands.add_parser("sync", help="同步 Gradle 模块、依赖、类与公开 API 索引")
    add_project_argument(sync_parser)
    sync_parser.add_argument("--gradle-user-home", help="单次 Gradle/资料缓存目录覆盖")
    sync_parser.add_argument("--configuration", action="append", default=[], help="只同步名称匹配的可解析配置，可重复")
    sync_parser.add_argument("--no-api", action="store_true", help="只索引依赖与类名，不下载 sources/Javadoc")

    status_parser = subcommands.add_parser("status", help="显示索引摘要与是否过期")
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

    classes_parser = subcommands.add_parser("classes", help="按类名、简单名或包前缀查找类")
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

    zoo_parser = subcommands.add_parser("install-zoo", help="显式安装可选 Zoo Code 查询工具")
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
    return state_root / "indexes" / "dependency-index.json"


def normalize_project(project: Path) -> Path:
    resolved = project.resolve()
    if not resolved.is_dir():
        raise IndexError(f"目标项目不存在或不是目录：{project}")
    return resolved


def project_files(project: Path) -> list[Path]:
    names = ("settings.gradle", "settings.gradle.kts", "build.gradle", "build.gradle.kts", "gradle.properties", "gradle.lockfile")
    files = [project / name for name in names if (project / name).is_file()]
    files.extend(sorted(path for path in project.rglob("*.versions.toml") if ".gradle" in path.parts))
    for lockfile in project.rglob("*.lockfile"):
        if ".gradle" in lockfile.parts:
            files.append(lockfile)
    wrapper = project / "gradle" / "wrapper"
    if wrapper.is_dir():
        files.extend(sorted(path for path in wrapper.iterdir() if path.is_file()))
    for name in ("gradlew", "gradlew.bat"):
        candidate = project / name
        if candidate.is_file():
            files.append(candidate)
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
    """跨平台启动项目 Wrapper；Windows 优先 gradlew.bat，再回退 Git Bash。"""
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


def run_gradle(project: Path, state_root: Path, explicit_home: str | None) -> dict[str, Any]:
    homes = default_gradle_homes(explicit_home, state_root)
    environment = os.environ.copy()
    if homes:
        environment["GRADLE_USER_HOME"] = str(homes[0])
    with tempfile.TemporaryDirectory(prefix="pluginbase-agent-index-") as temporary:
        init_file = Path(temporary) / "dependency-index.init.gradle"
        init_file.write_text(INIT_SCRIPT, encoding="utf-8", newline="\n")
        arguments = gradle_command(
            project, ["--no-daemon", "--console=plain", "--init-script", str(init_file), "pluginBaseAgentDependencyIndex"]
        )
        try:
            result = subprocess.run(
                arguments, cwd=project, env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=300, check=False,
            )
        except OSError as error:
            raise IndexError(f"无法启动 Gradle Wrapper：{error}") from error
        except subprocess.TimeoutExpired as error:
            raise IndexError("Gradle 依赖解析超过 300 秒；请检查网络、仓库或配置。") from error
    output = result.stdout or ""
    start = output.find(MARKER_START)
    end = output.find(MARKER_END, start + len(MARKER_START))
    if start < 0 or end < 0:
        tail = compact_text(output, 800)
        raise IndexError(f"Gradle 未输出索引 JSON（退出码 {result.returncode}）：{tail}")
    payload = output[start + len(MARKER_START):end].strip()
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as error:
        raise IndexError(f"Gradle 输出的索引 JSON 无效：{error}") from error
    if not isinstance(parsed, dict) or not isinstance(parsed.get("projects"), list):
        raise IndexError("Gradle 输出的索引结构无效。")
    return parsed


def compact_text(value: str, limit: int) -> str:
    normalized = " ".join(value.split())
    return normalized[:limit] + ("…" if len(normalized) > limit else "")


def selected_configurations(raw: dict[str, Any], names: list[str]) -> dict[str, Any]:
    if not names:
        return raw
    wanted = set(names)
    copy = dict(raw)
    projects = []
    for project in raw.get("projects", []):
        current = dict(project)
        current["configurations"] = [item for item in project.get("configurations", []) if item.get("name") in wanted]
        projects.append(current)
    copy["projects"] = projects
    return copy


def valid_coordinate(artifact: dict[str, Any]) -> tuple[str, str, str] | None:
    group = str(artifact.get("group", "")).strip()
    name = str(artifact.get("artifact", "")).strip()
    version = str(artifact.get("version", "")).strip()
    if not group or not name or not version or group == "unspecified" or version == "unspecified":
        return None
    return group, name, version


def class_names(archive: Path) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    try:
        with zipfile.ZipFile(archive) as source:
            for entry in source.namelist():
                if not entry.endswith(".class") or entry.startswith("META-INF/") or entry.endswith("module-info.class"):
                    continue
                binary = entry[:-6].replace("/", ".")
                if binary.rsplit(".", 1)[-1].isdigit():
                    continue
                result.append({"binaryName": binary, "name": binary.replace("$", ".")})
    except zipfile.BadZipFile:
        return []
    return sorted(result, key=lambda item: item["name"])


def clean_segment(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def artifact_cache_root(state_root: Path, artifact_hash: str) -> Path:
    return state_root / "indexes" / "artifacts" / artifact_hash


def repositories_for(project_data: dict[str, Any]) -> list[str]:
    values = [str(value).rstrip("/") + "/" for value in project_data.get("repositories", []) if str(value).startswith(("http://", "https://"))]
    return list(dict.fromkeys([*values, *DEFAULT_REPOSITORIES]))


def copy_reference_archive(
    *, state_root: Path, artifact_hash: str, classifier: str, coordinate: tuple[str, str, str], repositories: Iterable[str], homes: Iterable[Path]
) -> dict[str, Any] | None:
    group, artifact, version = coordinate
    root = artifact_cache_root(state_root, artifact_hash)
    destination = root / f"{classifier}.jar"
    extracted = root / classifier
    try:
        copied = copy_or_download(
            gradle_homes=homes, group=group, artifact=artifact, version=version, classifier=classifier,
            repositories=repositories, destination=destination,
        )
    except EvidenceError:
        return None
    current_hash = sha256(destination)
    if not extracted.is_dir() or not (root / f"{classifier}.sha256").is_file() or (root / f"{classifier}.sha256").read_text(encoding="utf-8").strip() != current_hash:
        if extracted.exists():
            shutil.rmtree(extracted)
        safe_extract_archive(destination, extracted)
        (root / f"{classifier}.sha256").write_text(current_hash + "\n", encoding="utf-8", newline="\n")
    return {
        "archive": str(destination.relative_to(state_root)).replace("\\", "/"),
        "sha256": current_hash,
        "origin": copied["origin"],
        "source": copied["source"],
        "extracted": str(extracted.relative_to(state_root)).replace("\\", "/"),
    }


def safe_extract_archive(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as source:
        for member in source.infolist():
            target = destination / member.filename
            resolved_root = destination.resolve()
            resolved_target = target.resolve()
            if member.filename.startswith(("/", "\\")) or ".." in Path(member.filename).parts or (resolved_root != resolved_target and resolved_root not in resolved_target.parents):
                raise IndexError(f"归档包含不安全路径：{member.filename}")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open(member) as input_stream, target.open("wb") as output_stream:
                shutil.copyfileobj(input_stream, output_stream)


def public_api(source_root: Path, javadoc_root: Path | None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not source_root.is_dir():
        return records
    for source in sorted(source_root.rglob("*.java")):
        try:
            lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        package = ""
        imports: dict[str, str] = {}
        for line in lines[:200]:
            found = re.match(r"\s*package\s+([\w.]+)\s*;", line)
            if found:
                package = found.group(1)
            imported = re.match(r"\s*import\s+(?:static\s+)?([\w.]+)\s*;", line)
            if imported and not imported.group(1).endswith(".*"):
                qualified_import = imported.group(1)
                imports[qualified_import.rsplit(".", 1)[-1]] = qualified_import
        records.extend(java_public_declarations(lines, package, imports, source.relative_to(source_root).as_posix(), javadoc_root))
    return records


def java_public_declarations(
    lines: list[str], package: str, imports: dict[str, str], source_path: str, javadoc_root: Path | None
) -> list[dict[str, Any]]:
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
        opened = line.count("{")
        closed = line.count("}")
        found_type = type_pattern.search(line)
        if found_type:
            kind = found_type.group(1)
            name = found_type.group(2)
            qualified = f"{package}.{name}" if package else name
            types.append((name, depth + opened - closed, kind in {"interface", "@interface"}))
            record = api_record("type", qualified, name, line.strip(), source_path, line_number, javadoc_root, None)
            record["supertypes"] = declared_supertypes(line, package, imports)
            records.append(record)
        if types:
            pending = (pending + " " + line.strip()).strip()
            if len(pending) > 1000:
                pending = ""
            if (";" in line or "{" in line) and ("public" in pending or types[-1][2]):
                declaration = re.sub(r"\s+", " ", pending).strip()
                owner = types[-1][0]
                qualified_owner = f"{package}.{owner}" if package else owner
                implicitly_public = types[-1][2]
                method = re.search(r"\b(?:public\s+)?(?:static\s+|final\s+|abstract\s+|synchronized\s+|default\s+|native\s+|strictfp\s+|<[^>]+>\s+)*[\w.$<>?, \[\]]+\s+(\w+)\s*\(([^)]*)\)", declaration)
                constructor = re.search(rf"\bpublic\s+{re.escape(owner)}\s*\(([^)]*)\)", declaration)
                field = re.search(r"\b(?:public\s+)?(?:static\s+|final\s+|volatile\s+|transient\s+)*[\w.$<>?, \[\]]+\s+(\w+)\s*(?:=|;|,)", declaration)
                if method:
                    member = method.group(1)
                    records.append(api_record("method", qualified_owner, member, declaration, source_path, line_number, javadoc_root, member))
                elif constructor:
                    records.append(api_record("constructor", qualified_owner, owner, declaration, source_path, line_number, javadoc_root, owner))
                elif field:
                    member = field.group(1)
                    records.append(api_record("field", qualified_owner, member, declaration, source_path, line_number, javadoc_root, member))
                pending = ""
            elif not line.rstrip().endswith((",", "throws")):
                pending = ""
        depth += opened - closed
        while types and depth < types[-1][1]:
            types.pop()
    return records


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
            continue
        if line.startswith("/*", index):
            in_block = True
            index += 2
            continue
        if line.startswith("//", index):
            break
        result += line[index]
        index += 1
    return result, in_block


def api_record(kind: str, owner: str, name: str, declaration: str, source: str, line: int, javadoc_root: Path | None, member: str | None) -> dict[str, Any]:
    type_path = owner.replace(".", "/") + ".html"
    javadoc: dict[str, str] | None = None
    if javadoc_root is not None and (javadoc_root / type_path).is_file():
        javadoc = {"path": type_path}
        if member:
            javadoc["anchorHint"] = member
    return {"kind": kind, "owner": owner, "name": name, "declaration": declaration, "source": source, "line": line, "javadoc": javadoc}


def declared_supertypes(declaration: str, package: str, imports: dict[str, str]) -> list[str]:
    """从 Java 类型声明提取 extends/implements；仅保存可追溯的声明关系。"""
    clauses = re.search(r"\b(?:extends|implements)\b\s+(.+?)(?:\{|$)", declaration)
    if not clauses:
        return []
    names = re.split(r"\s*,\s*|\bimplements\b", clauses.group(1))
    result: list[str] = []
    for raw in names:
        cleaned = re.sub(r"<.*?>", "", raw).strip().split()[0] if raw.strip() else ""
        if not cleaned:
            continue
        if "." in cleaned:
            result.append(cleaned)
        elif cleaned in imports:
            result.append(imports[cleaned])
        elif package:
            result.append(f"{package}.{cleaned}")
        else:
            result.append(cleaned)
    return result


def artifact_entry(
    *, artifact: dict[str, Any], state_root: Path, homes: list[Path], repositories: list[str], include_api: bool
) -> dict[str, Any]:
    source_file = Path(str(artifact.get("file", "")))
    if not source_file.is_file():
        return {"id": "missing:" + clean_segment(str(artifact.get("file", ""))), "status": "missing", "file": str(source_file)}
    file_hash = sha256(source_file)
    coordinate = valid_coordinate(artifact)
    entry: dict[str, Any] = {
        "id": file_hash,
        "status": "ok",
        "coordinate": {"group": coordinate[0], "artifact": coordinate[1], "version": coordinate[2]} if coordinate else None,
        "classifier": str(artifact.get("classifier", "")),
        "extension": str(artifact.get("extension", "")),
        "fileName": source_file.name,
        "file": str(source_file),
        "sha256": file_hash,
        "classes": class_names(source_file),
        "sources": None,
        "javadoc": None,
        "api": [],
        "apiStatus": "not-requested" if not include_api else "unavailable",
    }
    if not coordinate or not include_api:
        return entry
    sources = copy_reference_archive(
        state_root=state_root, artifact_hash=file_hash, classifier="sources", coordinate=coordinate,
        repositories=repositories, homes=homes,
    )
    javadoc = copy_reference_archive(
        state_root=state_root, artifact_hash=file_hash, classifier="javadoc", coordinate=coordinate,
        repositories=repositories, homes=homes,
    )
    entry["sources"] = sources
    entry["javadoc"] = javadoc
    if sources:
        source_root = state_root / str(sources["extracted"])
        javadoc_root = state_root / str(javadoc["extracted"]) if javadoc else None
        entry["api"] = public_api(source_root, javadoc_root)
        entry["apiStatus"] = "sources" if javadoc else "sources-only"
    elif javadoc:
        entry["apiStatus"] = "javadoc-only"
    return entry


def build_index(arguments: argparse.Namespace) -> dict[str, Any]:
    project = normalize_project(arguments.project)
    state_root = arguments.state.resolve()
    raw = selected_configurations(run_gradle(project, state_root, arguments.gradle_user_home), arguments.configuration)
    homes = default_gradle_homes(arguments.gradle_user_home, state_root)
    artifact_cache: dict[str, dict[str, Any]] = {}
    modules: list[dict[str, Any]] = []
    for project_data in raw["projects"]:
        repositories = repositories_for(project_data)
        configurations: list[dict[str, Any]] = []
        for configuration in project_data.get("configurations", []):
            artifact_ids: list[str] = []
            for raw_artifact in configuration.get("artifacts", []):
                path = Path(str(raw_artifact.get("file", "")))
                artifact_id = sha256(path) if path.is_file() else "missing:" + clean_segment(str(path))
                if artifact_id not in artifact_cache:
                    artifact_cache[artifact_id] = artifact_entry(
                        artifact=raw_artifact, state_root=state_root, homes=homes, repositories=repositories,
                        include_api=not arguments.no_api,
                    )
                artifact_ids.append(artifact_id)
            configurations.append({
                "name": str(configuration.get("name", "")), "status": str(configuration.get("status", "unknown")),
                "artifacts": sorted(set(artifact_ids)), "dependencies": configuration.get("dependencies", []),
                "failures": configuration.get("failures", []),
            })
        modules.append({"path": str(project_data.get("path", "")), "name": str(project_data.get("name", "")), "configurations": configurations})
    return {
        "schemaVersion": INDEX_SCHEMA_VERSION,
        "toolVersion": TOOL_VERSION,
        "createdAtEpoch": int(time.time()),
        "project": {"path": str(project), "fingerprint": fingerprint(project)},
        "gradleVersion": raw.get("gradleVersion"),
        "modules": modules,
        "artifacts": artifact_cache,
    }


def load_index(arguments: argparse.Namespace) -> dict[str, Any]:
    path = index_path(arguments.state)
    try:
        with path.open("r", encoding="utf-8") as stream:
            value = json.load(stream)
    except FileNotFoundError as error:
        raise IndexError(f"尚无依赖索引；先运行 `dependency_index.py sync --project {arguments.project}`。") from error
    except json.JSONDecodeError as error:
        raise IndexError(f"依赖索引 JSON 无效：{path}：{error}") from error
    if not isinstance(value, dict) or value.get("schemaVersion") != INDEX_SCHEMA_VERSION:
        raise IndexError("依赖索引版本不兼容；请重新运行 sync。")
    return value


def stale_reason(index: dict[str, Any], project: Path) -> str | None:
    indexed = index.get("project", {}).get("fingerprint", {}).get("sha256")
    current = fingerprint(project).get("sha256")
    if indexed != current:
        return "构建输入已变化，请重新运行 sync"
    return None


def clamp(arguments: argparse.Namespace) -> tuple[int, int]:
    limit = min(max(1, int(arguments.limit)), MAX_LIMIT)
    offset = max(0, int(arguments.offset))
    return limit, offset


def paged(items: list[dict[str, Any]], arguments: argparse.Namespace) -> tuple[list[dict[str, Any]], int]:
    limit, offset = clamp(arguments)
    return items[offset:offset + limit], max(0, len(items) - offset - limit)


def coordinate_text(artifact: dict[str, Any]) -> str:
    coordinate = artifact.get("coordinate")
    if not coordinate:
        return artifact.get("fileName", "未知文件")
    return f"{coordinate['group']}:{coordinate['artifact']}:{coordinate['version']}"


def command_sync(arguments: argparse.Namespace) -> int:
    index = build_index(arguments)
    write_json(index_path(arguments.state), index)
    artifacts = list(index["artifacts"].values())
    configuration_count = sum(len(module["configurations"]) for module in index["modules"])
    class_count = sum(len(item.get("classes", [])) for item in artifacts)
    api_count = sum(len(item.get("api", [])) for item in artifacts)
    unavailable = sum(1 for item in artifacts if item.get("apiStatus") in {"unavailable", "javadoc-only"})
    failures = sum(1 for module in index["modules"] for config in module["configurations"] if config["status"] != "ok")
    print(f"已同步：模块 {len(index['modules'])}，配置 {configuration_count}，构件 {len(artifacts)}，类 {class_count}，公开签名 {api_count}，资料缺失 {unavailable}，失败 {failures}")
    return 0


def command_status(arguments: argparse.Namespace) -> int:
    index = load_index(arguments)
    project = normalize_project(arguments.project)
    reason = stale_reason(index, project)
    artifacts = list(index["artifacts"].values())
    data = {
        "status": "stale" if reason else "ready", "reason": reason,
        "modules": len(index["modules"]), "artifacts": len(artifacts),
        "classes": sum(len(item.get("classes", [])) for item in artifacts),
        "members": sum(len(item.get("api", [])) for item in artifacts),
        "withoutSources": sum(1 for item in artifacts if item.get("apiStatus") not in {"sources", "sources-only"}),
    }
    if arguments.json:
        print(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    else:
        suffix = f"；{reason}" if reason else ""
        print(f"索引 {data['status']}：模块 {data['modules']}，构件 {data['artifacts']}，类 {data['classes']}，公开签名 {data['members']}，无源码资料 {data['withoutSources']}{suffix}")
    return 1 if reason else 0


def require_fresh(arguments: argparse.Namespace, index: dict[str, Any]) -> None:
    reason = stale_reason(index, normalize_project(arguments.project))
    if reason:
        raise IndexError(f"索引已过期：{reason}。")


def command_modules(arguments: argparse.Namespace) -> int:
    index = load_index(arguments)
    require_fresh(arguments, index)
    rows = [{"module": item["path"], "configurations": len(item["configurations"])} for item in index["modules"]]
    selected, remaining = paged(rows, arguments)
    if arguments.json:
        print(json.dumps({"count": len(rows), "items": selected, "remaining": remaining}, ensure_ascii=False, separators=(",", ":")))
    else:
        print(f"模块 {len(rows)}")
        for row in selected:
            print(f"{row['module']} | 配置 {row['configurations']}")
        print_remaining(remaining, arguments)
    return 0


def command_dependencies(arguments: argparse.Namespace) -> int:
    index = load_index(arguments)
    require_fresh(arguments, index)
    module = next((item for item in index["modules"] if item["path"] == arguments.module), None)
    if not module:
        raise IndexError(f"未找到模块：{arguments.module}")
    rows: list[dict[str, Any]] = []
    for config in module["configurations"]:
        if arguments.configuration and config["name"] != arguments.configuration:
            continue
        for artifact_id in config["artifacts"]:
            artifact = index["artifacts"].get(artifact_id, {})
            rows.append({"module": module["path"], "configuration": config["name"], "dependency": coordinate_text(artifact), "kind": "artifact"})
        if arguments.transitive:
            for dependency in config.get("dependencies", []):
                rows.append({"module": module["path"], "configuration": config["name"], "dependency": dependency.get("selected") or dependency.get("requested"), "kind": dependency.get("kind")})
        for failure in config.get("failures", []):
            rows.append({"module": module["path"], "configuration": config["name"], "dependency": compact_text(str(failure), 160), "kind": "failed"})
    rows.sort(key=lambda row: (row["configuration"], row["dependency"], row["kind"]))
    selected, remaining = paged(rows, arguments)
    if arguments.json:
        print(json.dumps({"count": len(rows), "items": selected, "remaining": remaining}, ensure_ascii=False, separators=(",", ":")))
    else:
        print(f"{module['path']} 依赖 {len(rows)}")
        for row in selected:
            print(f"{row['configuration']} | {row['dependency']} | {row['kind']}")
        print_remaining(remaining, arguments)
    return 0


def matching_artifacts(index: dict[str, Any], query: str) -> Iterable[dict[str, Any]]:
    normalized = query.casefold()
    for artifact in index["artifacts"].values():
        yield artifact


def command_classes(arguments: argparse.Namespace) -> int:
    index = load_index(arguments)
    require_fresh(arguments, index)
    query = arguments.query.casefold()
    rows = []
    for artifact in index["artifacts"].values():
        for item in artifact.get("classes", []):
            if query in item["name"].casefold() or query in item["binaryName"].casefold():
                rows.append({"class": item["name"], "artifact": coordinate_text(artifact), "binaryName": item["binaryName"], "id": artifact["id"]})
    rows.sort(key=lambda item: (item["class"], item["artifact"]))
    selected, remaining = paged(rows, arguments)
    if arguments.json:
        print(json.dumps({"count": len(rows), "items": selected, "remaining": remaining}, ensure_ascii=False, separators=(",", ":")))
    else:
        print(f"类命中 {len(rows)}")
        for row in selected:
            print(f"{row['class']} | {row['artifact']}")
            if arguments.verbose:
                print(f"  二进制名 {row['binaryName']} | 构件 {row['id'][:12]}")
        print_remaining(remaining, arguments)
    return 0 if rows else 1


def type_ancestors(artifacts: dict[str, dict[str, Any]], requested: str) -> dict[str, int]:
    """返回请求类型和其已索引父类/接口，值为从请求类型起的距离。"""
    by_name: dict[str, set[str]] = {}
    parents: dict[str, list[str]] = {}
    for artifact in artifacts.values():
        for item in artifact.get("api", []):
            if item.get("kind") != "type":
                continue
            owner = str(item.get("owner", ""))
            if not owner:
                continue
            by_name.setdefault(owner.rsplit(".", 1)[-1], set()).add(owner)
            parents[owner] = [str(value) for value in item.get("supertypes", [])]
    seeds = {requested} if "." in requested else by_name.get(requested, set())
    found: dict[str, int] = {}
    pending = [(seed, 0) for seed in seeds]
    while pending:
        current, distance = pending.pop(0)
        if current in found and found[current] <= distance:
            continue
        found[current] = distance
        for parent in parents.get(current, []):
            candidates = {parent} if "." in parent else by_name.get(parent, set())
            pending.extend((candidate, distance + 1) for candidate in candidates)
    return found


def command_members(arguments: argparse.Namespace) -> int:
    index = load_index(arguments)
    require_fresh(arguments, index)
    query = arguments.query.casefold()
    visible_from = type_ancestors(index["artifacts"], arguments.type_name) if arguments.type_name else None
    if arguments.type_name and not visible_from:
        raise IndexError(f"索引中未找到类型：{arguments.type_name}")
    rows = []
    for artifact in index["artifacts"].values():
        for item in artifact.get("api", []):
            searchable = " ".join(str(item.get(key, "")) for key in ("owner", "name", "declaration"))
            if query in searchable.casefold() and (visible_from is None or item.get("owner") in visible_from):
                rows.append({"kind": item["kind"], "owner": item["owner"], "declaration": item["declaration"], "artifact": coordinate_text(artifact), "source": item["source"], "line": item["line"], "javadoc": item.get("javadoc"), "id": artifact["id"], "inheritanceDistance": visible_from.get(item["owner"], 0) if visible_from else 0})
    rows.sort(key=lambda item: (item["inheritanceDistance"], item["owner"], item["declaration"], item["artifact"]))
    selected, remaining = paged(rows, arguments)
    if arguments.json:
        print(json.dumps({"count": len(rows), "items": selected, "remaining": remaining}, ensure_ascii=False, separators=(",", ":")))
    else:
        scope = f"；{arguments.type_name} 可见成员" if arguments.type_name else ""
        print(f"公开 API 命中 {len(rows)}{scope}")
        for row in selected:
            inherited = "" if row["inheritanceDistance"] == 0 else f" | 继承 {row['inheritanceDistance']}"
            print(f"{row['kind']} | 声明于 {row['owner']}{inherited} | {row['declaration']} | {row['artifact']} | {row['source']}:{row['line']}")
            if arguments.verbose:
                javadoc = row.get("javadoc")
                print(f"  Javadoc {javadoc.get('path') if javadoc else '无'} | 构件 {row['id'][:12]}")
        print_remaining(remaining, arguments)
    return 0 if rows else 1


def command_show(arguments: argparse.Namespace) -> int:
    index = load_index(arguments)
    require_fresh(arguments, index)
    query = arguments.artifact.casefold()
    matches = [item for item in index["artifacts"].values() if query in coordinate_text(item).casefold() or item["id"].startswith(query) or query in str(item.get("fileName", "")).casefold()]
    matches.sort(key=coordinate_text)
    selected, remaining = paged(matches, arguments)
    if arguments.json:
        result = [{"artifact": coordinate_text(item), "classes": len(item.get("classes", [])), "members": len(item.get("api", [])), "apiStatus": item.get("apiStatus"), "sha256": item.get("sha256")} for item in selected]
        print(json.dumps({"count": len(matches), "items": result, "remaining": remaining}, ensure_ascii=False, separators=(",", ":")))
    else:
        print(f"构件命中 {len(matches)}")
        for item in selected:
            print(f"{coordinate_text(item)} | 类 {len(item.get('classes', []))} | 公开签名 {len(item.get('api', []))} | {item.get('apiStatus')}")
            if arguments.verbose:
                print(f"  SHA-256 {item.get('sha256')} | 文件 {item.get('file')}")
                if item.get("sources"):
                    print(f"  sources {item['sources']['source']}")
                if item.get("javadoc"):
                    print(f"  javadoc {item['javadoc']['source']}")
        print_remaining(remaining, arguments)
    return 0 if matches else 1


def print_remaining(remaining: int, arguments: argparse.Namespace) -> None:
    if remaining:
        next_offset = max(0, arguments.offset) + min(max(1, arguments.limit), MAX_LIMIT)
        print(f"其余 {remaining} 条；使用更精确关键词或 --offset {next_offset}")


def zoo_template() -> Path:
    return SCRIPT_ROOT / "zoo" / "dependency-index.ts.template"


def command_install_zoo(arguments: argparse.Namespace) -> int:
    project = normalize_project(arguments.project)
    source = zoo_template()
    if not source.is_file():
        raise IndexError(f"找不到 Zoo 工具模板：{source}")
    destination = project / ".roo" / "tools" / "pluginbase-dependency-index.ts"
    if destination.exists() and not arguments.force:
        print(f"保留已有 Zoo 工具：{destination}")
        return 0
    action = "覆盖" if destination.exists() else "创建"
    prefix = "预览" if arguments.dry_run else ""
    print(f"{prefix}{action} Zoo 工具：{destination}")
    if not arguments.dry_run:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    return 0


def main() -> int:
    arguments = parser().parse_args()
    try:
        if arguments.command == "sync":
            return command_sync(arguments)
        if arguments.command == "status":
            return command_status(arguments)
        if arguments.command == "modules":
            return command_modules(arguments)
        if arguments.command == "dependencies":
            return command_dependencies(arguments)
        if arguments.command == "classes":
            return command_classes(arguments)
        if arguments.command == "members":
            return command_members(arguments)
        if arguments.command == "show":
            return command_show(arguments)
        if arguments.command == "install-zoo":
            return command_install_zoo(arguments)
        raise IndexError(f"未知命令：{arguments.command}")
    except EvidenceError as error:
        print_error(str(error))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
