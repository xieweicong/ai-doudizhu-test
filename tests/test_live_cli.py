import io
import unittest
from contextlib import redirect_stdout
from random import Random

from doudizhu.ai import RandomAI
from doudizhu.cli import _print_live_event
from doudizhu.game import BidRecord, Player


class LiveCliTest(unittest.TestCase):
    def test_print_live_event_for_bid(self):
        players = [
            Player(0, "P0:random", RandomAI(Random(1))),
            Player(1, "P1:random", RandomAI(Random(2))),
            Player(2, "P2:random", RandomAI(Random(3))),
        ]
        out = io.StringIO()
        with redirect_stdout(out):
            _print_live_event("bid_thinking", {"player": 0, "valid_bids": [0, 1, 2], "highest_bid": 0}, players, False)
            _print_live_event("bid_result", {"record": BidRecord(player=0, bid=1, reason="ok")}, players, True)
        text = out.getvalue()
        self.assertIn("思考中", text)
        self.assertIn("叫 1 分", text)

    def test_print_initial_deal_uses_chinese_jokers(self):
        players = [
            Player(0, "P0:random", RandomAI(Random(1))),
            Player(1, "P1:random", RandomAI(Random(2))),
            Player(2, "P2:random", RandomAI(Random(3))),
        ]
        out = io.StringIO()
        with redirect_stdout(out):
            _print_live_event(
                "initial_deal",
                {
                    "hands": {
                        0: ("3", "BJ", "RJ"),
                        1: ("4", "4"),
                        2: ("5", "5"),
                    },
                    "bottom_cards": ("6", "BJ", "RJ"),
                },
                players,
                False,
            )
        text = out.getvalue()
        self.assertIn("小王", text)
        self.assertIn("大王", text)


if __name__ == "__main__":
    unittest.main()
