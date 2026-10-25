from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 LimeLauncher/1.0"
)
MIRROR = "https://bmclapi2.bangbang93.com"
CHUNK = 256 * 1024

ProgressCallback = Callable[[int, int, str, float], None]


class DownloadError(RuntimeError):
    pass


class DownloadCancelled(RuntimeError):
    pass


def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if extra:
        headers.update(extra)
    return headers


def open_url(url: str, timeout: float = 30.0) -> Any:
    request = urllib.request.Request(url, headers=_headers())
    return urllib.request.urlopen(request, timeout=timeout)


def read_text(url: str, timeout: float = 30.0, attempts: int = 3) -> str:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with open_url(url, timeout=timeout) as response:
                return response.read().decode("utf-8", errors="replace")
        except Exception as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(0.6 * (attempt + 1))
    raise DownloadError(f"请求失败：{url}\n{last_error}")


def read_bytes(url: str, timeout: float = 20.0, attempts: int = 2) -> bytes:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with open_url(url, timeout=timeout) as response:
                return response.read()
        except Exception as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(0.4 * (attempt + 1))
    raise DownloadError(f"请求失败：{url}\n{last_error}")


def fetch_json(urls: str | Sequence[str], timeout: float = 30.0) -> Any:
    if isinstance(urls, str):
        urls = [urls]
    last_error: Exception | None = None
    for url in urls:
        try:
            return json.loads(read_text(url, timeout=timeout))
        except Exception as error:
            last_error = error
    raise DownloadError(f"无法获取版本信息。\n{last_error}")


def _with_host(url: str, path_prefix: str) -> str:
    marker = "://"
    if marker not in url:
        return url
    rest = url.split(marker, 1)[1]
    slash = rest.find("/")
    path = rest[slash:] if slash >= 0 else "/"
    return f"{MIRROR}{path_prefix}{path}"


def mirror_asset_url(url: str) -> str:
    for host in (
        "https://piston-data.mojang.com",
        "https://piston-meta.mojang.com",
        "https://resources.download.minecraft.net",
        "http://resources.download.minecraft.net",
    ):
        if url.startswith(host):
            return MIRROR + "/assets" + url[len(host):]
    return _with_host(url, "/assets")


def mirror_library_url(url: str) -> str:
    for host in (
        "https://libraries.minecraft.net",
        "https://piston-data.mojang.com",
        "https://piston-meta.mojang.com",
    ):
        if url.startswith(host):
            return MIRROR + "/maven" + url[len(host):]
    if "maven.fabricmc.net" in url or "maven.quiltmc.org" in url or "maven.neoforged.net" in url:
        return _with_host(url, "/maven")
    return _with_host(url, "/maven")


def url_candidates(url: str, kind: str, source: str = "auto", version_id: str = "") -> list[str]:
    if not url:
        return []
    official = url
    mirror = ""
    mirrors: list[str] = []
    if kind in ("asset", "asset_index"):
        mirrors = [mirror_asset_url(url)]
    elif kind == "library":
        mirrors = [mirror_library_url(url), _with_host(url, "/libraries")]
    elif kind == "client" and version_id:
        mirrors = [f"{MIRROR}/version/{version_id}/client"]
    elif kind == "version_json" and version_id:
        mirrors = [f"{MIRROR}/version/{version_id}/json"]
    elif kind == "raw":
        mirrors = [mirror_asset_url(url)]

    if source == "mirror":
        ordered = mirrors + [official]
    elif source == "official":
        ordered = [official]
    else:
        ordered = [official] + mirrors

    result: list[str] = []
    for item in ordered:
        if item and item not in result:
            result.append(item)
    return result


def _verify_sha1(path: Path, expected: str) -> bool:
    if not expected:
        return True
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest().lower() == expected.lower()


def _file_matches(path: Path, size: int = 0, sha1: str = "") -> bool:
    try:
        if not path.is_file():
            return False
        if size and path.stat().st_size != size:
            return False
        return True
    except OSError:
        return False


