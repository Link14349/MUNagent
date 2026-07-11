# 08 - 配置与密钥管理

> 上级文档: [index.md](index.md) | 相关: [05-agent-harness.md](05-agent-harness.md)(模型路由), [02-scenario-design.md](02-scenario-design.md)(MinerU)

## 1. 分层配置

加载优先级: **环境变量 > 用户配置文件 > 内置默认值**. 实现用pydantic-settings.

- **用户配置文件**: `~/.munagent/config.yaml`, 加入`.gitignore`; GUI设置页读写的就是它; 写入时`chmod 600`. 单机单人(决策D1)场景下, 本地明文+权限控制是合理安全线, 不做密钥加密(解密密钥的存放是同一个问题);
- **环境变量**: 前缀`MUNAGENT_`, 方便开发调试与不落盘需求;
- 后续可选: `keyring`接系统钥匙串, v1不做.

## 2. 配置文件全貌

```yaml
providers:                       # api key只出现在这里
  deepseek:
    base_url: https://api.deepseek.com
    api_key: sk-xxxx
  my-local:
    base_url: http://localhost:11434/v1
    api_key: none

roles:                           # 角色路由: 只引用provider名, 不碰key
  delegate: { provider: deepseek, model: deepseek-flash }
  chair:    { provider: deepseek, model: deepseek-pro }
  dm:       { provider: deepseek, model: deepseek-pro }
  recorder: { provider: deepseek, model: deepseek-flash }
  designer: { provider: deepseek, model: deepseek-pro }

tools:
  mineru:                        # 在线MinerU(PDF转Markdown), 决策D8
    base_url: http://<SERVER>:8282
  search:
    provider: <搜索API名>
    api_key: xxx

engine:                          # 推演默认参数(可被会话config覆盖)
  unmod_rounds: 4
  mod_max_speeches: 12
  session_max_tokens: 2000000
  human_timeout_s: 300
  human_timeout_fallback: ai_delegate   # ai_delegate | pass
  adjudication_thresholds: { great: 40, success: 10, partial: 0, fail: -20 }
  epoch_l3_max_tokens: 3000      # L3追加段纪元切换阈值, 见11§3
  cache_warmup: true             # 会话启动时预热G段缓存, 见11§6

server:
  host: 127.0.0.1                # 单机单人, 默认只监听本机
  port: 8000
  debug_dump_prompts: false      # 开启后完整prompt/response落本地文件(含私密信息)
```

### 环境变量对照(常用)

| 变量 | 对应配置 |
|---|---|
| `MUNAGENT_API_KEY` / `MUNAGENT_BASE_URL` | 默认provider的key/url快捷覆盖 |
| `MUNAGENT_MINERU_URL` | `tools.mineru.base_url` |
| `MUNAGENT_PORT` | `server.port` |

## 3. 安全红线

1. **key永远不回传前端**: 设置页展示掩码(`sk-****last4`); 后端配置API只接受写入, 不提供读取完整key的接口. 网页GUI意味着HTTP边界, 哪怕localhost也守此纪律;
2. **key永远不进事件日志**: 事件日志是可分享的存档格式(见03). LLM调用层在任何日志/事件/错误信息落地前剥离与脱敏key(包括401异常文本);
3. **场景包与存档导出不含任何配置**: 导出逻辑与配置系统代码上零交集;
4. **MinerU服务无鉴权**: 其地址应指向内网/VPN; 不要把8282端口暴露公网; 调用前打`/health`确认(见[../tools/agent-api-pdf-to-markdown-guide.md](../tools/agent-api-pdf-to-markdown-guide.md)).

## 4. 连接测试

设置页每个provider与每个工具服务旁有"测试连接"按钮:

- provider: 发一次1 token补全, 反馈 有效/无效key/网络不通/模型名不存在;
- mineru: `GET /health`, 反馈在线状态与worker数;
- 对应后端接口: `POST /api/config/test {target: provider:<name> | tool:mineru}`.

## 5. 会话级配置快照

创建推演会话时, 把当时生效的roles路由与engine参数**快照**进sessions表的config字段(不含key)——保证换了全局配置后, 旧会话续推行为一致, 复盘时也能追溯当时用的什么模型.
