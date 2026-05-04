from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request

from .cards import format_cards
from .combos import Combo
from .decision_types import BidDecision, PlayDecision

SYSTEM_PROMPT = (
    "你是斗地主 AI 玩家。你必须严格从给定合法动作中选择一个动作。"
    "请根据身份、队友、剩余牌数、历史出牌和当前目标牌做决策。"
    "只返回 JSON，不要 markdown，不要额外文字。"
    "不要泄露私有推理过程。"
    "`reason` 字段必须是中文短句，最多 30 个汉字。"
)


@dataclass(frozen=True)
class ParsedLLMSpec:
    provider: str
    model: str
    options: dict[str, str]


class ChatBackend:
    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        raise NotImplementedError


class RemoteLLMAI:
    def __init__(
        self,
        spec: ParsedLLMSpec,
        backend: ChatBackend,
        *,
        name: str | None = None,
    ) -> None:
        self.spec = spec
        self.backend = backend
        short_model = spec.model if len(spec.model) <= 36 else spec.model[:33] + "..."
        self.name = name or f"{spec.provider}@{short_model}"
        self.temperature = float(spec.options.get("temperature", "0"))
        self.max_tokens = int(spec.options.get("max_tokens", spec.options.get("output_tokens", "800")))

    def choose_bid(self, view: dict[str, Any], valid_bids: list[int]) -> BidDecision:
        payload = {
            "task": "bid",
            "rules": "从 valid_bids 里选一个叫分。0 表示不叫，1/2/3 表示叫对应分数。",
            "decision_notes": [
                "叫分阶段还没有地主和队友，只根据自己的牌力、叫分记录和风险选择。",
                "强牌、炸弹、火箭、高牌多时可以更积极；牌散时保守。",
            ],
            "valid_bids": valid_bids,
            "game_state": summarize_view(view),
            "output_schema": {"bid": "integer from valid_bids", "reason": "中文短句"},
            "output_examples": [
                {"bid": 0, "reason": "牌力一般，先不叫"},
                {"bid": 2, "reason": "高牌较多，可以争地主"},
            ],
        }
        response = self.backend.generate_json(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=json.dumps(payload, ensure_ascii=False),
            max_tokens=min(self.max_tokens, 800),
            temperature=self.temperature,
        )
        raw_text = str(response.get("raw_text", ""))
        bid = _coerce_int(response.get("bid"), default=_extract_bid_from_text(raw_text, valid_bids))
        reason = _truncate_reason(response.get("reason") or raw_text)
        return BidDecision(bid=bid, reason=reason)

    def choose_play(
        self,
        view: dict[str, Any],
        legal_plays: list[Combo],
        can_pass: bool,
    ) -> PlayDecision:
        payload = {
            "task": "play",
            "rules": (
                "只从 legal_options 里选一个合法动作。"
                "can_pass 为 true 时可以返回 action='pass'。"
                "否则必须返回 action='play' 和合法 option_index。"
            ),
            "decision_notes": [
                "你只能看到自己的手牌和公共信息，不能假设知道别人手牌。",
                "如果你是农民，要结合 teammate 字段配合同伴，不要无意义压队友的关键牌。",
                "重点关注 remaining_counts，优先阻止只剩少量牌的对手走完。",
                "结合 full_history、played_cards_by_player 和 my_played_cards 判断已出过的牌。",
                "current_trick 描述当前需要压过的牌；如果 target_player 是队友，可以考虑过牌配合。",
            ],
            "can_pass": can_pass,
            "game_state": summarize_view(view),
            "legal_options": [
                {
                    "option_index": index,
                    "kind": combo.kind,
                    "label": combo.label,
                    "cards": list(combo.cards),
                    "text": format_cards(combo.cards),
                }
                for index, combo in enumerate(legal_plays)
            ],
            "output_schema": {
                "action": "play 或 pass",
                "option_index": "action=play 时必填",
                "reason": "中文短句",
            },
            "output_examples": [
                {"action": "pass", "reason": "接牌代价太高"},
                {"action": "play", "option_index": 3, "reason": "用较小牌压住"},
            ],
        }
        response = self.backend.generate_json(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=json.dumps(payload, ensure_ascii=False),
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        raw_text = str(response.get("raw_text", ""))
        reason = _truncate_reason(response.get("reason") or raw_text)
        action = _normalize_action(str(response.get("action", "")), raw_text)
        if action == "pass":
            return PlayDecision(cards=(), reason=reason or "model chose pass")

        option_index = _coerce_int(
            _first_present_key(response, "option_index", "index", "option", "choice"),
            default=_extract_option_index_from_text(raw_text),
        )
        if 0 <= option_index < len(legal_plays):
            return PlayDecision(cards=legal_plays[option_index].cards, reason=reason)

        cards = _coerce_cards(
            _first_present_key(response, "cards", "card", "play_cards", "selected_cards", "play")
        )
        if not cards:
            text_cards = _extract_cards_from_text(raw_text)
            if text_cards:
                cards = text_cards
        return PlayDecision(cards=cards, reason=reason)


class OpenAICompatibleBackend(ChatBackend):
    def __init__(
        self,
        *,
        api_key: str | None,
        url: str,
        model: str,
        headers: dict[str, str] | None = None,
        timeout_seconds: float = 60.0,
        include_response_format: bool = True,
    ) -> None:
        self.api_key = api_key
        self.url = url
        self.model = model
        self.headers = headers or {}
        self.timeout_seconds = timeout_seconds
        self.include_response_format = include_response_format

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        attempts = []
        if self.include_response_format:
            attempts.append((True, user_prompt))
        attempts.append((False, user_prompt + "\n\n只返回紧凑 JSON 对象。不要 markdown，不要解释。reason 必须写中文。"))

        last_error: Exception | None = None
        for include_response_format, base_prompt in attempts:
            token_budget = max_tokens
            prompt = base_prompt
            for _ in range(3):
                payload = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": temperature,
                    "max_tokens": token_budget,
                }
                if include_response_format:
                    payload["response_format"] = {"type": "json_object"}
                headers = {"Content-Type": "application/json", **self.headers}
                if self.api_key:
                    headers["Authorization"] = f"Bearer {self.api_key}"
                try:
                    response = _post_json(
                        self.url,
                        payload,
                        headers,
                        timeout_seconds=self.timeout_seconds,
                    )
                    choice = response["choices"][0]
                    message = choice.get("message", {})
                    content = message.get("content")
                    finish_reason = choice.get("finish_reason")
                    if _is_empty_content(content):
                        reasoning_len = len(str(message.get("reasoning_content") or ""))
                        last_error = ValueError(_empty_content_message(finish_reason, reasoning_len))
                        token_budget = min(max(token_budget * 4, 512), 4096)
                        prompt = (
                            base_prompt
                            + "\n\n前一次没有输出可解析的 JSON 正文。"
                            + "不要展开思考，直接输出一个紧凑 JSON 对象。"
                        )
                        continue
                    return _parse_json_content(content)
                except Exception as error:
                    last_error = error
                    break

        if last_error is not None:
            raise last_error
        raise RuntimeError("模型连续返回空内容，已自动扩容重试但仍未得到正文")


