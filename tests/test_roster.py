"""角色数据(等级/技能/天赋/纹章)读取的单元测试 —— 合成 Lua 内存镜像, 不依赖真实游戏。

内存布局与 lua53 的期望一致(同 test_affinity.py):
- 表对象 +8=tt_5, +11=lsize_node, +24=节点数组;
- 哈希节点 32 字节: +0 值 TValue, +16 键 TValue;
- 短字符串对象 +8=gc_tag 4, +11=长度, +24 起内容。
"""
import json
import os
import struct
import tempfile
import time
import unittest
from pathlib import Path

from stellasora_toolkit import roster
from stellasora_toolkit.lua53 import Lua53Reader
from stellasora_toolkit.memory import MemoryRegion


class FakeProcess:
    def __init__(self, data: bytearray, base: int = 0x1000):
        self.data = data
        self.base = base

    def read(self, address, size):
        if not self.is_readable(address, size):
            raise OSError("outside buffer")
        offset = address - self.base
        return bytes(self.data[offset:offset + size])

    def try_read(self, address, size):
        try:
            return self.read(address, size)
        except OSError:
            return None

    def is_readable(self, address, size=1):
        return self.base <= address and address + size <= self.base + len(self.data)

    def scan(self, needle, regions=None):
        hits, start = [], 0
        while True:
            index = self.data.find(needle, start)
            if index < 0:
                return hits
            hits.append(self.base + index)
            start = index + 1

    def scan_any(self, patterns, regions=None):
        for pattern in patterns:
            for address in self.scan(pattern):
                yield address, pattern

    def regions(self):
        return [MemoryRegion(base=self.base, size=len(self.data))]


class Ref:
    """标记一个值是"指向另一张表的指针"。"""

    def __init__(self, address: int):
        self.address = address


class LuaImage:
    def __init__(self, size: int = 0x20000):
        self.process = FakeProcess(bytearray(size))
        self.lua = Lua53Reader(self.process)
        self._next = 0x1000 + 0x100

    def _alloc(self, size: int) -> int:
        address = self._next
        self._next += (size + 31) // 32 * 32
        return address

    def _write(self, address: int, payload: bytes) -> None:
        offset = address - self.process.base
        self.process.data[offset:offset + len(payload)] = payload

    def string_object(self, text: str) -> int:
        data = text.encode("utf-8")
        address = self._alloc(24 + len(data) + 1)
        self._write(address + 8, bytes([4, 0, 0, len(data)]))
        self._write(address + 24, data)
        return address

    def table(self, fields: dict) -> int:
        count = max(1, len(fields))
        lsize = 1
        while (1 << lsize) < count:
            lsize += 1
        table = self._alloc(48)
        nodes = self._alloc((1 << lsize) * 32)
        self._write(table + 8, bytes([5]))
        self._write(table + 11, bytes([lsize]))
        self._write(table + 24, struct.pack("<Q", nodes))
        for index, (key, value) in enumerate(fields.items()):
            node = nodes + index * 32
            self._write(node, self._tvalue(value))
            self._write(node + 16, self._key(key))
        return table

    def _tvalue(self, value) -> bytes:
        if isinstance(value, Ref):
            return struct.pack("<Qi", value.address, 0x45)
        if isinstance(value, str):
            return struct.pack("<Qi", self.string_object(value), 0x44)
        if isinstance(value, bool):
            return struct.pack("<qi", 1 if value else 0, 1)
        if isinstance(value, int):
            return struct.pack("<Qi", value, 0x13)
        if isinstance(value, float):
            return struct.pack("<di", value, 3) + b"\x00" * 4
        raise TypeError(value)

    def _key(self, key) -> bytes:
        if isinstance(key, str):
            return struct.pack("<Qi", self.string_object(key), 0x44)
        return struct.pack("<Qi", int(key), 0x13)


