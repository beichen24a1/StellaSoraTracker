from pathlib import Path
import unittest

from PIL import Image

from stellasora_toolkit.catalog import (
    FIVE_STAR_DISCS,
    FIVE_STAR_ITEMS,
    FIVE_STAR_TRAVELERS,
    gacha_item_kind,
    gacha_item_name,
    is_five_star_item,
)


ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"


class AnniversaryCatalogTests(unittest.TestCase):
    def test_anniversary_items_have_bundled_names_and_rarity(self):
        expected_items = (
            (162, "\u5c18\u6c99\uff08\u6e90\u521d\uff09", "traveler"),
            (214066, "\u6307\u5f15\u524d\u8def\u7684\u542f\u660e\u661f", "disc"),
        )
        for item_id, name, kind in expected_items:
            with self.subTest(item_id=item_id):
                self.assertEqual(gacha_item_name(item_id), name)
                self.assertEqual(gacha_item_kind(item_id), kind)
                self.assertTrue(is_five_star_item(item_id))
                self.assertIn(item_id, FIVE_STAR_ITEMS)
        self.assertIn(162, FIVE_STAR_TRAVELERS)
        self.assertIn(214066, FIVE_STAR_DISCS)

    def test_new_standard_travelers_remain_five_star(self):
        for item_id in (144, 155):
            with self.subTest(item_id=item_id):
                self.assertEqual(gacha_item_kind(item_id), "traveler")
                self.assertTrue(is_five_star_item(item_id))
                self.assertIn(item_id, FIVE_STAR_TRAVELERS)
                self.assertIn(item_id, FIVE_STAR_ITEMS)

    def test_anniversary_art_is_bundled_and_decodes(self):
        expected_images = (
            ("travelers/162.png", (192, 192)),
            ("discs/214066.png", (512, 512)),
        )
        for filename, size in expected_images:
            with self.subTest(filename=filename):
                with Image.open(ASSETS_DIR / filename) as image:
                    image.load()
                    self.assertEqual(image.format, "PNG")
                    self.assertEqual(image.size, size)
                    self.assertEqual(image.mode, "RGBA")


if __name__ == "__main__":
    unittest.main()
