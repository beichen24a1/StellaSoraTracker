"""好感度读取的单元测试 —— 用合成 Lua 内存镜像, 不依赖真实游戏。

内存布局与 lua53 的真实期望一致:
- 表对象: +8 字节 tt_=5, +11 是 lsize_node, +24 是节点数组指针;
- 哈希节点(32 字节): +0 值 TValue, +16 键 TValue;
- 短字符串对象: +8 gc_tag=4, +11 长度, +24 起是内容。

真实游戏里 ``_mapChar`` 的值是"角色ID -> 角色表", 每个角色表带
``nAffinityLevel`` / ``nAffinityExp``; 好感等级配置表每行带
``NeedExp`` / ``AffinityLevel``。这里按同样的形状构造。
"""
import json
import struct
import tempfile
import unittest
from pathlib import Path

from stellasora_toolkit.affinity import Affinity, latest_cache, load_cache, read_affinity, save_cache
from stellasora_toolkit.lua53 import TAG_INTEGER, TAG_SHORT_STRING, TAG_TABLE, Lua53Reader
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

    def regions(self):
        return [MemoryRegion(base=self.base, size=len(self.data))]


class Ref:
    """标记一个值是"指向另一张表的指针"。"""

    def __init__(self, address: int):
        self.address = address


class LuaImage:
    def __init__(self, size: int = 0x8000):
        self.process = FakeProcess(bytearray(size))
        self.lua = Lua53Reader(self.process)
        self._next = 0x1000 + 0x100

    def _alloc(self, size: int) -> int:
        address = self._next
        # 真实 Lua 节点是 32 字节一步, 这里也按 32 对齐, 让"隔壁表"的距离可复现
        self._next += (size + 31) // 32 * 32
        return address

    def _write(self, address: int, payload: bytes) -> None:
        offset = address - self.process.base
        self.process.data[offset:offset + len(payload)] = payload

    def string_object(self, text: str) -> int:
        address = self._alloc(24 + len(text) + 1)
        self._write(address + 8, bytes([4, 0, 0, len(text)]))
        self._write(address + 24, text.encode("utf-8"))
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
            return struct.pack("<Qi", value.address, TAG_TABLE)
        if isinstance(value, str):
            return struct.pack("<Qi", self.string_object(value), TAG_SHORT_STRING)
        if isinstance(value, bool):
            return struct.pack("<qi", 1 if value else 0, 1)
        if isinstance(value, int):
            return struct.pack("<Qi", value, TAG_INTEGER)
        raise TypeError(value)

    def _key(self, key) -> bytes:
        if isinstance(key, str):
            return struct.pack("<Qi", self.string_object(key), TAG_SHORT_STRING)
        return struct.pack("<Qi", int(key), TAG_INTEGER)


