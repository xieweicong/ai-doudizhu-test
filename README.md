# Dou Dizhu AI Arena

一个面向 AI 对战的斗地主后端与 CLI。当前版本重点提供：

- 完整 54 张牌发牌、叫分抢地主、底牌归地主、地主/农民胜负判定。
- 斗地主核心牌型识别与比较：单张、对子、三张、三带一、三带二、顺子、连对、飞机、飞机带单、飞机带对、四带二、四带两对、炸弹、火箭。
- 3 个本地基线 AI：`random`、`greedy`、`conservative`。
- 多类大模型接入：`OpenAI`、`DeepSeek`、`Gemini`、`Ollama`、`OpenRouter`、`Qwen / DashScope`、`AWS Bedrock Claude`。
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
doudizhu run --rounds 10 --players greedy conservative random --seed 42
```

项目启动时会自动读取当前目录下的 `.env`。

```bash
cp .env.example .env
```

也可以不安装，直接：

```bash
PYTHONPATH=src python -m doudizhu.cli play --players greedy conservative random
PYTHONPATH=src python -m doudizhu.cli run --rounds 100 --players greedy conservative random
```

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

## 常用命令

```bash
doudizhu list-ai
doudizhu play --players random greedy conservative --verbose
doudizhu play --players openai gemini ollama@qwen3:8b --show-reasons
doudizhu play --players deepseek openrouter@deepseek/deepseek-chat-v3-0324 bedrock --show-reasons
doudizhu play --players qwen deepseek bedrock --show-reasons
doudizhu run --rounds 1000 --players greedy conservative random --expose-all-hands
python -m unittest discover -s tests
```
