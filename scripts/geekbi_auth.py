#!/usr/bin/env python3
"""极鲸云 Agent 登录状态与 Bearer 请求封装。"""

import argparse
import errno
import json
import os
import tempfile
import time
import uuid
from contextlib import ExitStack, contextmanager
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from platformdirs import user_config_path


TOKEN_ENDPOINT = "/api/v1/agent/auth/token"
STATE_VERSION = 2
SUPPORTED_STATE_VERSIONS = {1, STATE_VERSION}
SKILL_VERSION = "1.7.6"
SKILL_VERSION_HEADER = "X-GeekBI-Skill-Version"
AUTH_FILE_NAME = "agent-auth.json"
AUTH_STATE_DIR = ".geekbi"


class ActionRequired(Exception):
    def __init__(
        self,
        message,
        jump_url,
        action="ACTION_REQUIRED",
        expires_in=0,
        pending=False,
    ):
        super().__init__(message)
        self.message = message
        self.jump_url = jump_url
        self.action = action
        self.expires_in = expires_in
        self.pending = pending

    def public_payload(self):
        return {
            "actionRequired": True,
            "actionPending": self.pending,
            "action": self.action,
            "msg": self.message,
            "jumpUrl": self.jump_url,
            "expiresIn": self.expires_in,
        }


class ResolvedStore:
    def __init__(self, path, kind="user-config-directory"):
        self.path = _absolute_path(path)
        self.kind = kind


def _absolute_path(path):
    path = Path(path).expanduser()
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError):
        return Path(os.path.abspath(os.fspath(path)))


def _user_config_state_path():
    return _absolute_path(
        user_config_path("GeekBI", appauthor=False, ensure_exists=True)
        / "temu-research-skill"
        / AUTH_FILE_NAME
    )


def _skill_state_path():
    return _absolute_path(Path(__file__).parent.parent / AUTH_STATE_DIR / AUTH_FILE_NAME)


def _workspace_state_path():
    return _absolute_path(Path(os.getcwd()) / AUTH_STATE_DIR / AUTH_FILE_NAME)


def _resolve_stores():
    candidates = (
        ResolvedStore(_user_config_state_path(), "user-config-directory"),
        ResolvedStore(_skill_state_path(), "skill-directory"),
        ResolvedStore(_workspace_state_path(), "working-directory"),
    )
    stores = []
    seen_paths = set()
    for store in candidates:
        path_key = os.path.normcase(os.fspath(store.path))
        if path_key in seen_paths:
            continue
        seen_paths.add(path_key)
        stores.append(store)
    return tuple(stores)


def _empty_state():
    return {
        "version": STATE_VERSION,
        "storeId": uuid.uuid4().hex,
        "servers": {},
    }


def _normalize_state(payload):
    if not isinstance(payload, dict):
        raise ValueError("登录状态文件内容无效")
    if payload.get("version") not in SUPPORTED_STATE_VERSIONS:
        raise ValueError("登录状态文件版本不受支持")
    servers = payload.get("servers")
    if not isinstance(servers, dict):
        raise ValueError("登录状态文件缺少服务状态")
    normalized_servers = {
        key: value
        for key, value in servers.items()
        if isinstance(key, str) and isinstance(value, dict)
    }
    store_id = payload.get("storeId")
    if not isinstance(store_id, str) or not store_id:
        store_id = uuid.uuid4().hex
    return {
        "version": STATE_VERSION,
        "storeId": store_id,
        "servers": normalized_servers,
    }


def _restrict_permissions(path, mode):
    if os.name != "posix":
        return
    chmod = getattr(os, "chmod", None)
    if not callable(chmod):
        return
    try:
        chmod(os.fspath(path), mode)
    except (OSError, AttributeError, NotImplementedError):
        pass


def _restrict_open_file(handle, mode):
    if os.name != "posix":
        return
    fchmod = getattr(os, "fchmod", None)
    if not callable(fchmod):
        return
    try:
        fchmod(handle.fileno(), mode)
    except (OSError, AttributeError, NotImplementedError):
        pass


def _storage_probe_reason(error):
    error_number = getattr(error, "errno", None)
    if isinstance(error, PermissionError) or error_number in (errno.EACCES, errno.EPERM):
        return "没有登录状态目录的读写权限"
    if error_number == errno.EROFS:
        return "登录状态目录位于只读文件系统"
    if error_number == errno.ENOSPC:
        return "登录状态目录所在磁盘空间不足"
    quota_error = getattr(errno, "EDQUOT", None)
    if quota_error is not None and error_number == quota_error:
        return "登录状态目录所在文件系统配额已用尽"
    message = str(error).strip()
    return f"登录状态目录不可用：{message}" if message else "登录状态目录不可用"


