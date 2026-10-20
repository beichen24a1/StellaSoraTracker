import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from io import BytesIO

from stellasora_toolkit.upload import UPLOAD_STATE_FILENAME, UploadError, mark_upload_success, upload_archive


class _Response:
    status = 201

    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, *_args):
        return self._body


class UploadTests(unittest.TestCase):
    def test_anniversary_upload_preserves_complete_raw_record(self):
        record = {
            "version": 1,
            "uid": "123456789",
            "updatedAt": "2026-10-20T12:00:00Z",
            "categories": {
                "1": [{"Gid": 10162, "Time": 1792487780, "Ids": [162]}],
                "2": [], "3": [], "4": [],
                "6": [{"Gid": 1001, "Time": 1792487790, "Ids": [211005, 112], "NextPackage": ""}],
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "123456789.json"
            archive.write_text(json.dumps(record), encoding="utf-8")
            before = archive.read_bytes()
            with patch("stellasora_toolkit.upload.urlopen", return_value=_Response({"ok": True})) as network:
                upload_archive(archive, "123456789", endpoint="https://example.test/upload")
            self.assertEqual(network.call_count, 1)
            sent = json.loads(network.call_args.args[0].data.decode("utf-8"))
            self.assertEqual(sent["record"], record)
            self.assertEqual(archive.read_bytes(), before)

    def test_anniversary_422_has_server_compatibility_hint_without_retry_or_file_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "123456789.json"
            archive.write_text(json.dumps({"categories": {"6": [{"Gid": 1001, "Time": 1, "Ids": [114]}]}}))
            before = archive.read_bytes()
            error = HTTPError("https://example.test", 422, "invalid", {}, BytesIO(b'{"ok":false,"error":"unknown category"}'))
            with patch("stellasora_toolkit.upload.urlopen", side_effect=error) as network:
                with self.assertRaises(UploadError) as raised:
                    upload_archive(archive, "123456789", endpoint="https://example.test/upload")
            self.assertIn("unknown category", str(raised.exception))
            self.assertIn("周年特选招募分类 6", str(raised.exception))
            self.assertIn("本地归档已保留", str(raised.exception))
            self.assertEqual(network.call_count, 1)
            sent = json.loads(network.call_args.args[0].data.decode("utf-8"))
            self.assertEqual(sent["record"]["categories"], json.loads(before)["categories"])
            self.assertEqual(archive.read_bytes(), before)
            self.assertFalse((Path(directory) / UPLOAD_STATE_FILENAME).exists())

    def test_original_four_category_422_does_not_claim_anniversary_issue(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "123456789.json"
            archive.write_text(json.dumps({"categories": {"1": []}}))
            error = HTTPError("https://example.test", 422, "invalid", {}, BytesIO(b'{"ok":false,"error":"invalid record"}'))
            with patch("stellasora_toolkit.upload.urlopen", side_effect=error):
                with self.assertRaises(UploadError) as raised:
                    upload_archive(archive, "123456789", endpoint="https://example.test/upload")
            self.assertNotIn("分类 6", str(raised.exception))

    def test_upload_sends_uid_and_complete_record(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "123456789.json"
            archive.write_text(
                json.dumps({"version": 1, "updatedAt": "2026-10-04T00:00:00Z", "categories": {"1": []}}),
                encoding="utf-8",
            )
            response = _Response({"ok": True, "bindCommand": "星塔抽卡绑定 123456789"})
            with patch("stellasora_toolkit.upload.urlopen", return_value=response) as open_url:
                result = upload_archive(archive, "123456789", endpoint="https://example.test/upload")

            request = open_url.call_args.args[0]
            body = json.loads(request.data.decode("utf-8"))
            self.assertEqual(body["uid"], "123456789")
            self.assertEqual(body["record"]["uid"], "123456789")
            self.assertEqual(result.bind_command, "星塔抽卡绑定 123456789")

    def test_rejects_missing_categories(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "123456789.json"
            archive.write_text(json.dumps({"version": 1}), encoding="utf-8")
            with self.assertRaises(UploadError):
                upload_archive(archive, "123456789", endpoint="https://example.test/upload")

    def test_first_success_is_persisted_per_uid(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertTrue(mark_upload_success(Path(directory), "123456789"))
            self.assertFalse(mark_upload_success(Path(directory), "123456789"))
            self.assertTrue(mark_upload_success(Path(directory), "987654321"))
            self.assertFalse(mark_upload_success(Path(directory), "123456789"))
            self.assertFalse(mark_upload_success(Path(directory), "987654321"))
            state = json.loads((Path(directory) / UPLOAD_STATE_FILENAME).read_text())
            self.assertEqual(state["uploadedUids"], ["123456789", "987654321"])

    def test_rejects_invalid_uid_version_category_and_groups_before_network(self):
        cases = [
            {"uid": "987654321", "categories": {"1": []}},
            {"version": 2, "categories": {"1": []}},
            {"version": True, "categories": {"1": []}},
            {"categories": {"1": [], "5": []}},
            {"categories": {"1": {}}},
            {"categories": {"1": [{"Gid": True, "Time": 1, "Ids": [1]}]}},
            {"categories": {"1": [{"Gid": 1, "Time": 1, "Ids": []}]}},
        ]
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "123456789.json"
            for record in cases:
                with self.subTest(record=record), patch("stellasora_toolkit.upload.urlopen") as open_url:
                    archive.write_text(json.dumps(record), encoding="utf-8")
                    with self.assertRaises(UploadError):
                        upload_archive(archive, "123456789")
                    open_url.assert_not_called()

    def test_failed_upload_leaves_archive_and_first_upload_state_untouched(self):
        errors = [
            URLError("offline"),
            TimeoutError("timeout"),
            HTTPError("https://example.test", 422, "invalid", {}, BytesIO(b'{"ok":false,"error":"invalid record"}')),
            HTTPError("https://example.test", 429, "limited", {"Retry-After": "600"}, BytesIO(b'{"ok":false}')),
        ]
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "123456789.json"
            archive.write_text(json.dumps({"version": 1, "categories": {"1": []}}), encoding="utf-8")
            original = archive.read_bytes()
            for error in errors:
                with self.subTest(error=error), patch("stellasora_toolkit.upload.urlopen", side_effect=error):
                    with self.assertRaises(UploadError):
                        upload_archive(archive, "123456789")
                    self.assertEqual(archive.read_bytes(), original)
                    self.assertFalse((Path(directory) / UPLOAD_STATE_FILENAME).exists())

    def test_rejects_non_json_and_false_success(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "123456789.json"
            archive.write_text(json.dumps({"categories": {"1": []}}), encoding="utf-8")
            for body in (b'<html>Bad gateway</html>', b'{"ok":false}', b'{"ok":"true"}'):
                response = _Response({})
                response._body = body
                with self.subTest(body=body), patch("stellasora_toolkit.upload.urlopen", return_value=response):
                    with self.assertRaises(UploadError):
                        upload_archive(archive, "123456789")

    def test_rejects_mismatched_filename(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "987654321.json"
            archive.write_text(json.dumps({"categories": {"1": []}}), encoding="utf-8")
            with patch("stellasora_toolkit.upload.urlopen") as open_url:
                with self.assertRaises(UploadError):
                    upload_archive(archive, "123456789")
                open_url.assert_not_called()


if __name__ == "__main__":
    unittest.main()
