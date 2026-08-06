#!/usr/bin/env python3
"""验证 Zoo JS 自定义工具的安装、动态加载与运行时依赖。"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = PROJECT_ROOT / "tools" / "dependency_index.py"
INSTALLER_PATH = PROJECT_ROOT / "skill" / "minecraft-pluginbase-development" / "scripts" / "install_kit.py"
TEMPLATE_PATH = PROJECT_ROOT / "tools" / "zoo" / "dependency-index.js.template"
ZOD_VERSION = "3.25.76"


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"无法加载模块：{path}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def verify_dynamic_import(tool: Path, root: Path) -> None:
    script = root / "verify-import.mjs"
    script.write_text(
        "import { pathToFileURL } from 'url';\n"
        "const loaded = await import(pathToFileURL(process.argv[2]).href);\n"
        "const tool = Object.values(loaded).find((value) => value?.name === 'pluginbase_dependency_index');\n"
        "if (!tool || typeof tool.execute !== 'function' || !tool.parameters?._def) process.exit(2);\n"
        "console.log(JSON.stringify({ exports: Object.keys(loaded), name: tool.name }));\n",
        encoding="utf-8",
        newline="\n",
    )
    result = subprocess.run(
        ["node", str(script), str(tool)],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"Zoo JS 工具动态加载失败：{result.stderr or result.stdout}")
    payload = json.loads(result.stdout)
    if payload["name"] != "pluginbase_dependency_index":
        raise RuntimeError(f"Zoo JS 工具名称错误：{payload}")


def assert_runtime(tools: Path) -> None:
    package = tools / "node_modules" / "zod" / "package.json"
    if not package.is_file():
        raise RuntimeError(f"未安装 Zoo 工具运行时：{package}")
    version = json.loads(package.read_text(encoding="utf-8")).get("version")
    if version != ZOD_VERSION:
        raise RuntimeError(f"Zoo 工具运行时版本错误：{version}")
    if (tools / "package-lock.json").exists():
        raise RuntimeError("Zoo 工具安装不应生成 package-lock.json")


def main() -> int:
    index = load_module("dependency_index", INDEX_PATH)
    installer = load_module("install_kit", INSTALLER_PATH)
    if not TEMPLATE_PATH.is_file():
        raise RuntimeError(f"找不到 Zoo JS 模板：{TEMPLATE_PATH}")
    template_text = TEMPLATE_PATH.read_text(encoding="utf-8")
    if 'z.enum(["modules", "dependencies", "classes", "members", "show"])' not in template_text:
        raise RuntimeError("Zoo 工具查询操作不符合受限集合")
    if 'verbose: z.boolean()' not in template_text or 'if (verbose) args.push("--verbose")' not in template_text:
        raise RuntimeError("Zoo 工具未将 show 的详细构件路径请求转发给索引 CLI")
    if '"status"' in template_text or "先用 CLI sync" in template_text:
        raise RuntimeError("Zoo 工具不应提供 status 或引导日常 CLI 同步")
    with tempfile.TemporaryDirectory(prefix="pluginbase-agent-zoo-tool-") as temporary:
        root = Path(temporary)
        target = root / "agent-dev"
        template = target / "tools" / "zoo" / "dependency-index.js.template"
        template.parent.mkdir(parents=True)
        template.write_bytes(TEMPLATE_PATH.read_bytes())

        project = root / "installer-project"
        project.mkdir()
        created, skipped = installer.install_zoo_tool(project, target, dry_run=False)
        tool = project / ".roo" / "tools" / "pluginbase-dependency-index.js"
        if (created, skipped) != (1, 0) or tool.read_bytes() != TEMPLATE_PATH.read_bytes():
            raise RuntimeError("安装器没有创建预期的 Zoo JS 工具")
        assert_runtime(tool.parent)
        verify_dynamic_import(tool, root)

        dry_project = root / "dry-project"
        dry_project.mkdir()
        created, skipped = installer.install_zoo_tool(dry_project, target, dry_run=True)
        if (created, skipped) != (1, 0) or (dry_project / ".roo").exists():
            raise RuntimeError("安装器 dry-run 写入了 Zoo 工具目录")

        cli_project = root / "cli-project"
        cli_project.mkdir()
        command = [sys.executable, str(INDEX_PATH), "install-zoo", "--project", str(cli_project)]
        result = subprocess.run(command, cwd=PROJECT_ROOT, text=True, capture_output=True, check=False)
        if result.returncode:
            raise RuntimeError(f"CLI Zoo 安装失败：{result.stderr or result.stdout}")
        cli_tool = cli_project / ".roo" / "tools" / "pluginbase-dependency-index.js"
        if cli_tool.read_bytes() != TEMPLATE_PATH.read_bytes():
            raise RuntimeError("CLI 没有创建预期的 Zoo JS 工具")
        assert_runtime(cli_tool.parent)
        cli_tool.write_text("module.exports = { name: 'custom' }\n", encoding="utf-8")
        forced = subprocess.run(command + ["--force"], cwd=PROJECT_ROOT, text=True, capture_output=True, check=False)
        if forced.returncode or cli_tool.read_bytes() != TEMPLATE_PATH.read_bytes():
            raise RuntimeError(f"CLI --force 未覆盖 Zoo JS 工具：{forced.stderr or forced.stdout}")

        generated_package = (tool.parent / "package.json").exists()
    print(f"通过：Zoo JS 工具可经 Node 动态加载，受限查询包含 show 的详细归档路径转发且不含 status 或日常 CLI sync 引导；两个安装入口均安装 zod@{ZOD_VERSION}，未生成锁文件，npm 生成 package.json：{generated_package}。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
