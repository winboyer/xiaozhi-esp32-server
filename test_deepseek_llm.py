#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DeepSeek V4 Pro LLM API Test Tool

Calls the CSCEC AI platform DeepSeek V4 Pro chat completions API.

Usage:
    # Single question
    python test_deepseek_llm.py --prompt "你是谁？"

    # With system prompt
    python test_deepseek_llm.py --prompt "介绍一下北京" --system "你是一个旅游助手"

    # Multi-turn conversation (JSON array)
    python test_deepseek_llm.py --messages '[{"role":"user","content":"你好"}]'

    # Streaming mode
    python test_deepseek_llm.py --prompt "写一首诗" --stream

    # Custom parameters
    python test_deepseek_llm.py --prompt "解释量子力学" --temperature 0.7 --max-tokens 512

Deps:
    pip install requests
"""

import argparse
import json
import sys

import requests

# ============================================================
# Configuration
# ============================================================
APP_ID = "758553f9254bfe4c53f1783049863996"
APP_KEY = "722ec295ca566ac3918f40c462519b9142547b30fd77f276c2b6853510b0b019"

API_URL = "https://jcpt.cscec.com/aijsxmywyapi/0510220001/v1.0/deepseek_v4_pro_public/chat/completions"

DEFAULT_SYSTEM = "You are a helpful assistant."
DEFAULT_MODEL = "deepseek-v4-pro"


def build_headers() -> dict:
    """Build request headers with authorization."""
    return {
        "Authorization": f"Bearer {APP_ID}",
        "Content-Type": "application/json",
    }


def build_payload(
    messages: list[dict],
    temperature: float = 0.7,
    max_tokens: int = 2048,
    top_p: float = 0.9,
    stream: bool = False,
    model: str = DEFAULT_MODEL,
) -> dict:
    """Build the request payload."""
    return {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "top_p": top_p,
        "stream": stream,
    }


def call_llm(payload: dict, verbose: bool = False) -> dict | None:
    """Send a non-streaming request and return the parsed response."""
    headers = build_headers()

    if verbose:
        print("=" * 60)
        print("[REQUEST]")
        print(f"URL: {API_URL}")
        print(f"Headers: {json.dumps(headers, indent=2, ensure_ascii=False)}")
        print(f"Payload: {json.dumps(payload, indent=2, ensure_ascii=False)}")
        print("=" * 60)

    try:
        resp = requests.post(API_URL, headers=headers, json=payload, timeout=120)
    except requests.RequestException as e:
        print(f"[ERROR] Request failed: {e}", file=sys.stderr)
        return None

    if verbose:
        print(f"[RESPONSE] HTTP {resp.status_code}")
        print(f"Headers: {dict(resp.headers)}")

    if resp.status_code != 200:
        print(f"[ERROR] HTTP {resp.status_code}: {resp.text}", file=sys.stderr)
        return None

    try:
        data = resp.json()
    except json.JSONDecodeError:
        print(f"[ERROR] Failed to parse JSON response: {resp.text}", file=sys.stderr)
        return None

    if verbose:
        print(f"Raw Response: {json.dumps(data, indent=2, ensure_ascii=False)}")

    return data


def call_llm_stream(payload: dict, verbose: bool = False) -> str:
    """Send a streaming request and print tokens as they arrive."""
    headers = build_headers()

    if verbose:
        print("=" * 60)
        print("[STREAM REQUEST]")
        print(f"URL: {API_URL}")
        print(f"Payload: {json.dumps(payload, indent=2, ensure_ascii=False)}")
        print("=" * 60)

    try:
        resp = requests.post(API_URL, headers=headers, json=payload, stream=True, timeout=120)
    except requests.RequestException as e:
        print(f"[ERROR] Stream request failed: {e}", file=sys.stderr)
        return ""

    if resp.status_code != 200:
        print(f"[ERROR] HTTP {resp.status_code}: {resp.text}", file=sys.stderr)
        return ""

    full_content = []
    print("\n--- Assistant ---")
    for line in resp.iter_lines(decode_unicode=True):
        if not line:
            continue
        # SSE format: "data: {...}"
        if line.startswith("data: "):
            data_str = line[len("data: "):]
            if data_str.strip() == "[DONE]":
                break
            try:
                chunk = json.loads(data_str)
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content", "")
                if content:
                    print(content, end="", flush=True)
                    full_content.append(content)
            except json.JSONDecodeError:
                if verbose:
                    print(f"\n[SKIP] {data_str[:100]}")
    print("\n--- End ---")
    return "".join(full_content)


def print_response(data: dict):
    """Pretty-print the non-streaming response."""
    print("\n" + "=" * 60)
    print("[RESPONSE]")
    print("-" * 60)

    choices = data.get("choices", [])
    if not choices:
        print("(No choices in response)")
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return

    message = choices[0].get("message", {})
    role = message.get("role", "unknown")
    content = message.get("content", "")

    print(f"Role: {role}")
    print(f"Content:\n{content}")
    print("-" * 60)

    usage = data.get("usage", {})
    if usage:
        print(f"Usage: prompt_tokens={usage.get('prompt_tokens')}, "
              f"completion_tokens={usage.get('completion_tokens')}, "
              f"total_tokens={usage.get('total_tokens')}")

    finish_reason = choices[0].get("finish_reason", "")
    if finish_reason:
        print(f"Finish Reason: {finish_reason}")

    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="DeepSeek V4 Pro LLM API Test Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --prompt "你是谁？"
  %(prog)s --prompt "介绍一下北京" --system "你是一个旅游助手"
  %(prog)s --messages '[{"role":"user","content":"你好"},{"role":"assistant","content":"你好！"},{"role":"user","content":"今天天气怎么样？"}]'
  %(prog)s --prompt "写一首关于春天的诗" --stream
  %(prog)s --prompt "解释相对论" --temperature 0.3 --max-tokens 1024 --verbose
        """,
    )

    # Input mode: --prompt (single turn) or --messages (multi-turn)
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--prompt", "-p", type=str,
        help="Single user prompt (simple mode)",
    )
    input_group.add_argument(
        "--messages", "-m", type=str,
        help="Full messages array as JSON string (advanced mode)",
    )

    # Optional system prompt (only used with --prompt)
    parser.add_argument(
        "--system", "-s", type=str, default=DEFAULT_SYSTEM,
        help=f"System prompt (default: '{DEFAULT_SYSTEM[:40]}...')",
    )

    # Model parameters
    parser.add_argument(
        "--temperature", "-t", type=float, default=0.7,
        help="Temperature (0.0-2.0, default: 0.7)",
    )
    parser.add_argument(
        "--max-tokens", "-n", type=int, default=2048,
        help="Max tokens to generate (default: 2048)",
    )
    parser.add_argument(
        "--top-p", type=float, default=0.9,
        help="Top-p sampling (default: 0.9)",
    )
    parser.add_argument(
        "--model", type=str, default=DEFAULT_MODEL,
        help=f"Model name (default: {DEFAULT_MODEL})",
    )

    # Stream mode
    parser.add_argument(
        "--stream", action="store_true",
        help="Enable streaming output",
    )

    # Debug
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Print request/response details",
    )

    args = parser.parse_args()

    # ---- Build messages ----
    if args.messages:
        try:
            messages = json.loads(args.messages)
        except json.JSONDecodeError as e:
            print(f"[ERROR] Invalid JSON for --messages: {e}", file=sys.stderr)
            sys.exit(1)
        if not isinstance(messages, list):
            print("[ERROR] --messages must be a JSON array", file=sys.stderr)
            sys.exit(1)
    else:
        messages = [
            {"role": "system", "content": args.system},
            {"role": "user", "content": args.prompt},
        ]

    # ---- Build payload ----
    payload = build_payload(
        messages=messages,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        top_p=args.top_p,
        stream=args.stream,
        model=args.model,
    )

    # ---- Call API ----
    if args.stream:
        call_llm_stream(payload, verbose=args.verbose)
    else:
        data = call_llm(payload, verbose=args.verbose)
        if data:
            print_response(data)
        else:
            sys.exit(1)


if __name__ == "__main__":
    main()