class OllamaBackend(ChatBackend):
    def __init__(
        self,
        *,
        url: str,
        model: str,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.url = url
        self.model = model
        self.timeout_seconds = timeout_seconds

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        response = _post_json(
            self.url,
            payload,
            {"Content-Type": "application/json"},
            timeout_seconds=self.timeout_seconds,
        )
        content = response["message"]["content"]
        return _parse_json_content(content)


class BedrockClaudeBackend(ChatBackend):
    def __init__(
        self,
        *,
        model_id: str,
        region_name: str,
        timeout_seconds: int = 120,
    ) -> None:
        self.model_id = model_id
        self.region_name = region_name
        self.timeout_seconds = timeout_seconds
        self._client = None

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        client = self._get_client()
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt,
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": user_prompt}],
                }
            ],
        }
        response = client.invoke_model(
            modelId=self.model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body),
        )
        payload = json.loads(response["body"].read())
        content_blocks = payload.get("content", [])
        text = "".join(block.get("text", "") for block in content_blocks if block.get("type") == "text")
        return _parse_json_content(text)

    def _get_client(self):
        if self._client is None:
            try:
                import boto3
                from botocore.config import Config
            except ImportError as error:
                raise RuntimeError(
                    "boto3 is required for Bedrock Claude. Run `python -m pip install -e .` first."
                ) from error
            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self.region_name,
                config=Config(
                    connect_timeout=30,
                    read_timeout=self.timeout_seconds,
                    retries={"max_attempts": 2},
                ),
            )
        return self._client


