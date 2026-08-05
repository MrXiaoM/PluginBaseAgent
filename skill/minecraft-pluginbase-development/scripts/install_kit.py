#!/usr/bin/env python3
"""将 Skill 资源中的 agent-dev 开发包初始化到目标 Gradle 插件项目。"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath
import tempfile


SCRIPT_ROOT = Path(__file__).resolve().parent
KIT_ARCHIVE = SCRIPT_ROOT.parent / "assets" / "agent-dev-kit.zip"
ENVIRONMENT_PATH = Path("state/environment.json")
GRADLE_HOME_START = "__PLUGIN_BASE_AGENT_GRADLE_HOME_START__"
GRADLE_HOME_END = "__PLUGIN_BASE_AGENT_GRADLE_HOME_END__"
GRADLE_HOME_INIT_SCRIPT = (
    "gradle.rootProject {\n"
    "    println(\"__PLUGIN_BASE_AGENT_GRADLE_HOME_START__\")\n"
    "    println(gradle.gradleUserHomeDir.absolutePath)\n"
    "    println(\"__PLUGIN_BASE_AGENT_GRADLE_HOME_END__\")\n"
    "}\n"
)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="一次完成 agent-dev 释放、本地 Gradle 环境配置和首次依赖索引同步。"
    )
    result.add_argument("--project", type=Path, required=True, help="目标 Gradle 插件项目根目录")
    result.add_argument("--gradle-user-home", help="仅在 Gradle Wrapper 无法启动时的显式诊断覆盖；正常安装由 Gradle 自身报告目录")
    result.add_argument("--force", action="store_true", help="覆盖 agent-dev 中已有的受管文件")
    result.add_argument("--skip-index", action="store_true", help="仅释放并配置环境，不执行首次依赖索引同步")
    result.add_argument("--dry-run", action="store_true", help="只显示将执行的动作，不写入或同步")
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


def load_environment(path: Path) -> tuple[list[str] | None, bool]:
    """返回已配置目录及是否为旧安装器生成的空模板。"""
    if not path.is_file():
        return None, False
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"已有本地环境配置无效：{path}：{error}") from error
    homes = value.get("gradleUserHomes") if isinstance(value, dict) else None
    if homes == [] and value.get("schemaVersion") == 1:
        return None, True
    if not isinstance(homes, list) or not homes or not all(isinstance(item, str) and item.strip() for item in homes):
        raise RuntimeError(f"已有本地环境配置未填写有效 gradleUserHomes：{path}；请修复该文件后重试。")
    return [item.strip() for item in homes], False


def gradle_command(project: Path, arguments: list[str]) -> list[str]:
    """跨平台启动目标项目 Wrapper；Windows 优先原生 bat，再回退 Git Bash。"""
    batch = project / "gradlew.bat"
    shell = project / "gradlew"
    if sys.platform == "win32" and batch.is_file():
        return [str(batch), *arguments]
    if shell.is_file():
        if sys.platform == "win32":
            bash = shutil.which("bash")
            if not bash:
                raise RuntimeError("目标项目只有 gradlew，但当前 Windows 环境找不到 bash；请使用带 gradlew.bat 的模板项目。")
            return [bash, str(shell), *arguments]
        return [str(shell), *arguments]
    if batch.is_file():
        return [str(batch), *arguments]
    raise RuntimeError(f"找不到目标项目 Gradle Wrapper：{shell} 或 {batch}")


def gradle_user_home(project: Path) -> str:
    """由目标项目的 Gradle 自身报告其实际 Gradle 用户目录。"""
    with tempfile.TemporaryDirectory(prefix="pluginbase-agent-gradle-home-") as temporary:
        init_script = Path(temporary) / "gradle-home.init.gradle"
        init_script.write_text(GRADLE_HOME_INIT_SCRIPT, encoding="utf-8", newline="\n")
        command = gradle_command(project, ["--no-daemon", "--console=plain", "--init-script", str(init_script), "help"])
        try:
            result = subprocess.run(
                command, cwd=project, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=120, check=False,
            )
        except OSError as error:
            raise RuntimeError(f"无法启动目标项目 Gradle Wrapper：{error}") from error
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("Gradle Wrapper 在获取用户目录时超过 120 秒。") from error
    output = result.stdout or ""
    start = output.find(GRADLE_HOME_START)
    end = output.find(GRADLE_HOME_END, start + len(GRADLE_HOME_START))
    if start < 0 or end < 0:
        detail = " ".join(output.split())[:600]
        raise RuntimeError(f"Gradle 未报告 gradleUserHomeDir（退出码 {result.returncode}）：{detail}")
    home = output[start + len(GRADLE_HOME_START):end].strip()
    if not home:
        raise RuntimeError("Gradle 报告的 gradleUserHomeDir 为空。")
    return home


def resolve_gradle_homes(project: Path, environment_path: Path, explicit: str | None) -> tuple[list[str], str, bool]:
    existing, empty_template = load_environment(environment_path)
    if existing is not None:
        return existing, "保留已有 environment.json", False
    try:
        return [gradle_user_home(project)], "目标项目 Gradle Wrapper", empty_template
    except RuntimeError:
        if explicit and explicit.strip():
            return [explicit.strip()], "--gradle-user-home（Wrapper 诊断失败后的显式覆盖）", empty_template
        raise


def write_environment(path: Path, homes: list[str], source: str, replace_empty_template: bool, dry_run: bool) -> tuple[int, int]:
    if path.exists() and not replace_empty_template:
        print(f"保留本地 Gradle 环境配置：{path}")
        return 0, 1
    action = "填充旧环境模板" if replace_empty_template else "创建本地 Gradle 环境配置"
    print(f"{action}（来源：{source}）：{path}")
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"schemaVersion": 1, "gradleUserHomes": homes}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    return 1, 0


def release_kit(project: Path, force: bool, dry_run: bool) -> tuple[Path, int, int]:
    if not KIT_ARCHIVE.is_file():
        raise RuntimeError(f"Skill 资源不完整：找不到 {KIT_ARCHIVE}")
    target = project / "agent-dev"
    installed = 0
    skipped = 0
    try:
        with zipfile.ZipFile(KIT_ARCHIVE) as archive:
            for member in archive.infolist():
                if member.is_dir() or member.filename == "manifest.json":
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
    return target, installed, skipped


def installed_from_roo_skill() -> bool:
    """仅从项目 .roo/skills 入口启动时自动部署 Zoo/Roo 工具。"""
    return SCRIPT_ROOT.parent.parent.parent.name == ".roo"


ZOO_ZOD_VERSION = "3.25.76"


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
        raise RuntimeError("Zoo 工具需要 npm 安装 zod，但当前环境找不到 npm。")
    command = [npm, "install", "--no-save", "--no-package-lock", f"zod@{ZOO_ZOD_VERSION}"]
    print(f"{'预览安装' if dry_run else '安装'} Zoo 工具运行时依赖：{' '.join(command)}")
    if dry_run:
        return
    result = subprocess.run(command, cwd=tools, check=False)
    if result.returncode or not package.is_file():
        raise RuntimeError("Zoo 工具运行时依赖 zod 安装失败；请检查 npm 网络/镜像后重试安装脚本。")


def install_zoo_tool(project: Path, target: Path, dry_run: bool) -> tuple[int, int]:
    """部署无 esbuild 裸包导入的 Zoo 索引工具，并自动准备本地 Zod 运行时。"""
    source = target / "tools" / "zoo" / "dependency-index.js.template"
    tools = project / ".roo" / "tools"
    destination = tools / "pluginbase-dependency-index.js"
    if not source.is_file():
        raise RuntimeError(f"资料包缺少 Zoo 工具模板：{source}")
    if destination.exists():
        print(f"保留已有 Zoo 工具：{destination}")
        install_zoo_runtime(tools, dry_run)
        return 0, 1
    action = "预览创建" if dry_run else "创建"
    print(f"{action} Zoo 工具：{destination}")
    if not dry_run:
        tools.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    install_zoo_runtime(tools, dry_run)
    return 1, 0


def sync_index(project: Path, target: Path, dry_run: bool) -> None:
    command = [sys.executable, str(target / "tools" / "dependency_index.py"), "sync", "--project", str(project)]
    print("同步首次 Gradle 依赖索引：" + " ".join(command))
    if dry_run:
        return
    result = subprocess.run(command, cwd=project, check=False)
    if result.returncode:
        raise RuntimeError(
            "开发包和本地环境已创建，但首次依赖索引同步失败。"
            "请修复上方 Gradle/依赖错误后重试同一安装命令，或单独运行 agent-dev/tools/dependency_index.py sync --project ."
        )


def install(arguments: argparse.Namespace) -> tuple[int, int]:
    project = arguments.project.resolve()
    target, installed, skipped = release_kit(project, arguments.force, arguments.dry_run)
    environment_path = safe_destination(target, ENVIRONMENT_PATH.as_posix())
    homes, source, replace_empty_template = resolve_gradle_homes(
        project, environment_path, arguments.gradle_user_home
    )
    environment_installed, environment_skipped = write_environment(
        environment_path, homes, source, replace_empty_template, arguments.dry_run
    )
    zoo_installed = 0
    zoo_skipped = 0
    if installed_from_roo_skill():
        zoo_installed, zoo_skipped = install_zoo_tool(project, target, arguments.dry_run)
    if arguments.skip_index:
        print("跳过首次依赖索引同步：--skip-index")
    else:
        sync_index(project, target, arguments.dry_run)
    return installed + environment_installed + zoo_installed, skipped + environment_skipped + zoo_skipped


def main() -> int:
    arguments = parser().parse_args()
    project = arguments.project.resolve()
    if not project.is_dir():
        print(f"错误：目标插件项目不存在或不是目录：{project}", file=sys.stderr)
        return 2
    try:
        installed, skipped = install(arguments)
    except RuntimeError as error:
        print(f"错误：{error}", file=sys.stderr)
        return 2
    result = "预览完成" if arguments.dry_run else "初始化完成"
    print(f"{result}：处理 {installed} 个文件，跳过 {skipped} 个已有文件。")
    if not arguments.dry_run:
        print(f"项目内开发包：{project / 'agent-dev'}")
        print("已完成本地 Gradle 环境配置与首次依赖索引同步；agent-dev/state/ 必须保持忽略，不能打进插件 JAR。")
        if installed_from_roo_skill():
            print("已从 .roo/skills 入口自动安装 Zoo/Roo 依赖索引工具；请在 Zoo Code Experimental 设置启用 Custom Tools。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
