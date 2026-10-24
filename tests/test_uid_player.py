import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stellasora_toolkit import service
from stellasora_toolkit.account_guard import AccountSafetyError
from stellasora_toolkit.account_uid import UidSearch
from stellasora_toolkit.account_verification import verified_uid_search
from stellasora_toolkit.lua53 import (
    Lua53Reader,
    TAG_BOOLEAN,
    TAG_FLOAT,
    TAG_INTEGER,
    TAG_NIL,
    TAG_SHORT_STRING,
)
from stellasora_toolkit.process import MemoryRegion
from stellasora_toolkit.uid import AmbiguousUidError, read_game_uid_from_process


class PlayerMemory:
    """Sparse, read-only-process-shaped memory with actual Lua 5.3 objects."""

    def __init__(self):
        self.blocks = {}
        self.next_address = 0x10100
        self.strings = {}
        self.add_region(0x10000, 0x20000)

    def add_region(self, address, size):
        self.blocks[address] = bytearray(size)

    def regions(self):
        return [MemoryRegion(base, len(data), 4) for base, data in sorted(self.blocks.items())]

    def _block(self, address, size):
        for base, data in self.blocks.items():
            if base <= address and address + size <= base + len(data):
                return data, address - base
        raise OSError("unreadable synthetic memory")

    def read(self, address, size):
        data, offset = self._block(address, size)
        return bytes(data[offset:offset + size])

    def try_read(self, address, size):
        try:
            return self.read(address, size)
        except OSError:
            return None

    def is_readable(self, address, size=1):
        return self.try_read(address, size) is not None

    def write(self, address, value):
        data, offset = self._block(address, len(value))
        data[offset:offset + len(value)] = value

    def allocate(self, size):
        address = self.next_address
        self.next_address += (size + 7) & ~7
        self._block(address, size)
        return address

    def scan(self, pattern, regions=None):
        for region in self.regions() if regions is None else regions:
            data = self.read(region.base, region.size)
            start = 0
            while True:
                position = data.find(pattern, start)
                if position < 0:
                    break
                yield region.base + position
                start = position + 1

    def string(self, text):
        if text not in self.strings:
            encoded = text.encode("utf-8")
            address = self.allocate(24 + len(encoded) + 1)
            header = bytearray(24)
            header[8] = 4
            header[11] = len(encoded)
            self.write(address, header + encoded + b"\0")
            self.strings[text] = address
        return self.strings[text]

    def tvalue(self, value, tag):
        if tag == TAG_SHORT_STRING:
            raw = struct.pack("<Q", self.string(value))
        elif tag == TAG_FLOAT:
            raw = struct.pack("<d", value)
        else:
            raw = struct.pack("<q", value)
        return raw + struct.pack("<i", tag) + b"\0" * 4

    def table(self, fields, *, address=None, nodes=None):
        count = 1 << (max(len(fields), 1) - 1).bit_length()
        address = self.allocate(48) if address is None else address
        nodes = self.allocate(count * 32) if nodes is None else nodes
        header = bytearray(48)
        header[8] = 5
        header[11] = count.bit_length() - 1
        struct.pack_into("<Q", header, 24, nodes)
        self.write(address, header)
        for index, (key, (value, tag)) in enumerate(fields.items()):
            self.write(nodes + index * 32, self.tvalue(value, tag))
            self.write(nodes + index * 32 + 16, self.tvalue(key, TAG_SHORT_STRING))
        return address, nodes

    def account(self, uid, *, uid_tag=TAG_INTEGER, overrides=None, omit=(), **locations):
        fields = {
            "_nPlayerId": (uid, uid_tag),
            "_sPlayerNickName": ("test-player", TAG_SHORT_STRING),
            "_nWorldClass": (42, TAG_INTEGER),
            "_nCurEnergy": (63, TAG_INTEGER),
        }
        fields.update(overrides or {})
        for name in omit:
            fields.pop(name)
        return self.table(fields, **locations)

    def label(self, uid, encoding="utf-16le"):
        raw = ("UID:" + uid + "\0").encode(encoding)
        self.write(self.allocate(160), raw)


