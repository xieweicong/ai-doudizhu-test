# Dou Dizhu AI Arena

一个面向 AI 对战的斗地主后端与 CLI。当前版本重点提供：

- 完整 54 张牌发牌、叫分抢地主、底牌归地主、地主/农民胜负判定。
- 斗地主核心牌型识别与比较：单张、对子、三张、三带一、三带二、顺子、连对、飞机、飞机带单、飞机带对、四带二、四带两对、炸弹、火箭。
- 3 个本地基线 AI：`random`、`greedy`、`conservative`。
- 多类大模型接入：`OpenAI`、`DeepSeek`、`Gemini`、`Ollama`、`OpenRouter`、`Qwen / DashScope`、`AWS Bedrock Claude`。
- 中文 CLI 实时播报和浏览器实时牌桌。
- 可自定义轮数批量运行，并统计胜率、地主胜率、农民胜率和积分。
- AI 扩展接口：大模型直连、Python 类插件或外部进程 JSON 接口。

## 已实际验证

目前我实际测试跑通过的 provider 是：

- `DeepSeek`
- `OpenRouter`
- `AWS Bedrock Claude`

其他已接入但还没有在这个仓库里做过完整实测的 provider：

- `OpenAI`
- `Gemini`
- `Ollama`
- `Qwen / DashScope`

## 快速开始

```bash
python -m pip install -e .
doudizhu play --players greedy conservative random --seed 1 --show-reasons
doudizhu live --players deepseek openrouter bedrock --show-reasons
doudizhu run --rounds 10 --players greedy conservative random --seed 42
```

项目启动时会自动读取当前目录下的 `.env`。

```bash
cp .env.example .env
```

也可以不安装，直接：

```bash
PYTHONPATH=src python -m doudizhu.cli play --players greedy conservative random
PYTHONPATH=src python -m doudizhu.cli live --players greedy conservative random
PYTHONPATH=src python -m doudizhu.cli run --rounds 100 --players greedy conservative random
```

## 运行模式

### CLI 实时播报

```bash
doudizhu play --players deepseek openrouter bedrock --show-reasons
```

终端会实时输出：

- 三家起手牌和底牌候选。
- 每次叫分和出牌前，该 AI 的当前手牌。
- 当前目标牌、是否合法可过、合法动作数量。
- 最终出牌、剩余张数、裁判修正原因和公开理由。

### 浏览器直播牌桌

```bash
doudizhu live --players deepseek openrouter bedrock --show-reasons
```

`live` 会启动一个本地实时牌桌，默认地址是 `http://127.0.0.1:8765/`。牌局运行时，发牌、叫分、思考中手牌、出牌、最后一手牌和最终积分都会实时推送到浏览器。

直播页面支持：

- 三家手牌动态展示。
- 当前思考玩家高亮。
- 出牌动画和桌面中央最后一手牌。
- 右侧事件历史可滚动查看。
- 默认跟随最新事件，手动滚动历史时暂停跟随，点击“跟随最新”可回到最新。
- 长模型名自动缩短显示，悬浮可查看完整名称。

常用参数：

```bash
doudizhu live --players deepseek openrouter bedrock --show-reasons --port 8876
doudizhu live --players deepseek openrouter bedrock --show-reasons --no-open
```

### 批量统计

```bash
doudizhu run --rounds 100 --players deepseek openrouter bedrock
```

`run` 会统计每个 AI 的阵营胜率、地主胜率、农民胜率和积分。注意真实大模型批量跑会产生 API 成本，建议先小轮数测试。

## 直接接大模型

### OpenAI

在 `.env` 里填写：

```dotenv
OPENAI_API_KEY=your-openai-key
OPENAI_MODEL=gpt-4.1-mini
```

运行示例：

```bash
doudizhu play --players openai deepseek greedy --show-reasons
```

### DeepSeek

在 `.env` 里填写：

```dotenv
DEEPSEEK_API_KEY=your-deepseek-key
DEEPSEEK_MODEL=deepseek-v4-flash
```

