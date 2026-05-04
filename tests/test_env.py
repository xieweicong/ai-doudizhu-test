import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from doudizhu.env import load_dotenv


class EnvTest(unittest.TestCase):
    def test_load_dotenv_sets_missing_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text(
                "DEEPSEEK_API_KEY=test-key\n"
                "OPENROUTER_MODEL=deepseek/test\n"
                "export AWS_REGION=us-east-1\n",
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {}, clear=True):
                loaded = load_dotenv(env_path)
                self.assertEqual(loaded, env_path)
                self.assertEqual(os.environ["DEEPSEEK_API_KEY"], "test-key")
                self.assertEqual(os.environ["OPENROUTER_MODEL"], "deepseek/test")
                self.assertEqual(os.environ["AWS_REGION"], "us-east-1")

    def test_load_dotenv_does_not_override_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text("DEEPSEEK_API_KEY=file-key\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "shell-key"}, clear=True):
                load_dotenv(env_path)
                self.assertEqual(os.environ["DEEPSEEK_API_KEY"], "shell-key")


if __name__ == "__main__":
    unittest.main()
