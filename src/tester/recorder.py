"""Traffic recording & replay (Keploy-style, simplified) (P2).

Record: wrap httpx transport, capture request/response pairs to YAML.
Replay: serve recorded responses without network (offline regression).

Usage:
    recorder = Recorder("reports/traffic.yaml")
    client = httpx.Client(transport=RecorderTransport(recorder, httpx.HTTPTransport()))
    ... run tests ...
    recorder.save()

    # offline replay
    recorder = Recorder("reports/traffic.yaml"); recorder.load()
    client = httpx.Client(transport=RecorderTransport(recorder))
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

import httpx
import yaml


def _serialize(obj: Any) -> Any:
    if isinstance(obj, (dict, list)):
        return json.loads(json.dumps(obj, default=str))
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


class Recorder:
    """Stores recorded exchanges, save/load YAML."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.exchanges: list[dict] = []

    def record(self, method: str, url: str, request_headers: dict, request_body: Any,
               status_code: int, response_headers: dict, response_body: Any,
               latency_ms: float) -> None:
        self.exchanges.append({
            "method": method.upper(),
            "url": url,
            "request": {
                "headers": {k: v for k, v in request_headers.items() if k.lower() not in ("authorization", "cookie", "host")},
                "body": _serialize(request_body),
            },
            "response": {
                "status_code": status_code,
                "headers": {k: v for k, v in response_headers.items() if k.lower() in ("content-type",)},
                "body": _serialize(response_body),
            },
            "latency_ms": round(latency_ms, 2),
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(yaml.safe_dump({"exchanges": self.exchanges},
                                            allow_unicode=True, sort_keys=False),
                             encoding="utf-8")
        return self.path

    def load(self) -> None:
        if not self.path.exists():
            return
        data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        self.exchanges = data.get("exchanges") or []

    def find(self, method: str, url: str) -> Optional[dict]:
        for ex in self.exchanges:
            if ex["method"] == method.upper() and ex["url"] == url:
                return ex
        return None


class RecorderTransport(httpx.BaseTransport):
    """Transport that records live traffic and/or replays recorded responses."""

    def __init__(self, recorder: Recorder, inner: Optional[httpx.BaseTransport] = None,
                 replay: bool = False):
        self.recorder = recorder
        self.inner = inner or httpx.HTTPTransport()
        self.replay = replay
        self.missed: list[tuple[str, str]] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        body = None
        if request.content:
            try:
                body = json.loads(request.content)
            except (ValueError, UnicodeDecodeError):
                body = request.content.decode("utf-8", errors="ignore")[:2000]

        if self.replay:
            ex = self.recorder.find(request.method, url)
            if ex is None:
                self.missed.append((request.method, url))
                return httpx.Response(502, json={"error": "no recording for this request"})
            resp = ex["response"]
            return httpx.Response(
                status_code=resp["status_code"],
                headers=resp.get("headers") or {},
                json=resp["body"] if isinstance(resp["body"], (dict, list)) else None,
                text=None if isinstance(resp["body"], (dict, list)) else str(resp["body"]),
                request=request,
            )

        start = time.perf_counter()
        response = self.inner.handle_request(request)
        latency = (time.perf_counter() - start) * 1000
        response.read()
        resp_body: Any = None
        try:
            resp_body = response.json()
        except ValueError:
            resp_body = response.text
        self.recorder.record(
            request.method, url, dict(request.headers), body,
            response.status_code, dict(response.headers), resp_body, latency,
        )
        return response
