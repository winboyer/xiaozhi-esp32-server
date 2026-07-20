#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DoubaoStreamASRV2 (seed-asr) ASR Test Tool

Converts MP3 to PCM, streams via WebSocket binary protocol to Volcano Engine ASR.

Usage:
    python test_doubao_asr.py --audio-file /Users/jinyfeng/Downloads/16k16bit.mp3
    python test_doubao_asr.py --audio-file ./audio.mp3 --verbose

Deps:
    pip install websockets
    ffmpeg (conda install -c conda-forge ffmpeg)
"""

import argparse
import asyncio
import gzip
import json
import os
import struct
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import websockets


# ---------------------------------------------------------------------------
# Config (from volcano engine console)
# ---------------------------------------------------------------------------
APPID = "9508506810"
ACCESS_TOKEN = "kycBkYIiX8Cvo_IZSw_josDDnFRZrU1w"
RESOURCE_ID = "volc.seedasr.sauc.duration"  # V2 seed-asr model
WS_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"

# Audio format for Doubao ASR
SAMPLE_RATE = 16000
BITS = 16
CHANNELS = 1
CHUNK_MS = 60  # send PCM in 60ms chunks (960 samples at 16kHz)
SAMPLES_PER_CHUNK = int(SAMPLE_RATE * CHUNK_MS / 1000)


# ---------------------------------------------------------------------------
# Binary protocol helpers (from doubao_stream.py)
# ---------------------------------------------------------------------------
FULL_REQUEST = 0x01
AUDIO_ONLY = 0x02
LAST_AUDIO = 0x02  # message_type_specific_flags = 0x02


def generate_header(
    version=0x01,
    message_type=0x01,
    message_type_specific_flags=0x00,
    serial_method=0x01,
    compression_type=0x01,
    reserved=0x00,
) -> bytearray:
    header = bytearray()
    header.append((version << 4) | 1)  # header_size = 1
    header.append((message_type << 4) | message_type_specific_flags)
    header.append((serial_method << 4) | compression_type)
    header.append(reserved)
    return header


def build_full_request(init_params: dict) -> bytes:
    """Build the initial full client request."""
    payload = gzip.compress(json.dumps(init_params).encode())
    req = generate_header(message_type=FULL_REQUEST)
    req.extend(struct.pack(">i", len(payload)))  # 4 bytes signed big-endian
    req.extend(payload)
    return bytes(req)


def build_audio_frame(pcm_chunk: bytes, is_last: bool = False) -> bytes:
    """Build an audio-only binary frame."""
    payload = gzip.compress(pcm_chunk)
    flags = 0x02 if is_last else 0x00
    req = generate_header(message_type=AUDIO_ONLY, message_type_specific_flags=flags)
    req.extend(struct.pack(">i", len(payload)))
    req.extend(payload)
    return bytes(req)


def parse_response(raw: bytes) -> dict:
    """Parse binary protocol response from server."""
    if len(raw) < 4:
        return {"error": "response too short"}

    msg_type = raw[1] >> 4  # message_type

    # Error response
    if msg_type == 0x0F:
        code = int.from_bytes(raw[4:8], "big", signed=False)
        msg_len = int.from_bytes(raw[8:12], "big", signed=False)
        err = json.loads(raw[12:12 + msg_len].decode("utf-8"))
        return {"code": code, "error": err}

    # Normal response with JSON payload
    try:
        length = int.from_bytes(raw[8:12], "big")
        if length > 0 and length <= len(raw) - 12:
            json_data = raw[12:12 + length].decode("utf-8")
        else:
            json_data = raw[8:].decode("utf-8")
        return {"payload_msg": json.loads(json_data)}
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as e:
        return {"error": f"parse error: {e}", "raw_hex": raw.hex()}


# ---------------------------------------------------------------------------
# ffmpeg: MP3 -> raw PCM
# ---------------------------------------------------------------------------
def convert_mp3_to_pcm(mp3_path: str) -> str:
    """Convert MP3 to 16kHz/16bit/mono raw PCM. Returns PCM file path."""
    print(f"[ffmpeg] converting: {os.path.basename(mp3_path)} -> raw PCM ...")

    with tempfile.NamedTemporaryFile(suffix=".pcm", delete=False) as tmp:
        pcm_path = tmp.name

    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", mp3_path,
                "-f", "s16le", "-acodec", "pcm_s16le",
                "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS),
                pcm_path,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        size_kb = Path(pcm_path).stat().st_size / 1024
        duration = size_kb / (SAMPLE_RATE * CHANNELS * BITS / 8) * 1000
        print(f"[ffmpeg] done: {size_kb:.1f} KB ({duration:.0f}ms PCM)")
        return pcm_path
    except subprocess.CalledProcessError as e:
        os.unlink(pcm_path)
        raise RuntimeError(f"ffmpeg error:\n{e.stderr}")
    except FileNotFoundError:
        os.unlink(pcm_path)
        raise RuntimeError("ffmpeg not found. Install: conda install -c conda-forge ffmpeg")


# ---------------------------------------------------------------------------
# Main ASR test
# ---------------------------------------------------------------------------
async def test_doubao_asr(
    pcm_path: str,
    appid: str,
    token: str,
    resource_id: str,
    verbose: bool = False,
):
    """Connect to Doubao ASR, send PCM, receive result."""
    print(f"\n{'='*60}")
    print(f"DoubaoStreamASRV2 (seed-asr) Test")
    print(f"{'='*60}")
    print(f"  WS URL:    {WS_URL}")
    print(f"  Resource:  {resource_id}")
    print(f"  PCM file:  {pcm_path}")

    # Read all PCM data
    pcm_data = Path(pcm_path).read_bytes()
    total_samples = len(pcm_data) // 2  # 16-bit = 2 bytes per sample

    print(f"  PCM size:  {len(pcm_data)/1024:.1f} KB ({total_samples} samples)")

    # Build init request
    init_params = {
        "app": {
            "appid": appid,
            "token": token,
        },
        "user": {"uid": "streaming_asr_service"},
        "request": {
            "reqid": str(uuid.uuid4()),
            "workflow": "audio_in,resample,partition,vad,fe,decode,itn,nlu_punctuate",
            "show_utterances": True,
            "result_type": "single",
            "sequence": 1,
            "end_window_size": 200,
            "corpus": {
                "boosting_table_name": "",
                "correct_table_name": "",
            },
        },
        "audio": {
            "format": "pcm",
            "codec": "pcm",
            "rate": SAMPLE_RATE,
            "bits": BITS,
            "channel": CHANNELS,
            "sample_rate": SAMPLE_RATE,
        },
    }

    headers = {
        "X-Api-App-Key": appid,
        "X-Api-Access-Key": token,
        "X-Api-Resource-Id": resource_id,
        "X-Api-Connect-Id": str(uuid.uuid4()),
    }

    if verbose:
        print(f"\n  Init params:\n{json.dumps(init_params, indent=2, ensure_ascii=False)}")
        print(f"\n  Headers:\n{json.dumps(headers, indent=2)}")

    print(f"\n  Connecting to Doubao ASR...")

    try:
        async with websockets.connect(
            WS_URL,
            additional_headers=headers,
            max_size=100_000_000,
            ping_interval=None,
            ping_timeout=None,
            close_timeout=10,
        ) as ws:
            # --- Step 1: Send full client request ---
            full_req = build_full_request(init_params)
            await ws.send(full_req)
            print("  >> Sent: full client request")

            # --- Step 2: Receive init response ---
            init_raw = await ws.recv()
            init_result = parse_response(init_raw)

            if "error" in init_result:
                print(f"  !! Init error: {init_result['error']}")
                return
            if init_result.get("code"):
                print(f"  !! Init failed with code {init_result['code']}: {init_result.get('error')}")
                return

            print(f"  << Init OK: log_id={init_result.get('payload_msg', {}).get('result', {}).get('additions', {}).get('log_id', 'N/A')}")

            # --- Step 3: Send audio data in chunks ---
            offset = 0
            chunk_bytes = SAMPLES_PER_CHUNK * 2  # 16-bit = 2 bytes
            seq = 0
            last_result_text = ""

            print(f"\n  Sending {len(pcm_data)} bytes PCM ({total_samples} samples)...")

            while offset < len(pcm_data):
                chunk = pcm_data[offset:offset + chunk_bytes]
                offset += len(chunk)
                is_last = offset >= len(pcm_data)

                frame = build_audio_frame(chunk, is_last=is_last)
                await ws.send(frame)
                seq += 1

                if verbose and seq % 50 == 0:
                    print(f"  >> Sent chunk {seq} ({offset/len(pcm_data)*100:.0f}%)")

            print(f"  >> Sent {seq} audio chunks (including last frame)")

            # --- Step 4: Receive results ---
            print(f"\n  Waiting for results...")
            utterances = []

            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=15.0)
                    result = parse_response(raw)

                    if "error" in result:
                        print(f"  !! Response error: {result['error']}")
                        break

                    payload = result.get("payload_msg", {})

                    # Check for error code 1013 (no valid speech)
                    if payload.get("code") == 1013:
                        continue

                    # Check for result
                    result_data = payload.get("result", {})
                    if result_data:
                        text = result_data.get("text", "")
                        utts = result_data.get("utterances", [])

                        # Print utterances
                        for u in utts:
                            if u.get("definite"):
                                utt_text = u["text"]
                                if utt_text not in utterances:
                                    utterances.append(utt_text)
                                    print(f"  << [{len(utterances)}] {utt_text}")

                        # If there's a final text
                        if text and text not in utterances:
                            print(f"  << [final] {text}")

                        # Check audio_info for completion
                        audio_info = payload.get("audio_info", {})
                        if audio_info.get("duration", 0) > 0:
                            last_result_text = text or utterances[-1] if utterances else ""

                    # Check if response indicates completion
                    if result.get("code") or "error" in payload:
                        break

                    if payload:
                        if verbose:
                            print(f"  << payload: {json.dumps(payload, ensure_ascii=False)[:200]}")

                except asyncio.TimeoutError:
                    print("  (no more responses, closing)")
                    break

            # --- Final summary ---
            print(f"\n{'='*60}")
            if utterances:
                print(f"  Final text: {' '.join(utterances)}")
            elif last_result_text:
                print(f"  Final text: {last_result_text}")
            else:
                print(f"  (no text recognized)")
            print(f"{'='*60}")

    except websockets.ConnectionClosed as e:
        print(f"  !! Connection closed: {e}")
    except Exception as e:
        print(f"  !! Error: {e}")
        raise


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="DoubaoStreamASRV2 ASR Test Tool")
    parser.add_argument(
        "--audio-file",
        default="/Users/jinyfeng/Downloads/16k16bit.mp3",
        help="MP3 audio file path",
    )
    parser.add_argument("--appid", default=APPID, help="Volcano App ID")
    parser.add_argument("--token", default=ACCESS_TOKEN, help="Access Token")
    parser.add_argument("--resource-id", default=RESOURCE_ID, help="Resource ID")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    if not os.path.exists(args.audio_file):
        print(f"ERROR: file not found: {args.audio_file}")
        sys.exit(1)

    # Convert MP3 to PCM
    pcm_path = convert_mp3_to_pcm(args.audio_file)

    try:
        asyncio.run(test_doubao_asr(
            pcm_path, args.appid, args.token, args.resource_id, args.verbose,
        ))
    finally:
        try:
            os.unlink(pcm_path)
        except OSError:
            pass


if __name__ == "__main__":
    main()
