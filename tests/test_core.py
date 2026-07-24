import unittest

import wttg3_auto_gambler as app


class CoreTests(unittest.TestCase):
    def test_amount_parsing(self):
        self.assertEqual(app.parse_amount("1,234.50"), 1234.5)
        self.assertEqual(app.parse_amount("icon 50.00"), 50)
        self.assertEqual(app.parse_amount("30000"), 300)
        with self.assertRaises(ValueError):
            app.parse_amount("")

    def test_target_requires_three_confirmations(self):
        self.assertTrue(app.target_confirmed([30000, 30010, 40000], 30000))
        self.assertFalse(app.target_confirmed([30000, 29999, 40000], 30000))
        self.assertFalse(app.target_confirmed([30000, 30000], 30000))

    def test_restart_requires_low_balance_and_static_reels(self):
        self.assertTrue(app.should_restart([5, 5, 5], 100, 0))
        self.assertFalse(app.should_restart([5, 5, 5], 100, 10))
        self.assertFalse(app.should_restart([375, 375, 375], 100, 0))


if __name__ == "__main__":
    unittest.main()

