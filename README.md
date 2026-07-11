# MUNagent

基于 LLM Agent 的模联历史危机联动场景设计與推演工具.

## 环境管理(Conda, 推荐)

本项目用 **Conda 环境 `munagent`** 管理 Python 与依赖, **不要**再叠加项目内 `.venv`——否则命令行会同时出现 `(base)` 和 `(.venv)`, 也容易混用两套 Python.

```bash
# 首次: 在项目根目录创建环境
conda env create -f environment.yml
conda activate munagent

# 依赖变更后更新
conda activate munagent
pip install -e ".[dev]"

# 配置 API key(二选一)
export MUNAGENT_API_KEY=sk-your-key
# 或写入 ~/.munagent/config.yaml  (在用户主目录, 不会进 git)

munagent version
munagent config-test
pytest
```

若不想每次开终端都自动进入 `(base)`, 可执行一次:

```bash
conda config --set auto_activate_base false
```

之后需要 base 时手动 `conda activate base` 即可.

## 配置 API key

配置文件路径: `~/.munagent/config.yaml` (在用户主目录, **不在仓库内**, 不会被 git 提交).

```yaml
providers:
  deepseek:
    base_url: https://api.deepseek.com
    api_key: sk-你的key
roles:
  delegate: { provider: deepseek, model: deepseek-v4-flash }
  chair:    { provider: deepseek, model: deepseek-v4-pro }
  dm:       { provider: deepseek, model: deepseek-v4-pro }
  recorder: { provider: deepseek, model: deepseek-v4-flash }
  designer: { provider: deepseek, model: deepseek-v4-pro }
```

写入后建议: `chmod 600 ~/.munagent/config.yaml`

设计文档见 [docs/design/index.md](docs/design/index.md), 开发计划见 [plan.md](plan.md).
