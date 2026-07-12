# 配置

| 函数 | 说明 |
|---|---|
| `load_config(path=None) -> AppConfig` | env > yaml > 默认 三层加载 |
| `save_config(config, path=None) -> Path` | 写入 yaml 并 chmod 600 |
| `mask_api_key(key) -> str` | 展示用掩码, 不回传明文 |
| `default_config() -> AppConfig` | 内置默认(无 key) |

路径常量: `CONFIG_PATH` = `~/.munagent/config.yaml`