默认模型是 `deepseek-v4-flash`，也可以显式指定：

```bash
doudizhu play --players deepseek deepseek@deepseek-v4-pro greedy --show-reasons
```

### Gemini

在 `.env` 里填写：

```dotenv
GEMINI_API_KEY=your-gemini-key
GEMINI_MODEL=gemini-2.5-flash
```

运行示例：

```bash
doudizhu play --players gemini deepseek greedy --show-reasons
```

### Ollama

在 `.env` 里填写：

```dotenv
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:8b
```

确保本地 Ollama 已启动，并且模型已经拉取好：

```bash
ollama pull qwen3:8b
ollama serve
```

运行示例：

```bash
doudizhu play --players ollama deepseek greedy --show-reasons
```

### OpenRouter

在 `.env` 里填写：

```dotenv
OPENROUTER_API_KEY=your-openrouter-key
OPENROUTER_MODEL=deepseek/deepseek-chat-v3-0324
OPENROUTER_SITE_URL=
OPENROUTER_APP_NAME=doudizhu-ai
```

也可以把模型直接写在玩家 spec 里：

```bash
doudizhu run --rounds 20 \
  --players openrouter@deepseek/deepseek-chat-v3-0324 openrouter@anthropic/claude-3.5-haiku deepseek
```

### Qwen / DashScope

在 `.env` 里填写：

```dotenv
QWEN_API_KEY=your-dashscope-key
QWEN_MODEL=qwen-plus
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

运行示例：

```bash
doudizhu play --players qwen deepseek greedy --show-reasons
```

### AWS Bedrock Claude

在 `.env` 里填写：

```dotenv
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0
```

然后运行：

```bash
doudizhu play --players bedrock deepseek openrouter@deepseek/deepseek-chat-v3-0324 --show-reasons
```

或者直接显式指定 Bedrock 模型 ID：

```bash
doudizhu play \
  --players bedrock@anthropic.claude-3-5-sonnet-20241022-v2:0 deepseek greedy
