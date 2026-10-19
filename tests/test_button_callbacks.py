"""按钮回调回归: 点一下必须把"选中的 key"传进去, 而不是 clicked 带的 checked(bool)。

事故: 游戏版本按钮写的是 `lambda k=_key: cb(k)`, 但 clicked(bool) 会把 True/False 顶给 k,
于是 set_active(True) 失败 -> 界面弹回原来的版本, 看起来就是"点不动、选不了、默认国际服"。
"""
import os
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

TEMP_ROOT = Path(__file__).resolve().parent.parent / ".testtmp"


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class ServerButtonsTests(unittest.TestCase):
    """设置页「游戏版本」四个按钮: 每次点击都要精确回调对应的 key。"""

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        from stellasora_toolkit import server_config
        self.server_config = server_config
        self._saved = server_config._active
        server_config.set_active(server_config.SERVER_INTL)     # 复现"默认变成国际服"
        self.directory = TEMP_ROOT / "server_buttons"
        shutil.rmtree(self.directory, ignore_errors=True)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.calls = []

    def tearDown(self):
        from stellasora_toolkit import server_config
        server_config._active = self._saved
        shutil.rmtree(self.directory, ignore_errors=True)

    def _view(self):
        from stellasora_toolkit.ui.views import SettingsView
        view = SettingsView({
            "server_changed": lambda key: self.calls.append(("server", key)),
            "server_auto": lambda: self.calls.append(("auto", None)),
            "open": lambda: None, "copy": lambda: None, "backup": lambda: None,
            "save_uid": lambda _text: None, "read_uid": lambda: None, "share": lambda _text=None: None,
            "account_switch": lambda _key: None, "account_new": lambda: None,
            "account_rename": lambda _key: None, "account_merge": lambda _key: None,
            "account_remove": lambda _key: None,
        })
        view.build(str(self.directory / "archive.json"), "摘要")
        return view

    def test_every_server_button_passes_its_key(self):
        view = self._view()
        try:
            for key in ("cn", "intl", "jp"):
                button = view._server_buttons[key]
                self.calls.clear()
                button.click()                       # 真点一下(以前这里传出去的是 bool)
                self.assertEqual(self.calls, [("server", key)],
                                 f"{key} 按钮没有把 key 传出去: {self.calls}")
        finally:
            view.deleteLater()
            self.app.processEvents()

    def test_clicking_actually_switches_the_active_profile(self):
        """把真实 controller 的槽接上, 确认点击后生效版本真的变了。"""
        from stellasora_toolkit import server_config
        from stellasora_toolkit.ui.views import SettingsView

        def on_changed(key: str) -> None:
            if server_config.set_active(key):
                server_config.save_key(server_config.config_path(self.directory), key, manual=True)
            view.refresh_server_buttons()

        view = SettingsView({
            "server_changed": on_changed, "server_auto": lambda: None,
            "open": lambda: None, "copy": lambda: None, "backup": lambda: None,
            "save_uid": lambda _text: None, "read_uid": lambda: None, "share": lambda _text=None: None,
            "account_switch": lambda _key: None, "account_new": lambda: None,
            "account_rename": lambda _key: None, "account_merge": lambda _key: None,
            "account_remove": lambda _key: None,
        })
        view.build(str(self.directory / "archive.json"), "摘要")
        try:
            view._server_buttons["cn"].click()
            self.assertEqual(server_config.active().key, "cn", "点了国服却没切过去")
            self.assertTrue(view._server_buttons["cn"].isChecked())
            self.assertFalse(view._server_buttons["intl"].isChecked())
            self.assertEqual(server_config.load_key(server_config.config_path(self.directory)), "cn")
            self.assertTrue(server_config.load_manual(server_config.config_path(self.directory)),
                            "手动点选应当记为手动指定, 否则会被自动识别覆盖")

            view._server_buttons["jp"].click()
            self.assertEqual(server_config.active().key, "jp")
        finally:
            view.deleteLater()
            self.app.processEvents()

    def test_auto_button_callback_receives_no_argument(self):
        view = self._view()
        try:
            for button in view.findChildren(type(view._server_buttons["cn"])):
                if button.text() == "自动识别":
                    self.calls.clear()
                    button.click()
                    self.assertEqual(self.calls, [("auto", None)])
                    break
            else:
                self.fail("没找到「自动识别」按钮")
        finally:
            view.deleteLater()
            self.app.processEvents()


class FactorySemanticsTests(unittest.TestCase):
    """工厂的既有语义要保住, 并且要知道哪种写法才安全。"""

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_plain_button_forwards_checked_false(self):
        """非 checkable 按钮的 checked 是 False —— 一参回调会收到它。"""
        from stellasora_toolkit.ui.views import SettingsView
        received = []
        button = SettingsView._btn(object(), "回调", "ghost", lambda checked: received.append(checked))
        button.click()
        self.assertEqual(received, [False])

    def test_checkable_button_forwards_checked_true(self):
        from stellasora_toolkit.ui.beta_views import button
        received = []
        widget = button("回调", lambda checked: received.append(checked))
        widget.setCheckable(True)
        widget.click()
        self.assertEqual(received, [True], "checkable 按钮点下去 checked=True, 会顶掉默认参数")

    def test_keyword_only_argument_survives_the_checked_flag(self):
        """推荐写法: `lambda *, k=默认:` —— checked 传不进去, 默认值安全。"""
        from stellasora_toolkit.ui.views import SettingsView
        received = []
        button = SettingsView._btn(object(), "回调", "ghost",
                                   lambda *, k="cn": received.append(k))
        button.click()
        self.assertEqual(received, ["cn"])

    def test_positional_default_is_shadowed(self):
        """反面教材: `lambda k=默认:` 会被 checked 顶掉(版本按钮的老 bug), 靠测试兜住。"""
        from stellasora_toolkit.ui.views import SettingsView
        received = []
        button = SettingsView._btn(object(), "回调", "ghost", lambda k="cn": received.append(k))
        button.setCheckable(True)
        button.click()
        self.assertEqual(received, [True], "这就是当初那个 bug 的机制, 保留为文档")


if __name__ == "__main__":
    unittest.main()