def is_llm_spec(spec: str) -> bool:
    normalized = spec.strip()
    prefixes = (
        "deepseek",
        "openrouter",
        "bedrock",
        "bedrock-claude",
        "openai",
        "gemini",
        "ollama",
        "qwen",
    )
    return any(normalized == prefix or normalized.startswith(prefix + "@") for prefix in prefixes)


def create_llm_ai(spec_text: str) -> RemoteLLMAI:
    spec = parse_llm_spec(spec_text)
    if spec.provider == "openai":
        api_key = _require_env("OPENAI_API_KEY")
        backend = OpenAICompatibleBackend(
            api_key=api_key,
            url=_env("OPENAI_BASE_URL", "https://api.openai.com/v1") + "/chat/completions",
            model=spec.model,
            timeout_seconds=_option_float(spec.options, "timeout", "timeout_seconds", default=60.0),
        )
        return RemoteLLMAI(spec, backend)
    if spec.provider == "deepseek":
        api_key = _require_env("DEEPSEEK_API_KEY")
        backend = OpenAICompatibleBackend(
            api_key=api_key,
            url=_env("DEEPSEEK_BASE_URL", "https://api.deepseek.com") + "/chat/completions",
            model=spec.model,
            timeout_seconds=_option_float(spec.options, "timeout", "timeout_seconds", default=60.0),
            include_response_format=False,
        )
        return RemoteLLMAI(spec, backend)
    if spec.provider == "gemini":
        api_key = _require_env("GEMINI_API_KEY")
        backend = OpenAICompatibleBackend(
            api_key=api_key,
            url=_env("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai") + "/chat/completions",
            model=spec.model,
            timeout_seconds=_option_float(spec.options, "timeout", "timeout_seconds", default=60.0),
        )
        return RemoteLLMAI(spec, backend)
    if spec.provider == "openrouter":
        api_key = _require_env("OPENROUTER_API_KEY")
        extra_headers = {}
        site_url = os.getenv("OPENROUTER_SITE_URL")
        app_name = os.getenv("OPENROUTER_APP_NAME", "doudizhu-ai")
        if site_url:
            extra_headers["HTTP-Referer"] = site_url
        if app_name:
            extra_headers["X-Title"] = app_name
        backend = OpenAICompatibleBackend(
            api_key=api_key,
            url=_env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1") + "/chat/completions",
            model=spec.model,
            headers=extra_headers,
            timeout_seconds=_option_float(spec.options, "timeout", "timeout_seconds", default=60.0),
            include_response_format=False,
        )
        return RemoteLLMAI(spec, backend)
    if spec.provider == "qwen":
        api_key = _first_present_env("QWEN_API_KEY", "DASHSCOPE_API_KEY")
        if not api_key:
            raise ValueError("Missing QWEN_API_KEY or DASHSCOPE_API_KEY.")
        backend = OpenAICompatibleBackend(
            api_key=api_key,
            url=_env("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1") + "/chat/completions",
            model=spec.model,
            timeout_seconds=_option_float(spec.options, "timeout", "timeout_seconds", default=60.0),
        )
        return RemoteLLMAI(spec, backend)
    if spec.provider == "ollama":
        backend = OllamaBackend(
            url=_env("OLLAMA_BASE_URL", "http://localhost:11434") + "/api/chat",
            model=spec.model,
            timeout_seconds=_option_float(spec.options, "timeout", "timeout_seconds", default=120.0),
        )
        return RemoteLLMAI(spec, backend)
    if spec.provider == "bedrock":
        region_name = _first_present_env("AWS_REGION", "AWS_DEFAULT_REGION", "aws_region")
        if not region_name:
            raise ValueError("Missing AWS region. Set AWS_REGION, AWS_DEFAULT_REGION, or aws_region.")
        backend = BedrockClaudeBackend(
            model_id=spec.model,
            region_name=region_name,
            timeout_seconds=int(_option_float(spec.options, "timeout", "timeout_seconds", default=120.0)),
        )
        return RemoteLLMAI(spec, backend)
    raise ValueError(f"unsupported llm provider: {spec.provider}")


