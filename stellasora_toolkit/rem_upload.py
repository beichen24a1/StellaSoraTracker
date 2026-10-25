"""上传抽卡记录到蕾姆(Rem)。

接口语义照搬上游 zhenkotone/stellasora_gacha 的 upload.py:

    POST <内置上传地址>
    {"uid": "<5-15 位数字>", "record": <完整的 <uid>.json>}
    无鉴权(没有 Token / Cookie / CSRF)
    成功 {"ok": true, "bindCommand": "星塔抽卡绑定 UID xxx"}
    失败 {"error": "..."}; 429 会带 Retry-After

上传地址是固定的, 不在界面显示、也不允许用户修改; 源码里以编码形式保存,
避免地址被直接检索到。客户端里不存在真正的"秘密", 这只是减少暴露面。

注意"上传 ≠ 绑定": 上传只是把归档暂存到服务器, 还要把 bindCommand 这条指令发给
蕾姆才算正式更新。所以首次上传成功时界面提示一次, 状态记在账号目录下的
rem_upload_state.json(同一 UID 以后不再弹)。
"""

from __future__ import annotations

import base64
import json
import hashlib
import re
import socket
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from .history_schema import HISTORY_CATEGORY_KEYS
from .account_guard import check_account_records, AccountSafetyError

# 固定上传地址: 异或编码后保存, 解码逻辑在下面。改域名时只换这两行即可。
_ENDPOINT_SALT = b"StellaSoraGachaTool/rem/2026"
_ENDPOINT_BLOB = (
    "xThNu6r+Lnty2gz/Xm3S/jbmz1PF2qp3M787NyA2vr3ZKVWnuLduJmqaHvtWMJuoYryeS4eEvmEo4Q=="
)


def _decode_endpoint(blob: str = _ENDPOINT_BLOB, salt: bytes = _ENDPOINT_SALT) -> str:
    key = hashlib.sha256(salt).digest()
    raw = base64.b64decode(blob)
    return bytes(byte ^ key[index % len(key)]
                 for index, byte in enumerate(raw)).decode("utf-8")


UPLOAD_URL = _decode_endpoint()
STATE_FILENAME = "rem_upload_state.json"
UID_RE = re.compile(r"^[0-9]{5,15}$")
MAX_PAYLOAD_BYTES = 16 * 1024 * 1024
MAX_PULLS = 200000
CATEGORY_KEYS = HISTORY_CATEGORY_KEYS
BIND_TEMPLATE = "星塔抽卡绑定 UID {uid}"
MAX_SAFE_INT = 2**53 - 1


class RemUploadError(RuntimeError):
    """上传失败; 消息可以直接显示给用户。"""

    @property
    def message(self) -> str:
        return str(self)


@dataclass(frozen=True)
class RemUploadResult:
    status_code: int
    payload: dict = field(default_factory=dict)
    uid: str = ""

    @property
    def bind_command(self) -> str:
        return str(self.payload.get("bindCommand") or bind_command_for(self.uid))


def bind_command_for(uid: str) -> str:
    """发给蕾姆的绑定指令(服务器没给 bindCommand 时用这个模板)。"""
    return BIND_TEMPLATE.format(uid=validate_uid(uid))


def validate_uid(uid: object) -> str:
    value = str(uid or "").strip()
    if not UID_RE.fullmatch(value):
        raise RemUploadError("游戏 UID 必须是 5-15 位数字")
    return value


def _valid_number(value: object) -> bool:
    return type(value) is int and 0 < value <= MAX_SAFE_INT


