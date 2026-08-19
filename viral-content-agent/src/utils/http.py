"""极简 HTTP 客户端：优先用 requests，缺失时自动降级到标准库 urllib。

好处：核心链路零第三方依赖也能跑（评审 clone 下来直接 python demo.py）。
"""

from __future__ import annotations

import json as _json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 viral-content-agent/1.0")

try:  # pragma: no cover
    import requests  # type: ignore

    _HAS_REQUESTS = True
except Exception:  # pragma: no cover
    requests = None  # type: ignore
    _HAS_REQUESTS = False


class HttpError(RuntimeError):
    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


def get_text(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 25,
             params: Optional[Dict[str, Any]] = None) -> str:
    h = {"User-Agent": DEFAULT_UA, "Accept": "*/*"}
    h.update(headers or {})
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params, safe="><=,:+")
    if _HAS_REQUESTS:
        try:
            r = requests.get(url, headers=h, timeout=timeout)
            if r.status_code >= 400:
                raise HttpError(f"GET {url} -> HTTP {r.status_code}", r.status_code)
            r.encoding = r.encoding or "utf-8"
            return r.text
        except HttpError:
            raise
        except Exception as exc:
            raise HttpError(f"GET {url} 失败: {exc}") from exc
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as exc:
        raise HttpError(f"GET {url} -> HTTP {exc.code}", exc.code) from exc
    except Exception as exc:
        raise HttpError(f"GET {url} 失败: {exc}") from exc


def get_json(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 25,
             params: Optional[Dict[str, Any]] = None) -> Any:
    raw = get_text(url, headers=headers, timeout=timeout, params=params)
    try:
        return _json.loads(raw)
    except Exception as exc:
        raise HttpError(f"响应不是合法 JSON: {raw[:200]}") from exc


def post_json(url: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None,
              timeout: int = 60) -> Any:
    h = {"User-Agent": DEFAULT_UA, "Content-Type": "application/json"}
    h.update(headers or {})
    body = _json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if _HAS_REQUESTS:
        try:
            r = requests.post(url, data=body, headers=h, timeout=timeout)
            if r.status_code >= 400:
                raise HttpError(f"POST {url} -> HTTP {r.status_code}: {r.text[:200]}", r.status_code)
            return r.json()
        except HttpError:
            raise
        except Exception as exc:
            raise HttpError(f"POST {url} 失败: {exc}") from exc
    req = urllib.request.Request(url, data=body, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return _json.loads(resp.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")[:200] if hasattr(exc, "read") else ""
        raise HttpError(f"POST {url} -> HTTP {exc.code}: {detail}", exc.code) from exc
    except Exception as exc:
        raise HttpError(f"POST {url} 失败: {exc}") from exc