def _probe_file_lock(handle):
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            return
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        return
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _probe_storage_path(path):
    """Verify the exact state directory using reversible file operations."""
    path = _absolute_path(path)
    result = {
        "readable": False,
        "writable": False,
        "lockable": False,
        "atomicReplace": False,
        "usable": False,
        "reason": None,
    }
    source_path = None
    target_path = None

    try:
        if path.exists():
            if not path.is_file():
                raise OSError(errno.EISDIR, "登录状态路径不是文件")
            with path.open("rb") as existing:
                existing.read(1)
        result["readable"] = True

        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w+b",
            dir=path.parent,
            prefix=".agent-auth-probe-",
            delete=False,
        ) as source:
            source_path = Path(source.name)
            _restrict_open_file(source, 0o600)
            source.write(b"\0")
            source.flush()
            fsync = getattr(os, "fsync", None)
            if callable(fsync):
                try:
                    fsync(source.fileno())
                except (OSError, AttributeError, NotImplementedError):
                    pass
            result["writable"] = True
            _probe_file_lock(source)
            result["lockable"] = True

        with tempfile.NamedTemporaryFile(
            mode="w+b",
            dir=path.parent,
            prefix=".agent-auth-probe-target-",
            delete=False,
        ) as target:
            target_path = Path(target.name)
            _restrict_open_file(target, 0o600)

        os.replace(source_path, target_path)
        source_path = None
        result["atomicReplace"] = True
        result["usable"] = True
    except (OSError, ImportError, AttributeError, NotImplementedError) as error:
        result["reason"] = _storage_probe_reason(error)
    finally:
        for temporary_path in (source_path, target_path):
            if temporary_path is None:
                continue
            try:
                temporary_path.unlink()
            except OSError:
                pass

    return result


def _write_json_file(path, payload, prefix):
    path.parent.mkdir(parents=True, exist_ok=True)
    _restrict_permissions(path.parent, 0o700)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=prefix,
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False)
            handle.flush()
            fsync = getattr(os, "fsync", None)
            if callable(fsync):
                try:
                    fsync(handle.fileno())
                except (OSError, AttributeError, NotImplementedError):
                    pass
            _restrict_open_file(handle, 0o600)
        os.replace(temp_path, path)
        _restrict_permissions(path, 0o600)
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass


def _read_state_file(path):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError("无法读取登录状态文件") from error
    except ValueError as error:
        raise ValueError("登录状态文件不是有效的 JSON") from error
    return _normalize_state(payload)


def _write_state_file(store, payload):
    _write_json_file(
        store.path,
        _normalize_state(payload),
        ".agent-auth-",
    )


