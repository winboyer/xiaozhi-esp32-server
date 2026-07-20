#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ASR Test Tool (qwen3-asr-flash)

This API only accepts public audio URLs for recognition.
base64 inline data, multipart/form-data, and localhost URLs are NOT supported.

Usage:
    # Public audio URL (recommended)
    python test_asr_api.py --audio-url "https://example.com/audio.mp3"

    # Local file: auto convert to MP3 + upload temp host + call API
    python test_asr_api.py --audio-file ./recording.m4a

    # Convert only (no API call)
    python test_asr_api.py --audio-file ./recording.m4a --convert-only

    # Enable ITN + verbose output
    python test_asr_api.py --audio-url "https://..." --enable-itn --verbose

Deps:
    pip install requests
    For local files: ffmpeg (brew install ffmpeg)
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

import requests


# ---------------------------------------------------------------------------
# Default config
# ---------------------------------------------------------------------------
DEFAULT_ENDPOINT = (
    "https://jcpt.cscec.com/aijsxmywyapi/0510220001/v1.0/"
    "qwen3_asr_flash_public/services/aigc/multimodal-generation/generation"
)
DEFAULT_APPID = "758553f9254bfe4c53f1783049863996"
DEFAULT_MODEL = "qwen3-asr-flash"
REQUEST_TIMEOUT = 60


# ---------------------------------------------------------------------------
# Payload builder (URL mode only)
# ---------------------------------------------------------------------------
def build_payload(
    audio_url: str,
    model: str = DEFAULT_MODEL,
    enable_itn: bool = False,
    system_prompt: str = "",
) -> dict:
    """Build ASR JSON request payload (URL mode only)."""
    return {
        "model": model,
        "input": {
            "messages": [
                {
                    "content": [{"text": system_prompt}],
                    "role": "system",
                },
                {
                    "content": [{"audio": audio_url}],
                    "role": "user",
                },
            ],
        },
        "parameters": {
            "asr_options": {"enable_itn": enable_itn},
        },
    }


