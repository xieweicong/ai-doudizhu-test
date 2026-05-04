from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request

from .cards import format_cards
from .combos import Combo
from .decision_types import BidDecision, PlayDecision

SYSTEM_PROMPT = (
    "You are an AI player in Dou Dizhu. "
    "You must follow the rules and choose exactly one legal action from the provided options. "
    "Return JSON only. Do not wrap JSON in markdown. "
    "Do not reveal hidden chain-of-thought. "
    "The optional `reason` field must be a short public summary."
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
        self.max_tokens = int(spec.options.get("max_tokens", spec.options.get("output_tokens", "220")))

    def choose_bid(self, view: dict[str, Any], valid_bids: list[int]) -> BidDecision:
        payload = {
            "task": "bid",
            "rules": "Choose one number from valid_bids. Higher bid means stronger confidence.",
            "valid_bids": valid_bids,
            "game_state": summarize_view(view),
            "output_schema": {"bid": "integer from valid_bids", "reason": "optional short string"},
        }
        response = self.backend.generate_json(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=json.dumps(payload, ensure_ascii=False),
            max_tokens=min(self.max_tokens, 120),
            temperature=self.temperature,
        )
        bid = _coerce_int(response.get("bid"), default=0)
        reason = _truncate_reason(response.get("reason", ""))
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
                "Choose exactly one legal action. "
                "When can_pass is true, you may return action='pass'. "
                "Otherwise you must return action='play' with a valid option_index."
            ),
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
                "action": "play or pass",
                "option_index": "required when action=play",
                "reason": "optional short string",
            },
        }
        response = self.backend.generate_json(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=json.dumps(payload, ensure_ascii=False),
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        reason = _truncate_reason(response.get("reason", ""))
        action = str(response.get("action", "play")).strip().lower()
        if action == "pass":
            return PlayDecision(cards=(), reason=reason or "model chose pass")

        option_index = _coerce_int(response.get("option_index"), default=-1)
        if 0 <= option_index < len(legal_plays):
            return PlayDecision(cards=legal_plays[option_index].cards, reason=reason)

        cards = tuple(response.get("cards", []) or ())
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
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self.include_response_format:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json", **self.headers}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        response = _post_json(
            self.url,
            payload,
            headers,
            timeout_seconds=self.timeout_seconds,
        )
        content = response["choices"][0]["message"]["content"]
        return _parse_json_content(content)


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
        )
        return RemoteLLMAI(spec, backend)
    if spec.provider == "deepseek":
        api_key = _require_env("DEEPSEEK_API_KEY")
        backend = OpenAICompatibleBackend(
            api_key=api_key,
            url=_env("DEEPSEEK_BASE_URL", "https://api.deepseek.com") + "/chat/completions",
            model=spec.model,
        )
        return RemoteLLMAI(spec, backend)
    if spec.provider == "gemini":
        api_key = _require_env("GEMINI_API_KEY")
        backend = OpenAICompatibleBackend(
            api_key=api_key,
            url=_env("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai") + "/chat/completions",
            model=spec.model,
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
        )
        return RemoteLLMAI(spec, backend)
    if spec.provider == "ollama":
        backend = OllamaBackend(
            url=_env("OLLAMA_BASE_URL", "http://localhost:11434") + "/api/chat",
            model=spec.model,
        )
        return RemoteLLMAI(spec, backend)
    if spec.provider == "bedrock":
        region_name = _first_present_env("AWS_REGION", "AWS_DEFAULT_REGION", "aws_region")
        if not region_name:
            raise ValueError("Missing AWS region. Set AWS_REGION, AWS_DEFAULT_REGION, or aws_region.")
        backend = BedrockClaudeBackend(model_id=spec.model, region_name=region_name)
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
        "role": view.get("role"),
        "hand": view.get("hand"),
        "hand_text": view.get("hand_text"),
        "remaining_counts": view.get("remaining_counts"),
        "highest_bid": view.get("highest_bid"),
        "bids": view.get("bids"),
        "last_combo": view.get("last_combo"),
        "bottom_cards": view.get("bottom_cards"),
        "recent_history": list(view.get("history", []))[-12:],
    }
    if "all_hands" in view:
        summarized["all_hands"] = view["all_hands"]
    return summarized


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
        raise ValueError(f"model did not return valid JSON: {text[:300]}")


def _coerce_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _truncate_reason(value: Any) -> str:
    text = str(value or "").strip().replace("\n", " ")
    return text[:160]


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
