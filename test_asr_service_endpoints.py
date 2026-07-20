#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ASR Service Endpoint Tests — Doubao BigModel ASR (submit/query)

测试编号:
  01-09  GET /health
  10-19  POST /transcribe        (URL → Doubao BigModel)
  20-29  POST /transcribe/upload (File → Doubao BigModel)
"""

import os
import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path

import requests


# ============================================================================
# Configuration
# ============================================================================

def _parse_base_urls() -> list[str]:
    raw = os.getenv("ASR_BASE_URLS",
                     "http://192.168.8.8:8088,http://120.26.34.95:7118")
    urls = [u.strip().rstrip("/") for u in raw.split(",") if u.strip()]
    # 只加一个本地回环地址，避免同一服务重复测试
    if "http://127.0.0.1:8088" not in urls and "http://localhost:8088" not in urls:
        urls.append("http://127.0.0.1:8088")
    return urls or ["http://127.0.0.1:8088"]


BASE_URLS = _parse_base_urls()
REQUEST_TIMEOUT = float(os.getenv("ASR_TEST_TIMEOUT", "120"))
REQUEST_RETRIES = int(os.getenv("ASR_TEST_RETRIES", "1"))
TEST_AUDIO_URL = os.getenv(
    "ASR_TEST_AUDIO_URL",
    "https://dashscope.oss-cn-beijing.aliyuncs.com/audios/welcome.mp3",
)
TEST_UPLOAD_FILE = os.getenv(
    "ASR_TEST_UPLOAD_FILE",
    "/Users/jinyfeng/Downloads/16k16bit.mp3",
)

BACKEND_NAME = "doubao-bigmodel"


# ============================================================================
# Helpers
# ============================================================================

def _assert_response_shape(tc: unittest.TestCase, body: dict):
    tc.assertIn("text", body)
    tc.assertIn("backend", body)
    tc.assertIn("duration_ms", body)
    tc.assertIn("request_id", body)
    tc.assertIn("error", body)
    tc.assertIn("usage", body)


def _assert_valid_transcribe_response(tc: unittest.TestCase, body: dict):
    """校验转写响应。API 可能成功或失败，都应有完整的响应结构。"""
    _assert_response_shape(tc, body)
    error = body.get("error")
    backend = body.get("backend", "")
    text = body.get("text", "")

    if error is None and text:
        tc.assertEqual(backend, BACKEND_NAME,
                        f"Expected '{BACKEND_NAME}', got '{backend}'")
    elif error:
        tc.assertIn(backend, (BACKEND_NAME, "asr-service"))
        tc.assertIsInstance(error, str)
    else:
        tc.assertIn(backend, (BACKEND_NAME, "asr-service"))

    _print_response(body)


def _print_response(body: dict):
    """打印响应（stderr，避免 unittest 缓冲）."""
    text = body.get("text", "")
    backend = body.get("backend", "")
    error = body.get("error")
    duration = body.get("duration_ms", 0)
    reqid = body.get("request_id", "")

    lines = [f"  [RESP] backend={backend}"]
    if text:
        lines.append(f"  [RESP] text=\"{text[:200]}\"")
    if error:
        lines.append(f"  [RESP] error={error[:250]}")
    if duration:
        lines.append(f"  [RESP] duration_ms={duration}")
    if reqid:
        lines.append(f"  [RESP] request_id={reqid}")

    for line in lines:
        print(line, file=sys.stderr, flush=True)


def _assert_error_400(tc: unittest.TestCase, resp, keyword: str = ""):
    tc.assertEqual(resp.status_code, 400, msg=resp.text)
    if keyword:
        detail = resp.json().get("detail", "")
        tc.assertIn(keyword, detail.lower())


# ============================================================================
# Test Class
# ============================================================================

class TestASRServiceEndpoints(unittest.TestCase):
    """ASR 服务测试 — Doubao BigModel (submit/query)."""

    server_proc = None
    local_base_url = None

    # ---- Setup / Teardown ----

    @staticmethod
    def _find_free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return int(s.getsockname()[1])

    @staticmethod
    def _discover_upload_file() -> Path:
        c = Path(TEST_UPLOAD_FILE)
        if c.exists():
            return c
        for root in (Path("./main/xiaozhi-server/config/assets"),
                     Path("./main/xiaozhi-server/models/SenseVoiceSmall/example"),
                     Path(".")):
            if not root.exists():
                continue
            for ext in ("*.mp3", "*.wav", "*.m4a"):
                found = list(root.rglob(ext))
                if found:
                    return min(found, key=lambda p: p.stat().st_size)
        raise FileNotFoundError(
            f"Upload file not found: {c}. Set ASR_TEST_UPLOAD_FILE.")

    @classmethod
    def _start_local_server(cls):
        if cls.server_proc is not None:
            return
        subprocess.run(["pkill", "-f", "asr_service.py serve"], check=False)
        time.sleep(0.5)
        port = cls._find_free_port()
        cls.local_base_url = f"http://127.0.0.1:{port}"
        cls.server_proc = subprocess.Popen(
            ["/opt/miniconda3/envs/xiaozhi/bin/python", "asr_service.py",
             "serve", "--host", "0.0.0.0", "--port", str(port)],
            cwd=str(Path(__file__).resolve().parent),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    @classmethod
    def _wait_for_local_health(cls, timeout_s: float = 10.0) -> bool:
        if not cls.local_base_url:
            return False
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                r = requests.get(f"{cls.local_base_url}/health", timeout=2)
                if r.status_code == 200:
                    return True
            except requests.RequestException:
                pass
            time.sleep(0.3)
        return False

    @classmethod
    def _stop_local_server(cls):
        if cls.server_proc is None:
            return
        try:
            cls.server_proc.terminate()
            cls.server_proc.wait(timeout=3)
        except Exception:
            cls.server_proc.kill()
        finally:
            cls.server_proc = None

    @classmethod
    def _probe_reachable_urls(cls) -> tuple[list[str], dict]:
        reachable, unreachable = [], {}
        for bu in BASE_URLS:
            try:
                r = requests.get(f"{bu}/health", timeout=REQUEST_TIMEOUT)
                if r.status_code == 200:
                    reachable.append(bu)
                else:
                    unreachable[bu] = f"status {r.status_code}"
            except requests.RequestException as e:
                unreachable[bu] = str(e)
        return reachable, unreachable

    @classmethod
    def setUpClass(cls):
        cls.upload_path = cls._discover_upload_file()
        cls.reachable_urls, unreachable = cls._probe_reachable_urls()

        if not cls.reachable_urls:
            cls._start_local_server()
            if cls._wait_for_local_health(10) and cls.local_base_url:
                cls.reachable_urls = [cls.local_base_url]
            else:
                cls.reachable_urls, unreachable = cls._probe_reachable_urls()

        if not cls.reachable_urls:
            reason = "; ".join(f"{k}: {v}" for k, v in unreachable.items())
            raise RuntimeError(f"No reachable ASR URL. {reason}")

        print(f"\n{'='*60}")
        print(f"Reachable: {cls.reachable_urls}")
        print(f"Audio URL: {TEST_AUDIO_URL}")
        print(f"Upload:    {cls.upload_path}")
        print(f"{'='*60}\n")

    @classmethod
    def tearDownClass(cls):
        cls._stop_local_server()

    def _request(self, method: str, base_url: str, path: str, **kw):
        last = None
        for i in range(REQUEST_RETRIES):
            try:
                return requests.request(
                    method, f"{base_url}{path}",
                    timeout=REQUEST_TIMEOUT, **kw,
                )
            except requests.RequestException as e:
                last = e
                if i < REQUEST_RETRIES - 1:
                    time.sleep(0.2)
        self.fail(f"{method} {base_url}{path} failed: {last}")

    def _iter_urls(self):
        return self.reachable_urls

    # ==================================================================
    # 01-09: GET /health
    # ==================================================================

    def test_01_health_status(self):
        """GET /health → 200."""
        for bu in self._iter_urls():
            with self.subTest(base_url=bu):
                r = self._request("GET", bu, "/health")
                self.assertEqual(r.status_code, 200, msg=r.text)

    def test_02_health_body(self):
        """GET /health → status=ok, backends=[doubao-bigmodel]."""
        for bu in self._iter_urls():
            with self.subTest(base_url=bu):
                r = self._request("GET", bu, "/health")
                b = r.json()
                self.assertEqual(b.get("status"), "ok")
                self.assertIn(BACKEND_NAME, b.get("backends", []))

    # ==================================================================
    # 10-19: POST /transcribe (URL → Doubao BigModel)
    # ==================================================================

    def test_10_transcribe_json(self):
        """POST /transcribe + JSON {audio_url} → 200."""
        for bu in self._iter_urls():
            with self.subTest(base_url=bu):
                r = self._request("POST", bu, "/transcribe",
                                  json={"audio_url": TEST_AUDIO_URL})
                self.assertEqual(r.status_code, 200, msg=r.text)
                _assert_valid_transcribe_response(self, r.json())

    def test_11_transcribe_form(self):
        """POST /transcribe + Form audio_url=... → 200."""
        for bu in self._iter_urls():
            with self.subTest(base_url=bu):
                r = self._request("POST", bu, "/transcribe",
                                  data={"audio_url": TEST_AUDIO_URL})
                self.assertEqual(r.status_code, 200, msg=r.text)
                _assert_valid_transcribe_response(self, r.json())

    def test_12_transcribe_empty_json(self):
        """POST /transcribe + {} → 400."""
        for bu in self._iter_urls():
            with self.subTest(base_url=bu):
                r = self._request("POST", bu, "/transcribe", json={})
                _assert_error_400(self, r, "audio_url")

    def test_13_transcribe_null_url(self):
        """POST /transcribe + {audio_url: null} → 400."""
        for bu in self._iter_urls():
            with self.subTest(base_url=bu):
                r = self._request("POST", bu, "/transcribe",
                                  json={"audio_url": None})
                _assert_error_400(self, r, "audio_url")

    def test_14_transcribe_empty_url(self):
        """POST /transcribe + {audio_url: ''} → 400."""
        for bu in self._iter_urls():
            with self.subTest(base_url=bu):
                r = self._request("POST", bu, "/transcribe",
                                  json={"audio_url": ""})
                _assert_error_400(self, r, "audio_url")

    # ==================================================================
    # 20-29: POST /transcribe/upload (File → Doubao BigModel)
    # ==================================================================

    def test_20_upload_missing(self):
        """POST /transcribe/upload 无文件 → 400."""
        for bu in self._iter_urls():
            with self.subTest(base_url=bu):
                r = self._request("POST", bu, "/transcribe/upload")
                _assert_error_400(self, r, "file")

    def test_21_upload_file(self):
        """POST /transcribe/upload + file= → 200."""
        for bu in self._iter_urls():
            with self.subTest(base_url=bu):
                with self.upload_path.open("rb") as f:
                    r = self._request(
                        "POST", bu, "/transcribe/upload",
                        files={"file": (self.upload_path.name, f, "audio/mpeg")},
                    )
                self.assertEqual(r.status_code, 200, msg=r.text)
                _assert_valid_transcribe_response(self, r.json())

    def test_22_upload_alias(self):
        """POST /transcribe/upload + audio_file= → 200."""
        for bu in self._iter_urls():
            with self.subTest(base_url=bu):
                with self.upload_path.open("rb") as f:
                    r = self._request(
                        "POST", bu, "/transcribe/upload",
                        files={"audio_file": (self.upload_path.name, f, "audio/mpeg")},
                    )
                self.assertEqual(r.status_code, 200, msg=r.text)
                _assert_valid_transcribe_response(self, r.json())


# ============================================================================
# Entry Point
# ============================================================================

if __name__ == "__main__":
    print("ASR Integration Tests — Doubao BigModel (submit/query)")
    print(f"  Base URLs:  {BASE_URLS}")
    print(f"  Timeout:    {REQUEST_TIMEOUT}s")
    print(f"  Audio URL:  {TEST_AUDIO_URL}")
    print(f"  Upload:     {TEST_UPLOAD_FILE}")
    print()
    unittest.main(verbosity=2)
