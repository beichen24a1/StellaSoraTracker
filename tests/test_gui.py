import unittest

from stellasora_toolkit.gacha_stats import FiveStarPull, PoolStats
from stellasora_toolkit.gui import StellaSoraApp


class GuiTests(unittest.TestCase):
    def test_up_name_comparison_normalizes_parentheses_and_spaces(self):
        self.assertTrue(StellaSoraApp._same_item_name("薇洛（盛夏）", "薇洛(盛夏)"))
        self.assertFalse(StellaSoraApp._same_item_name("归途", "鹿鸣"))

    def test_pity_colors_use_green_yellow_and_red_ranges(self):
        self.assertEqual(StellaSoraApp._pity_color(30), "#50c69f")
        self.assertEqual(StellaSoraApp._pity_color(31), "#e7c65e")
        self.assertEqual(StellaSoraApp._pity_color(61), "#df654f")

    def test_pity_bar_uses_the_160_pull_guarantee_scale(self):
        self.assertEqual(StellaSoraApp._pity_bar_width(120, 500), 375)
        self.assertEqual(StellaSoraApp._pity_bar_width(80, 500), 250)
        self.assertEqual(StellaSoraApp._pity_bar_width(160, 500), 500)

    def test_disc_pity_bar_uses_the_120_pull_guarantee_scale(self):
        self.assertEqual(StellaSoraApp._pity_bar_width(60, 500, 120), 250)
        self.assertEqual(StellaSoraApp._pity_bar_width(90, 500, 120), 375)
        self.assertEqual(StellaSoraApp._pity_bar_width(120, 500, 120), 500)

    def test_limited_pool_up_average_ignores_off_banner_five_stars(self):
        pool = PoolStats(
            gid=0,
            total_pulls=240,
            start_time=0,
            end_time=0,
            five_stars=(
                FiveStarPull(133, "traveler", "夏花", 80, 0, 80, 11133),
                FiveStarPull(110, "traveler", "安可", 70, 0, 150, 11133),
                FiveStarPull(133, "traveler", "夏花", 90, 0, 240, 11133),
            ),
        )
        self.assertEqual(StellaSoraApp._up_average_pulls(pool), 120)

    def test_limited_pool_without_up_has_no_up_average(self):
        pool = PoolStats(
            gid=0,
            total_pulls=80,
            start_time=0,
            end_time=0,
            five_stars=(FiveStarPull(110, "traveler", "安可", 80, 0, 80, 11133),),
        )
        self.assertIsNone(StellaSoraApp._up_average_pulls(pool))
