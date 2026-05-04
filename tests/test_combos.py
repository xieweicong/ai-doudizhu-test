import unittest
from collections import Counter

from doudizhu.combos import analyze_cards, can_beat, legal_plays


class ComboTest(unittest.TestCase):
    def test_basic_combos(self):
        self.assertEqual(analyze_cards(["BJ", "RJ"]).kind, "rocket")
        self.assertEqual(analyze_cards(["9", "9", "9", "9"]).kind, "bomb")
        self.assertEqual(analyze_cards(["3", "4", "5", "6", "7"]).kind, "straight")
        self.assertIsNone(analyze_cards(["10", "J", "Q", "K", "A", "2"]))
        self.assertEqual(analyze_cards(["3", "3", "4", "4", "5", "5"]).kind, "pair_straight")
        self.assertEqual(analyze_cards(["3", "3", "3", "4", "4", "4"]).kind, "triple_straight")

    def test_wing_combos(self):
        self.assertEqual(analyze_cards(["3", "3", "3", "4", "4", "4", "7", "8"]).kind, "airplane_single")
        self.assertEqual(
            analyze_cards(["3", "3", "3", "4", "4", "4", "7", "7", "8", "8"]).kind,
            "airplane_pair",
        )
        self.assertEqual(analyze_cards(["9", "9", "9", "9", "3", "4"]).kind, "four_two_singles")
        self.assertEqual(analyze_cards(["9", "9", "9", "9", "3", "3", "4", "4"]).kind, "four_two_pairs")

    def test_comparison(self):
        pair_44 = analyze_cards(["4", "4"])
        pair_55 = analyze_cards(["5", "5"])
        bomb = analyze_cards(["3", "3", "3", "3"])
        rocket = analyze_cards(["BJ", "RJ"])
        self.assertTrue(can_beat(pair_55, pair_44))
        self.assertTrue(can_beat(bomb, pair_55))
        self.assertTrue(can_beat(rocket, bomb))
        self.assertFalse(can_beat(pair_44, pair_55))

    def test_legal_plays(self):
        hand = Counter(["3", "3", "4", "4", "5", "5", "BJ", "RJ"])
        target = analyze_cards(["9", "9", "9", "9"])
        plays = legal_plays(hand, target)
        self.assertEqual([play.kind for play in plays], ["rocket"])


if __name__ == "__main__":
    unittest.main()

