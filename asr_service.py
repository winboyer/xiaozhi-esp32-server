#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unified ASR Service — Doubao BigModel ASR (HTTP, submit/query)

Both URL and binary audio use Volcano Engine BigModel ASR:
- URL  → submit audio URL  → poll for result
- File → submit base64 data → poll for result

Reference: auc_http_demo.py (Volcano Engine BigModel ASR submit/query HTTP API)

Usage:
    from asr_service import ASRService
    service = ASRService()
    result = await service.transcribe("https://example.com/audio.mp3")
    result = await service.transcribe(audio_bytes)
"""

import asyncio
import base64
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union
from urllib.parse import urlparse

import requests


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------
@dataclass
class ASRResult:
    """Standardized ASR result."""
    text: str
    backend: str
    duration_ms: float = 0.0
    request_id: str = ""
    usage: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Doubao BigModel ASR backend (submit/query pattern)
# ---------------------------------------------------------------------------
class DoubaoBigModelASRBackend:
    """ASR via Volcano Engine BigModel ASR (submit → poll → result).

    Reference: auc_http_demo.py
    - Submit: POST /api/v3/auc/bigmodel/submit
    - Query:  POST /api/v3/auc/bigmodel/query
    - Resource: volc.bigasr.auc
    """

    def __init__(
        self,
        appid: str = "9508506810",
        access_token: str = "kycBkYIiX8Cvo_IZSw_josDDnFRZrU1w",
        resource_id: str = "volc.bigasr.auc",
        base_url: str = "https://openspeech-direct.zijieapi.com",
        model_name: str = "bigmodel",
        submit_timeout: int = 30,
        query_timeout: int = 15,
        poll_interval: float = 2.0,
        max_poll_time: float = 120.0,
        # ---- Recognition features ----
        enable_itn: bool = True,
        enable_punc: bool = True,
        enable_ddc: bool = False,
        enable_speaker_info: bool = False,
        enable_channel_split: bool = False,
    ):
        self.appid = appid
        self.access_token = access_token
        self.resource_id = resource_id
        self.submit_url = f"{base_url}/api/v3/auc/bigmodel/submit"
        self.query_url = f"{base_url}/api/v3/auc/bigmodel/query"
        self.model_name = model_name
        self.submit_timeout = submit_timeout
        self.query_timeout = query_timeout
        self.poll_interval = poll_interval
        self.max_poll_time = max_poll_time
        # Recognition features
        self.enable_itn = enable_itn
        self.enable_punc = enable_punc
        self.enable_ddc = enable_ddc
        self.enable_speaker_info = enable_speaker_info
        self.enable_channel_split = enable_channel_split

    def transcribe_url(self, audio_url: str) -> ASRResult:
        """Transcribe audio from a public URL."""
        return self._submit_and_poll(audio={"url": audio_url})

    def transcribe_data(self, audio_bytes: bytes) -> ASRResult:
        """Transcribe binary audio data (base64-encoded)."""
        if not audio_bytes:
            return ASRResult(
                text="", backend="doubao-bigmodel", error="empty audio data"
            )
        base64_data = base64.b64encode(audio_bytes).decode("utf-8")
        return self._submit_and_poll(audio={"data": base64_data})

    def _submit_and_poll(self, audio: dict) -> ASRResult:
        """Submit audio to ASR, then poll until complete or error."""
        task_id = str(uuid.uuid4())

        # ---- Step 1: Submit ----
        status, logid, raw = self._submit(task_id, audio)
        if status is None:
            return ASRResult(
                text="", backend="doubao-bigmodel",
                error=raw if isinstance(raw, str) else "submit failed",
                request_id=task_id,
            )

        # ---- Step 2: Poll until done ----
        deadline = time.time() + self.max_poll_time
        while time.time() < deadline:
            time.sleep(self.poll_interval)
            status, body = self._query(task_id, logid)

            if status == "20000000":
                # Success
                text = self._extract_text(body)
                duration_ms = body.get("audio_info", {}).get("duration", 0)
                return ASRResult(
                    text=text,
                    backend="doubao-bigmodel",
                    duration_ms=duration_ms,
                    request_id=task_id,
                    raw=body,
                )

            if status not in ("20000001", "20000002"):
                # Failed
                msg = body.get("message", "") if isinstance(body, dict) else str(body)
                return ASRResult(
                    text="", backend="doubao-bigmodel",
                    error=f"ASR failed (code={status}): {msg[:200]}",
                    request_id=task_id,
                    raw=body if isinstance(body, dict) else {},
                )

        return ASRResult(
            text="", backend="doubao-bigmodel",
            error=f"polling timeout ({self.max_poll_time}s)",
            request_id=task_id,
        )

    # ---- Submit ----

    def _submit(self, task_id: str, audio: dict) -> tuple:
        """Submit ASR task. Returns (status_code, log_id, raw)."""
        headers = self._build_headers(task_id)

        body = {
            "user": {"uid": self.appid},
            "audio": audio,
            "request": {
                "model_name": self.model_name,
                "enable_itn": self.enable_itn,
                "enable_punc": self.enable_punc,
                "enable_ddc": self.enable_ddc,
                "enable_speaker_info": self.enable_speaker_info,
                "enable_channel_split": self.enable_channel_split,
                "corpus": {
                    "correct_table_name": "",
                    "context": "",
                },
            },
        }

        try:
            resp = requests.post(
                self.submit_url,
                data=json.dumps(body),
                headers=headers,
                timeout=self.submit_timeout,
            )
        except Exception as e:
            return None, "", f"submit request failed: {e}"

        code = resp.headers.get("X-Api-Status-Code", "")
        logid = resp.headers.get("X-Tt-Logid", "")

        if code == "20000000":
            return code, logid, None
        else:
            msg = resp.headers.get("X-Api-Message", resp.text[:500])
            return None, logid, f"submit failed (code={code}, logid={logid}): {msg}"

    # ---- Query ----

    def _query(self, task_id: str, logid: str) -> tuple:
        """Query task status. Returns (status_code, response_body_dict)."""
        headers = self._build_headers(task_id)
        headers["X-Tt-Logid"] = logid

        try:
            resp = requests.post(
                self.query_url,
                data=json.dumps({}),
                headers=headers,
                timeout=self.query_timeout,
            )
        except Exception:
            return "", {}

        code = resp.headers.get("X-Api-Status-Code", "")
        try:
            body = resp.json()
        except json.JSONDecodeError:
            body = {"_raw": resp.text[:500]}

        return code, body

    def _build_headers(self, task_id: str) -> dict:
        return {
            "X-Api-App-Key": self.appid,
            "X-Api-Access-Key": self.access_token,
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Request-Id": task_id,
            "X-Api-Sequence": "-1",
        }

    # ---- Text extraction ----

    @staticmethod
    def _extract_text(body: dict) -> str:
        """Extract transcribed text from BigModel response."""
        result = body.get("result", {})
        if isinstance(result, dict):
            text = result.get("text", "")
            if text:
                return text
            utterances = result.get("utterances", [])
            if utterances:
                return "".join(u.get("text", "") for u in utterances if u.get("text"))

        direct = body.get("text", "")
        if direct:
            return direct

        results = body.get("results", [])
        if results:
            for r in results:
                alts = r.get("alternatives", [])
                if alts:
                    return alts[0].get("transcript", "")

        return ""


# ---------------------------------------------------------------------------
# Unified ASR Service
# ---------------------------------------------------------------------------
class ASRService:
    """Unified ASR service — all inputs go to Doubao BigModel ASR.

    - str URL → submit audio URL → poll for result
    - bytes    → submit base64 data → poll for result
    """

    def __init__(self, config: Optional[dict] = None):
        self.backend = DoubaoBigModelASRBackend(**(config or {}))

    @staticmethod
    def _is_url(input_str: str) -> bool:
        try:
            parsed = urlparse(input_str)
            return parsed.scheme in ("http", "https") and bool(parsed.netloc)
        except Exception:
            return False

    async def transcribe(self, audio_input: Union[str, bytes]) -> ASRResult:
        """Transcribe audio via Doubao BigModel ASR.

        Args:
            audio_input: str URL or bytes audio data.
        Returns:
            ASRResult with recognized text and metadata.
        """
        if isinstance(audio_input, str) and self._is_url(audio_input):
            return await asyncio.to_thread(
                self.backend.transcribe_url, audio_input
            )
        if isinstance(audio_input, bytes):
            return await asyncio.to_thread(
                self.backend.transcribe_data, audio_input
            )
        return ASRResult(
            text="", backend="asr-service",
            error=f"unsupported input type: {type(audio_input).__name__}",
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
async def _cli_main():
    import argparse

    parser = argparse.ArgumentParser(description="Doubao BigModel ASR Service")
    parser.add_argument("input", nargs="?", help="Audio URL or local file path")
    parser.add_argument("--appid", default=None)
    parser.add_argument("--token", default=None)

    args = parser.parse_args()
    if not args.input:
        print("Usage: python asr_service.py <audio_url_or_file>")
        return

    cfg = {}
    if args.appid:
        cfg["appid"] = args.appid
    if args.token:
        cfg["access_token"] = args.token

    service = ASRService(config=cfg)
    print(f"Input: {args.input}")

    if os.path.isfile(args.input):
        print("Backend: doubao-bigmodel (local file)")
        audio_bytes = Path(args.input).read_bytes()
        result = await service.transcribe(audio_bytes)
    else:
        print("Backend: doubao-bigmodel (URL)")
        result = await service.transcribe(args.input)

    print(f"\n{'='*60}")
    print("Result")
    print(f"{'='*60}")
    if result.error:
        print(f"  Error:    {result.error}")
    else:
        print(f"  Backend:  {result.backend}")
        print(f"  Text:     {result.text}")
        print(f"  Duration: {result.duration_ms:.0f}ms")
        print(f"  Req ID:   {result.request_id}")
    print(f"{'='*60}")


# ---------------------------------------------------------------------------
# HTTP Server (FastAPI)
# ---------------------------------------------------------------------------

def _create_http_app(service: ASRService):
    try:
        from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import JSONResponse
    except ImportError:
        raise ImportError(
            "FastAPI required. Install: pip install fastapi uvicorn python-multipart"
        )

    app = FastAPI(
        title="Doubao BigModel ASR Service",
        description="Submit/query pattern via Volcano Engine BigModel ASR HTTP API.",
        version="4.0.0",
    )

    REQUEST_TIMEOUT_SECONDS = max(1, int(os.getenv("ASR_REQUEST_TIMEOUT", "120")))

    cors_origins_env = os.getenv("ASR_CORS_ORIGINS", "*").strip()
    cors_origins = (
        ["*"] if cors_origins_env == "*"
        else [o.strip() for o in cors_origins_env.split(",") if o.strip()]
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request, exc):
        return JSONResponse(
            status_code=500,
            content={
                "text": "", "backend": "asr-service",
                "duration_ms": 0.0, "request_id": "",
                "error": f"internal error: {exc}", "usage": {},
            },
        )

    def _to_resp(result: ASRResult) -> dict:
        return {
            "text": result.text,
            "backend": result.backend,
            "duration_ms": result.duration_ms,
            "request_id": result.request_id,
            "error": result.error,
            "usage": result.usage,
        }

    # ---- GET /health ----
    @app.get("/health")
    async def health():
        return {"status": "ok", "backends": ["doubao-bigmodel"]}

    # ---- POST /transcribe (URL → Doubao BigModel) ----
    @app.post("/transcribe")
    async def transcribe_url(
        request: Request,
        audio_url: Optional[str] = Form(default=None),
    ):
        """Transcribe from public URL → Doubao BigModel ASR."""
        if not audio_url:
            try:
                body_bytes = await request.body()
                if body_bytes:
                    body = json.loads(body_bytes)
                    audio_url = body.get("audio_url") or body.get("audioUrl")
            except Exception:
                pass
        if not audio_url:
            raise HTTPException(
                status_code=400,
                detail="audio_url is required.",
            )
        try:
            result = await asyncio.wait_for(
                service.transcribe(audio_url),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            result = ASRResult(
                text="", backend="doubao-bigmodel", error="request timeout",
            )
        return _to_resp(result)

    # ---- POST /transcribe/upload (Binary → Doubao BigModel) ----
    @app.post("/transcribe/upload")
    async def transcribe_upload(
        file: Optional[UploadFile] = File(default=None),
        audio_file: Optional[UploadFile] = File(default=None, alias="audio_file"),
    ):
        """Transcribe uploaded binary audio → Doubao BigModel ASR."""
        upload = file or audio_file
        if upload is None:
            raise HTTPException(
                status_code=400,
                detail="Missing upload file. Use 'file' or 'audio_file'.",
            )
        try:
            audio_bytes = await upload.read()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to read file: {e}")

        try:
            result = await asyncio.wait_for(
                service.transcribe(audio_bytes),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            result = ASRResult(
                text="", backend="doubao-bigmodel", error="request timeout",
            )
        return _to_resp(result)

    return app


# ---- Module-level app ----
_app = None


def get_app():
    global _app
    if _app is None:
        _app = _create_http_app(ASRService())
    return _app


app = get_app()


def _run_http_server(host: str, port: int, reload: bool, workers: int = 1):
    import uvicorn
    print(f"ASR HTTP Server: http://{host}:{port}")
    print(f"API Docs:        http://{host}:{port}/docs")
    if workers > 1 or reload:
        uvicorn.run("asr_service:app", host=host, port=port,
                     reload=reload, workers=workers)
    else:
        uvicorn.run(app, host=host, port=port)


# ---- Entry Point ----
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Doubao BigModel ASR Service")
    sub = parser.add_subparsers(dest="mode")

    sp = sub.add_parser("serve")
    sp.add_argument("--host", default="0.0.0.0")
    sp.add_argument("--port", type=int, default=8088)
    sp.add_argument("--reload", action="store_true")
    sp.add_argument("--workers", type=int, default=1)

    tp = sub.add_parser("transcribe")
    tp.add_argument("input")
    tp.add_argument("--appid", default=None)
    tp.add_argument("--token", default=None)

    args = parser.parse_args()
    if args.mode == "serve":
        _run_http_server(args.host, args.port, args.reload, args.workers)
    elif args.mode == "transcribe":
        asyncio.run(_cli_main())
    else:
        parser.print_help()
