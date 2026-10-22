"""拖入 <uid>.json 直接导入抽卡记录。

用户需求: 把网页版/桌面版导出的 100872990.json 拖进窗口就能导入抽卡信息。
这里锁三件事: 只认 .json/.csv、拖入时接受/释放事件对不对、导入后归档真的合并了。
"""
import json
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QMimeData, QPoint, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QDragEnterEvent, QDropEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from stellasora_toolkit.ui.window import StellaSoraApp  # noqa: E402

TEMP_ROOT = Path(__file__).resolve().parent.parent / ".testtmp"

SHARE = {
    "version": 1,
    "uid": "100872990",
    "updatedAt": "2026-10-22T12:00:00",
    "categories": {
        "1": [{"Gid": 10162, "Time": 1791883135, "Ids": [162, 107]}],
        "3": [{"Gid": 20162, "Time": 1791883200, "Ids": [214066]}],
    },
}


def mime_for(paths) -> QMimeData:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
    return mime


class DropImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.work = (TEMP_ROOT / "drop_case").resolve()
        shutil.rmtree(self.work, ignore_errors=True)
        self.work.mkdir(parents=True, exist_ok=True)
        self.share = self.work / "100872990.json"
        self.share.write_text(json.dumps(SHARE, ensure_ascii=False), encoding="utf-8")
        self.window = StellaSoraApp(self.work / "out", variant="sky", online_sync=False)
        self.window.resize(1000, 700)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        shutil.rmtree(self.work, ignore_errors=True)

    def test_dropped_paths_accepts_json_and_csv_only(self):
        csv = self.work / "records.csv"
        csv.write_text("Gid,Time,Ids\n10162,1791883135,162\n", encoding="utf-8")
        txt = self.work / "notes.txt"
        txt.write_text("x", encoding="utf-8")
        self.assertEqual(StellaSoraApp.dropped_paths(mime_for([self.share, csv])),
                         [self.share, csv])
        self.assertEqual(StellaSoraApp.dropped_paths(mime_for([txt])), [])
        self.assertEqual(StellaSoraApp.dropped_paths(mime_for([self.work])), [], "目录不能当文件")
        self.assertEqual(StellaSoraApp.dropped_paths(None), [])

    def test_drag_enter_accepts_json_and_rejects_others(self):
        mime = mime_for([self.share])          # 必须留引用, 否则 QMimeData 会被回收
        enter = QDragEnterEvent(QPoint(5, 5), Qt.CopyAction, mime,
                               Qt.LeftButton, Qt.NoModifier)
        self.window.dragEnterEvent(enter)
        self.assertTrue(enter.isAccepted())

        txt = self.work / "notes.txt"
        txt.write_text("x", encoding="utf-8")
        mime_txt = mime_for([txt])
        enter2 = QDragEnterEvent(QPoint(5, 5), Qt.CopyAction, mime_txt,
                                Qt.LeftButton, Qt.NoModifier)
        self.window.dragEnterEvent(enter2)
        self.assertFalse(enter2.isAccepted())

    def test_drop_imports_the_share_file(self):
        mime = mime_for([self.share])
        drop = QDropEvent(QPoint(5, 5), Qt.CopyAction, mime,
                          Qt.LeftButton, Qt.NoModifier)
        self.window.dropEvent(drop)
        self.assertTrue(drop.isAccepted())
        archive = next((self.work / "out").rglob("stellasora_gacha_archive.json"))
        payload = json.loads(archive.read_text(encoding="utf-8"))
        self.assertEqual(payload["uid"], "100872990")
        self.assertEqual(sorted(payload["categories"]), ["1", "3"])
        self.assertEqual(payload["categories"]["1"][0]["Gid"], 10162)
        # 分享文件也要同步生成, 名字仍然是 <uid>.json
        share_out = next((self.work / "out").rglob("100872990.json"))
        self.assertEqual(json.loads(share_out.read_text(encoding="utf-8"))["uid"], "100872990")

    def test_dropping_the_same_file_twice_does_not_double_count(self):
        mime = mime_for([self.share])
        for _ in range(2):
            drop = QDropEvent(QPoint(5, 5), Qt.CopyAction, mime,
                              Qt.LeftButton, Qt.NoModifier)
            self.window.dropEvent(drop)
        archive = next((self.work / "out").rglob("stellasora_gacha_archive.json"))
        payload = json.loads(archive.read_text(encoding="utf-8"))
        groups = sum(len(value) for value in payload["categories"].values())
        pulls = sum(len(group.get("Ids") or []) for groups in payload["categories"].values()
                    for group in groups)
        self.assertEqual(groups, 2, "同一份文件重复拖入不应产生重复记录")
        self.assertEqual(pulls, 3)

    def test_drop_on_a_child_widget_still_imports(self):
        """拖放事件先给光标下的子控件; 应用级过滤器要保证照样能导入。"""
        from PySide6.QtWidgets import QApplication, QLabel
        child = self.window.findChild(QLabel)
        self.assertIsNotNone(child)
        mime = mime_for([self.share])
        # 真实拖放是先 DragEnter 再 Drop, 少了前者 Qt 不会派发 Drop
        enter = QDragEnterEvent(QPoint(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(child, enter)
        drop = QDropEvent(QPoint(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(child, drop)
        archive = next((self.work / "out").rglob("stellasora_gacha_archive.json"), None)
        self.assertIsNotNone(archive, "子控件上的拖放也必须导入")
        self.assertEqual(json.loads(archive.read_text(encoding="utf-8"))["uid"], "100872990")

    def test_manual_import_zone_exists_in_topbar(self):
        """顶部有手动导入区域(替代原来的演示按钮)。"""
        zone = getattr(self.window, "import_zone", None)
        self.assertIsNotNone(zone, "顶部栏缺少导入区域")
        self.assertTrue(zone.acceptDrops(), "导入区域应能直接接收拖放")
        self.assertIn("导入", zone.text())

    def test_import_zone_click_opens_file_dialog(self):
        from unittest import mock
        with mock.patch("stellasora_toolkit.ui.window.QFileDialog.getOpenFileName",
                        return_value=("", "")) as dialog:
            self.window.import_zone.click()
        self.assertTrue(dialog.called, "点击导入区域应弹出选择文件对话框")

    def test_zone_drop_imports_the_file(self):
        from PySide6.QtWidgets import QApplication
        zone = self.window.import_zone
        mime = mime_for([self.share])
        enter = QDragEnterEvent(QPoint(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(zone, enter)
        self.assertTrue(enter.isAccepted())
        drop = QDropEvent(QPoint(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(zone, drop)
        archive = next((self.work / "out").rglob("stellasora_gacha_archive.json"), None)
        self.assertIsNotNone(archive)
        self.assertEqual(json.loads(archive.read_text(encoding="utf-8"))["uid"], "100872990")

    def test_demo_toggle_button_is_gone(self):
        """用户要求删掉「演示 · 切换本地」按钮。"""
        labels = [b.text() for b in self.window.findChildren(type(self.window.refresh_button))]
        self.assertFalse(any("演示" in text for text in labels), labels)

    def test_drop_in_demo_mode_is_ignored(self):
        demo = StellaSoraApp(self.work / "demo", variant="sky", demo=True, online_sync=False)
        try:
            mime = mime_for([self.share])
            drop = QDropEvent(QPoint(5, 5), Qt.CopyAction, mime,
                              Qt.LeftButton, Qt.NoModifier)
            demo.dropEvent(drop)
            self.assertFalse(drop.isAccepted(), "演示模式不应该写真实归档")
        finally:
            demo.close()
            demo.deleteLater()


if __name__ == "__main__":
    unittest.main()
