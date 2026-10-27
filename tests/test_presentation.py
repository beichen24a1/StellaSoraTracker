"""Business regressions retained from the retired desktop widgets."""
import unittest
from unittest.mock import patch

from stellasora_toolkit.catalog import same_item_name
from stellasora_toolkit.presentation import is_up, overview


class PresentationTests(unittest.TestCase):
    def test_up_name_comparison_normalizes_parentheses_and_spaces(self):
        self.assertTrue(same_item_name('薇洛（盛夏）', '薇洛(盛夏)'))
        self.assertFalse(same_item_name('归途', '鹿鸣'))

    def test_off_banner_five_does_not_reset_limited_up_pity(self):
        ids = [103]*9 + [162] + [103]*4 + [110] + [103]*2
        value = overview([{'Gid': 10162, 'Time': 100, 'Ids': ids}])
        self.assertEqual(value.total_pulls, 17)
        self.assertEqual(value.total_five, 2)
        self.assertEqual(value.category_stats['traveler_limited'].current_pity, 7)

    def test_unknown_banner_still_resets_pity_on_a_five_star(self):
        with patch('stellasora_toolkit.presentation.official_pool_info', return_value=None):
            self.assertTrue(is_up(19999, 162))
            value = overview([{'Gid': 19999, 'Time': 100, 'Ids': [103, 162, 103, 103]}])
        self.assertEqual(value.category_stats['traveler_limited'].current_pity, 2)

    def test_exchange_rewards_do_not_inflate_pull_or_five_star_totals(self):
        value = overview([{'Gid': 10162, 'Time': 1792700000, 'Ids': [103]*119 + [162]}])
        self.assertEqual((value.total_pulls, value.total_five), (120, 1))
        self.assertEqual(value.well_banners, {10162: 120})
        self.assertIn(10162, value.rewards)
