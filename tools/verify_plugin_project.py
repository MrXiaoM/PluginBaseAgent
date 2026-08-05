#!/usr/bin/env python3
"""对 PluginBase 插件项目执行不依赖第三方库的静态结构检查。"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Finding:
    level: str
    code: str
    message: str
    path: Path | None = None

    def display(self, root: Path) -> str:
        location = ""
        if self.path:
            try:
                location = f" [{self.path.relative_to(root)}]"
            except ValueError:
                location = f" [{self.path}]"
        return f"{self.level} {self.code}{location}：{self.message}"


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="检查 PluginBase 插件项目的构建、资源和源码约定。")
    root.add_argument("--project", type=Path, default=Path.cwd(), help="目标插件项目根目录")
    root.add_argument("--jar", type=Path, help="额外检查指定 Shadow JAR 内容")
    root.add_argument("--json", action="store_true", help="以 JSON 输出检查结果")
    return root


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def java_sources(root: Path) -> Iterable[Path]:
    source_root = root / "src" / "main" / "java"
    return source_root.rglob("*.java") if source_root.is_dir() else []


def locate_shadow_jar(root: Path) -> Path | None:
    candidates = [
        path for path in (root / "build" / "libs").glob("*.jar")
        if "sources" not in path.name and "javadoc" not in path.name
    ] if (root / "build" / "libs").is_dir() else []
    return max(candidates, key=lambda item: item.stat().st_mtime) if candidates else None


def validate_yaml_value(text: str, key: str) -> str | None:
    match = re.search(rf"^{re.escape(key)}:\s*(.+?)\s*$", text, flags=re.MULTILINE)
    return match.group(1).strip(" '\"") if match else None


def validate_project(root: Path, jar_override: Path | None) -> list[Finding]:
    findings: list[Finding] = []
    gradle = root / "build.gradle.kts"
    plugin_yml = root / "src" / "main" / "resources" / "plugin.yml"
    if not gradle.is_file():
        findings.append(Finding("错误", "构建文件缺失", "找不到 build.gradle.kts。", gradle))
        return findings
    build = read_text(gradle)
    if "LibraryHelper" not in build:
        findings.append(Finding("警告", "未检测到 LibraryHelper", "项目可能不遵循模板基线；人工核对 PluginBase 依赖管理。", gradle))
    if "top.mrxiaom.pluginbase" not in build:
        findings.append(Finding("错误", "PluginBase 重定位缺失", "未找到 top.mrxiaom.pluginbase；必须作为实现依赖重定位。", gradle))
    if not re.search(r"val\s+shadowGroup\s*=\s*\"[^\"]+\"", build):
        findings.append(Finding("错误", "shadowGroup 缺失", "未检测到非空 shadowGroup 定义。", gradle))
    if "relocate(" not in build:
        findings.append(Finding("错误", "Shadow 重定位缺失", "未检测到 relocate(...) 配置。", gradle))
    elif not re.search(r"relocate\s*\(\s*original\s*,", build) and not re.search(r"relocate\s*\(\s*\"top\.mrxiaom\.pluginbase", build):
        findings.append(Finding("错误", "PluginBase 重定位缺失", "未检测到对 top.mrxiaom.pluginbase 的可识别重定位规则。", gradle))
    if "append(\"META-INF/PluginBaseHolders\")" not in build:
        findings.append(Finding("错误", "Holder 索引合并缺失", "shadowJar 必须 append(\"META-INF/PluginBaseHolders\")。", gradle))
    if re.search(r"(?:org\.spigotmc:spigot-api|io\.papermc\.paper:paper-api)", build) and not re.search(r"compileOnly\s*\(\s*\"(?:org\.spigotmc:spigot-api|io\.papermc\.paper:paper-api)", build):
        findings.append(Finding("错误", "服务器 API 依赖范围", "Spigot/Paper API 应使用 compileOnly。", gradle))
    if "top.mrxiaom.pluginbase" in build and "implementation" not in build:
        findings.append(Finding("警告", "PluginBase implementation 未确认", "未检测到 implementation；人工确认模块是否会进入 Shadow JAR。", gradle))
    if not plugin_yml.is_file():
        findings.append(Finding("错误", "plugin.yml 缺失", "找不到 src/main/resources/plugin.yml。", plugin_yml))
    else:
        yaml = read_text(plugin_yml)
        main_class = validate_yaml_value(yaml, "main")
        if not main_class:
            findings.append(Finding("错误", "主类声明缺失", "plugin.yml 缺少 main。", plugin_yml))
        else:
            class_path = root / "src" / "main" / "java" / Path(*main_class.split(".")).with_suffix(".java")
            if not class_path.is_file():
                findings.append(Finding("错误", "主类源码缺失", f"plugin.yml 主类 `{main_class}` 对应源码不存在。", plugin_yml))
        if not validate_yaml_value(yaml, "api-version"):
            findings.append(Finding("警告", "api-version 缺失", "plugin.yml 未声明 api-version。", plugin_yml))
        if "folia-supported:" not in yaml:
            findings.append(Finding("警告", "Folia 声明缺失", "模板基线含 folia-supported；人工确认项目策略。", plugin_yml))
    source_texts: dict[Path, str] = {path: read_text(path) for path in java_sources(root)}
    main_sources = [path for path, text in source_texts.items() if "extends BukkitPlugin" in text]
    if not main_sources:
        findings.append(Finding("错误", "BukkitPlugin 主类缺失", "未找到继承 BukkitPlugin 的源码。", root / "src" / "main" / "java"))
    for path, text in source_texts.items():
        for method in ("onLoad", "onEnable", "onDisable"):
            if re.search(rf"(?:public|protected)\s+void\s+{method}\s*\(", text):
                findings.append(Finding("错误", "禁止覆写 Bukkit 生命周期", f"不得覆写 {method}()；请使用 BukkitPlugin 扩展点。", path))
        if "@AutoRegister" in text and "extends Abstract" not in text:
            findings.append(Finding("警告", "自动注册基类未确认", "@AutoRegister 类未检测到 Abstract* Holder/Module 基类。", path))
        if re.search(r"\b(?:Enum|Material)\.valueOf\s*\(", text):
            findings.append(Finding("错误", "不兼容的枚举解析", "使用 Util.valueOr/valueOrNull 或 Util.parse*，不要使用 Enum.valueOf/Material.valueOf。", path))
    paper_module = bool(re.search(r"\bpaper\b", build))
    paper_factory = any("PaperFactory" in text for text in source_texts.values())
    if paper_module and not paper_factory:
        findings.append(Finding("警告", "paper 模块接入未确认", "检测到 paper 模块但未找到 PaperFactory；若要双端物品/库存兼容，应覆写两个工厂方法。", gradle))
    if paper_factory and not paper_module:
        findings.append(Finding("错误", "paper 模块缺失", "源码使用 PaperFactory，但构建脚本未检测到 paper 模块。", gradle))
    jar = jar_override or locate_shadow_jar(root)
    if jar:
        findings.extend(validate_jar(root, jar))
    else:
        findings.append(Finding("警告", "未找到 Shadow JAR", "未检查归档内容；先执行项目构建或使用 --jar。"))
    return findings


def validate_jar(root: Path, jar: Path) -> list[Finding]:
    findings: list[Finding] = []
    if not jar.is_file():
        return [Finding("错误", "JAR 不存在", "指定的 --jar 文件不存在。", jar)]
    try:
        with zipfile.ZipFile(jar) as archive:
            names = set(archive.namelist())
    except zipfile.BadZipFile:
        return [Finding("错误", "JAR 无效", "指定文件不是有效 ZIP/JAR。", jar)]
    if "plugin.yml" not in names:
        findings.append(Finding("错误", "JAR 缺少 plugin.yml", "plugin.yml 必须位于 JAR 根目录。", jar))
    if "META-INF/PluginBaseHolders" not in names:
        findings.append(Finding("错误", "JAR 缺少 Holder 索引", "最终 JAR 缺少 META-INF/PluginBaseHolders。", jar))
    if any(name.startswith("top/mrxiaom/pluginbase/") for name in names):
        findings.append(Finding("错误", "原始 PluginBase 包泄漏", "JAR 含未重定位的 top/mrxiaom/pluginbase/ 路径。", jar))
    if any(name.startswith(prefix) for name in names for prefix in ("org/bukkit/", "io/papermc/paper/")):
        findings.append(Finding("错误", "服务器 API 被打包", "JAR 包含 Spigot/Paper API 类，服务器 API 应为 compileOnly。", jar))
    if any(name.startswith("agent-dev/") for name in names):
        findings.append(Finding("错误", "开发资料被打包", "JAR 包含 agent-dev/，开发资料不得进入插件产物。", jar))
    return findings


def main() -> int:
    arguments = parser().parse_args()
    root = arguments.project.resolve()
    findings = validate_project(root, arguments.jar.resolve() if arguments.jar else None)
    if arguments.json:
        print(json.dumps([{
            "level": item.level, "code": item.code, "message": item.message,
            "path": str(item.path) if item.path else None,
        } for item in findings], ensure_ascii=False, indent=2))
    else:
        print(f"检查项目：{root}")
        for finding in findings:
            print(finding.display(root))
        if not findings:
            print("通过：未发现本工具可静态判定的问题。")
    errors = sum(item.level == "错误" for item in findings)
    warnings = sum(item.level == "警告" for item in findings)
    print(f"结果：错误 {errors}，警告 {warnings}")
    return 2 if errors else (1 if warnings else 0)


if __name__ == "__main__":
    raise SystemExit(main())
