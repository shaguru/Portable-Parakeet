"""Regression cases for removing fillers without deleting intended words."""
import unittest

from parakeet_dictation import clean_transcript


class CleanupTests(unittest.TestCase):
    def test_removes_clear_fillers(self):
        cases = {
            "Like, I think we should go.": "I think we should go.",
            "I was, like, thinking about it.": "I was thinking about it.",
            "We should, like, go home.": "We should go home.",
            "And like, then we left.": "And then we left.",
            "Done. Like, we can go now.": "Done. we can go now.",
            "I like don't know.": "I don't know.",
            "I was like thinking about it.": "I was thinking about it.",
            "They were like going home.": "They were going home.",
            "We like want to leave.": "We want to leave.",
            "Um, I was, like, thinking, uh, about it.": "I was thinking about it.",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(clean_transcript(source), expected)

    def test_preserves_intended_like(self):
        cases = [
            "I like this idea.", "I like swimming.", "I don't like this.",
            "I don't, like, this.", "It's, like, a bird.",
            "That thing is like a bird.", "That thing is, like, a bird.",
            "It looks, like, rain.", "Something, like, this.",
            "I would, like, to go.", "I, like, pizza.",
            "I like, this idea.", "Like I said, we should go.",
            "Things, like, painting and hiking.",
            'He was like, "What happened?"',
            'The word "like" appears here.',
            "I dislike that, but it's likely to work.",
        ]
        for source in cases:
            with self.subTest(source=source):
                self.assertEqual(clean_transcript(source), source)

    def test_existing_hesitation_cleanup(self):
        self.assertEqual(clean_transcript("The umbrella is, um, blue."), "The umbrella is blue.")
        self.assertEqual(clean_transcript("Er... thermal error"), "thermal error")


if __name__ == "__main__":
    unittest.main()