```

说明：

- `OpenAI`、`DeepSeek`、`Gemini`、`OpenRouter`、`Qwen / DashScope` 走兼容 chat completions 的 HTTP 接口。
- `Ollama` 走本地 `POST /api/chat` 接口，并要求返回 JSON。
- `Bedrock Claude` 走 AWS Bedrock 的 Claude Messages API。
- `.env` 只会补充未设置的环境变量，不会覆盖你已经在 shell 里导出的值。
- CLI 只展示公开 `reason` 字段，不主动展示私有思维链。

## Provider Spec 速查

常见写法：

```bash
openai
openai@gpt-4.1-mini
deepseek
deepseek@deepseek-v4-pro
gemini
gemini@gemini-2.5-flash
ollama@qwen3:8b
openrouter@deepseek/deepseek-chat-v3-0324
qwen@qwen-plus
bedrock@anthropic.claude-3-5-sonnet-20241022-v2:0
```

也可以给部分 provider 加查询参数覆盖输出配置：

```bash
deepseek@deepseek-v4-pro?max_tokens=1200&temperature=0
openrouter@tencent/hy3-preview:free?max_tokens=1200
deepseek@deepseek-v4-flash?timeout=120
deepseek@deepseek-v4-flash?thinking=enabled&max_tokens=8192
```

常用参数：

- `max_tokens` / `output_tokens`：模型最大输出 token，默认 800。
- `temperature`：采样温度，默认 0。
- `timeout` / `timeout_seconds`：单次模型请求超时时间，OpenAI-compatible 默认 60 秒，Ollama 和 Bedrock 默认 120 秒。
- `thinking`：DeepSeek 专用，默认 `disabled`，避免模型把输出额度耗在 `reasoning_content` 上而没有返回 JSON 正文；如需实验深度思考可显式设为 `enabled`。
- `reasoning_effort`：DeepSeek thinking 开启时可传，例如 `high` / `max`。

## AI 能看到什么

默认是“公平玩家视角”：AI 只能看到自己的手牌和公共信息，不会看到其他玩家手牌。

每次叫分和出牌时，AI 会收到结构化上下文，主要包括：

- 自己的座位、模型名、当前手牌和手牌数量。
- 当前身份：地主或农民。
- 如果是农民，会明确给出 `teammate` 队友座位；地主没有队友。
- `opponents` 对手座位。
- 每个人还剩多少张牌。
- 叫分记录。
- 地主确定后的底牌。
- 当前要压谁的什么牌、是否可以过牌。
- 所有历史出牌 `full_history`。
- 最近 12 手 `recent_history`。
- 每个玩家已经出过哪些牌 `played_cards_by_player`。
- 自己已经出过哪些牌 `my_played_cards`。
- 当前步骤全部合法动作 `legal_options`，模型必须从这里选择。

如果你想测试“全知 AI”，可以显式打开：

```bash
doudizhu play --players deepseek openrouter bedrock --expose-all-hands
doudizhu live --players deepseek openrouter bedrock --expose-all-hands
```

打开后，AI 上下文会额外包含 `all_hands`，也就是所有人的当前手牌。这个模式适合做实验，但不再是正常斗地主公平视角。

## LLM 输出约束与容错

LLM 玩家需要返回 JSON。叫分示例：

```json
{"bid": 2, "reason": "高牌较多，可以争地主"}
```

出牌示例：

```json
{"action": "play", "option_index": 3, "reason": "用较小牌压住"}
```

过牌示例：

```json
{"action": "pass", "reason": "接牌代价太高"}
```

程序会做几层兜底：

- 如果模型不支持强制 JSON，会自动降级为普通 chat completions 再解析。
- 如果推理模型先输出太多 reasoning 导致正文为空，会自动扩大 token 预算并追加“直接输出 JSON”的提示重试。
- 如果模型返回普通文本，会尽量解析叫分、`option_index` 或牌面。
- 如果模型仍然非法出牌，裁判会修正：可过时过牌，不可过时出第一手合法牌，并在输出里标明裁判修正原因。直播界面也会展示底层原因，例如超时、空正文、不能过牌却选择过牌、牌型不合法、压不过目标牌等。

## AI 扩展方式

除了上面的直连大模型，之后接入自定义模型时还有两种方式：

### Python 类

传入 `module.path:ClassName`。类需要实现 `choose_bid(view, valid_bids)` 和 `choose_play(view, legal_plays, can_pass)`，返回可以是内置的 `BidDecision` / `PlayDecision`，也可以是普通 `int` 或牌面列表。

### 外部进程

传入 `process:your-command --arg`。程序每次决策会收到一段 JSON，需输出一段 JSON：

```json
{"bid": 1, "reason": "strong high cards"}
```

或：

```json
{"cards": ["3", "3"], "reason": "lowest pair"}
```

CLI 展示的是 AI 提供的公开 `reason` 字段。若接 LLM，建议输出简短理由，不输出私有思维链。

## 安全提示

- `.env` 会被 `.gitignore` 忽略，不要把真实 API key 提交到仓库。
- 只提交 `.env.example` 这样的模板文件。
- 如果 key 曾经出现在公开仓库或日志里，请及时轮换。
- `--show-reasons` 只展示公开短理由，不展示私有思维链。

## 常用命令

```bash
doudizhu list-ai
doudizhu play --players random greedy conservative --verbose
doudizhu live --players deepseek openrouter bedrock --show-reasons
doudizhu live --players deepseek openrouter bedrock --show-reasons --no-open
doudizhu play --players openai gemini ollama@qwen3:8b --show-reasons
doudizhu play --players deepseek openrouter@deepseek/deepseek-chat-v3-0324 bedrock --show-reasons
doudizhu play --players qwen deepseek bedrock --show-reasons
doudizhu run --rounds 1000 --players greedy conservative random --expose-all-hands
python -m unittest discover -s tests
```
