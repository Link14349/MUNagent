# config 模块 API

## `load_config(path=None) -> MunagentConfig`
加载配置. 优先级: 环境变量 > YAML 文件 > 内置默认. 默认文件 `~/.munagent/config.yaml`.

## `save_config(config, path=None) -> Path`
写入用户配置, `chmod 600`.

## `mask_api_key(api_key) -> str`
返回掩码字符串, 供 GUI 展示, 禁止回传完整 key.

## `MunagentConfig.resolve_role(role) -> (ProviderConfig, model)`
角色→provider+model 路由.

## 环境变量
- `MUNAGENT_API_KEY` / `MUNAGENT_BASE_URL`: 覆盖默认 provider
- `MUNAGENT_MINERU_URL`, `MUNAGENT_PORT`, `MUNAGENT_CONFIG_PATH`
