import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from stellasora_toolkit.account_guard import (
    SESSION_DIRECTORY,
    AccountSafetyError,
    block_process_session,
    check_account_records,
    check_process_account,
    session_uid,
)


UID_A = "100000001"
UID_B = "100000002"


def record(timestamp, ids=None, gid=1201):
    return {"Gid": gid, "Time": timestamp, "Ids": ids or [101]}


class ProcessAccountGuardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def session_path(self, pid=20, creation_time=100):
        return self.root / SESSION_DIRECTORY / f"{pid}-{creation_time}.json"

    def test_first_uid_is_immutable_for_same_game_session(self):
        check_process_account(self.root, 20, 100, UID_A)
        path = self.session_path()
        before = path.read_bytes()
        check_process_account(self.root, 20, 100, UID_A)
        self.assertEqual(path.read_bytes(), before)
        with self.assertRaises(AccountSafetyError):
            check_process_account(self.root, 20, 100, UID_B)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(json.loads(before)["uid"], UID_A)
        self.assertTrue(path.with_suffix(".blocked").is_file())

    def test_switching_back_does_not_unblock_session(self):
        check_process_account(self.root, 20, 100, UID_A)
        with self.assertRaises(AccountSafetyError):
            check_process_account(self.root, 20, 100, UID_B)
        for uid in (UID_A, UID_B):
            with self.subTest(uid=uid), self.assertRaises(AccountSafetyError):
                check_process_account(self.root, 20, 100, uid)

    def test_session_uid_reads_the_already_verified_uid(self):
        self.assertEqual(session_uid(self.root, 20, 100), "")
        check_process_account(self.root, 20, 100, UID_A)
        self.assertEqual(session_uid(self.root, 20, 100), UID_A)
        self.assertEqual(session_uid(self.root, 20, 200), "")  # 另一个游戏进程

    def test_block_survives_fresh_python_process(self):
        check_process_account(self.root, 20, 100, UID_A)
        before = self.session_path().read_bytes()
        code = "\n".join(
            [
                "import sys",
                "from pathlib import Path",
                "from stellasora_toolkit.account_guard import AccountSafetyError, check_process_account",
                "try:",
                "    check_process_account(Path(sys.argv[1]), 20, 100, sys.argv[2])",
                "except AccountSafetyError:",
                "    sys.exit(0)",
                "sys.exit(1)",
            ]
        )
        for uid in (UID_B, UID_A):
            with self.subTest(uid=uid):
                result = subprocess.run(
                    [sys.executable, "-c", code, str(self.root), uid],
                    cwd=Path(__file__).resolve().parents[1],
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(self.session_path().read_bytes(), before)
                self.assertTrue(self.session_path().with_suffix(".blocked").is_file())

    def test_independent_processes_keep_separate_first_uids(self):
        check_process_account(self.root, 20, 100, UID_A)
        check_process_account(self.root, 30, 100, UID_B)
        check_process_account(self.root, 20, 100, UID_A)
        block_process_session(self.root, 20, 100)
        check_process_account(self.root, 30, 100, UID_B)
        self.assertEqual(json.loads(self.session_path().read_bytes())["uid"], UID_A)
        self.assertEqual(json.loads(self.session_path(30).read_bytes())["uid"], UID_B)

    def test_pid_reuse_with_new_creation_time_is_a_new_session(self):
        check_process_account(self.root, 20, 100, UID_A)
        block_process_session(self.root, 20, 100)
        check_process_account(self.root, 20, 200, UID_B)
        with self.assertRaises(AccountSafetyError):
            check_process_account(self.root, 20, 100, UID_A)
        self.assertEqual(json.loads(self.session_path(20, 200).read_bytes())["uid"], UID_B)

    def test_orphan_block_without_bound_uid_is_cleared(self):
        """没有绑定过 UID 的 .blocked 是旧版临时失败留下的, 不能锁死整个会话。"""
        block_process_session(self.root, 20, 100)
        self.assertFalse(self.session_path().exists())
        check_process_account(self.root, 20, 100, UID_A)
        self.assertFalse(self.session_path().with_suffix(".blocked").exists())
        self.assertEqual(json.loads(self.session_path().read_bytes())["uid"], UID_A)
        check_process_account(self.root, 20, 200, UID_B)

    def test_corrupt_session_marker_fails_closed_without_rewriting(self):
        invalid_states = [
            b"broken json",
            b"[]",
            b"null",
            b'{}',
            b'{"version": 2, "uid": "100000001"}',
            b'{"version": true, "uid": "100000001"}',
            b'{"version": 1.0, "uid": "100000001"}',
            b'{"version": 1, "uid": 100000001}',
            b'{"version": 1, "uid": "../other"}',
        ]
        for index, content in enumerate(invalid_states, 1):
            with self.subTest(content=content):
                path = self.session_path(20, index)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                with self.assertRaises(AccountSafetyError):
                    check_process_account(self.root, 20, index, UID_A)
                self.assertEqual(path.read_bytes(), content)

    def test_invalid_process_identity_and_uid_do_not_create_state(self):
        cases = [
            (0, 100, UID_A),
            (True, 100, UID_A),
            (20, 0, UID_A),
            (20, 100.0, UID_A),
            (20, True, UID_A),
            (20, 100, "../other"),
            (20, 100, 100000001),
        ]
        for args in cases:
            with self.subTest(args=args), self.assertRaises(AccountSafetyError):
                check_process_account(self.root, *args)
        self.assertEqual(list(self.root.iterdir()), [])


class RecordAccountGuardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.shared = [record(100, [101]), record(101, [102]), record(102, [103])]

    def write_archive(self, uid, categories):
        path = self.root / f"{uid}.json"
        path.write_text(
            json.dumps({"version": 1, "uid": uid, "categories": categories}, indent=2),
            encoding="utf-8",
        )
        return path

    def file_bytes(self):
        return {path.name: path.read_bytes() for path in self.root.iterdir() if path.is_file()}

    def test_identical_archives_rejected_without_mutating_files_or_input(self):
        categories = {1: self.shared}
        self.write_archive(UID_A, categories)
        self.write_archive(UID_B, categories)
        before = self.file_bytes()
        original = copy.deepcopy(categories)
        for uid in (UID_A, UID_B):
            with self.subTest(uid=uid), self.assertRaises(AccountSafetyError):
                check_account_records(self.root, uid, categories)
        self.assertEqual(self.file_bytes(), before)
        self.assertEqual(categories, original)

    def test_anniversary_records_participate_in_cross_account_checks(self):
        groups = [record(100 + index, [114, 112], gid=1001) for index in range(3)]
        self.write_archive(UID_B, {"6": groups})
        current = {6: groups}
        original = copy.deepcopy(current)
        before = self.file_bytes()
        with self.assertRaisesRegex(AccountSafetyError, "3 条"):
            check_account_records(self.root, UID_A, current)
        self.assertEqual(current, original)
        self.assertEqual(self.file_bytes(), before)

    def test_nonoverlapping_anniversary_history_does_not_block(self):
        self.write_archive(UID_B, {"6": [record(100, [114], gid=1001)]})
        before = self.file_bytes()
        check_account_records(self.root, UID_A, {6: [record(200, [155], gid=1001)]})
        self.assertEqual(self.file_bytes(), before)

    def test_cross_account_overlap_spanning_anniversary_and_old_categories_blocks(self):
        categories = {1: self.shared[:2], 6: [record(102, [114], gid=1001)]}
        self.write_archive(UID_B, categories)
        before = self.file_bytes()
        with self.assertRaises(AccountSafetyError):
            check_account_records(self.root, UID_A, categories)
        self.assertEqual(self.file_bytes(), before)

    def test_three_matching_batches_at_two_times_rejected(self):
        shared = [record(100, [101]), record(100, [102]), record(101, [103])]
        self.write_archive(UID_B, {"1": shared})
        with self.assertRaises(AccountSafetyError):
            check_account_records(self.root, UID_A, {1: shared})

    def test_subset_in_either_direction_rejected(self):
        larger = self.shared + [record(200, [999])]
        for current, other in ((self.shared, larger), (larger, self.shared)):
            with self.subTest(current_size=len(current)):
                self.write_archive(UID_B, {"1": other})
                before = self.file_bytes()
                with self.assertRaises(AccountSafetyError):
                    check_account_records(self.root, UID_A, {1: current})
                self.assertEqual(self.file_bytes(), before)

    def test_one_stale_category_is_detected_among_other_changed_categories(self):
        self.write_archive(UID_B, {"1": [record(200, [201])], "2": self.shared})
        current = {1: [record(300, [301])], 2: self.shared, 3: [record(400, [401])]}
        with self.assertRaises(AccountSafetyError):
            check_account_records(self.root, UID_A, current)

    def test_matching_batches_can_span_multiple_categories(self):
        categories = {1: self.shared[:2], 2: self.shared[2:]}
        self.write_archive(UID_B, categories)
        with self.assertRaises(AccountSafetyError):
            check_account_records(self.root, UID_A, categories)

    def test_at_most_two_matching_batches_do_not_block(self):
        self.write_archive(UID_B, {1: self.shared})
        before = self.file_bytes()
        for count in (1, 2):
            with self.subTest(count=count):
                check_account_records(self.root, UID_A, {1: self.shared[:count]})
        self.assertEqual(self.file_bytes(), before)

    def test_three_same_second_batches_do_not_block(self):
        shared = [record(100, [101]), record(100, [102]), record(100, [103])]
        self.write_archive(UID_B, {1: shared})
        check_account_records(self.root, UID_A, {1: shared})

    def test_repeated_copies_of_one_batch_do_not_inflate_overlap(self):
        shared = [record(100, [101])] * 20 + [record(101, [102])] * 20
        self.write_archive(UID_B, {1: shared})
        check_account_records(self.root, UID_A, {1: shared})

    def test_other_times_results_pools_and_categories_are_not_equal(self):
        original = [record(100 + index, [101, 102]) for index in range(3)]
        self.write_archive(UID_B, {1: original})
        cases = [
            {1: [record(200 + index, [101, 102]) for index in range(3)]},
            {1: [record(100 + index, [101, 999]) for index in range(3)]},
            {1: [record(100 + index, [102, 101]) for index in range(3)]},
            {1: [record(100 + index, [101, 102], gid=1202) for index in range(3)]},
            {2: original},
        ]
        before = self.file_bytes()
        for categories in cases:
            with self.subTest(categories=categories):
                check_account_records(self.root, UID_A, categories)
        self.assertEqual(self.file_bytes(), before)

    def test_empty_histories_are_not_cross_account_matches(self):
        self.write_archive(UID_B, {"1": [], "2": [], "3": [], "4": []})
        before = self.file_bytes()
        check_account_records(self.root, UID_A, {})
        check_account_records(self.root, UID_A, {1: [], 2: [], 3: [], 4: []})
        check_account_records(self.root, UID_A, {1: self.shared})
        self.assertEqual(self.file_bytes(), before)

    def test_same_uid_archive_and_non_uid_files_are_not_other_accounts(self):
        self.write_archive(UID_A, {1: self.shared})
        for name in ("ui_settings.json", "rem_upload_state.json", "123.json", "notes-100000002.json"):
            (self.root / name).write_bytes(b"not an account archive")
        before = self.file_bytes()
        check_account_records(self.root, UID_A, {1: self.shared})
        self.assertEqual(self.file_bytes(), before)

    def test_malformed_sibling_archive_blocks_without_rewriting(self):
        malformed = [
            b"broken json",
            b"[]",
            b'{"uid":"100000003","categories":{}}',
            b'{"uid":"100000002"}',
            b'{"uid":"100000002","categories":{"5":[]}}',
            b'{"uid":"100000002","categories":{"1":{}}}',
            b'{"uid":"100000002","categories":{"1":[null]}}',
            b'{"uid":"100000002","categories":{"1":[{"Gid":1,"Time":0,"Ids":[1]}]}}',
            b'{"uid":"100000002","categories":{"1":[{"Gid":1,"Time":1,"Ids":[]}]}}',
            b'{"uid":"100000002","categories":{"1":[{"Gid":1,"Time":1,"Ids":[true]}]}}',
        ]
        for content in malformed:
            with self.subTest(content=content):
                (self.root / f"{UID_B}.json").write_bytes(content)
                before = self.file_bytes()
                with self.assertRaises(AccountSafetyError):
                    check_account_records(self.root, UID_A, {1: self.shared})
                self.assertEqual(self.file_bytes(), before)

    def test_malformed_current_records_block_without_touching_archive(self):
        self.write_archive(UID_B, {1: self.shared})
        cases = [
            [],
            {5: []},
            {1: {}},
            {1: [None]},
            {1: [{"Gid": True, "Time": 100, "Ids": [101]}]},
            {1: [{"Gid": 1201, "Time": 100.0, "Ids": [101]}]},
            {1: [{"Gid": 1201, "Time": 100, "Ids": [0]}]},
        ]
        before = self.file_bytes()
        for categories in cases:
            with self.subTest(categories=categories), self.assertRaises(AccountSafetyError):
                check_account_records(self.root, UID_A, categories)
        self.assertEqual(self.file_bytes(), before)


if __name__ == "__main__":
    unittest.main()
