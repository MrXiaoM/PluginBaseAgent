#!/usr/bin/env python3
"""验证 dependency_index 的分批类名写入与外部内容 FTS。"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import sqlite3
import stat
import struct
import tempfile
import zipfile
import os
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = PROJECT_ROOT / "tools" / "dependency_index.py"
CLASS_COUNT = 4_501
API_COUNT = 4_501


def load_module():
    specification = importlib.util.spec_from_file_location("dependency_index", MODULE_PATH)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"无法加载工具：{MODULE_PATH}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def bytecode_fixture(owner: str = "example/bytecode/Sample") -> bytes:
    def utf8(value: str) -> bytes:
        encoded = value.encode("utf-8")
        return b"\x01" + struct.pack(">H", len(encoded)) + encoded

    pool = [
        utf8(owner), b"\x07\x00\x01",
        utf8("java/lang/Object"), b"\x07\x00\x03",
        utf8("java/lang/Runnable"), b"\x07\x00\x05",
        utf8("value"), utf8("I"),
        utf8("<init>"), utf8("()V"),
        utf8("run"), utf8("echo"), utf8("(Ljava/lang/String;)Ljava/lang/String;"),
    ]
    field = struct.pack(">HHHH", 0x0019, 7, 8, 0)
    constructor = struct.pack(">HHHH", 0x0001, 9, 10, 0)
    run = struct.pack(">HHHH", 0x0001, 11, 10, 0)
    echo = struct.pack(">HHHH", 0x0009, 12, 13, 0)
    return b"\xca\xfe\xba\xbe" + struct.pack(">HHH", 0, 52, len(pool) + 1) + b"".join(pool) + struct.pack(">HHHHH", 0x0001, 2, 4, 1, 6) + struct.pack(">H", 1) + field + struct.pack(">H", 3) + constructor + run + echo + struct.pack(">H", 0)


def verify_gradle_output_stream(tool, root: Path) -> None:
    project = root / "gradle-project"
    project.mkdir()
    wrapper = project / "gradlew"
    wrapper.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' '[PluginBase Agent] 解析资料构件 1：example:library:1.0:sources'\n"
        "sleep 0.05\n"
        "case \" $* \" in *' -PpluginBaseAgentIncludeApi=false '*) printf '%s\\n' '[PluginBase Agent] 已跳过资料变体' ;; esac\n"
        f"printf '%s\\n' '{tool.MARKER_START}'\n"
        "printf '%s\\n' '{\"schemaVersion\":2,\"projects\":[]}'\n"
        f"printf '%s\\n' '{tool.MARKER_END}'\n",
        encoding="utf-8",
        newline="\n",
    )
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        parsed = tool.run_gradle(project, root, str(root), include_api=False)
    text = output.getvalue()
    assert parsed == {"schemaVersion": 2, "projects": []}, parsed
    assert "[Gradle] [PluginBase Agent] 解析资料构件 1：example:library:1.0:sources" in text, text
    assert "[Gradle] [PluginBase Agent] 已跳过资料变体" in text, text
    assert tool.MARKER_START not in text and '"projects"' not in text, text


def verify_full_rebuild(tool, root: Path) -> None:
    """同步从空临时库重建，旧索引中的已移除构件不能残留。"""
    project = root / "rebuild-project"
    state = project / "agent-dev" / "state"
    database = state / "indexes" / "dependency-index.sqlite3"
    database.parent.mkdir(parents=True)
    stale = sqlite3.connect(database)
    try:
        stale.execute("CREATE TABLE stale_artifacts (name TEXT)")
        stale.execute("INSERT INTO stale_artifacts VALUES ('removed-dependency')")
        stale.commit()
    finally:
        stale.close()
    original = tool.run_gradle
    tool.run_gradle = lambda *_: {"projects": [{"path": ":", "name": "rebuild", "configurations": [{"name": "runtimeClasspath", "status": "ok", "artifacts": [], "dependencies": [], "failures": []}]}], "gradleVersion": "fixture"}
    try:
        output = io.StringIO()
        arguments = SimpleNamespace(project=project, state=state, gradle_user_home=None, no_api=False, configuration=[])
        with contextlib.redirect_stdout(output):
            tool.build_database(arguments, database)
    finally:
        tool.run_gradle = original
    rebuilt = sqlite3.connect(database)
    try:
        tables = {row[0] for row in rebuilt.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        artifacts = rebuilt.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
    finally:
        rebuilt.close()
    assert "stale_artifacts" not in tables and artifacts == 0, tables
    assert "清理旧 SQLite 索引" in output.getvalue(), output.getvalue()


def main() -> int:
    tool = load_module()
    with tempfile.TemporaryDirectory(prefix="pluginbase-agent-class-batch-") as temporary:
        root = Path(temporary)
        archive = root / "fixture.jar"
        relocated_archive = root / "relocated.jar"
        source_archive = root / "sources.jar"
        javadoc_archive = root / "javadoc.jar"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as output:
            for index in range(CLASS_COUNT):
                output.writestr(f"example/generated/Class{index:04d}.class", b"\xca\xfe\xba\xbe")
            output.writestr("example/generated/Outer$Inner.class", b"\xca\xfe\xba\xbe")
            output.writestr("META-INF/versions/21/example/generated/Skipped.class", b"\xca\xfe\xba\xbe")
            output.writestr("module-info.class", b"\xca\xfe\xba\xbe")
            output.writestr("example/generated/12.class", b"\xca\xfe\xba\xbe")
            output.writestr("example/bytecode/Sample.class", bytecode_fixture())
        with zipfile.ZipFile(relocated_archive, "w", compression=zipfile.ZIP_STORED) as output:
            output.writestr("shadow/relocated/Sample.class", bytecode_fixture("shadow/relocated/Sample"))
        with zipfile.ZipFile(source_archive, "w", compression=zipfile.ZIP_STORED) as output:
            output.writestr("original/api/Sample.java", "package original.api;\npublic class Sample {\n  public String echo(String value) { return value; }\n  public String echo(Integer value) { return String.valueOf(value); }\n  public int onlyInSources(int input) { return input; }\n}\n")
        with zipfile.ZipFile(javadoc_archive, "w", compression=zipfile.ZIP_STORED) as output:
            output.writestr("original/api/Sample.html", '<div class="block">Relocated type summary</div><section id="echo(java.lang.String)"><div class="block">Echo summary</div></section><section id="echo(java.lang.Integer)"><div class="block">Wrong overload summary</div></section><section id="onlyInSources(int)"><div class="block">Must not become a runtime member</div></section>')
        gradle_archive = tool.reference_archive({"sources": {"file": str(archive)}, "version": "test"}, "sources", tool.ArchiveHashCache())
        verify_gradle_output_stream(tool, root)
        verify_full_rebuild(tool, root)
        database = root / "index.sqlite3"
        connection = sqlite3.connect(database)
        try:
            tool.create_schema(connection)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                tool.insert_class_names(connection, archive, "fixture", "[验证] ")
            api_records = (
                {
                    "kind": "type" if index == 0 else "method",
                    "owner": "example.generated.ApiOwner",
                    "name": "ApiOwner" if index == 0 else f"method{index:04d}",
                    "declaration": f"public void method{index:04d}()",
                    "source": "example/generated/ApiOwner.java",
                    "line": index + 1,
                    "javadoc": None,
                    "documentation": None,
                    "supertypes": ["example.generated.ApiParent"] if index == 0 else [],
                }
                for index in range(API_COUNT)
            )
            tool.insert_public_api(connection, api_records, "fixture")
            tool.insert_public_api(connection, tool.iter_bytecode_api(archive, "[验证] "), "bytecode")
            relocated_records = list(tool.iter_runtime_api(relocated_archive, source_archive, javadoc_archive, "[验证重定位] "))
            tool.insert_public_api(connection, relocated_records, "relocated")
            connection.execute("INSERT INTO class_search(class_search) VALUES ('rebuild')")
            connection.execute("INSERT INTO api_search(api_search) VALUES ('rebuild')")
            total = connection.execute("SELECT COUNT(*) FROM classes").fetchone()[0]
            indexed = connection.execute("SELECT COUNT(*) FROM class_search WHERE class_search MATCH ?", ('"Class4321"*',)).fetchone()[0]
            api_total = connection.execute("SELECT COUNT(*) FROM api").fetchone()[0]
            api_indexed = connection.execute("SELECT COUNT(*) FROM api_search WHERE api_search MATCH ?", ('"method4321"*',)).fetchone()[0]
            edge = connection.execute("SELECT child_owner, parent_owner FROM type_edges").fetchone()
            inner = connection.execute("SELECT name, binary_name FROM classes WHERE binary_name = ?", ("example.generated.Outer$Inner",)).fetchone()
            bytecode_members = {row[0] for row in connection.execute("SELECT name FROM api WHERE artifact_id = ?", ("bytecode",))}
            bytecode_edges = {row[0] for row in connection.execute("SELECT parent_owner FROM type_edges WHERE child_owner = ?", ("example.bytecode.Sample",))}
            relocated_members = {row[0]: (row[1], row[2]) for row in connection.execute("SELECT name, owner, documentation FROM api WHERE artifact_id = ?", ("relocated",))}
        finally:
            connection.close()
    javadoc_summaries = tool.javadoc_member_summaries(
        '<section id="alpha()"><div class="block">Alpha summary</div></section><section id="beta(java.lang.String)"><div class="block">Beta summary</div></section>',
        {"alpha", "beta", "missing"},
    )
    progress = output.getvalue()
    assert gradle_archive is not None, gradle_archive
    assert gradle_archive[0] == archive.resolve(), gradle_archive
    assert gradle_archive[1]["origin"] == "gradle", gradle_archive
    assert total == CLASS_COUNT + 2, total
    assert indexed == 1, indexed
    assert api_total == API_COUNT + 10, api_total
    assert api_indexed == 1, api_indexed
    assert edge == ("example.generated.ApiOwner", "example.generated.ApiParent"), edge
    assert inner == ("example.generated.Outer.Inner", "example.generated.Outer$Inner"), inner
    assert bytecode_members == {"Sample", "value", "run", "echo"}, bytecode_members
    assert bytecode_edges == {"java.lang.Object", "java.lang.Runnable"}, bytecode_edges
    assert javadoc_summaries == {"alpha": "Alpha summary", "beta": "Beta summary"}, javadoc_summaries
    assert set(relocated_members) == {"Sample", "value", "run", "echo"}, relocated_members
    assert all(owner == "shadow.relocated.Sample" for owner, _ in relocated_members.values()), relocated_members
    assert relocated_members["echo"][1] == "Echo summary", relocated_members
    relocated_type = next(record for record in relocated_records if record["kind"] == "type")
    relocated_echo = next(record for record in relocated_records if record["name"] == "echo")
    assert relocated_type["source"] == "original/api/Sample.java" and relocated_type["line"] == 2, relocated_type
    assert relocated_echo["source"] == "original/api/Sample.java" and relocated_echo["line"] == 3, relocated_echo
    for expected in ("类名 2000/4503", "类名 4000/4503", "类名 4503/4503"):
        assert expected in progress, progress
    print(f"通过：Gradle 实时输出、旧 SQLite 索引全量删除重建与资料路径、Javadoc 单页摘要映射、分批写入 {CLASS_COUNT + 2} 个类与 {API_COUNT} 条源码 API、5 条字节码 API；重定位运行类保留字节码签名且唯一关联 echo 文档，两个 FTS 各命中 1 条，类名进度覆盖 3 个批次。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
