#!/usr/bin/env python3
"""离线验证依赖源码检查工具的 sources JAR 读取与歧义拒绝。"""

from __future__ import annotations

import importlib.util
import tempfile
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TOOL_PATH = PROJECT_ROOT / "tools" / "inspect_dependency.py"


def load_module():
    specification = importlib.util.spec_from_file_location("inspect_dependency", TOOL_PATH)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"无法加载工具：{TOOL_PATH}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def main() -> int:
    tool = load_module()
    with tempfile.TemporaryDirectory(prefix="pluginbase-agent-inspect-dependency-") as temporary:
        root = Path(temporary)
        sources = root / "sources.jar"
        ambiguous = root / "ambiguous.jar"
        with zipfile.ZipFile(sources, "w") as archive:
            archive.writestr("example/api/Sample.java", "package example.api;\npublic class Sample {}\n")
            archive.writestr("example/api/Outer.java", "package example.api;\npublic class Outer { class Inner {} }\n")
        with zipfile.ZipFile(ambiguous, "w") as archive:
            archive.writestr("first/Sample.java", "package first;\npublic class Sample {}\n")
            archive.writestr("second/Sample.java", "package second;\npublic class Sample {}\n")
        entry, text = tool.read_java(sources, "example.api.Sample")
        inner_entry, inner_text = tool.read_java(sources, "example.api.Outer$Inner")
        assert entry == "example/api/Sample.java" and "class Sample" in text, (entry, text)
        assert inner_entry == "example/api/Outer.java" and "class Inner" in inner_text, (inner_entry, inner_text)
        try:
            tool.read_java(ambiguous, "missing.api.Sample")
        except RuntimeError as error:
            assert "多个同名候选" in str(error), error
        else:
            raise RuntimeError("同简单类名多候选时未停止")
    print("通过：依赖源码检查工具可直接读取精确 sources 条目、将内部类映射到外部类源码，并拒绝多个同名候选。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
