import queue
import unittest
from unittest.mock import Mock, patch

from stellasora_toolkit.gacha_stats import FiveStarPull, PoolStats
from stellasora_toolkit.gui import StellaSoraApp
from stellasora_toolkit.upload import UploadResult
from stellasora_toolkit.account_guard import AccountSafetyError


class GuiTests(unittest.TestCase):
    def test_account_protection_keeps_previous_view_and_cleans_up_busy_state(self):
        app = StellaSoraApp.__new__(StellaSoraApp)
        app.root = Mock()
        app.status_var = Mock()
        app._finish_busy = Mock()
        app._apply_snapshot = Mock()
        app.snapshot = previous_snapshot = Mock()
        app.events = queue.Queue()
        app.events.put(("error", AccountSafetyError("account changed")))
        with patch("stellasora_toolkit.gui.messagebox.showwarning") as warning:
            app._poll_events()
        app._finish_busy.assert_called_once()
        app._apply_snapshot.assert_not_called()
        self.assertIs(app.snapshot, previous_snapshot)
        warning.assert_called_once()
        self.assertIn("上次本地记录", warning.call_args.args[1])

    def test_binding_popup_only_depends_on_local_first_success(self):
        app = StellaSoraApp.__new__(StellaSoraApp)
        app.root = Mock()
        app.status_var = Mock()
        app._finish_busy = Mock()
        for first in (True, False):
            for replaced in (True, False):
                result = UploadResult(201, {"ok": True, "replaced": replaced, "bindCommand": "test command"})
                with self.subTest(first=first, replaced=replaced), patch("stellasora_toolkit.gui.messagebox.showinfo") as show:
                    app._handle_upload_complete((result, "123456789", first, None))
                    self.assertEqual(show.call_count, int(first))

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
