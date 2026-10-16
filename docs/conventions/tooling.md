# 工具链配置

AGENTS.md 里只写规则。凡是能由工具自动检查的，都交给下面这些配置，并在 CI 里强制执行。

## `pyproject.toml`

```toml
[project]
requires-python = ">=3.12"

[tool.uv]
# 只安装发布满 7 天的版本，降低供应链投毒风险。
# 旧版 uv 不支持相对时长，需要改成 RFC 3339 日期
exclude-newer = "1 week"

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = [
  "E", "W", "F",   # pycodestyle / pyflakes
  "I",             # isort
  "B",             # bugbear
  "C4",            # comprehensions
  "UP",            # pyupgrade
  "ASYNC",         # async 中的阻塞调用
  "S",             # bandit 安全规则
  "T20",           # 禁止 print
  "PT",            # pytest 风格
  "TID251",        # banned-api：见下方 SQL 分层约束
  "RUF",
]
ignore = [
  "B008",          # FastAPI 的 Depends/Query 默认参数写法
  "E501",          # 行长交给 formatter
]

# SQL 只能写在 repository.py：其他文件 import 这些 API 会报 TID251
[tool.ruff.lint.flake8-tidy-imports.banned-api]
"sqlalchemy.select".msg = "SQL 只写在 repository.py，这里调用 repository 方法"
"sqlalchemy.insert".msg = "SQL 只写在 repository.py，这里调用 repository 方法"
"sqlalchemy.update".msg = "SQL 只写在 repository.py，这里调用 repository 方法"
"sqlalchemy.delete".msg = "SQL 只写在 repository.py，这里调用 repository 方法"
"sqlalchemy.text".msg = "SQL 只写在 repository.py，这里调用 repository 方法"

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101", "TID251"]   # 测试里允许 assert 和直接查库断言
"app/**/repository.py" = ["TID251"]
"migrations/**" = ["TID251"]

[tool.mypy]
strict = true
plugins = ["pydantic.mypy"]

[tool.pydantic-mypy]
init_forbid_extra = true
init_typed = true
warn_required_dynamic_aliases = true
```

`ASYNC` 规则能拦住 `async def` 中的 `time.sleep`、`requests` 等阻塞调用，这样 AGENTS.md 里"禁止阻塞 IO"这条规则就有了工具兜底。`TID251` 同理兜底"SQL 只写在 repository"。

## Claude Code hook

`.claude/settings.json` 注册了 PreToolUse hook `.claude/hooks/guard.py`，在工具调用执行前拦截以下操作（exit 2 阻止并把原因回传给 agent）：

| 拦截 | 替代做法 |
|------|----------|
| 读取 / 输出 / 修改 / `git add` `.env`、`.env.*`（`.env.example` 除外） | 读 `.env.example` 和 `Settings` |
| `pip install`、`python -m pip install`、`uv pip install` | `uv add <pkg>` / `uv sync` |
| `git push` 到 `main` / `master` | 推 feature 分支，发 MR/PR |

这些规则如果只写在 AGENTS.md 里，靠的是 agent "大多数时候"遵守；放进 hook 才是真正的强制。新增硬性禁令时，优先加到 hook，而不是在 AGENTS.md 里加粗。hook 只对 Claude Code 生效，所以 AGENTS.md 仍保留一行简短说明给其他 agent。

## pre-commit（可选）

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.x.x          # 固定到当前版本
    hooks:
      - id: ruff-check
        args: [--fix]
      - id: ruff-format
```

## CI 最小流水线

```bash
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest --cov=app --cov-fail-under=80
```