class AffinityReaderTests(unittest.TestCase):
    @staticmethod
    def character(image: LuaImage, character_id: int, level: int, exp: int,
                  favorite: bool = False) -> int:
        return image.table({
            "nId": character_id,
            "nAffinityLevel": level,
            "nAffinityExp": exp,
            "bIsFavorite": favorite,
            "tbAffinityQuests": "ignored",
        })

    def test_reads_level_exp_and_need(self):
        image = LuaImage()
        map_char = image.table({
            156: Ref(self.character(image, 156, 65, 6040, True)),
            130: Ref(self.character(image, 130, 12, 1575)),
        })
        image.table({"_mapChar": Ref(map_char), "_mapGachaHistory": Ref(image.table({"a": 1}))})
        image.table({"_mapChar": 12345})  # 值不是表 -> 跳过
        image.table({"Id": 2065, "AffinityLevel": 65, "NeedExp": 33100})
        image.table({"Id": 2012, "AffinityLevel": 12, "NeedExp": 2000})

        rows = read_affinity(image.process)

        self.assertEqual([row.id for row in rows], [156, 130])
        self.assertEqual(rows[0].name, "小禾")
        self.assertEqual((rows[0].level, rows[0].exp, rows[0].need), (65, 6040, 33100))
        self.assertTrue(rows[0].favorite)
        self.assertAlmostEqual(rows[0].ratio, 6040 / 33100, places=3)
        self.assertEqual((rows[1].level, rows[1].exp, rows[1].need), (12, 1575, 2000))

    def test_missing_config_keeps_need_zero(self):
        image = LuaImage()
        map_char = image.table({156: Ref(self.character(image, 156, 65, 6040))})
        image.table({"_mapChar": Ref(map_char)})

        rows = read_affinity(image.process)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].need, 0)
        self.assertEqual(rows[0].ratio, 0.0)

    def test_other_tables_sharing_need_exp_do_not_corrupt_levels(self):
        """角色升级等配置表也有 NeedExp 但没有 AffinityLevel。

        这些行紧挨着好感配置行时, 旧实现会把它们的 NeedExp 错配到旁边好感行的
        等级上, 造成"部分等级的最大经验错误"。用 Id - 等级 的一致性把它们剔掉。
        """
        image = LuaImage()
        map_char = image.table({
            156: Ref(self.character(image, 156, 48, 100)),
            130: Ref(self.character(image, 130, 49, 200)),
            145: Ref(self.character(image, 145, 50, 300)),
        })
        image.table({"_mapChar": Ref(map_char)})
        # 三行真正的好感配置(Id = 2000 + 等级)
        image.table({"Id": 2048, "AffinityLevel": 48, "NeedExp": 33100})
        # 夹在中间的另一张配置表: 只有 Id 和 NeedExp, 没有 AffinityLevel
        image.table({"Id": 120041, "NeedExp": 999999})
        image.table({"Id": 2049, "AffinityLevel": 49, "NeedExp": 34000})
        image.table({"Id": 2050, "AffinityLevel": 50, "NeedExp": 35000})

        rows = {row.level: row.need for row in read_affinity(image.process)}

        self.assertEqual(rows[48], 33100)
        self.assertEqual(rows[49], 34000)
        self.assertEqual(rows[50], 35000)
        self.assertEqual(len(rows), 3)

    def test_raises_when_field_missing(self):
        image = LuaImage()
        image.table({"nId": 156, "nAffinityLevel": 65})

        with self.assertRaises(LookupError) as context:
            read_affinity(image.process)
        self.assertIn("_mapChar", str(context.exception))


class AffinityCacheTests(unittest.TestCase):
    """好感度按 UID 单独存放: exports/<UID>_affinity.json, 与抽卡归档无关。"""

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.directory = Path(self._temp.name)

    def tearDown(self):
        self._temp.cleanup()

    def test_round_trips_entries(self):
        rows = [Affinity(id=156, name="小禾", level=65, exp=6040, need=33100, favorite=True)]
        payload = save_cache(self.directory, "100000001", rows)

        saved = self.directory / "100000001_affinity.json"
        self.assertTrue(saved.is_file())
        self.assertEqual(payload["uid"], "100000001")
        self.assertEqual(payload["entries"][0]["name"], "小禾")

        loaded = load_cache(saved)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["uid"], "100000001")
        self.assertTrue(loaded["updatedAt"])
        self.assertEqual(loaded["entries"][0]["level"], 65)
        self.assertEqual(loaded["entries"][0]["need"], 33100)
        self.assertTrue(loaded["entries"][0]["favorite"])

    def test_unknown_uid_uses_a_separate_file(self):
        save_cache(self.directory, "", [Affinity(id=103, name="琥珀", level=4, exp=650, need=500)])
        self.assertTrue((self.directory / "unverified_affinity.json").is_file())
        self.assertIsNone(load_cache(self.directory / "100000001_affinity.json"))

    def test_latest_cache_returns_newest_file(self):
        save_cache(self.directory, "100000001", [Affinity(id=156, name="小禾", level=65, exp=0, need=33100)])
        save_cache(self.directory, "100000002", [Affinity(id=103, name="琥珀", level=4, exp=0, need=500)])
        newest = latest_cache(self.directory)
        self.assertIsNotNone(newest)
        path, payload = newest
        self.assertTrue(path.name in {"100000001_affinity.json", "100000002_affinity.json"})
        self.assertEqual(payload["entries"][0]["level"], 4)

    def test_missing_or_broken_file_returns_none(self):
        self.assertIsNone(load_cache(self.directory / "100000001_affinity.json"))
        broken = self.directory / "100000001_affinity.json"
        broken.write_text("{not json", encoding="utf-8")
        self.assertIsNone(load_cache(broken))
        broken.write_text(json.dumps({"version": 99}), encoding="utf-8")
        self.assertIsNone(load_cache(broken))


if __name__ == "__main__":
    unittest.main()