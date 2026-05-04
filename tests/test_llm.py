import os
import unittest
from unittest import mock

from doudizhu.ai import create_ai
from doudizhu.combos import analyze_cards
from doudizhu.llm import ParsedLLMSpec, RemoteLLMAI, parse_llm_spec


class FakeBackend:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def generate_json(self, **kwargs):
        self.calls.append(kwargs)
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


if __name__ == "__main__":
    unittest.main()
