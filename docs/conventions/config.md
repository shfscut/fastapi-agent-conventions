# 配置与本地开发环境

遵循 [12-Factor App · Config](https://12factor.net/zh_cn/config)：配置（尤其是密钥）与代码分离，一律通过**环境变量**注入。本地开发用 `.env` 存放这些值，并让终端、编辑器、调试器都从同一个 `.env` 读取。

## 文件约定

```
.env                   # 本地配置和密钥，禁止提交
.env.example           # 配置项模板，必须提交
.envrc                 # direnv：进入目录时自动加载 .env，必须提交
.vscode/settings.json  # 统一解释器，必须提交
.vscode/launch.json    # 统一启动和调试配置，必须提交
```

| 文件 | 解决的问题 | 是否提交 |
|------|-----------|---------|
| `.env` | 本机的实际配置值 | 否 |
| `.env.example` | 列出服务需要哪些配置，相当于"配置契约" | 是 |
| `.envrc` | 终端里运行 `uv run ...` 时自动注入环境变量 | 是 |
| `.vscode/settings.json` | 所有人使用同一个 `.venv` 解释器 | 是 |
| `.vscode/launch.json` | F5 启动和调试的方式保持一致 | 是 |

密钥只存在 `.env` 这一个文件里。其余文件都不含密钥，可以放心提交。

## `.env.example`

列出全部配置项。敏感项留空，非敏感项可以填本地开发用的默认值。

```bash
ENV=dev
SERVICE_NAME=order
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/order
JWT_SECRET=
```

新人第一次初始化：

```bash
cp .env.example .env    # 然后填写密钥
direnv allow
```

## `.envrc`

```bash
dotenv_if_exists
```

`dotenv_if_exists` 只加载根目录的 `.env`。文件不存在时不会报错。需要 shell 的 direnv hook：`eval "$(direnv hook zsh)"`。

## `.vscode/settings.json`

```json
{
  "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python"
}
```

VS Code Python 扩展的 `python.envFile` 默认就是 `${workspaceFolder}/.env`，所以不需要额外配置。运行按钮、测试面板和调试都会自动加载它。

## `.vscode/launch.json`

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "FastAPI",
      "type": "debugpy",
      "request": "launch",
      "module": "uvicorn",
      "args": ["app.main:app", "--reload"],
      "jinja": true
    },
    {
      "name": "Python: Current File",
      "type": "debugpy",
      "request": "launch",
      "program": "${file}",
      "console": "integratedTerminal"
    }
  ]
}
```

不要写 `envFile`，默认就会读取根目录的 `.env`。

## `.gitignore`

```gitignore
.env
.env.*
!.env.example

.vscode/*
!.vscode/settings.json
!.vscode/launch.json
```

`.vscode/` 下只提交这两个共享文件，个人设置不提交。

## 代码侧：`pydantic-settings`

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    ENV: str = "dev"
    SERVICE_NAME: str
    DATABASE_URL: str
    JWT_SECRET: str


settings = Settings()  # type: ignore[call-arg]
```

- **不要设置 `env_file`**。`Settings` 只从进程的环境变量读取。本地由 direnv 或 VS Code 注入，线上由 K8s Secret 或 ConfigMap 注入。这样所有环境都只有一种加载路径，也不会在容器或 CI 里误读到某个残留的 `.env`。
- 也不要在代码里调用 `load_dotenv()`，不需要引入 `python-dotenv`。
- 没有 direnv 的场景（比如 CI 或临时运行）可以用 `uv run --env-file .env <cmd>`。
- 必填项不给默认值。缺配置时启动直接失败，比运行到一半才出错更好排查。

## 新增配置项的流程

1. 在对应的 `Settings` 类里加字段。
2. 在 `.env.example` 里加同名变量，敏感值留空。
3. 更新部署侧的配置（Helm values、K8s Secret 等）。

三处必须在同一个提交里完成。

## 注意：环境变量会被 agent CLI 继承

direnv 会把 `.env` 里的变量导出到当前 shell。在这个目录里启动的 Claude Code、Codex 等 CLI 也会继承这些变量。

如果服务本身要调用 LLM，**不要直接用 `ANTHROPIC_API_KEY`、`OPENAI_API_KEY`、`ANTHROPIC_BASE_URL` 这类变量名**，否则 agent 自身的认证可能被覆盖成服务的 key 或网关。应改用带服务前缀的名字，例如 `LLM_API_KEY`、`LLM_BASE_URL`，再在代码里显式传给 SDK 客户端。
