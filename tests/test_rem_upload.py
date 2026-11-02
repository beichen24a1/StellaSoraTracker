"""上传到蕾姆(Rem)与 hhmx.cn 的接口回归。

两个服务使用同一请求体，POST {uid, record}，无鉴权，成功 {"ok": true}。
蕾姆首次上传提示绑定指令，429 要读 Retry-After；hhmx.cn 用 FastAPI 的 detail 报错。
这里用假 urlopen 覆盖各分支。
"""
import io
import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from stellasora_toolkit import rem_upload  # noqa: E402

TEMP_ROOT = Path(__file__).resolve().parent.parent / ".testtmp"

CATEGORIES = {
    "1": [{"Time": 100, "NextPackage": "", "Gid": 10139, "Ids": [212007, 139]}],
    "2": [],
    "3": [{"Time": 300, "NextPackage": "", "Gid": 20140, "Ids": [214001]}],
    "4": [],
}


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200, headers: dict | None = None):
        self._body = body
        self.status = status
        self.headers = headers or {}

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class UploadCase(unittest.TestCase):
    def setUp(self):
        self.directory = TEMP_ROOT / "rem_upload"
        shutil.rmtree(self.directory, ignore_errors=True)
        self.directory.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def write_archive(self, uid: str = "100872990", record: dict | None = None) -> Path:
        payload = record if record is not None else {
            "version": 1, "uid": uid, "updatedAt": "2026-10-12T07:18:09+00:00",
            "categories": CATEGORIES,
        }
        path = self.directory / f"{uid}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path