class PlayerUidTests(unittest.TestCase):
    def test_reads_japanese_player_id_without_ui_label(self):
        memory = PlayerMemory()
        memory.account(300000001)
        self.assertEqual(read_game_uid_from_process(memory), "300000001")

    def test_reads_taiwanese_player_id_without_ui_label(self):
        memory = PlayerMemory()
        memory.account(900000001)
        self.assertEqual(read_game_uid_from_process(memory), "900000001")

    def test_accepts_ascii_digit_string_uid(self):
        memory = PlayerMemory()
        memory.account("900000001", uid_tag=TAG_SHORT_STRING)
        self.assertEqual(read_game_uid_from_process(memory), "900000001")

    def test_multiple_account_tables_and_labels_can_agree(self):
        memory = PlayerMemory()
        memory.account(300000001)
        memory.account("300000001", uid_tag=TAG_SHORT_STRING)
        memory.label("300000001")
        memory.label("300000001", "ascii")
        self.assertEqual(read_game_uid_from_process(memory), "300000001")

    def test_conflicting_account_tables_are_not_chosen_by_frequency(self):
        memory = PlayerMemory()
        memory.account(300000001)
        memory.account(300000001)
        memory.account(900000001)
        with self.assertRaises(AmbiguousUidError):
            read_game_uid_from_process(memory)

    def test_distinct_key_string_objects_preserve_all_uid_candidates(self):
        memory = PlayerMemory()
        memory.account(300000001)
        memory.strings.pop("_nPlayerId")
        memory.account(900000001)
        with self.assertRaises(AmbiguousUidError):
            read_game_uid_from_process(memory)

    def test_player_table_wins_over_stale_ui_label(self):
        """玩家表是当前账号的权威值；旧 UI 标签不能把它顶成"两个 UID"。"""
        memory = PlayerMemory()
        memory.account(300000001)
        memory.label("900000001")
        self.assertEqual(read_game_uid_from_process(memory), "300000001")

    def test_duplicate_player_keys_in_one_snapshot_do_not_choose_first(self):
        memory = PlayerMemory()
        _, nodes = memory.account(300000001, overrides={
            "_retiredPlayerId": (900000001, TAG_INTEGER),
        })
        memory.write(nodes + 4 * 32 + 16, memory.tvalue("_nPlayerId", TAG_SHORT_STRING))
        with self.assertRaises(AmbiguousUidError):
            read_game_uid_from_process(memory)

    def test_missing_account_companion_does_not_identify_uid(self):
        for field in ("_sPlayerNickName", "_nWorldClass", "_nCurEnergy"):
            with self.subTest(field=field):
                memory = PlayerMemory()
                memory.account(300000001, omit=(field,))
                with self.assertRaises(LookupError):
                    read_game_uid_from_process(memory)

    def test_invalid_companion_value_does_not_identify_uid(self):
        invalid = (
            ("_sPlayerNickName", (0, TAG_NIL)),
            ("_sPlayerNickName", (123, TAG_INTEGER)),
            ("_nWorldClass", (0, TAG_NIL)),
            ("_nWorldClass", (-1, TAG_INTEGER)),
            ("_nWorldClass", (42.0, TAG_FLOAT)),
            ("_nCurEnergy", (-1, TAG_INTEGER)),
            ("_nCurEnergy", (1, TAG_BOOLEAN)),
        )
        for field, value in invalid:
            with self.subTest(field=field, value=value):
                memory = PlayerMemory()
                memory.account(300000001, overrides={field: value})
                with self.assertRaises(LookupError):
                    read_game_uid_from_process(memory)

    def test_zero_energy_and_world_class_are_allowed(self):
        memory = PlayerMemory()
        memory.account(300000001, overrides={
            "_nWorldClass": (0, TAG_INTEGER),
            "_nCurEnergy": (0, TAG_INTEGER),
        })
        self.assertEqual(read_game_uid_from_process(memory), "300000001")

    def test_invalid_uid_values_are_ignored(self):
        invalid = (
            (0, TAG_NIL),
            (1, TAG_BOOLEAN),
            (-300000001, TAG_INTEGER),
            (300000001.0, TAG_FLOAT),
            (1234, TAG_INTEGER),
            (1234567890123456, TAG_INTEGER),
            ("300000001 ", TAG_SHORT_STRING),
            ("+300000001", TAG_SHORT_STRING),
            ("3.00000001e8", TAG_SHORT_STRING),
            ("\uff13\uff10\uff10\uff10\uff10\uff10\uff10\uff10\uff11", TAG_SHORT_STRING),
        )
        for value, tag in invalid:
            with self.subTest(value=value, tag=tag):
                memory = PlayerMemory()
                memory.account(value, uid_tag=tag)
                with self.assertRaises(LookupError):
                    read_game_uid_from_process(memory)

    def test_unqualified_player_id_does_not_conflict_with_account(self):
        memory = PlayerMemory()
        memory.table({"_nPlayerId": (900000001, TAG_INTEGER)})
        memory.account(300000001)
        self.assertEqual(read_game_uid_from_process(memory), "300000001")

    def test_orphan_key_node_does_not_identify_uid(self):
        memory = PlayerMemory()
        node = memory.allocate(32)
        memory.write(node, memory.tvalue(300000001, TAG_INTEGER))
        memory.write(node + 16, memory.tvalue("_nPlayerId", TAG_SHORT_STRING))
        with self.assertRaises(LookupError):
            read_game_uid_from_process(memory)

    def test_invalid_table_node_pointer_does_not_identify_uid(self):
        memory = PlayerMemory()
        table, _ = memory.account(300000001)
        memory.write(table + 24, struct.pack("<Q", 0xDEAD0000))
        with self.assertRaises(LookupError):
            read_game_uid_from_process(memory)

    def test_oversized_table_is_rejected_before_reading_entries(self):
        memory = PlayerMemory()
        table, _ = memory.account(300000001)
        memory.write(table + 11, b"\x14")
        with patch("stellasora_toolkit.lua53.Lua53Reader.get_table_field_tvalue") as read_field:
            with self.assertRaises(LookupError):
                read_game_uid_from_process(memory)
            read_field.assert_not_called()

    def test_node_outside_revalidated_live_table_is_not_an_account(self):
        memory = PlayerMemory()
        table, _ = memory.table({
            "_sPlayerNickName": ("test-player", TAG_SHORT_STRING),
            "_nWorldClass": (42, TAG_INTEGER),
            "_nCurEnergy": (63, TAG_INTEGER),
            "_unused": (0, TAG_INTEGER),
            "_nPlayerId": (300000001, TAG_INTEGER),
        })
        original_header = Lua53Reader.table_header

        def live_header(lua, address):
            lsize, array_size, array, nodes = original_header(lua, address)
            return (2 if address == table else lsize), array_size, array, nodes

        with patch.object(Lua53Reader, "table_header", live_header):
            with self.assertRaises(LookupError):
                read_game_uid_from_process(memory)

    def test_large_region_table_header_spans_scan_chunk_boundary(self):
        memory = PlayerMemory()
        base = 0x1000000
        memory.add_region(base, 1024 * 1024 + 0x1000)
        memory.account(300000001, address=base + 1024 * 1024 - 16)
        self.assertEqual(read_game_uid_from_process(memory), "300000001")

    def test_far_account_table_is_not_limited_to_local_allocator_window(self):
        memory = PlayerMemory()
        base = 0x10000000
        memory.add_region(base, 0x1000)
        memory.account(300000001, address=base + 0x100)
        self.assertEqual(read_game_uid_from_process(memory), "300000001")

    def test_uid_conflict_in_distant_region_is_not_ignored(self):
        memory = PlayerMemory()
        memory.account(300000001)
        base = 0x10000000
        memory.add_region(base, 0x1000)
        memory.account(900000001, address=base + 0x100)
        with self.assertRaises(AmbiguousUidError):
            read_game_uid_from_process(memory)

    def test_empty_memory_does_not_invent_an_account(self):
        with self.assertRaises(LookupError):
            read_game_uid_from_process(PlayerMemory())


