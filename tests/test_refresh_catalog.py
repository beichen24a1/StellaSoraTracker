# -*- coding: utf-8 -*-
"""发版前刷新脚本: 名称转义 + 原子写回（review 指出的 P2：名字带引号会写出坏文件）。"""
import ast
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from tools import refresh_catalog

CATALOG = Path(__file__).resolve().parents[1] / "stellasora_toolkit" / "catalog.py"


def missing(**groups):
    payload = {"travelers": [], "five_travelers": [], "discs": [], "five_discs": []}
    payload.update(groups)
    return payload


def entry(item_id, name, kind="traveler", rarity=5):
    return {"id": item_id, "kind": kind, "name": name, "rarity": rarity}


class NameLiteralTests(unittest.TestCase):
    def test_literal_roundtrips_tricky_names(self):
        # 名称来自公开接口，可能带引号/反斜杠/换行；生成的字面量必须还原成原名
        for raw in ('普通名称', 'A "quoted" name', 'back\\slash', 'line\nbreak', '带\r回车', 'emoji ★ 名字'):
            with self.subTest(raw=raw):
                self.assertEqual(eval(refresh_catalog.name_literal(raw)), raw)  # noqa: S307


class RewriteCatalogTests(unittest.TestCase):
    def setUp(self):
        self.source = CATALOG.read_text(encoding="utf-8")

    def test_tricky_names_still_parse_and_verify(self):
        weird = 'A "quoted" name\\with\\backslashes\nand a newline'
        rewritten, applied = refresh_catalog.rewrite_catalog(
            self.source, missing(travelers=[entry(163, weird)], five_travelers=[entry(163, weird)]))
        ast.parse(rewritten)                       # 不能有 SyntaxError
        self.assertEqual([item["id"] for item in applied["travelers"]], [163])
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "catalog.py"
            target.write_text(rewritten, encoding="utf-8", newline="")
            problems = refresh_catalog.verify_catalog(target, [entry(163, weird)])
        self.assertEqual(problems, [], "写回的真实模块必须回显原始名称")

    def test_rewrite_is_idempotent(self):
        payload = missing(five_discs=[entry(214070, "测试秘纹", kind="disc")])
        once, applied = refresh_catalog.rewrite_catalog(self.source, payload)
        self.assertEqual([item["id"] for item in applied["five_discs"]], [214070])
        twice, again = refresh_catalog.rewrite_catalog(once, payload)
        self.assertEqual(twice, once)
        self.assertEqual(again["five_discs"], [], "同一条目第二次不应重复插入")

    def test_plan_then_write_mixed_rarity_batch(self):
        """复审 P2: 低星名称 + 五星条目混在一批里, plan -> 写回 全流程要成功。"""
        fetched = [
            entry(211009, "新三星秘纹", kind="disc", rarity=3),
            entry(214070, "新五星秘纹", kind="disc", rarity=5),
            entry(163, "新五星旅人", kind="traveler", rarity=5),
        ]
        tables = SimpleNamespace(TRAVELER_NAMES={}, DISC_NAMES={},
                                 FIVE_STAR_TRAVELERS=set(), FIVE_STAR_DISCS={})
        missing_entries = refresh_catalog.plan(fetched, tables)
        self.assertEqual([item["id"] for item in missing_entries["discs"]], [211009])
        self.assertEqual([item["id"] for item in missing_entries["five_discs"]], [214070])
        rewritten, applied = refresh_catalog.rewrite_catalog(self.source, missing_entries)
        expected = [item for value in applied.values() for item in value]
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "catalog.py"
            target.write_text(self.source, encoding="utf-8", newline="")
            refresh_catalog.write_catalog_atomic(target, rewritten, expected)
            text = target.read_text(encoding="utf-8")
        self.assertIn('211009: "新三星秘纹",', text)
        self.assertIn('214070: "新五星秘纹",', text)
        self.assertIn('163: "新五星旅人",', text)

    def test_five_star_item_still_must_be_marked_five_star(self):
        # 名字能回显但没登记成五星 → 自检仍要报错（低星放宽不能把五星检查也放掉）
        payload = missing(discs=[entry(211009, "伪五星", kind="disc", rarity=5)])
        rewritten, applied = refresh_catalog.rewrite_catalog(self.source, payload)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "catalog.py"
            target.write_text(rewritten, encoding="utf-8", newline="")
            problems = refresh_catalog.verify_catalog(target, applied["discs"])
        self.assertEqual(problems, ["211009 没有登记成五星"])


class AtomicWriteTests(unittest.TestCase):
    def setUp(self):
        self.source = CATALOG.read_text(encoding="utf-8")

    def test_syntax_error_leaves_file_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "catalog.py"
            target.write_text("original = 1\n", encoding="utf-8")
            with self.assertRaises(SyntaxError):
                refresh_catalog.write_catalog_atomic(target, "broken = (\n", [])
            self.assertEqual(target.read_text(encoding="utf-8"), "original = 1\n")
            self.assertFalse((Path(tmp) / "catalog.py.tmp").exists(), "临时文件不能留在目录里")

    def test_verification_failure_leaves_file_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "catalog.py"
            target.write_text(self.source, encoding="utf-8", newline="")
            before = target.read_text(encoding="utf-8")
            with self.assertRaises(RuntimeError):
                refresh_catalog.write_catalog_atomic(
                    target, self.source, [{"id": 161, "name": "这不是优叶"}])
            self.assertEqual(target.read_text(encoding="utf-8"), before)
            self.assertFalse((Path(tmp) / "catalog.py.tmp").exists())

    def test_successful_write_replaces_file(self):
        payload = missing(five_discs=[entry(214070, "测试秘纹", kind="disc")])
        rewritten, applied = refresh_catalog.rewrite_catalog(self.source, payload)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "catalog.py"
            target.write_text(self.source, encoding="utf-8", newline="")
            refresh_catalog.write_catalog_atomic(target, rewritten, applied["five_discs"])
            text = target.read_text(encoding="utf-8")
            self.assertIn('214070: "测试秘纹",', text)
            self.assertFalse((Path(tmp) / "catalog.py.tmp").exists())


if __name__ == "__main__":
    unittest.main()
