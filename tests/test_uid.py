import unittest
import struct
from types import SimpleNamespace

from test_lua53 import BufferMemory
from stellasora_toolkit.lua53 import TAG_INTEGER, TAG_SHORT_STRING, TAG_BOOLEAN

from stellasora_toolkit.uid import read_game_uid_from_process


class _Memory:
    def scan(self, pattern):
        if pattern == "UID".encode("utf-16le"):
            return iter([0x1000])
        return iter(())

    def try_read(self, address, size):
        del address
        return ("UID:123456789\x00".encode("utf-16le") + b"\x00" * size)[:size]


class UidTests(unittest.TestCase):
    def test_reads_utf16_uid_label(self):
        self.assertEqual(read_game_uid_from_process(_Memory()), "123456789")

    def test_conflicting_accounts_are_not_decided_by_frequency(self):
        class ConflictingMemory(_Memory):
            def scan(self, pattern):
                return iter([0x1000, 0x2000, 0x3000]) if pattern == b"UID" else iter(())

            def try_read(self, address, size):
                value = b"UID:987654321" if address == 0x3000 else b"UID:123456789"
                return value.ljust(size, b"\0")

        with self.assertRaises(LookupError):
            read_game_uid_from_process(ConflictingMemory())

    def test_missing_uid_is_reported(self):
        class EmptyMemory(_Memory):
            def scan(self, pattern):
                return iter(())

        with self.assertRaises(LookupError):
            read_game_uid_from_process(EmptyMemory())

    def test_localized_labels(self):
        for label in ("UID: 900123456", "UID\uff1a900123456", "UID : 300123456"):
            class LabelMemory(_Memory):
                def try_read(self, address, size):
                    return (label + "\0").encode("utf-16le").ljust(size, b"\0")[:size]
            with self.subTest(label=label):
                self.assertEqual(read_game_uid_from_process(LabelMemory()), label[-9:])


class LuaMemory(BufferMemory):
    def scan(self, pattern):
        pos = self.data.find(pattern)
        while pos >= 0:
            yield pos
            pos = self.data.find(pattern, pos + 1)

    def regions(self):
        return [SimpleNamespace(base=0, size=len(self.data))]

    def account(self, slot, uid, field="_uid", tag=TAG_SHORT_STRING, table=None):
        base = 0x100 + slot * 0x400
        table = base if table is None else table
        nodes, key, value = base + 0x80, base + 0x100, base + 0x180
        self.data[table + 8] = 5
        struct.pack_into("<Q", self.data, table + 24, nodes)
        self.string(key, field)
        self.tvalue(nodes + 16, key, TAG_SHORT_STRING)
        if tag == TAG_SHORT_STRING:
            self.string(value, uid)
            self.tvalue(nodes, value, tag)
        else:
            self.tvalue(nodes, uid, tag)


class LuaUidTests(unittest.TestCase):
    def test_lua_without_ui_label(self):
        for field in ("_uid", "_sUid", "_nUid", "uid", "_playerUid"):
            for tag in (TAG_INTEGER, TAG_SHORT_STRING):
                memory = LuaMemory()
                memory.account(0, 900123456 if tag == TAG_INTEGER else "900123456", field, tag)
                with self.subTest(field=field, tag=tag):
                    self.assertEqual(read_game_uid_from_process(memory), "900123456")

    def test_conflicting_values_under_same_field_are_rejected(self):
        memory = LuaMemory()
        memory.account(0, "900123456")
        memory.account(1, "900123456")
        memory.account(2, "900654321")
        with self.assertRaises(LookupError):
            read_game_uid_from_process(memory)

    def test_conflicting_fields_are_rejected(self):
        memory = LuaMemory()
        memory.account(0, "900123456")
        memory.account(1, "900654321", "_sUid")
        with self.assertRaises(LookupError):
            read_game_uid_from_process(memory)

    def test_duplicate_same_uid_is_accepted(self):
        memory = LuaMemory()
        memory.account(0, "900123456")
        memory.account(1, "900123456")
        self.assertEqual(read_game_uid_from_process(memory), "900123456")

    def test_invalid_values_are_rejected(self):
        for value, tag in (("1234", TAG_SHORT_STRING), ("9" * 16, TAG_SHORT_STRING),
                           ("900123456token", TAG_SHORT_STRING), (1, TAG_BOOLEAN)):
            memory = LuaMemory()
            memory.account(0, value, tag=tag)
            with self.subTest(value=value), self.assertRaises(LookupError):
                read_game_uid_from_process(memory)

    def test_unrelated_id_field_is_not_an_account(self):
        memory = LuaMemory()
        memory.account(0, "900123456", "_itemId")
        with self.assertRaises(LookupError):
            read_game_uid_from_process(memory)

    def test_node_without_table_is_rejected(self):
        memory = LuaMemory()
        memory.account(0, "900123456")
        memory.data[0x108] = 0
        with self.assertRaises(LookupError):
            read_game_uid_from_process(memory)

    def test_table_header_crossing_scan_chunk(self):
        memory = LuaMemory(2 * 1024 * 1024)
        memory.account(0, "900123456", table=1024 * 1024 - 24)
        self.assertEqual(read_game_uid_from_process(memory), "900123456")

    def test_utf8_fullwidth_label(self):
        memory = LuaMemory()
        label = "UID\uff1a 900123456\0".encode("utf-8")
        memory.data[0x1800:0x1800 + len(label)] = label
        self.assertEqual(read_game_uid_from_process(memory), "900123456")

    def test_invalid_bytes_are_not_silently_removed(self):
        memory = LuaMemory()
        label = b"UID:900\xff123456\0"
        memory.data[0x1800:0x1800 + len(label)] = label
        with self.assertRaises(LookupError):
            read_game_uid_from_process(memory)

    def test_ui_conflict_does_not_fall_back_to_lua(self):
        memory = LuaMemory()
        memory.account(0, "900123456")
        memory.data[0x1800:0x180e] = b"UID:900123456\0\0"
        memory.data[0x1900:0x190e] = b"UID:900654321\0\0"
        with self.assertRaises(LookupError):
            read_game_uid_from_process(memory)


if __name__ == "__main__":
    unittest.main()