def build_world() -> tuple[LuaImage, int]:
    image = LuaImage()
    emblem = image.table({
        "sName": "虔信者尖章",
        "sDesc": "闪烁着虔诚力量的尖章。",
        "sIcon": "Equipment/101/101",
        "nType": 1,
        "nGemId": 101,
        "nGenerateId": 35001,
        "nRefreshId": 35001,
        "bLock": False,
        "tbUpgradeCount": Ref(image.table({1: 0, 2: 0, 3: 1, 4: 0})),
        "tbAlterUpgradeCount": Ref(image.table({1: 0, 2: 0, 3: 0, 4: 0})),
        "tbAffix": Ref(image.table({1: 804, 2: 2603, 3: 2003, 4: 1404})),
        "tbAlterAffix": Ref(image.table({1: 0, 2: 0, 3: 0, 4: 0})),
        "tbSkillAffix": Ref(image.table({})),
        "tbPotentialAffix": Ref(image.table({})),
        "tbRandomAttr": Ref(image.table({
            1: Ref(image.table({"AttrId": 804, "Value": 0.15, "CfgValue": 1500})),
        })),
        "tbSkillAffix": Ref(image.table({
            1: Ref(image.table({"TypeId": 37, "Id": 3702, "AttrTypeFirstSubtype": 3})),
        })),
        "tbPotentialAffix": Ref(image.table({
            1: Ref(image.table({"TypeId": 52, "Id": 5203, "AttrTypeFirstSubtype": 29})),
        })),
    })
    char = image.table({
        "nId": 130,
        "nLevel": 90,
        "nAdvance": 8,
        "bIsFavorite": True,
        "tbSkillLvs": Ref(image.table({1: 1, 2: 1, 3: 10, 4: 8, 5: 1})),
    })
    char_map = image.table({130: Ref(char)})
    talent = image.table({130: Ref(image.table({
        "nAllNormalCount": 11,
        "nMaxNormalCount": 50,
        "nFirstGroup": 13001,
        "tbActiveTalent": Ref(image.table({1300101: True, 1300102: True, 1300116: True})),
    }))})
    fate = image.table({130: Ref(image.table({1: 1300116, 2: 1300232}))})
    alternate = image.table({"sName": "测试纹章·方案2", "nType": 1, "nGemId": 999})
    equipment = image.table({130: Ref(image.table({
        1: Ref(image.table({1: Ref(emblem), 2: Ref(alternate)})),
    }))})
    slots = image.table({
        1: Ref(image.table({"Id": 1, "UnlockLevel": 70})),
        2: Ref(image.table({"Id": 2, "UnlockLevel": 80})),
        3: Ref(image.table({"Id": 3, "UnlockLevel": 90})),
    })
    presets = image.table({130: Ref(image.table({
        1: Ref(image.table({"sName": "方案1", "tbSlot": Ref(image.table({1: 1, 2: 2, 3: 3}))})),
    }))})
    select = image.table({130: 1})
    root = image.table({
        "_mapChar": Ref(char_map),
        "_tbCharTalentNode": Ref(talent),
        "_tbCharFateTalent": Ref(fate),
        "tbCharEquipment": Ref(equipment),
        "tbSlotControl": Ref(slots),
        "tbCharPreset": Ref(presets),
        "tbCharSelectPreset": Ref(select),
    })
    # 同名诱饵: 值不是表, 不能被认成角色表
    image.table({"_mapChar": 12345})
    return image, root


