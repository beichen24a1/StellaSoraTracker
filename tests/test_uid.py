import unittest

from stellasora_toolkit.uid import read_game_uid_from_process


class _Memory:
    def scan(self, pattern):
        if pattern == "UID:".encode("utf-16le"):
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
                return iter([0x1000, 0x2000, 0x3000]) if pattern == b"UID:" else iter(())

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


if __name__ == "__main__":
    unittest.main()
