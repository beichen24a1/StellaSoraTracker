"""界面重建后的"死控件"回归测试。

事故: 换主题/重建外壳后, controller 手里的 self._sub 还指向旧 header 的标签,
旧 centralWidget 被 deleteLater() 删掉, 于是 _refresh_server_labels 一 setText 就炸:

    RuntimeError: libshiboken: Internal C++ object (PySide6.QtWidgets.QLabel) already deleted

触发点有三处(后台名称同步回来、切主题、点「自动识别」), 都走 _refresh_server_labels。
这里用离屏 Qt 直接跑一遍, 保证不再复现。
"""
import os
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# 注意: 不要在这里设置 STELLASORA_SERVER —— 进程内环境变量是全局的, 会污染
# server_config 的其它测试(它们假定"环境变量优先"那条规则是干净的)。

TEMP_ROOT = Path(__file__).resolve().parent.parent / ".testtmp"


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class DeadWidgetGuardTests(unittest.TestCase):
    """先删控件, 再调用更新函数 —— 必须安静跳过, 而不是抛 RuntimeError。"""

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_set_text_skips_a_deleted_widget(self):
        import shiboken6
        from PySide6.QtWidgets import QLabel

        from stellasora_toolkit.ui.controller import StellaSoraWindow

        label = QLabel("before")
        shiboken6.delete(label)           # 等价于 C++ 对象已被销毁(界面重建后就是这样)
        self.assertFalse(StellaSoraWindow._alive(label))
        self.assertFalse(StellaSoraWindow._set_text(label, "after"), "死控件不该被写入")

    def test_set_text_writes_a_live_widget(self):
        from PySide6.QtWidgets import QLabel

        from stellasora_toolkit.ui.controller import StellaSoraWindow

        label = QLabel("before")
        self.assertTrue(StellaSoraWindow._set_text(label, "after"))
        self.assertEqual(label.text(), "after")

    def test_set_text_tolerates_none(self):
        from stellasora_toolkit.ui.controller import StellaSoraWindow

        self.assertFalse(StellaSoraWindow._alive(None))
        self.assertFalse(StellaSoraWindow._set_text(None, "x"))


class ShellRebuildTests(unittest.TestCase):
    """真实窗口: 重建外壳 + 换主题 + 后台回调, 都不能再碰死标签。"""

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        self.directory = TEMP_ROOT / "shell_rebuild"
        shutil.rmtree(self.directory, ignore_errors=True)
        self.directory.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def _window(self):
        from stellasora_toolkit.ui.window import StellaSoraApp
        return StellaSoraApp(self.directory, variant="sky", online_sync=False)

    def test_refresh_server_labels_survives_a_rebuild(self):
        import shiboken6

        window = self._window()
        try:
            old_sub = window._sub
            window._mount_shell()                     # 换主题时走的就是这条路径
            self.app.processEvents()
            self.assertIsNot(window._sub, old_sub, "新外壳必须重新绑定副标题")
            # 真实场景里旧 header 随旧 centralWidget 一起被销毁 —— 这里显式销毁它,
            # 复现"引用还在、C++ 对象已删"; 修复前 setText 会抛 already deleted。
            shiboken6.delete(old_sub)
            window._refresh_server_labels()
            self.assertIn("五类卡池与五星记录", window._sub.text())
            # 就算哪天又把 _sub 指回死控件, 也不该崩(只是这一行字不更新)
            window._sub = old_sub
            window._refresh_server_labels()
        finally:
            window.deleteLater()
            self.app.processEvents()

    def test_change_variant_does_not_crash(self):
        window = self._window()
        try:
            window.change_variant("orbit")
            self.app.processEvents()
            self.assertEqual(window.variant, "orbit")
            window._refresh_server_labels()
        finally:
            window.deleteLater()
            self.app.processEvents()

    def test_catalog_done_and_server_auto_do_not_crash(self):
        from stellasora_toolkit.service import Snapshot

        window = self._window()
        try:
            window._apply_snapshot(Snapshot([]))      # 空快照: 只走重画路径
            self.app.processEvents()
            window._on_catalog_done(0)                # 后台名称同步结束
            window._reset_server_auto()               # 设置页「自动识别」
            window._set_busy(True)
            window._set_busy(False)
            window._set_metrics(_stats())             # 新外壳里没有磁贴也不该炸
        finally:
            window.deleteLater()
            self.app.processEvents()


def _stats():
    from stellasora_toolkit.ui.controller import Stats
    return Stats()


if __name__ == "__main__":
    unittest.main()