def parse_llm_spec(spec_text: str) -> ParsedLLMSpec:
    spec_text = spec_text.strip()
    if "?" in spec_text:
        base, query_string = spec_text.split("?", 1)
        query = parse.parse_qs(query_string, keep_blank_values=False)
        options = {key: values[-1] for key, values in query.items()}
    else:
        base = spec_text
        options = {}

    if "@" in base:
        provider, model = base.split("@", 1)
    else:
        provider, model = base, ""
    provider = provider.strip().lower()
    model = model.strip()

    if provider == "openai":
        model = model or _env("OPENAI_MODEL", "gpt-4.1-mini")
    elif provider == "deepseek":
        model = model or _env("DEEPSEEK_MODEL", "deepseek-v4-flash")
    elif provider == "gemini":
        model = model or _env("GEMINI_MODEL", "gemini-2.5-flash")
    elif provider == "openrouter":
        model = model or _first_present_env("OPENROUTER_MODEL")
        if not model:
            raise ValueError("OpenRouter requires a model. Use `openrouter@provider/model` or set OPENROUTER_MODEL.")
    elif provider == "qwen":
        model = model or _first_present_env("QWEN_MODEL", "DASHSCOPE_MODEL")
        if not model:
            model = "qwen-plus"
    elif provider == "ollama":
        model = model or _first_present_env("OLLAMA_MODEL")
        if not model:
            raise ValueError("Ollama requires a model. Use `ollama@model-name` or set OLLAMA_MODEL.")
    elif provider in {"bedrock", "bedrock-claude"}:
        provider = "bedrock"
        model = model or _first_present_env("BEDROCK_MODEL_ID", "AWS_BEDROCK_MODEL_ID")
        if not model:
            raise ValueError(
                "Bedrock Claude requires a model id. Use `bedrock@anthropic.claude-...` or set BEDROCK_MODEL_ID."
            )
    else:
        raise ValueError(f"unknown llm provider spec: {spec_text}")

    return ParsedLLMSpec(provider=provider, model=model, options=options)


def summarize_view(view: dict[str, Any]) -> dict[str, Any]:
    summarized = {
        "phase": view.get("phase"),
        "seat": view.get("seat"),
        "players": view.get("players"),
        "role": view.get("role"),
        "role_by_player": view.get("role_by_player"),
        "my_side": view.get("my_side"),
        "landlord": view.get("landlord"),
        "farmers": view.get("farmers"),
        "teammate": view.get("teammate"),
        "opponents": view.get("opponents"),
        "hand": view.get("hand"),
        "hand_text": view.get("hand_text"),
        "hand_count": view.get("hand_count"),
        "remaining_counts": view.get("remaining_counts"),
        "highest_bid": view.get("highest_bid"),
        "bids": view.get("bids"),
        "current_player": view.get("current_player"),
        "turn": view.get("turn"),
        "can_pass": view.get("can_pass"),
        "last_combo": view.get("last_combo"),
        "last_player": view.get("last_player"),
        "current_trick": view.get("current_trick"),
        "bottom_cards": view.get("bottom_cards"),
        "bottom_cards_text": view.get("bottom_cards_text"),
        "played_cards": view.get("played_cards"),
        "played_cards_text": view.get("played_cards_text"),
        "played_cards_by_player": view.get("played_cards_by_player"),
        "my_played_cards": view.get("my_played_cards"),
        "non_pass_counts": view.get("non_pass_counts"),
        "recent_history": list(view.get("recent_history") or view.get("history", []))[-12:],
        "full_history": view.get("full_history", view.get("history", [])),
    }
    if "all_hands" in view:
        summarized["all_hands"] = view["all_hands"]
    return {key: value for key, value in summarized.items() if value is not None}