def validate_record(archive_path: Path, uid: str) -> dict:
    """按上游服务端的口径校验归档, 通过后返回可上传的 record。"""
    archive_path = Path(archive_path)
    uid = validate_uid(uid)
    if archive_path.name != f"{uid}.json":
        raise RemUploadError(f"归档文件名（{archive_path.name}）与 UID 不一致，已取消上传")
    if not archive_path.is_file():
        raise RemUploadError(f"未找到归档文件：{archive_path.name}")
    if archive_path.stat().st_size > MAX_PAYLOAD_BYTES:
        raise RemUploadError("归档超过服务器允许的 16 MiB 大小限制")
    try:
        record = json.loads(archive_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise RemUploadError(f"无法读取归档文件：{error}") from error
    if not isinstance(record, dict):
        raise RemUploadError("归档内容不是 JSON 对象")
    record = dict(record)
    version = record.get("version", 1)
    if type(version) is not int or version != 1:
        raise RemUploadError("不支持此归档版本")
    if "uid" in record and record["uid"] != uid:
        raise RemUploadError("归档内的 UID 与文件名不一致，已取消上传")
    record["version"] = 1
    record["uid"] = uid
    categories = record.get("categories")
    if not isinstance(categories, dict) or not categories or set(categories) - CATEGORY_KEYS:
        raise RemUploadError("归档中没有有效的抽卡分类")
    pulls = 0
    for groups in categories.values():
        if not isinstance(groups, list):
            raise RemUploadError("归档分类必须是数组")
        for group in groups:
            if not isinstance(group, dict) or not all(
                    _valid_number(group.get(key)) for key in ("Gid", "Time")):
                raise RemUploadError("归档中存在无效的卡池 ID 或时间")
            ids = group.get("Ids")
            if not isinstance(ids, list) or not ids or not all(_valid_number(v) for v in ids):
                raise RemUploadError("归档中存在无效的抽卡结果")
            pulls += len(ids)
    if pulls > MAX_PULLS:
        raise RemUploadError("归档超过服务器允许的 200000 抽限制")
    return record


def build_body(record: dict, uid: str) -> bytes:
    """请求体: {"uid": ..., "record": ...}; 与上游一致的紧凑写法。"""
    body = json.dumps({"uid": uid, "record": record},
                      ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_PAYLOAD_BYTES:
        raise RemUploadError("归档超过服务器允许的 16 MiB 大小限制")
    return body


def _decode(status_code: int, body: bytes) -> dict:
    try:
        payload = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as error:
        sample = body[:300].decode("utf-8", errors="replace")
        raise RemUploadError(f"上传服务返回非 JSON（HTTP {status_code}）：{sample}") from error
    if not isinstance(payload, dict):
        raise RemUploadError(f"上传服务返回格式无效（HTTP {status_code}）")
    return payload


def diagnose(url: str) -> str:
    """给失败的上传地址做个体检, 返回一句人话(解析不了/端口不通/TLS 问题)。"""
    parts = urlsplit(url)
    host = parts.hostname or ""
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if not host:
        return "上传地址格式不对"
    try:
        socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as err:
        code = getattr(err, "errno", "") or ""
        return (f"域名解析失败（{host} 当前没有可用的 A 记录{('，错误码 ' + str(code)) if code else ''}）。"
                f"服务器可能已下线或换了地址；可以先用页面下方的「手动上传」网页。")
    except OSError as err:
        return f"解析 {host} 时出错：{err}"
    try:
        with socket.create_connection((host, port), timeout=8):
            pass
    except OSError as err:
        return f"能解析 {host}，但连不上 {host}:{port}（{err}）。端口可能被墙或服务未启动。"
    return ""      # 网络层没问题, 那就是协议/证书层面的事


def upload_file(archive_path: Path, *, endpoint: str = UPLOAD_URL,
                timeout: float = 45.0) -> RemUploadResult:
    """校验并上传一个 <uid>.json；沿用上游的 HTTPS 证书校验，不自动降级。"""
    archive_path = Path(archive_path)
    uid = validate_uid(archive_path.stem)
    record = validate_record(archive_path, uid)
    try:
        check_account_records(archive_path.parent, uid, record['categories'])
    except AccountSafetyError as error:
        raise RemUploadError(str(error)) from error
    body = build_body(record, uid)
    request = Request(
        endpoint, data=body, method="POST",
        headers={"Accept": "application/json", "Content-Type": "application/json",
                 "User-Agent": "StellaSoraGachaTool/1.0"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            status_code = int(response.status)
            response_body = response.read()
        return _finish(status_code, response_body, uid)
    except HTTPError as error:
        return _raise_http_error(error, uid)
    except (URLError, TimeoutError, OSError) as error:
        raise RemUploadError(f"连接上传服务失败：{error}") from error


def _finish(status_code: int, response_body: bytes, uid: str) -> RemUploadResult:
    payload = _decode(status_code, response_body)
    if not 200 <= status_code < 300 or payload.get("ok") is not True:
        raise RemUploadError(str(payload.get("error") or f"上传失败：HTTP {status_code}"))
    if "uid" in payload and payload["uid"] != uid:
        raise RemUploadError("服务器返回的 UID 不一致，请勿绑定")
    return RemUploadResult(status_code=status_code, payload=payload, uid=uid)


def _raise_http_error(error: HTTPError, uid: str) -> None:
    response_body = error.read()
    try:
        message = str(_decode(error.code, response_body).get("error") or f"HTTP {error.code}")
    except RemUploadError:
        message = f"HTTP {error.code}"
    if error.code == 429:
        delay = error.headers.get("Retry-After", "600") if error.headers else "600"
        message += f"（Retry-After: {delay} 秒，请稍后再试）"
    if error.code == 422:
        message += '。若归档含周年分类 6，请联系服务维护者确认兼容性；本地归档已保留。'
    raise RemUploadError(f"上传失败：{message}")

def uploaded_uids(directory: Path) -> set[str]:
    """读过 rem_upload_state.json; 文件缺失或损坏都当空集合。"""
    path = Path(directory) / STATE_FILENAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return set()
    values = payload.get("uploadedUids") if isinstance(payload, dict) else None
    if not isinstance(values, list):
        return set()
    return {value for value in values if isinstance(value, str) and UID_RE.fullmatch(value)}


def record_fingerprint(archive_path: Path) -> str:
    uid = validate_uid(archive_path.stem)
    record = validate_record(archive_path, uid)
    content = {key: record[key] for key in ('version', 'uid', 'categories')}
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _upload_state(directory: Path) -> dict:
    try:
        state = json.loads((Path(directory) / STATE_FILENAME).read_text(encoding='utf-8-sig'))
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def _state_directory(directory: Path, uid: str) -> Path:
    """Keep existing per-account upload receipts when the archive moves to root."""
    directory = Path(directory)
    root = directory.parent.parent if directory.parent.name == 'accounts' else directory
    try:
        state = json.loads((root / 'accounts.json').read_text('utf-8'))
        for row in state['accounts']:
            key = row.get('key')
            if row.get('uid') == uid and isinstance(key, str) and re.fullmatch(r'[0-9A-Za-z_-]{1,64}', key):
                return root / 'accounts' / key
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return directory


def was_uploaded(archive_path: Path, fingerprint: str, endpoint: str) -> bool:
    uid = validate_uid(archive_path.stem)
    state = _upload_state(_state_directory(archive_path.parent, uid))
    per_uid = state.get('fingerprintsByUid', {})
    hashes = per_uid.get(uid, {}) if isinstance(per_uid, dict) else {}
    if isinstance(hashes, dict) and endpoint in hashes:
        return hashes[endpoint] == fingerprint
    # Legacy endpoint-only states are safe only if they identify this single UID.
    hashes = state.get('fingerprints', {})
    return state.get('uploadedUids') == [uid] and isinstance(hashes, dict) and hashes.get(endpoint) == fingerprint


def mark_uploaded(directory: Path, uid: str, *, fingerprint: str = '', endpoint: str = UPLOAD_URL) -> bool:
    """记下"这个 UID 已上传过"; 返回是否是首次(界面据此决定弹不弹绑定指令)。"""
    uid = validate_uid(uid)
    directory = _state_directory(Path(directory), uid)
    uploaded = uploaded_uids(directory)
    first = uid not in uploaded
    if not first and not fingerprint:
        return False
    uploaded.add(uid)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / STATE_FILENAME
    state = _upload_state(directory)
    state.update(version=1, uploadedUids=sorted(uploaded))
    if fingerprint:
        per_uid = state.get('fingerprintsByUid')
        per_uid = dict(per_uid) if isinstance(per_uid, dict) else {}
        hashes = per_uid.get(uid)
        hashes = dict(hashes) if isinstance(hashes, dict) else {}
        hashes[endpoint] = fingerprint
        per_uid[uid] = hashes
        state['fingerprintsByUid'] = per_uid
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=directory,
                                         prefix='.rem-upload-', suffix='.tmp', delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(state, handle, ensure_ascii=False, indent=2)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return first


__all__ = [
    "UPLOAD_URL", "STATE_FILENAME", "BIND_TEMPLATE",
    "MAX_PAYLOAD_BYTES", "MAX_PULLS", "RemUploadError", "RemUploadResult",
    "bind_command_for", "validate_uid", "validate_record", "build_body",
    "diagnose", "upload_file", "uploaded_uids", "mark_uploaded",
]
