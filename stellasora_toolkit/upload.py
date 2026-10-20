from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .account_guard import AccountSafetyError, check_account_records
from .history_schema import HISTORY_CATEGORY_KEYS

UPLOAD_URL = "https://yostar.772077.xyz:7777/stellasora/api/gacha/upload"
UID_RE = re.compile(r"^[0-9]{5,15}$")
MAX_PAYLOAD_BYTES = 16 * 1024 * 1024
UPLOAD_STATE_FILENAME = "rem_upload_state.json"


class UploadError(RuntimeError):
    pass


@dataclass(frozen=True)
class UploadResult:
    status_code: int
    payload: dict

    @property
    def bind_command(self) -> str:
        return str(self.payload.get("bindCommand") or "")


def mark_upload_success(output_dir: Path, uid: str) -> bool:
    """Persist successful uploads per UID; return whether this is the first."""
    uid = _validate_uid(uid)
    path = output_dir / UPLOAD_STATE_FILENAME
    try:
        state = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        state = {}
    if not isinstance(state, dict) or not isinstance(state.get("uploadedUids", []), list):
        raise ValueError("上传提示记录格式错误")
    uploaded = {value for value in state.get("uploadedUids", []) if isinstance(value, str) and UID_RE.fullmatch(value)}
    if uid in uploaded:
        return False
    uploaded.add(uid)
    output_dir.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({"version": 1, "uploadedUids": sorted(uploaded)}, indent=2), encoding="utf-8")
    temporary.replace(path)
    return True


def _validate_uid(uid: str) -> str:
    value = str(uid).strip()
    if not UID_RE.fullmatch(value):
        raise UploadError("游戏 UID 必须是 5-15 位数字")
    return value


def _read_record(archive_path: Path, uid: str) -> dict:
    if archive_path.name != f"{uid}.json":
        raise UploadError("归档文件名与 UID 不一致，已取消上传")
    if archive_path.stat().st_size > MAX_PAYLOAD_BYTES:
        raise UploadError("归档超过服务器允许的 16 MiB 大小限制")
    try:
        record = json.loads(archive_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise UploadError(f"无法读取归档文件：{error}") from error
    if not isinstance(record, dict):
        raise UploadError("归档内容不是 JSON 对象")
    record = dict(record)
    if type(record.get("version", 1)) is not int or record.get("version", 1) != 1:
        raise UploadError("不支持此归档版本")
    if "uid" in record and record["uid"] != uid:
        raise UploadError("归档内 UID 与文件名不一致，已取消上传")
    record["version"] = 1
    record["uid"] = uid
    categories = record.get("categories")
    if not isinstance(categories, dict) or not categories or set(categories) - HISTORY_CATEGORY_KEYS:
        raise UploadError("归档中没有有效的抽卡分类")
    pulls = 0
    valid_number = lambda value: type(value) is int and 0 < value <= 2**53 - 1
    for groups in categories.values():
        if not isinstance(groups, list):
            raise UploadError("归档分类必须是数组")
        for group in groups:
            if not isinstance(group, dict) or not all(valid_number(group.get(key)) for key in ("Gid", "Time")):
                raise UploadError("归档中存在无效的卡池 ID 或时间")
            ids = group.get("Ids")
            if not isinstance(ids, list) or not ids or not all(valid_number(value) for value in ids):
                raise UploadError("归档中存在无效的抽卡结果")
            pulls += len(ids)
    if pulls > 200000:
        raise UploadError("归档超过服务器允许的 200000 抽限制")
    return record


def _decode_response(status_code: int, body: bytes) -> dict:
    try:
        payload = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as error:
        sample = body[:300].decode("utf-8", errors="replace")
        raise UploadError(f"上传服务返回非 JSON（HTTP {status_code}）：{sample}") from error
    if not isinstance(payload, dict):
        raise UploadError(f"上传服务返回格式无效（HTTP {status_code}）")
    return payload


def upload_archive(
    archive_path: Path,
    uid: str,
    *,
    endpoint: str = UPLOAD_URL,
    timeout: float = 45.0,
) -> UploadResult:
    """Upload a complete UID.json archive to the Rem server."""

    uid = _validate_uid(uid)
    if not archive_path.is_file():
        raise UploadError(f"未找到归档文件：{archive_path.name}")
    record = _read_record(archive_path, uid)
    try:
        check_account_records(archive_path.parent, uid, record["categories"])
    except AccountSafetyError as error:
        raise UploadError(str(error)) from error
    body = json.dumps({"uid": uid, "record": record}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_PAYLOAD_BYTES:
        raise UploadError("归档超过服务器允许的 16 MiB 大小限制")
    request = Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "StellaSoraGachaTool/1.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            status_code = int(response.status)
            response_body = response.read()
    except HTTPError as error:
        response_body = error.read()
        try:
            payload = _decode_response(error.code, response_body)
            message = str(payload.get("error") or f"HTTP {error.code}")
        except UploadError:
            message = f"HTTP {error.code}"
        if error.code == 429:
            delay = error.headers.get("Retry-After", "600") if error.headers else "600"
            message += f"（Retry-After: {delay}，请稍后再试）"
        if error.code == 422 and "6" in record["categories"]:
            message += "。服务器可能尚未支持周年特选招募分类 6，本地归档已保留；请联系上传服务维护者确认兼容性。"
        raise UploadError(f"上传失败：{message}") from error
    except (URLError, TimeoutError, OSError) as error:
        raise UploadError(f"连接上传服务失败：{error}") from error

    payload = _decode_response(status_code, response_body)
    if status_code < 200 or status_code >= 300 or payload.get("ok") is not True:
        raise UploadError(str(payload.get("error") or f"上传失败：HTTP {status_code}"))
    if "uid" in payload and payload["uid"] != uid:
        raise UploadError("服务器返回的 UID 不一致，请勿绑定")
    return UploadResult(status_code, payload)
