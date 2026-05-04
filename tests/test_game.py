import unittest
from random import Random

from doudizhu.ai import ConservativeAI, GreedyAI, RandomAI
from doudizhu.cards import cards_counter
from doudizhu.combos import analyze_cards
from doudizhu.game import DouDizhuGame, GameConfig, Player, PlayRecord, run_match


class GameTest(unittest.TestCase):
    def test_game_completes(self):
        players = [
            Player(0, "greedy", GreedyAI()),
            Player(1, "conservative", ConservativeAI()),
            Player(2, "random", RandomAI(Random(3))),
        ]
        result = DouDizhuGame(players, GameConfig(seed=7)).play()
        self.assertIn(result.winner, {0, 1, 2})
        self.assertIn(result.winner_side, {"landlord", "farmers"})
        self.assertEqual(sum(result.points.values()), 0)
        self.assertGreater(result.turns, 0)

    def test_match_stats(self):
        players = [
            Player(0, "greedy", GreedyAI()),
            Player(1, "conservative", ConservativeAI()),
            Player(2, "random", RandomAI(Random(4))),
        ]
        report = run_match(players, rounds=3, seed=11)
        self.assertEqual(report["rounds"], 3)
        self.assertEqual(sum(row["games"] for row in report["stats"].values()), 9)

    def test_ai_view_contains_team_and_public_context(self):
        players = [
            Player(0, "greedy", GreedyAI()),
            Player(1, "conservative", ConservativeAI()),
            Player(2, "random", RandomAI(Random(4))),
        ]
        game = DouDizhuGame(players, GameConfig(seed=11))
        game.landlord = 0
        game.farmers = (1, 2)
        game.hands = [
            cards_counter(["3", "4", "5"]),
            cards_counter(["6", "7", "8"]),
            cards_counter(["9", "10", "J"]),
        ]
        game.bottom_cards = ("Q", "K", "A")
        game.plays = [
            PlayRecord(turn=1, player=0, role="landlord", cards=("3",), combo="单张", remaining=2),
            PlayRecord(turn=2, player=1, role="farmer", cards=(), combo="pass", remaining=3),
            PlayRecord(turn=3, player=2, role="farmer", cards=("9",), combo="单张", remaining=2),
        ]
        game.played_cards = ["3", "9"]
        current_trick = game._current_trick_view(analyze_cards(["9"]), last_player=2, can_pass=True)
        view = game._view_for(
            1,
            phase="play",
            turn=4,
            current_player=1,
            can_pass=True,
            last_combo=analyze_cards(["9"]),
            last_player=2,
            current_trick=current_trick,
        )
        self.assertEqual(view["teammate"], 2)
        self.assertEqual(view["opponents"], [0])
        self.assertEqual(view["remaining_counts"], {0: 3, 1: 3, 2: 3})
        self.assertEqual(view["my_played_cards"], [])
        self.assertEqual(view["played_cards_by_player"][0], ["3"])
        self.assertEqual(view["played_cards_by_player"][2], ["9"])
        self.assertEqual(view["current_trick"]["target_player"], 2)
        self.assertEqual(view["current_trick"]["target_cards"], ["9"])
        self.assertEqual(len(view["full_history"]), 3)


if __name__ == "__main__":
    unittest.main()