# ---------------------------------------------------------------------------
# ffmpeg: any audio -> MP3 (16kHz mono 64kbps)
# ---------------------------------------------------------------------------
def convert_to_mp3(file_path: str) -> str:
    """Convert audio to MP3 using ffmpeg. Returns output file path.
    Caller is responsible for deleting the temp file when done.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    print(f"  [ffmpeg] converting: {os.path.basename(file_path)} -> MP3 ...")

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        out_path = tmp.name

    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", file_path,
                "-acodec", "libmp3lame", "-ab", "64k",
                "-ar", "16000", "-ac", "1",
                out_path,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        size_kb = Path(out_path).stat().st_size / 1024
        print(f"  [ffmpeg] done: {size_kb:.1f} KB -> {out_path}")
        return out_path
    except subprocess.CalledProcessError as e:
        os.unlink(out_path)
        print(f"  [ffmpeg] error:\n{e.stderr}")
        raise
    except FileNotFoundError:
        os.unlink(out_path)
        print("  [ffmpeg] not found. Install: brew install ffmpeg")
        raise


# ---------------------------------------------------------------------------
# Upload to temp file host -> get public URL
# ---------------------------------------------------------------------------
TEMP_HOSTS = [
    {
        "name": "file.io",
        "url": "https://file.io",
        "field": "file",
        "extract": lambda r: r.json().get("link"),
    },
    {
        "name": "tmpfiles.org",
        "url": "https://tmpfiles.org/api/v1/upload",
        "field": "file",
        "extract": lambda r: (
            r.json()
            .get("data", {})
            .get("url", "")
            .replace("https://tmpfiles.org/", "https://tmpfiles.org/dl/")
        ),
    },
    {
        "name": "0x0.st",
        "url": "https://0x0.st",
        "field": "file",
        "extract": lambda r: r.text.strip(),
    },
]


def upload_to_temp_host(file_path: str) -> str:
    """Upload file to a temporary hosting service, return a public download URL."""
    file_name = os.path.basename(file_path)

    for host in TEMP_HOSTS:
        try:
            print(f"  [upload] trying {host['name']} ...")
            with open(file_path, "rb") as f:
                resp = requests.post(
                    host["url"],
                    files={host["field"]: (file_name, f)},
                    timeout=30,
                )
            if resp.ok:
                url = host["extract"](resp)
                if url:
                    print(f"  [upload] public URL: {url}")
                    return url
            print(f"  [upload] {host['name']}: HTTP {resp.status_code}")
        except Exception as e:
            print(f"  [upload] {host['name']} unavailable: {e}")

    raise RuntimeError(
        f"All temp hosts unavailable. The MP3 file is ready at:\n"
        f"  {file_path}\n"
        f"Upload it to a public location (OSS, COS, etc.) and run:\n"
        f"  python test_asr_api.py --audio-url \"<your_public_url>\" --enable-itn"
    )


def upload_to_temp_host(file_path: str) -> str:
    """Upload file to a temporary hosting service, return a public download URL."""
    file_name = os.path.basename(file_path)

    for host in TEMP_HOSTS:
        try:
            print(f"  [upload] trying {host['name']} ...")
            with open(file_path, "rb") as f:
                resp = requests.post(
                    host["url"],
                    files={host["field"]: (file_name, f)},
                    timeout=30,
                )
            if resp.ok:
                url = host["extract"](resp)
                if url:
                    print(f"  [upload] public URL: {url}")
                    return url
            print(f"  [upload] {host['name']}: HTTP {resp.status_code} - {resp.text[:200]}")
        except Exception as e:
            print(f"  [upload] {host['name']} unavailable: {e}")

    raise RuntimeError(
        "All temp hosts unavailable. Upload the file to a public location "
        "and use --audio-url instead."
    )


# ---------------------------------------------------------------------------
# API call (requests first, curl fallback for TLS compat)
# ---------------------------------------------------------------------------
def _call_via_curl(endpoint: str, appid: str, payload_json: str, timeout: int) -> dict:
    """Call API via curl subprocess (fallback for Python SSL/TLS issues)."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        f.write(payload_json)
        tmp_path = f.name

    try:
        result = subprocess.run(
            [
                "curl", "-s", "-X", "POST", "--location",
                "--max-time", str(timeout),
                "-H", f"Authorization: Bearer {appid}",
                "-H", "Content-Type: application/json",
                "-d", f"@{tmp_path}",
                "-w", "\n%{http_code}|%{time_total}",
                endpoint,
            ],
            capture_output=True, text=True, timeout=timeout + 5,
        )
        output = result.stdout.strip()

        if result.returncode != 0 and not output:
            raise RuntimeError(f"curl failed: {result.stderr.strip()}")

        lines = output.rsplit("\n", 1)
        if len(lines) == 2 and "|" in lines[1]:
            body, meta = lines[0], lines[1].split("|")
            http_code, elapsed = int(meta[0]), float(meta[1])
        else:
            body, http_code, elapsed = output, 0, 0.0

        print(f"\n  time: {elapsed:.2f}s  |  HTTP {http_code}")

        if http_code != 200:
            print(f"  ERROR: {body[:1000]}")
            raise RuntimeError(f"HTTP {http_code}")

        return json.loads(body)

    except subprocess.TimeoutExpired:
        raise TimeoutError(f"Request timeout ({timeout}s)")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def call_asr_api(
    endpoint: str,
    appid: str,
    payload: dict,
    timeout: int = REQUEST_TIMEOUT,
    verbose: bool = False,
    verify_ssl: bool = True,
) -> dict:
    """Call ASR API. Tries Python requests first, falls back to curl on SSL errors."""
    payload_json = json.dumps(payload, ensure_ascii=False)

    if verbose:
        print("\n" + "=" * 60)
        print(">> REQUEST")
        print("=" * 60)
        print(f"  URL:      {endpoint}")
        print(f"  Model:    {payload.get('model', '-')}")
        itn = payload.get("parameters", {}).get("asr_options", {}).get("enable_itn", False)
        print(f"  ITN:      {itn}")
        print(f"  Audio:    {payload['input']['messages'][1]['content'][0]['audio']}")
        print("=" * 60)

    # Try Python requests first
    try:
        start = time.time()
        resp = requests.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {appid}",
                "Content-Type": "application/json",
            },
            data=payload_json.encode("utf-8"),
            timeout=timeout,
            verify=verify_ssl,
        )
        elapsed = time.time() - start
        print(f"\n  time: {elapsed:.2f}s  |  HTTP {resp.status_code}")

        if not resp.ok:
            print(f"  ERROR: {resp.status_code}\n  {resp.text[:1000]}")
            resp.raise_for_status()

        return resp.json()

    except (requests.exceptions.SSLError, requests.exceptions.ConnectionError):
        print("  Python SSL/connection error, falling back to curl ...")
        return _call_via_curl(endpoint, appid, payload_json, timeout)

    except requests.exceptions.Timeout:
        raise TimeoutError(f"Request timeout ({timeout}s)")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Request error: {e}")