class RegionalUidServiceTests(unittest.TestCase):
    def test_region_account_change_during_read_never_writes_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(service, "find_process_id", return_value=20),
                patch.object(service, "RemoteProcess") as process,
                patch.object(service, "verified_uid_search", side_effect=[service.UidSearch(uid='300000001'), service.UidSearch(uid='900000001')]),
                patch.object(service, "LuaTableDiscovery") as discovery,
                patch.object(service, "export_all") as export,
            ):
                process.return_value.__enter__.return_value.get_creation_time.return_value = 1000
                discovery.return_value.read_target_field.return_value = {
                    1: [{"Gid": 10162, "Time": 100, "Ids": [162]}],
                }
                with self.assertRaises(AccountSafetyError):
                    service.extract_snapshot(root, process_id=20)
                export.assert_not_called()
                self.assertEqual(list(root.rglob('stellasora_gacha_archive.json')), [])
                self.assertFalse(any(path.stem.isdigit() for path in root.rglob('*.json')))
                self.assertTrue((root / "account_sessions" / "20-1000.blocked").exists())


class VerifiedUidSearchTests(unittest.TestCase):
    def test_player_table_uid_wins_over_generic_lua_uid_field(self):
        """国服实测: Lua 的 nUid 是内部账号 ID, 游戏内玩家表/UID 才是上传用 UID。"""
        with (
            patch(
                'stellasora_toolkit.account_verification.read_game_uid_from_process',
                return_value='100872990',
            ),
            patch(
                'stellasora_toolkit.account_verification.find_account_uid',
                side_effect=AssertionError('玩家表已给出 UID 时不该再采信 nUid'),
            ),
        ):
            result = verified_uid_search(object(), object())
        self.assertEqual(result.uid, '100872990')
        self.assertEqual(result.field_name, '')

    def test_falls_back_to_lua_field_when_player_table_is_missing(self):
        learned = UidSearch(uid='100872990', field_name='_uid')
        with (
            patch(
                'stellasora_toolkit.account_verification.read_game_uid_from_process',
                side_effect=LookupError('no player table'),
            ),
            patch(
                'stellasora_toolkit.account_verification.find_account_uid',
                return_value=learned,
            ),
        ):
            result = verified_uid_search(object(), object())
        self.assertEqual(result.uid, '100872990')
        self.assertEqual(result.field_name, '_uid')

    def test_ambiguous_player_table_is_rejected(self):
        with patch(
            'stellasora_toolkit.account_verification.read_game_uid_from_process',
            side_effect=AmbiguousUidError('two player ids'),
        ), patch(
            'stellasora_toolkit.account_verification.find_account_uid'
        ) as learned:
            with self.assertRaises(AccountSafetyError):
                verified_uid_search(object(), object())
        learned.assert_not_called()


if __name__ == "__main__":
    unittest.main()