class ValidateRecordTests(UploadCase):
    def test_upload_endpoint_is_embedded_instead_of_plain_text(self):
        source = Path(rem_upload.__file__).read_text(encoding="utf-8")
        self.assertNotIn("http://", source)
        self.assertNotIn("https://", source)
        self.assertTrue(rem_upload.UPLOAD_URL.startswith("https://"))
        self.assertTrue(rem_upload.HHMX_UPLOAD_URL.startswith("https://"))
        self.assertNotEqual(rem_upload.UPLOAD_URL, rem_upload.HHMX_UPLOAD_URL)

    def test_accepts_a_normal_archive(self):
        path = self.write_archive()
        record = rem_upload.validate_record(path, "100872990")
        self.assertEqual(record["uid"], "100872990")
        self.assertEqual(record["version"], 1)

    def test_rejects_name_uid_mismatch(self):
        path = self.write_archive()
        with self.assertRaises(rem_upload.RemUploadError) as ctx:
            rem_upload.validate_record(path, "100000001")
        self.assertIn("与 UID 不一致", str(ctx.exception))

    def test_rejects_inner_uid_mismatch(self):
        path = self.write_archive("100872990", {
            "version": 1, "uid": "200000002", "updatedAt": "x", "categories": CATEGORIES})
        with self.assertRaises(rem_upload.RemUploadError):
            rem_upload.validate_record(path, "100872990")

    def test_rejects_bad_version_and_categories(self):
        for record in (
            {"version": 2, "uid": "100872990", "categories": CATEGORIES},
            {"version": 1, "uid": "100872990", "categories": {}},
            {"version": 1, "uid": "100872990", "categories": {"5": []}},
            {"version": 1, "uid": "100872990", "categories": {"1": {"Gid": 1}}},
            {"version": 1, "uid": "100872990", "categories": {
                "1": [{"Time": 1, "NextPackage": "", "Gid": 10139, "Ids": []}]}},
            {"version": 1, "uid": "100872990", "categories": {
                "1": [{"Time": 1, "NextPackage": "", "Gid": 0, "Ids": [1]}]}},
            {"version": 1, "uid": "100872990", "categories": {
                "1": [{"Time": 1, "NextPackage": "", "Gid": 10139, "Ids": [2**53]}]}},
        ):
            with self.subTest(record=record):
                path = self.write_archive("100872990", record)
                with self.assertRaises(rem_upload.RemUploadError):
                    rem_upload.validate_record(path, "100872990")

    def test_rejects_too_many_pulls(self):
        huge = {"1": [{"Time": 1, "NextPackage": "", "Gid": 10139,
                       "Ids": list(range(1, rem_upload.MAX_PULLS // 1000 + 2)) * 1000}]}
        path = self.write_archive("100872990", {
            "version": 1, "uid": "100872990", "categories": huge})
        with self.assertRaises(rem_upload.RemUploadError) as ctx:
            rem_upload.validate_record(path, "100872990")
        self.assertIn("200000", str(ctx.exception))

    def test_rejects_bad_uid(self):
        for uid in ("1234", "1234567890123456", "abc123", ""):
            with self.subTest(uid=uid):
                with self.assertRaises(rem_upload.RemUploadError):
                    rem_upload.validate_uid(uid)


class UploadFileTests(UploadCase):
    def test_posts_uid_and_record_to_the_rem_endpoint(self):
        path = self.write_archive()
        seen = {}

        def fake_urlopen(request, timeout=0, context=None):
            seen["url"] = request.full_url
            seen["headers"] = dict(request.header_items())
            seen["body"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse(json.dumps({"ok": True, "uid": "100872990"}).encode("utf-8"))

        with mock.patch("stellasora_toolkit.rem_upload.urlopen", fake_urlopen):
            result = rem_upload.upload_file(path)

        self.assertEqual(seen["url"], rem_upload.UPLOAD_URL)
        self.assertEqual(seen["body"]["uid"], "100872990")
        self.assertEqual(seen["body"]["record"]["categories"]["1"][0]["Gid"], 10139)
        self.assertEqual(seen["headers"].get("Content-type"), "application/json")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.uid, "100872990")
        self.assertEqual(result.bind_command, "星塔抽卡绑定 UID 100872990")

    def test_posts_uid_and_record_to_hhmx_when_endpoint_is_given(self):
        path = self.write_archive()
        seen = {}

        def fake_urlopen(request, timeout=0, context=None):
            seen["url"] = request.full_url
            seen["body"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse(json.dumps({"ok": True, "uid": "100872990", "recorded": 2}).encode("utf-8"))

        with mock.patch("stellasora_toolkit.rem_upload.urlopen", fake_urlopen):
            result = rem_upload.upload_file(path, endpoint=rem_upload.HHMX_UPLOAD_URL)

        self.assertEqual(seen["url"], rem_upload.HHMX_UPLOAD_URL)
        self.assertEqual(seen["body"]["uid"], "100872990")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.uid, "100872990")

    def test_uses_server_bind_command_when_given(self):
        path = self.write_archive()

        def fake_urlopen(request, timeout=0, context=None):
            return FakeResponse(json.dumps(
                {"ok": True, "bindCommand": "服务器给的指令"}).encode("utf-8"))

        with mock.patch("stellasora_toolkit.rem_upload.urlopen", fake_urlopen):
            result = rem_upload.upload_file(path)
        self.assertEqual(result.bind_command, "服务器给的指令")

    def test_error_payload_is_reported(self):
        path = self.write_archive()

        def fake_urlopen(request, timeout=0, context=None):
            return FakeResponse(json.dumps({"ok": False, "error": "Uid already bound"}).encode("utf-8"))

        with mock.patch("stellasora_toolkit.rem_upload.urlopen", fake_urlopen):
            with self.assertRaises(rem_upload.RemUploadError) as ctx:
                rem_upload.upload_file(path)
        self.assertIn("Uid already bound", str(ctx.exception))

    def test_fastapi_detail_error_is_reported(self):
        from urllib.error import HTTPError

        path = self.write_archive()
        body = json.dumps({"detail": "缺少有效的 uid"}, ensure_ascii=False).encode("utf-8")

        def fake_urlopen(request, timeout=0, context=None):
            raise HTTPError(rem_upload.HHMX_UPLOAD_URL, 400, "Bad Request",
                            {"Content-Type": "application/json"}, io.BytesIO(body))

        with mock.patch("stellasora_toolkit.rem_upload.urlopen", fake_urlopen):
            with self.assertRaises(rem_upload.RemUploadError) as ctx:
                rem_upload.upload_file(path, endpoint=rem_upload.HHMX_UPLOAD_URL)
        self.assertIn("缺少有效的 uid", str(ctx.exception))

    def test_detail_error_in_ok_false_payload_is_reported(self):
        path = self.write_archive()

        def fake_urlopen(request, timeout=0, context=None):
            return FakeResponse(json.dumps(
                {"ok": False, "detail": "缺少有效的 uid"}, ensure_ascii=False).encode("utf-8"))

        with mock.patch("stellasora_toolkit.rem_upload.urlopen", fake_urlopen):
            with self.assertRaises(rem_upload.RemUploadError) as ctx:
                rem_upload.upload_file(path, endpoint=rem_upload.HHMX_UPLOAD_URL)
        self.assertIn("缺少有效的 uid", str(ctx.exception))

    def test_structured_detail_error_keeps_the_message(self):
        from urllib.error import HTTPError

        path = self.write_archive()
        body = json.dumps({"detail": [
            {"loc": ["body", "uid"], "msg": "field required", "type": "missing"},
        ]}).encode("utf-8")

        def fake_urlopen(request, timeout=0, context=None):
            raise HTTPError(rem_upload.HHMX_UPLOAD_URL, 422, "Unprocessable Entity",
                            {"Content-Type": "application/json"}, io.BytesIO(body))

        with mock.patch("stellasora_toolkit.rem_upload.urlopen", fake_urlopen):
            with self.assertRaises(rem_upload.RemUploadError) as ctx:
                rem_upload.upload_file(path, endpoint=rem_upload.HHMX_UPLOAD_URL)
        self.assertIn("field required", str(ctx.exception))
        self.assertIn("分类 6", str(ctx.exception))

    def test_nested_detail_message_is_reported(self):
        from urllib.error import HTTPError

        path = self.write_archive()
        body = json.dumps({"detail": {
            "code": "invalid_uid", "message": "缺少有效的 uid"}}, ensure_ascii=False).encode("utf-8")

        def fake_urlopen(request, timeout=0, context=None):
            raise HTTPError(rem_upload.HHMX_UPLOAD_URL, 400, "Bad Request",
                            {"Content-Type": "application/json"}, io.BytesIO(body))

        with mock.patch("stellasora_toolkit.rem_upload.urlopen", fake_urlopen):
            with self.assertRaises(rem_upload.RemUploadError) as ctx:
                rem_upload.upload_file(path, endpoint=rem_upload.HHMX_UPLOAD_URL)
        self.assertIn("缺少有效的 uid", str(ctx.exception))

    def test_uid_mismatch_in_response_is_rejected(self):
        path = self.write_archive()

        def fake_urlopen(request, timeout=0, context=None):
            return FakeResponse(json.dumps({"ok": True, "uid": "999999"}).encode("utf-8"))

        with mock.patch("stellasora_toolkit.rem_upload.urlopen", fake_urlopen):
            with self.assertRaises(rem_upload.RemUploadError) as ctx:
                rem_upload.upload_file(path)
        self.assertIn("UID 不一致", str(ctx.exception))

    def test_rate_limit_reports_retry_after(self):
        from urllib.error import HTTPError

        path = self.write_archive()

        def fake_urlopen(request, timeout=0, context=None):
            raise HTTPError(rem_upload.UPLOAD_URL, 429, "Too Many Requests",
                            {"Retry-After": "120"}, None)

        with mock.patch("stellasora_toolkit.rem_upload.urlopen", fake_urlopen):
            with self.assertRaises(rem_upload.RemUploadError) as ctx:
                rem_upload.upload_file(path)
        self.assertIn("Retry-After", str(ctx.exception))
        self.assertIn("120", str(ctx.exception))

    def test_network_error_is_wrapped(self):
        from urllib.error import URLError

        path = self.write_archive()

        def fake_urlopen(request, timeout=0, context=None):
            raise URLError("boom")

        with mock.patch("stellasora_toolkit.rem_upload.urlopen", fake_urlopen):
            with self.assertRaises(rem_upload.RemUploadError) as ctx:
                rem_upload.upload_file(path)
        self.assertIn("连接上传服务失败", str(ctx.exception))

    def test_tls_failure_does_not_retry_insecure_or_plain_http(self):
        import ssl
        path = self.write_archive()
        with mock.patch('stellasora_toolkit.rem_upload.urlopen',
                        side_effect=ssl.SSLCertVerificationError('invalid certificate')) as request:
            with self.assertRaises(rem_upload.RemUploadError):
                rem_upload.upload_file(path)
        request.assert_called_once()
        self.assertEqual(request.call_args.args[0].full_url, rem_upload.UPLOAD_URL)
        self.assertNotIn('context', request.call_args.kwargs)

    def test_fingerprint_ignores_export_time_but_includes_records_and_endpoint(self):
        path = self.write_archive()
        fingerprint = rem_upload.record_fingerprint(path)
        self.assertTrue(rem_upload.mark_uploaded(path.parent, path.stem,
                                                fingerprint=fingerprint))
        record = json.loads(path.read_text())
        record['updatedAt'] = 'a new export time'
        path.write_text(json.dumps(record))
        self.assertEqual(rem_upload.record_fingerprint(path), fingerprint)
        self.assertTrue(rem_upload.was_uploaded(path, fingerprint, rem_upload.UPLOAD_URL))
        self.assertFalse(rem_upload.was_uploaded(path, fingerprint, 'https://other.test/upload'))
        record['categories']['1'][0]['Ids'].append(162)
        path.write_text(json.dumps(record))
        changed = rem_upload.record_fingerprint(path)
        self.assertNotEqual(changed, fingerprint)
        self.assertFalse(rem_upload.mark_uploaded(path.parent, path.stem, fingerprint=changed))
        self.assertTrue(rem_upload.was_uploaded(path, changed, rem_upload.UPLOAD_URL))


class FirstUploadStateTests(UploadCase):
    def test_first_upload_then_silent(self):
        self.assertTrue(rem_upload.mark_uploaded(self.directory, "100872990"))
        self.assertFalse(rem_upload.mark_uploaded(self.directory, "100872990"))
        self.assertEqual(rem_upload.uploaded_uids(self.directory), {"100872990"})
        payload = json.loads(
            (self.directory / rem_upload.STATE_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(payload, {"version": 1, "uploadedUids": ["100872990"]})

    def test_corrupted_state_is_treated_as_empty(self):
        (self.directory / rem_upload.STATE_FILENAME).write_text("{not json", encoding="utf-8")
        self.assertEqual(rem_upload.uploaded_uids(self.directory), set())
        self.assertTrue(rem_upload.mark_uploaded(self.directory, "100872990"))


if __name__ == "__main__":
    unittest.main()
