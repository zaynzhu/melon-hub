"""HTTP 客户端:同一 host 连续请求强制间隔(默认 2 秒,全局规范)。"""
import time
import threading

import requests

from collector.config import load_config

_lock = threading.Lock()
_last_request_at = {}  # host -> monotonic 时间戳


def _throttle(host, interval):
    with _lock:
        now = time.monotonic()
        wait = _last_request_at.get(host, 0) + interval - now
        if wait > 0:
            time.sleep(wait)
        _last_request_at[host] = time.monotonic()


def get(url, *, headers=None, timeout=25):
    cfg = load_config()
    interval = cfg.get('request_interval_seconds', 2)
    host = requests.utils.urlparse(url).netloc
    merged = {'User-Agent': cfg.get('default_user_agent')}
    if headers:
        merged.update(headers)
    _throttle(host, interval)
    return requests.get(url, headers=merged, timeout=timeout)
