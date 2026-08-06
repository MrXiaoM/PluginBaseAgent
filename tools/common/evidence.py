"""依赖索引使用的轻量本地环境与哈希工具。"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


class EvidenceError(RuntimeError):
    """项目资料环境或索引处理失败。"""


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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)


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