@contextmanager
def _state_lock(store):
    probe = _probe_storage_path(store.path)
    if not probe["usable"]:
        raise OSError(probe["reason"] or "登录状态目录不可用")
    lock_path = store.path.with_name(f".{store.path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    _restrict_permissions(lock_path.parent, 0o700)
    with open(lock_path, "a+b") as handle:
        _restrict_open_file(handle, 0o600)
        if os.name == "nt":
            import msvcrt

            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _stores_lock(stores):
    errors = []
    with ExitStack() as stack:
        locked_stores = []
        for store in stores:
            try:
                stack.enter_context(_state_lock(store))
                locked_stores.append(store)
            except (OSError, ImportError, AttributeError, NotImplementedError) as error:
                errors.append(f"{store.kind}: {_storage_probe_reason(error)}")
        if not locked_stores:
            reason = "；".join(errors) or "登录状态目录不可用"
            raise OSError(reason)
        yield tuple(locked_stores)


def _load_state_from_stores(stores):
    for store in stores:
        if store.path.is_file():
            return _read_state_file(store.path)
    return _empty_state()


def _write_state_files(stores, payload):
    normalized = _normalize_state(payload)
    errors = []
    written = 0
    for store in stores:
        try:
            _write_state_file(store, normalized)
            written += 1
        except OSError as error:
            errors.append(f"{store.kind}: {_storage_probe_reason(error)}")
    if written == 0:
        reason = "；".join(errors) or "登录状态目录不可用"
        raise OSError(reason)


def _state_file_matches(store, payload):
    if not store.path.is_file():
        return False
    try:
        return _read_state_file(store.path) == _normalize_state(payload)
    except (OSError, ValueError):
        return False


def _load_state():
    try:
        return _load_state_from_stores(_resolve_stores())
    except OSError as error:
        raise ValueError(
            f"无法读取登录状态：{error}。"
            "请确保登录状态目录可访问"
        ) from error


def _save_state(payload):
    stores = _resolve_stores()
    try:
        with _stores_lock(stores) as locked_stores:
            _write_state_files(locked_stores, payload)
    except OSError as error:
        raise ValueError(
            f"无法保存登录状态：{error}。"
            "请确保至少有一个登录状态目录可写"
        ) from error


def _update_state(callback):
    stores = _resolve_stores()
    try:
        with _stores_lock(stores) as locked_stores:
            payload = _load_state_from_stores(stores)
            changed, result = callback(payload)
            needs_sync = any(
                not _state_file_matches(store, payload)
                for store in locked_stores
            )
            if changed or needs_sync:
                _write_state_files(locked_stores, payload)
            return result
    except OSError as error:
        raise ValueError(
            f"无法更新登录状态：{error}。"
            "请确保至少有一个登录状态目录可写"
        ) from error


def storage_status():
    stores = _resolve_stores()
    store_statuses = []
    for store in stores:
        probe = _probe_storage_path(store.path)
        store_statuses.append(
            {
                "storageType": store.kind,
                "path": os.fspath(store.path),
                "initialized": store.path.is_file(),
                **probe,
            }
        )
    active_store = next(
        (store for store in stores if store.path.is_file()),
        stores[0],
    )
    return {
        "storageType": "mirrored",
        "readPriority": [store.kind for store in stores],
        "activeReadStorageType": active_store.kind,
        "activeReadPath": os.fspath(active_store.path),
        "initialized": any(item["initialized"] for item in store_statuses),
        "usable": any(item["usable"] for item in store_statuses),
        "stores": store_statuses,
    }


def clear_auth_state():
    for store in _resolve_stores():
        try:
            store.path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _server_key(base_url):
    return base_url.rstrip("/")


def _server_state(payload, base_url):
    return payload["servers"].setdefault(_server_key(base_url), {})


def _read_json_response(response):
    return json.loads(response.read().decode("utf-8"))


def _read_http_error(error):
    try:
        return json.loads(error.read().decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None


def response_message(payload, fallback):
    if isinstance(payload, dict):
        message = payload.get("msg")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return fallback


def _raise_action_if_needed(payload):
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    jump_url = data.get("jumpUrl") if isinstance(data, dict) else None
    if not isinstance(jump_url, str) or not jump_url:
        return
    raise ActionRequired(
        response_message(payload, "请完成页面操作后继续"),
        jump_url,
        action=data.get("error") or "ACTION_REQUIRED",
        expires_in=int(data.get("expiresIn", 0)),
    )


def _api_headers(content_type=None):
    headers = {
        "Accept": "application/json",
        SKILL_VERSION_HEADER: SKILL_VERSION,
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _post_json(url, body, timeout):
    request = Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=_api_headers("application/json"),
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        return _read_json_response(response)


def _remove_access_token(server):
    server.pop("accessToken", None)
    server.pop("accessTokenExpiresAt", None)


def _clear_expired(server, now):
    changed = False
    token_expires_at = server.get("accessTokenExpiresAt", 0)
    if server.get("accessToken") and token_expires_at <= now:
        _remove_access_token(server)
        changed = True
    pending = server.get("pending")
    if isinstance(pending, dict) and pending.get("expiresAt", 0) <= now:
        server.pop("pending", None)
        changed = True
    return changed


def _persist_expiry_cleanup(server_key, now):
    def save_expiry(payload):
        server = payload["servers"].get(server_key)
        if not isinstance(server, dict):
            return False, None
        return _clear_expired(server, now), None

    _update_state(save_expiry)


def complete_pending_login(base_url, timeout):
    payload = _load_state()
    server_key = _server_key(base_url)
    server = payload["servers"].get(server_key)
    if not isinstance(server, dict):
        return False
    now = int(time.time())
    changed = _clear_expired(server, now)
    pending = server.get("pending")
    if not isinstance(pending, dict):
        if changed:
            _persist_expiry_cleanup(server_key, now)
        return False

    endpoint = f"{base_url.rstrip('/')}{TOKEN_ENDPOINT}"
    try:
        response = _post_json(endpoint, {"deviceCode": pending["deviceCode"]}, timeout)
    except HTTPError as error:
        error_payload = _read_http_error(error)
        data = error_payload.get("data", {}) if isinstance(error_payload, dict) else {}
        error_code = data.get("error") if isinstance(data, dict) else None
        if error.code == 202 or error_code == "AUTHORIZATION_PENDING":
            if changed:
                _persist_expiry_cleanup(server_key, now)
            raise ActionRequired(
                "等待用户完成网页登录。完成后请再次调用原查询。",
                pending.get("jumpUrl", ""),
                action="AUTH_REQUIRED",
                expires_in=max(0, pending.get("expiresAt", now) - now),
                pending=True,
            ) from error
        if error.code in (400, 410) or error_code in (
            "INVALID_DEVICE_CODE",
            "AUTHORIZATION_EXPIRED",
        ):
            def remove_pending(latest):
                latest_server = latest["servers"].get(server_key)
                if not isinstance(latest_server, dict):
                    return False, None
                latest_pending = latest_server.get("pending")
                if not isinstance(latest_pending, dict):
                    return False, None
                if latest_pending.get("deviceCode") != pending.get("deviceCode"):
                    return False, None
                latest_server.pop("pending", None)
                return True, None

            _update_state(remove_pending)
            return False
        message = response_message(error_payload, None)
        if message:
            raise ValueError(message) from error
        raise

    response_data = response.get("data", {}) if isinstance(response, dict) else {}
    if isinstance(response_data, dict) and response_data.get("error") == "AUTHORIZATION_PENDING":
        if changed:
            _persist_expiry_cleanup(server_key, now)
        raise ActionRequired(
            "等待用户完成网页登录。完成后请再次调用原查询。",
            pending.get("jumpUrl", ""),
            action="AUTH_REQUIRED",
            expires_in=max(0, pending.get("expiresAt", now) - now),
            pending=True,
        )
    if response.get("code") != 0 or not isinstance(response.get("data"), dict):
        raise ValueError(response_message(response, "登录令牌响应异常"))
    token_data = response["data"]
    access_token = token_data.get("accessToken")
    if not isinstance(access_token, str) or not access_token:
        raise ValueError("登录令牌响应缺少 accessToken")
    expires_in = int(token_data.get("expiresIn", 0))

    def save_token(latest):
        latest_server = latest["servers"].get(server_key)
        if not isinstance(latest_server, dict):
            return False, False
        latest_pending = latest_server.get("pending")
        if not isinstance(latest_pending, dict):
            return False, False
        if latest_pending.get("deviceCode") != pending.get("deviceCode"):
            return False, False
        _remove_access_token(latest_server)
        latest_server["accessToken"] = access_token
        latest_server["accessTokenExpiresAt"] = now + max(0, expires_in - 30)
        latest_server.pop("pending", None)
        return True, True

    return _update_state(save_token)


def _authorization_header(base_url):
    server_key = _server_key(base_url)

    def read_token(payload):
        server = payload["servers"].get(server_key)
        if not isinstance(server, dict):
            return False, None
        changed = _clear_expired(server, int(time.time()))
        token = server.get("accessToken")
        return changed, f"Bearer {token}" if token else None

    return _update_state(read_token)


def _save_challenge(base_url, response_payload):
    data = response_payload.get("data", {})
    device_code = data.get("deviceCode")
    jump_url = data.get("jumpUrl")
    if not isinstance(device_code, str) or not device_code:
        raise ValueError("登录响应缺少 deviceCode")
    if not isinstance(jump_url, str) or not jump_url:
        raise ValueError("登录响应缺少 jumpUrl")
    expires_in = int(data.get("expiresIn", 0))

    def save_challenge(payload):
        server = _server_state(payload, base_url)
        _remove_access_token(server)
        server["pending"] = {
            "deviceCode": device_code,
            "jumpUrl": jump_url,
            "expiresAt": int(time.time()) + expires_in,
        }
        return True, None

    _update_state(save_challenge)
    raise ActionRequired(
        response_payload.get("msg", "需要登录后继续"),
        jump_url,
        action="AUTH_REQUIRED",
        expires_in=expires_in,
    )


def authenticated_json_request(
    url,
    base_url,
    timeout,
    *,
    method="GET",
    body=None,
    headers=None,
):
    complete_pending_login(base_url, timeout)
    request_headers = _api_headers()
    if headers:
        request_headers.update(headers)
    authorization = _authorization_header(base_url)
    if authorization:
        request_headers["token"] = authorization
    request = Request(
        url,
        data=body,
        headers=request_headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            response_payload = _read_json_response(response)
            _raise_action_if_needed(response_payload)
            return response_payload
    except HTTPError as error:
        error_payload = _read_http_error(error)
        data = error_payload.get("data", {}) if isinstance(error_payload, dict) else {}
        if (
            error.code == 401
            and isinstance(data, dict)
            and data.get("error") == "AUTH_REQUIRED"
        ):
            _save_challenge(base_url, error_payload)
        try:
            _raise_action_if_needed(error_payload)
        except ActionRequired as action:
            raise action from error
        message = response_message(error_payload, None)
        if message:
            raise ValueError(message) from error
        raise


def main():
    parser = argparse.ArgumentParser(description="管理极鲸云登录状态")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("storage-status", help="检查登录状态存储")
    subparsers.add_parser("clear", help="清除登录状态")
    args = parser.parse_args()

    try:
        if args.command == "clear":
            clear_auth_state()
            result = {"cleared": True}
        else:
            result = storage_status()
    except ValueError as error:
        print(json.dumps({"error": True, "msg": str(error)}, ensure_ascii=False))
        return 1

    print(json.dumps({"code": 0, "data": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
