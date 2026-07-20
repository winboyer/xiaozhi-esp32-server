#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Voice pipeline intent recognition integration test.

Simulates: ASR output -> startToChat -> handle_user_intent ->
conn.chat -> staff_safe_query -> result

Usage:
    python test_voice_intent_pipeline.py
"""

import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "main/xiaozhi-server"))

import yaml
from core.utils.llm import create_instance
from plugins_func.functions.staff_safe_query import (
    _build_intent_prompt,
    _build_summary_prompt,
    _call_api,
    _select_api_by_intent,
    _truncate_data,
    API_CATALOG,
)

VOICE_INPUT = "班组出勤情况查询"


def load_config():
    root = os.path.join(os.path.dirname(__file__), "main/xiaozhi-server")
    cfg = yaml.safe_load(open(os.path.join(root, "config.yaml")))
    cust = os.path.join(root, "data", ".config.yaml")
    if os.path.exists(cust):
        c = yaml.safe_load(open(cust))
        if not c.get("manager-api", {}).get("url"):
            for k in ["LLM", "selected_module"]:
                if k in c:
                    cfg[k] = {**cfg.get(k, {}), **c[k]}
    return cfg


def get_first_valid_llm(llm_map):
    for name, cfg in llm_map.items():
        if isinstance(cfg, dict) and cfg.get("api_key") and "?" not in str(cfg["api_key"]):
            return name, cfg
    return None, None


print("=" * 60)
print("  Voice Pipeline Intent Recognition Test")
print(f"  Simulated voice input: {VOICE_INPUT}")
print("=" * 60)

cfg = load_config()
sel = cfg["selected_module"]["LLM"]
llm_cfg = cfg["LLM"].get(sel, {})
if not llm_cfg:
    sel, llm_cfg = get_first_valid_llm(cfg.get("LLM", {}))
assert llm_cfg, "No valid LLM config found"

print(f"  Using LLM: {sel}, model: {llm_cfg.get('model_name')}")
llm = create_instance(llm_cfg.get("type", "openai"), llm_cfg)
start = time.time()

# Step 1: Intent analysis
print("\n--- Step 1: LLM Intent Analysis ---")
prompt = _build_intent_prompt(VOICE_INPUT)
raw = llm.response_no_stream(system_prompt=prompt, user_prompt=VOICE_INPUT)
m = re.search(r"\{.*\}", raw.strip(), re.DOTALL)
intent = json.loads(m.group(0) if m else raw)
print(f"  api_id: {intent.get('api_id')} | reason: {intent.get('reason')}")

# Step 2: API routing
print("\n--- Step 2: API Routing ---")
api = _select_api_by_intent(intent)
if not api:
    try:
        idx = int(intent.get("api_id", "-1"))
        if 0 <= idx < len(API_CATALOG):
            api = API_CATALOG[idx]
    except Exception:
        pass
assert api, f"API not found: {intent.get('api_id')}"
print(f"  -> [{api['method']}] {api['api_id']} - {api['description']}")

# Step 3: API call
print("\n--- Step 3: API Call ---")
extra = intent.get("extra_params", {})
path = api["path"]
if "snapshoot" in path and "startDate" not in extra:
    t = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
    extra["startDate"] = f"{t} 00:00:00"
    extra["endDate"] = f"{t} 23:59:59"
result = _call_api(api, extra)
assert result["success"], f"API call failed: {result.get('error')}"
print(f"  HTTP {result['http_status']} | {result['elapsed']}s | data_len={len(json.dumps(result['data']))}")

# Step 4: LLM summary
print("\n--- Step 4: LLM Data Summary ---")
data = _truncate_data(result["data"], 3000)
sp = _build_summary_prompt(api["description"], data, VOICE_INPUT, api["category"])
summary = llm.response_no_stream(system_prompt=sp, user_prompt="Generate summary")
print(f"  Summary: {summary.strip()[:150]}...")

elapsed = time.time() - start
print()
print("=" * 60)
print(f"  ALL 4 STEPS PASSED | {elapsed:.1f}s")
print(f"  Input: {VOICE_INPUT}")
print(f"  API: {api['api_id']} ({api['description']})")
print("=" * 60)