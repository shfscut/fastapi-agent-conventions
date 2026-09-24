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
  "RUF",
]
ignore = [
  "B008",          # FastAPI 的 Depends/Query 默认参数写法
  "E501",          # 行长交给 formatter
]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101"]  # 测试里允许 assert

[tool.mypy]
strict = true
plugins = ["pydantic.mypy"]

[tool.pydantic-mypy]
init_forbid_extra = true
init_typed = true
warn_required_dynamic_aliases = true
```

`ASYNC` 规则能拦住 `async def` 中的 `time.sleep`、`requests` 等阻塞调用，这样 AGENTS.md 里"禁止阻塞 IO"这条规则就有了工具兜底。

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
