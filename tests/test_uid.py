import unittest

from stellasora_toolkit.uid import (
    UID_LABEL_PREFIXES,
    UID_PREFIX_UTF16,
    read_game_uid_from_process,
)


class _Memory:
    def __init__(self, label="UID:123456789"):
        self.label = label

    def regions(self):
        return []

    def scan(self, pattern):
        if (pattern, "utf-16le") in UID_LABEL_PREFIXES:
            return iter([0x1000])
        return iter(())

    def try_read(self, address, size):
        del address
        return (self.label + "\x00").encode("utf-16le").ljust(size, b"\x00")[:size]


class _Utf8Memory(_Memory):
    def scan(self, pattern):
        if (pattern, "utf-8") in UID_LABEL_PREFIXES:
            return iter([0x2000])
        return iter(())

    def try_read(self, address, size):
        del address
        return self.label.encode("utf-8").ljust(size, b"\x00")[:size]


class UidTests(unittest.TestCase):
    def test_reads_utf16_uid_label(self):
        self.assertEqual(read_game_uid_from_process(_Memory()), "123456789")

    def test_reads_localized_utf16_uid_labels(self):
        for label in ("UID：123456789", "UID: 123456789", "UID ： 123456789"):
            with self.subTest(label=label):
                self.assertEqual(read_game_uid_from_process(_Memory(label)), "123456789")

    def test_reads_utf8_uid_label_with_full_width_colon(self):
        self.assertEqual(
            read_game_uid_from_process(_Utf8Memory("UID：123456789")), "123456789"
        )

    def test_conflicting_accounts_are_not_decided_by_frequency(self):
        class ConflictingMemory(_Memory):
            def scan(self, pattern):
                return iter([0x1000, 0x2000, 0x3000]) if pattern == UID_PREFIX_UTF16 else iter(())

            def try_read(self, address, size):
                value = "UID:987654321" if address == 0x3000 else "UID:123456789"
                return (value + "\x00").encode("utf-16le").ljust(size, b"\x00")[:size]

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
