#!/usr/bin/env python3
"""PreToolUse hook：拦截 AGENTS.md 中的硬性禁令。exit 2 = 阻止该工具调用，stderr 回传给 agent。"""

import json
import re
import shlex
import sys
from pathlib import PurePath


def is_secret_env(path: str) -> bool:
    name = PurePath(path).name
    return (name == ".env" or name.startswith(".env.")) and name != ".env.example"


def check_bash(cmd: str) -> str | None:
    if re.search(r"(^|[\s;&|(])(pip3?|python3?\s+-m\s+pip|uv\s+pip)\s+install\b", cmd):
        return "禁止 pip install。添加依赖用 `uv add <pkg>`，安装依赖用 `uv sync`。"
    # 首次初始化 `cp .env.example .env` 只写入模板，不涉及密钥，放行
    scrubbed = re.sub(r"\bcp\s+\.env\.example\s+\.env\b", "", cmd)
    try:
        tokens = shlex.split(scrubbed, comments=True)
    except ValueError:
        tokens = scrubbed.split()
    if any(is_secret_env(t) for t in tokens if not t.startswith("-")):
        return "禁止读取、输出或提交 .env。查看配置项请读 `.env.example` 和 `Settings`。"
    if re.search(r"\bgit\s+push\b", cmd) and re.search(r"(^|[\s:/+])(main|master)(\s|$)", cmd):
        return "禁止直接 push 到 main/master。推到 feature 分支并发起 MR/PR。"
    return None


def main() -> None:
    event = json.load(sys.stdin)
    tool, args = event.get("tool_name", ""), event.get("tool_input", {})
    reason = None
    if tool == "Bash":
        reason = check_bash(args.get("command", ""))
    elif tool in ("Read", "Edit", "Write", "MultiEdit", "NotebookEdit"):
        if is_secret_env(args.get("file_path", "")):
            reason = "禁止读取或修改 .env。查看配置项请读 `.env.example` 和 `Settings`。"
    if reason:
        print(reason, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