class RosterReaderTests(unittest.TestCase):
    def test_reads_level_skills_talent_and_emblems(self):
        image, _root = build_world()
        rows = roster.read_roster(image.process)

        self.assertEqual([row.id for row in rows], [130])
        hero = rows[0]
        self.assertEqual(hero.name, "多娜")
        self.assertEqual((hero.level, hero.advance), (90, 8))
        self.assertTrue(hero.favorite)
        self.assertEqual(list(hero.skills), [1, 1, 10, 8, 1])
        self.assertEqual((hero.talent_active, hero.talent_max), (11, 50))
        self.assertEqual(list(hero.talent_nodes), [1300101, 1300102, 1300116])
        self.assertEqual(list(hero.fate_nodes), [1300116, 1300232])
        self.assertEqual([slot["unlockLevel"] for slot in hero.slots], [70, 80, 90])

        # 同一槽位刷出的两件都保留, 方案指向的第 1 件标记为装备中
        self.assertEqual(len(hero.emblems), 2)
        emblem = hero.emblems[0]
        self.assertEqual((emblem.slot, emblem.index, emblem.preset, emblem.active), (1, 1, 1, True))
        self.assertEqual(emblem.name, "虔信者尖章")
        self.assertEqual(emblem.type_name, "尖章")
        self.assertEqual(emblem.slot_name, "尖章")
        self.assertEqual((emblem.gem_id, emblem.generate_id), (101, 35001))
        self.assertEqual(list(emblem.affixes), [804, 2603, 2003, 1404])
        self.assertEqual(emblem.attrs[0]["attrId"], 804)
        self.assertEqual(emblem.attrs[0]["value"], 0.15)
        self.assertEqual(emblem.attrs[0]["cfgValue"], 1500)
        self.assertEqual(list(emblem.upgrades), [0, 0, 1, 0])
        self.assertFalse(hero.emblems[1].active)
        self.assertEqual(hero.emblems[1].index, 2)
        self.assertEqual(emblem.skill_affixes[0]["level"], 2)
        self.assertEqual(emblem.potential_affixes[0]["level"], 3)

    def test_skill_affix_uses_skill_type_text(self):
        detail = roster._skill_affix_detail(
            {"TypeId": 37, "Id": 3702, "AttrTypeFirstSubtype": 3},
            {"UIText.Char_Skill_Type_3.1": "援护技能"},
        )
        self.assertEqual(detail["name"], "援护技能等级提升 +2级")

    def test_text_helpers_translate_ids(self):
        texts = {
            "UIText.Enums_Effect_28.1": "暗系穿透",
            "UIText.Enums_Effect_8.1": "暴击伤害",
            "Talent.1070101.1": "攻击强化",
            "Talent.1070101.2": "基础攻击提升<color=#0abec5>&Param1&</color>",
        }
        self.assertEqual(roster._attr_name(texts, {}, 2803), "暗系穿透")
        self.assertEqual(roster._attr_name(texts, {10001: 8}, 10001), "暴击伤害")
        self.assertEqual(roster._attr_name(texts, {}, 999999), "")
        self.assertEqual(roster._clean_text(texts["Talent.1070101.2"]), "基础攻击提升…")

    def test_talent_and_emblems_are_optional(self):
        image = LuaImage()
        char = image.table({"nId": 132, "nLevel": 80, "nAdvance": 5})
        image.table({"_mapChar": Ref(image.table({132: Ref(char)}))})

        rows = roster.read_roster(image.process)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].level, 80)
        self.assertEqual(rows[0].talent_max, 0)
        self.assertEqual(rows[0].emblems, ())
        self.assertEqual(rows[0].slots, ())

    def test_missing_char_table_raises(self):
        image = LuaImage()
        image.table({"unrelated": 1})
        with self.assertRaises(LookupError) as context:
            roster.read_roster(image.process)
        self.assertIn("_mapChar", str(context.exception))


class RosterCacheTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.directory = Path(self._temp.name)

    def tearDown(self):
        self._temp.cleanup()

    def test_round_trips_characters(self):
        image, _root = build_world()
        rows = roster.read_roster(image.process)
        payload = roster.save_cache(self.directory, "100000001", rows)

        saved = self.directory / "100000001_roster.json"
        self.assertTrue(saved.is_file())
        self.assertEqual(payload["uid"], "100000001")

        loaded = roster.load_cache(saved)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["characters"][0]["level"], 90)
        self.assertEqual(loaded["characters"][0]["emblems"][0]["name"], "虔信者尖章")
        self.assertEqual(loaded["characters"][0]["talent"]["active"], 11)
        self.assertTrue(loaded["updatedAt"])

    def test_unknown_uid_uses_a_separate_file(self):
        image, _root = build_world()
        rows = roster.read_roster(image.process)
        roster.save_cache(self.directory, "", rows)
        self.assertTrue((self.directory / "unverified_roster.json").is_file())
        self.assertIsNone(roster.load_cache(self.directory / "100000001_roster.json"))

    def test_latest_cache_returns_newest_file(self):
        image, _root = build_world()
        rows = roster.read_roster(image.process)
        older = self.directory / "100000001_roster.json"
        newer = self.directory / "100000002_roster.json"
        roster.save_cache(self.directory, "100000001", rows)
        roster.save_cache(self.directory, "100000002", rows)
        now = time.time()
        os.utime(older, (now - 10, now - 10))
        os.utime(newer, (now, now))

        newest = roster.latest_cache(self.directory)
        self.assertIsNotNone(newest)
        self.assertEqual(newest[0].name, "100000002_roster.json")

    def test_broken_file_returns_none(self):
        broken = self.directory / "100000001_roster.json"
        broken.write_text("{not json", encoding="utf-8")
        self.assertIsNone(roster.load_cache(broken))
        broken.write_text(json.dumps({"version": 99}), encoding="utf-8")
        self.assertIsNone(roster.load_cache(broken))


if __name__ == "__main__":
    unittest.main()
