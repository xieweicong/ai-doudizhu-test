import unittest

from doudizhu.game import PlayRecord
from doudizhu.web_live import _to_jsonable, display_player_name


class WebLiveTest(unittest.TestCase):
    def test_to_jsonable_converts_dataclass_and_tuple(self):
        record = PlayRecord(
            turn=1,
            player=0,
            role="landlord",
            cards=("3", "BJ"),
            combo="对子",
            remaining=15,
        )
        payload = _to_jsonable({"record": record})
        self.assertEqual(payload["record"]["cards"], ["3", "BJ"])
        self.assertEqual(payload["record"]["turn"], 1)

    def test_display_player_name_shortens_long_names(self):
        name = "P0:openrouter@some-provider/some-very-long-model-name"
        display = display_player_name(name, max_length=24)
        self.assertLessEqual(len(display), 24)
        self.assertIn("...", display)

    def test_display_player_name_keeps_short_names(self):
        self.assertEqual(display_player_name("P0:deepseek"), "P0:deepseek")


if __name__ == "__main__":
    unittest.main()
