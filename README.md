# MUNagent

基于 LLM Agent 的模联历史危机联动场景设计與推演工具.

## 快速开始(P0)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 配置 API key(二选一)
export MUNAGENT_API_KEY=sk-your-key
# 或写入 ~/.munagent/config.yaml

munagent version
munagent config-test
pytest
```

设计文档见 [docs/design/index.md](docs/design/index.md)，开发计划见 [plan.md](plan.md)。