# ---------------------------------------------------------------------------
# Result display
# ---------------------------------------------------------------------------
def print_result(result: dict):
    """Pretty-print ASR result."""
    print("\n" + "=" * 60)
    print("<< RESULT")
    print("=" * 60)

    text = None

    # Structure: output.choices[0].message.content (multimodal list format)
    output = result.get("output", {})
    if isinstance(output, dict):
        choices = output.get("choices", [])
        if choices:
            content = choices[0].get("message", {}).get("content")
            if isinstance(content, list):
                text = "".join(
                    item.get("text", "") for item in content if isinstance(item, dict)
                )
            elif isinstance(content, str):
                text = content

    # Structure: output.text
    if text is None and isinstance(output, dict):
        text = output.get("text")
    elif text is None and isinstance(output, str):
        text = output

    # Structure: top-level text
    if text is None:
        text = result.get("text")

    if text:
        print(f"  Text:\n{text}")
    else:
        print("  (raw response)")
        print(json.dumps(result, indent=2, ensure_ascii=False))

    usage = result.get("usage") or (
        output.get("usage") if isinstance(output, dict) else None
    )
    if usage:
        print(f"\n  Usage: {json.dumps(usage, ensure_ascii=False)}")

    request_id = result.get("request_id") or result.get("id")
    if request_id:
        print(f"  Request ID: {request_id}")

    print("=" * 60)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="ASR Test Tool (qwen3-asr-flash)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Public audio URL (recommended)
  python test_asr_api.py --audio-url "https://example.com/audio.mp3"

  # Local file (auto convert + upload + call API)
  python test_asr_api.py --audio-file ./recording.m4a

  # Convert only (no API call)
  python test_asr_api.py --audio-file ./recording.m4a --convert-only

  # Enable ITN + verbose
  python test_asr_api.py --audio-url "https://..." --enable-itn --verbose
        """,
    )

    audio_group = parser.add_mutually_exclusive_group()
    audio_group.add_argument("--audio-url", default=None, help="Public audio URL")
    audio_group.add_argument("--audio-file", default=None, help="Local audio file path")

    parser.add_argument("--appid", default=DEFAULT_APPID, help="Bearer Token")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help="ASR API endpoint")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Model name")
    parser.add_argument("--enable-itn", action="store_true", help="Enable ITN")
    parser.add_argument("--system-prompt", default="", help="System prompt")
    parser.add_argument("--timeout", type=int, default=REQUEST_TIMEOUT, help="Timeout (s)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--save-raw", metavar="FILE", help="Save raw JSON response")
    parser.add_argument("--no-verify-ssl", action="store_true", help="Skip SSL verify")
    parser.add_argument(
        "--convert-only",
        action="store_true",
        help="Convert to MP3 only, skip API call (needs --audio-file)",
    )

    args = parser.parse_args()

    # ---- Resolve audio URL ----
    audio_url: str
    cleanup_files: list[str] = []

    if args.audio_file:
        if not os.path.exists(args.audio_file):
            print(f"ERROR: file not found: {args.audio_file}")
            sys.exit(1)

        mp3_path = convert_to_mp3(args.audio_file)
        cleanup_files.append(mp3_path)

        if args.convert_only:
            print(f"\nMP3 file: {mp3_path}")
            return

        try:
            audio_url = upload_to_temp_host(mp3_path)
        except RuntimeError as e:
            cleanup_files.remove(mp3_path)  # 保留 MP3 让用户手动处理
            print(f"\n{e}")
            sys.exit(1)

    elif args.audio_url:
        audio_url = args.audio_url
        print(f"Audio URL: {audio_url}")
    else:
        print("ERROR: specify --audio-url or --audio-file")
        sys.exit(1)

    # ---- Build & Call ----
    payload = build_payload(
        audio_url=audio_url,
        model=args.model,
        enable_itn=args.enable_itn,
        system_prompt=args.system_prompt,
    )

    try:
        result = call_asr_api(
            endpoint=args.endpoint,
            appid=args.appid,
            payload=payload,
            timeout=args.timeout,
            verbose=args.verbose,
            verify_ssl=not args.no_verify_ssl,
        )
    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)
    finally:
        for f in cleanup_files:
            try:
                os.unlink(f)
            except OSError:
                pass

    if args.save_raw:
        Path(args.save_raw).write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"Saved: {args.save_raw}")

    print_result(result)


if __name__ == "__main__":
    main()