def _post_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(url=url, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as http_error:
        details = http_error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{url} returned HTTP {http_error.code}: {details}") from http_error
    except error.URLError as url_error:
        raise RuntimeError(f"request to {url} failed: {url_error.reason}") from url_error


def _parse_json_content(content: Any) -> dict[str, Any]:
    if isinstance(content, list):
        content = "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    if isinstance(content, dict):
        return content
    text = str(content).strip()
    if not text:
        raise ValueError("model returned empty content")
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.startswith("```")]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        return {"raw_text": text}


def _coerce_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        match = re.search(r"-?\d+", str(value or ""))
        return int(match.group(0)) if match else default


def _first_present_key(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = data.get(key)
        if value is not None:
            return value
    return None


def _coerce_cards(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return _extract_cards_from_text(value)
    if isinstance(value, (list, tuple)):
        return tuple(card for card in (_normalize_card(item) for item in value) if card)
    try:
        return tuple(card for card in (_normalize_card(item) for item in value or ()) if card)
    except TypeError:
        return ()


def _truncate_reason(value: Any) -> str:
    text = str(value or "").strip().replace("\n", " ")
    return text[:160]


def _is_empty_content(content: Any) -> bool:
    if content is None:
        return True
    if isinstance(content, list):
        text = "".join(
            str(block.get("text", "")) if isinstance(block, dict) else str(block)
            for block in content
        )
        return not text.strip()
    if isinstance(content, str):
        return not content.strip()
    return False


def _empty_content_message(finish_reason: Any, reasoning_len: int) -> str:
    reason = str(finish_reason or "-")
    if reasoning_len:
        return f"模型返回了空正文(finish_reason={reason}, reasoning_content_len={reasoning_len})"
    return f"模型返回了空正文(finish_reason={reason})"


def _extract_bid_from_text(text: str, valid_bids: list[int]) -> int:
    lowered = text.lower()
    if any(token in lowered for token in ("不叫", "pass", "bid 0", "bid: 0")):
        return 0 if 0 in valid_bids else valid_bids[0]
    for match in re.findall(r"\b[0-3]\b", text):
        value = int(match)
        if value in valid_bids:
            return value
    return 0 if 0 in valid_bids else valid_bids[0]


def _normalize_action(action: str, raw_text: str) -> str:
    action = action.strip().lower()
    if action in {"play", "pass"}:
        return action
    if action in {"出", "出牌", "打", "压", "play_card"}:
        return "play"
    if action in {"过", "不出", "不要", "pass_turn"}:
        return "pass"
    lowered = f"{action} {raw_text}".lower()
    if any(token in lowered for token in ("pass", "过", "不要")):
        return "pass"
    return "play"


def _extract_option_index_from_text(text: str) -> int:
    patterns = [
        r"option_index\s*[:=]\s*(\d+)",
        r"option\s*[:=]?\s*(\d+)",
        r"index\s*[:=]\s*(\d+)",
        r"第\s*(\d+)\s*个",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return -1


def _extract_cards_from_text(text: str) -> tuple[str, ...]:
    normalized = (
        text.upper()
        .replace("小王", " BJ ")
        .replace("大王", " RJ ")
    )
    found = re.findall(r"\b(?:10|[3-9JQKA2]|BJ|RJ)\b", normalized)
    return tuple(found)


def _normalize_card(value: Any) -> str:
    text = str(value).strip().upper()
    aliases = {"小王": "BJ", "大王": "RJ"}
    if text in aliases:
        return aliases[text]
    if text in {"3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A", "2", "BJ", "RJ"}:
        return text
    extracted = _extract_cards_from_text(text)
    return extracted[0] if len(extracted) == 1 else ""


def _env(name: str, default: str) -> str:
    return os.getenv(name, default).rstrip("/")


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing {name}.")
    return value


def _first_present_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return ""


def _option_float(options: dict[str, str], *names: str, default: float) -> float:
    for name in names:
        value = options.get(name)
        if value:
            return float(value)
    return default
