import os
import unittest
from unittest import mock

from doudizhu.ai import create_ai
from doudizhu.combos import analyze_cards
from doudizhu.llm import OpenAICompatibleBackend, ParsedLLMSpec, RemoteLLMAI, parse_llm_spec, summarize_view


class FakeBackend:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def generate_json(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class FlakyTextBackend:
    def __init__(self, responses):
        self.responses = list(responses)

    def generate_json(self, **kwargs):
        return self.responses.pop(0)


class LLMTest(unittest.TestCase):
    def test_parse_llm_spec_defaults(self):
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "x"}, clear=False):
            spec = parse_llm_spec("deepseek")
        self.assertEqual(spec.provider, "deepseek")
        self.assertEqual(spec.model, "deepseek-v4-flash")

    def test_parse_openrouter_requires_model(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "OpenRouter requires a model"):
                parse_llm_spec("openrouter")

    def test_parse_provider_defaults(self):
        with mock.patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "x",
                "GEMINI_API_KEY": "x",
                "QWEN_API_KEY": "x",
                "OLLAMA_MODEL": "qwen3:8b",
            },
            clear=False,
        ):
            self.assertEqual(parse_llm_spec("openai").model, "gpt-4.1-mini")
            self.assertEqual(parse_llm_spec("gemini").model, "gemini-2.5-flash")
            self.assertEqual(parse_llm_spec("qwen").model, "qwen-plus")
            self.assertEqual(parse_llm_spec("ollama").model, "qwen3:8b")

    def test_create_ai_recognizes_deepseek(self):
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "token"}, clear=False):
            ai = create_ai("deepseek")
        self.assertTrue(ai.name.startswith("deepseek@"))

    def test_create_ai_recognizes_other_llm_providers(self):
        env = {
            "OPENAI_API_KEY": "token",
            "GEMINI_API_KEY": "token",
            "QWEN_API_KEY": "token",
            "OLLAMA_MODEL": "qwen3:8b",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertTrue(create_ai("openai").name.startswith("openai@"))
            self.assertTrue(create_ai("gemini").name.startswith("gemini@"))
            self.assertTrue(create_ai("qwen").name.startswith("qwen@"))
            self.assertTrue(create_ai("ollama").name.startswith("ollama@"))

    def test_remote_llm_ai_chooses_bid_and_play(self):
        backend = FakeBackend(
            [
                {"bid": 2, "reason": "high cards"},
                {"action": "play", "option_index": 1, "reason": "beat cheaply"},
            ]
        )
        ai = RemoteLLMAI(
            ParsedLLMSpec("deepseek", "deepseek-v4-flash", {}),
            backend,
            name="test-llm",
        )
        bid = ai.choose_bid({"phase": "bid", "hand": ["A", "A"], "hand_text": "A A", "history": []}, [0, 1, 2, 3])
        legal_plays = [analyze_cards(["3"]), analyze_cards(["4"])]
        play = ai.choose_play(
            {"phase": "play", "hand": ["3", "4"], "hand_text": "3 4", "history": []},
            legal_plays,
            can_pass=False,
        )
        self.assertEqual(bid.bid, 2)
        self.assertEqual(play.cards, ("4",))
        self.assertEqual(len(backend.calls), 2)

    def test_summarize_view_keeps_team_and_history_context(self):
        summary = summarize_view(
            {
                "phase": "play",
                "seat": 1,
                "players": {0: "A", 1: "B", 2: "C"},
                "role": "farmer",
                "role_by_player": {0: "landlord", 1: "farmer", 2: "farmer"},
                "my_side": "farmers",
                "landlord": 0,
                "farmers": [1, 2],
                "teammate": 2,
                "opponents": [0],
                "hand": ["6", "7"],
                "hand_text": "6 7",
                "remaining_counts": {0: 2, 1: 2, 2: 1},
                "played_cards_by_player": {0: ["3"], 1: [], 2: ["9"]},
                "my_played_cards": [],
                "current_trick": {"target_player": 2, "target_cards": ["9"]},
                "full_history": [{"turn": 1}, {"turn": 2}],
                "recent_history": [{"turn": 2}],
            }
        )
        self.assertEqual(summary["teammate"], 2)
        self.assertEqual(summary["opponents"], [0])
        self.assertEqual(summary["played_cards_by_player"][2], ["9"])
        self.assertEqual(summary["current_trick"]["target_player"], 2)
        self.assertEqual(summary["full_history"], [{"turn": 1}, {"turn": 2}])

    def test_remote_llm_ai_parses_text_fallbacks(self):
        backend = FlakyTextBackend(
            [
                {"raw_text": "我选择叫 2 分，理由是对子和高牌不错"},
                {"raw_text": "action=play option_index=1 reason=压最小能赢的牌"},
            ]
        )
        ai = RemoteLLMAI(
            ParsedLLMSpec("deepseek", "deepseek-v4-flash", {}),
            backend,
            name="test-llm",
        )
        bid = ai.choose_bid({"phase": "bid", "hand": ["A", "A"], "hand_text": "A A", "history": []}, [0, 1, 2, 3])
        legal_plays = [analyze_cards(["3"]), analyze_cards(["4"])]
        play = ai.choose_play(
            {"phase": "play", "hand": ["3", "4"], "hand_text": "3 4", "history": []},
            legal_plays,
            can_pass=False,
        )
        self.assertEqual(bid.bid, 2)
        self.assertEqual(play.cards, ("4",))

    def test_openai_compatible_backend_retries_without_response_format(self):
        backend = OpenAICompatibleBackend(
            api_key="token",
            url="https://example.com/v1/chat/completions",
            model="test-model",
            include_response_format=True,
        )
        responses = [
            RuntimeError("https://example.com returned HTTP 400: unsupported response_format"),
            {"choices": [{"message": {"content": '{"bid": 1, "reason": "ok"}'}}]},
        ]

        def fake_post_json(url, payload, headers, timeout_seconds):
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        with mock.patch("doudizhu.llm._post_json", side_effect=fake_post_json):
            result = backend.generate_json(
                system_prompt="system",
                user_prompt="user",
                max_tokens=50,
                temperature=0,
            )
        self.assertEqual(result["bid"], 1)

    def test_openai_compatible_backend_retries_when_content_truncated(self):
        backend = OpenAICompatibleBackend(
            api_key="token",
            url="https://example.com/v1/chat/completions",
            model="test-model",
            include_response_format=False,
        )
        responses = [
            {"choices": [{"finish_reason": "length", "message": {"content": ""}}]},
            {"choices": [{"finish_reason": "stop", "message": {"content": '{"bid": 2, "reason": "ok"}'}}]},
        ]

        def fake_post_json(url, payload, headers, timeout_seconds):
            return responses.pop(0)

        with mock.patch("doudizhu.llm._post_json", side_effect=fake_post_json):
            result = backend.generate_json(
                system_prompt="system",
                user_prompt="user",
                max_tokens=120,
                temperature=0,
            )
        self.assertEqual(result["bid"], 2)


if __name__ == "__main__":
    unittest.main()