def download_file(
    urls: Sequence[str],
    destination: Path,
    expected_size: int = 0,
    expected_sha1: str = "",
    timeout: float = 45.0,
    on_bytes: Callable[[int], None] | None = None,
    cancel: threading.Event | None = None,
) -> bool:
    if _file_matches(destination, expected_size):
        if not expected_sha1 or _verify_sha1(destination, expected_sha1):
            return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for url in urls:
        part = destination.with_name(f"{destination.name}.part-{uuid.uuid4().hex[:8]}")
        try:
            with open_url(url, timeout=timeout) as response, part.open("wb") as handle:
                while True:
                    if cancel is not None and cancel.is_set():
                        raise DownloadCancelled("下载已取消")
                    block = response.read(CHUNK)
                    if not block:
                        break
                    handle.write(block)
                    if on_bytes:
                        on_bytes(len(block))
            part_size = part.stat().st_size
            if expected_size and part_size != expected_size:
                raise DownloadError(f"文件大小不正确（{part_size}/{expected_size}）")
            if expected_sha1 and not _verify_sha1(part, expected_sha1):
                raise DownloadError("文件校验失败（SHA1 不匹配）")
            os.replace(part, destination)
            return True
        except DownloadCancelled:
            try:
                part.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        except Exception as error:
            last_error = error
            try:
                part.unlink(missing_ok=True)
            except OSError:
                pass
    raise DownloadError(f"下载失败：{destination.name}\n{last_error}")


@dataclass
class DownloadItem:
    urls: list[str]
    destination: Path
    size: int = 0
    sha1: str = ""
    label: str = ""
    kind: str = ""


class TransferProgress:
    def __init__(
        self,
        total: int,
        callback: ProgressCallback | None = None,
        initial: int = 0,
        text: str = "",
    ) -> None:
        self.total = max(0, total)
        self.done = max(0, initial)
        self.callback = callback
        self.text = text
        self._started = time.monotonic()
        self._last_emit = 0.0
        self._lock = threading.Lock()

    def add(self, amount: int) -> None:
        with self._lock:
            self.done += amount
        self.emit()

    def set_text(self, text: str) -> None:
        with self._lock:
            self.text = text
        self.emit(force=True)

    def emit(self, force: bool = False) -> None:
        if self.callback is None:
            return
        now = time.monotonic()
        with self._lock:
            if not force and now - self._last_emit < 0.12:
                return
            self._last_emit = now
            done, total, text = self.done, self.total, self.text
        elapsed = max(0.05, now - self._started)
        speed = done / elapsed if done else 0.0
        try:
            self.callback(done, total, text, speed)
        except Exception:
            pass


def prepare_download_items(items: Iterable[DownloadItem]) -> tuple[list[DownloadItem], int, int]:
    unique: dict[str, DownloadItem] = {}
    for item in items:
        key = str(item.destination).lower()
        if key not in unique:
            unique[key] = item
    pending: list[DownloadItem] = []
    total = 0
    done = 0
    for item in unique.values():
        total += max(0, item.size)
        if _file_matches(item.destination, item.size):
            done += max(0, item.size)
        else:
            pending.append(item)
    return pending, total, done


def download_many(
    items: Iterable[DownloadItem],
    callback: ProgressCallback | None = None,
    max_workers: int = 10,
    cancel: threading.Event | None = None,
    text: str = "下载游戏文件",
) -> int:
    pending, total, done = prepare_download_items(items)
    tracker = TransferProgress(total, callback, initial=done, text=text)
    tracker.emit(force=True)
    if not pending:
        tracker.done = max(tracker.done, total)
        tracker.emit(force=True)
        return 0

    count = 0
    errors: list[Exception] = []
    lock = threading.Lock()

    def work(item: DownloadItem) -> bool:
        if cancel is not None and cancel.is_set():
            raise DownloadCancelled("下载已取消")
        changed = download_file(
            item.urls,
            item.destination,
            expected_size=item.size,
            expected_sha1=item.sha1,
            on_bytes=tracker.add,
            cancel=cancel,
        )
        return changed

    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, 16))) as pool:
        futures = [pool.submit(work, item) for item in pending]
        for future in as_completed(futures):
            try:
                if future.result():
                    with lock:
                        count += 1
            except DownloadCancelled:
                if cancel is not None:
                    cancel.set()
                for pending_future in futures:
                    pending_future.cancel()
                raise
            except Exception as error:
                errors.append(error)
                if len(errors) >= 3:
                    if cancel is not None:
                        cancel.set()
                    for pending_future in futures:
                        pending_future.cancel()
                    break

    if errors:
        detail = "\n".join(str(err) for err in errors[:3])
        raise DownloadError(f"部分文件下载失败：\n{detail}")
    tracker.done = max(tracker.done, total)
    tracker.emit(force=True)
    return count
