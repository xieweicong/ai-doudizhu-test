import unittest
from random import Random

from doudizhu.ai import ConservativeAI, GreedyAI, RandomAI
from doudizhu.game import DouDizhuGame, GameConfig, Player, run_match


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


if __name__ == "__main__":
    unittest.main()

