#!/usr/bin/env python3
"""
向阳村项目塔机作业状态查询测试 HTTP 服务

用途：阶段一 —— 独立测试服务，验证塔机历史作业数据接口的调用链路。
      输入塔机名称，自动映射到设备 SN，查询历史作业记录并返回作业状态。

启动方式：
    python test_taji_work_status_server.py

接口：
    GET  /test/status             - 服务状态检查
    GET  /test/catalog            - 接口目录
    POST /test/taji/work-status   - 按塔机名称查询作业状态（结构化参数）
    POST /test/taji/nl-query      - 自然语言查询（LLM 解析意图）
    GET  /                        - 交互式测试页面

字段说明：
    device_name  塔机名称（如「向阳村4#塔机」，支持「4#塔机」「塔机4」等简写）
    startTime    可选，开始时间，格式 YYYY-MM-DD HH:MM:SS
    endTime      可选，结束时间，格式 YYYY-MM-DD HH:MM:SS（支持 24:00:00）
"""

import json
import os
import re
import time
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

import requests

# ==================== 配置 ====================
SERVER_PORT = 8006

TOWER_CRANE_WORK_CYCLE_URL = (
    "https://tciccs.cscec3bxjy.cn:30400/api/towercranedataservice/getWorkCycleInfoHis"
)
TOWER_CRANE_REQUEST_TIMEOUT = 30

# LLM 意图解析配置（DeepSeek / OpenAI 兼容接口）
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "sk-655f2d0a7fa64b089c9155ce8931bb3b")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-v4-flash")
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "30"))

# 向阳村项目塔机名称 → 设备 SN 映射
TOWER_CRANE_NAME_TO_SN = {
    "向阳村4#塔机": "91320506MAE18ATB9XTC202606181EW4",
    "向阳村3#塔机": "91320506MAE18ATB9XTC202606181EW3",
    "向阳村2#塔机": "91320506MAE18ATB9XTC202606181EW2",
}


# ==================== 查询逻辑 ====================

def resolve_device_sn(name):
    """按塔机名称解析设备 SN，支持简写匹配。"""
    text = re.sub(r"\s+", "", str(name or ""))
    if not text:
        return None, None
    if text in TOWER_CRANE_NAME_TO_SN:
        return text, TOWER_CRANE_NAME_TO_SN[text]
    for full_name, device_sn in TOWER_CRANE_NAME_TO_SN.items():
        if full_name in text or text in full_name:
            return full_name, device_sn
    nums = re.findall(r"\d+", text)
    for full_name, device_sn in TOWER_CRANE_NAME_TO_SN.items():
        full_nums = re.findall(r"\d+", full_name)
        if nums and full_nums and any(n in full_nums for n in nums):
            return full_name, device_sn
    return None, None


def validate_time(value, field_name):
    """校验时间格式，允许日终 24:00:00。"""
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2} (?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d"
        r"|\d{4}-\d{2}-\d{2} 24:00:00",
        value,
    ):
        raise ValueError(f"{field_name} 必须使用 YYYY-MM-DD HH:MM:SS 格式")
    return value


def default_time_range():
    """默认查询当天 00:00:00 至 24:00:00。"""
    today = datetime.now().strftime("%Y-%m-%d")
    return f"{today} 00:00:00", f"{today} 24:00:00"


def query_tower_crane_work_status(device_name, start_time=None, end_time=None):
    """查询塔机历史作业记录并生成状态摘要。"""
    resolved_name, device_sn = resolve_device_sn(device_name)
    if not device_sn:
        raise ValueError(
            "未找到塔机名称，当前支持：" + "、".join(TOWER_CRANE_NAME_TO_SN)
        )

    default_start, default_end = default_time_range()
    start_time = validate_time(start_time or default_start, "startTime")
    end_time = validate_time(end_time or default_end, "endTime")

    try:
        resp = requests.post(
            TOWER_CRANE_WORK_CYCLE_URL,
            json={"deviceSN": device_sn, "startTime": start_time, "endTime": end_time},
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=TOWER_CRANE_REQUEST_TIMEOUT,
            verify=False,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"塔机数据接口请求失败: {exc}") from exc

    try:
        payload = resp.json()
    except ValueError as exc:
        raise RuntimeError(f"塔机数据接口返回非 JSON（HTTP {resp.status_code}）") from exc

    if resp.status_code != 200 or not payload.get("success"):
        message = payload.get("msg") or f"HTTP {resp.status_code}"
        raise RuntimeError(f"塔机数据接口查询失败: {message}")

    cycles = payload.get("data") or []
    if not isinstance(cycles, list):
        raise RuntimeError("塔机数据接口返回的 data 不是数组")

    latest = max(
        cycles,
        key=lambda item: item.get("endTime") or item.get("startTime") or "",
    ) if cycles else None

    return {
        "device_name": resolved_name,
        "device_sn": device_sn,
        "start_time": start_time,
        "end_time": end_time,
        "status": "有作业记录" if cycles else "查询范围内无作业记录",
        "work_cycle_count": len(cycles),
        "latest_cycle": latest,
    }


def query_all_cranes(start_time=None, end_time=None):
    """查询全部塔机的历史作业状态。"""
    results = []
    for name in TOWER_CRANE_NAME_TO_SN:
        try:
            results.append(query_tower_crane_work_status(name, start_time, end_time))
        except (ValueError, RuntimeError) as exc:
            results.append({"device_name": name, "error": str(exc)})
    return results


def crane_status_summary(result):
    """从单台塔机查询结果中提取作业状态摘要字段。"""
    if not isinstance(result, dict) or result.get("error"):
        return result
    latest = result.get("latest_cycle") or {}
    return {
        "device_name": result.get("device_name"),
        "device_sn": result.get("device_sn"),
        "status": result.get("status"),
        "work_cycle_count": result.get("work_cycle_count"),
        "type": latest.get("type"),
        "weight": latest.get("weight"),
        "hasObjectType": latest.get("hasObjectType"),
    }


def _safe_parse_json(raw):
    """安全解析 LLM 返回的 JSON。"""
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return {}


def llm_parse_query(query_text):
    """用 LLM 解析自然语言查询：目标塔机（或全部）与时间范围。"""
    today = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    system_prompt = (
        "你是塔机查询意图解析器。根据用户自然语言输入，解析查询目标，只返回 JSON 对象。\n"
        'JSON格式：{"device_name":"塔机名称或null","start_time":"YYYY-MM-DD HH:MM:SS或null","end_time":"YYYY-MM-DD HH:MM:SS或null"}\n'
        "规则：\n"
        "1. device_name：用户指定塔机时返回塔机名称（如\"向阳村4#塔机\"、\"4#塔机\"、\"塔机2\"）；查询全部塔机时返回 null。\n"
        "2. start_time/end_time：解析用户指定的时间范围并转为绝对时间。未指定时默认当天 00:00:00 至 24:00:00。支持\"今天\"、\"昨天\"、\"最近三天\"、\"6月20日\"等表达。\n"
        f"3. 今天是{today}，当前时间{now}。"
    )
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query_text},
        ],
        "temperature": 0,
        "max_tokens": 500,
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
    }
    resp = requests.post(
        f"{LLM_BASE_URL}/v1/chat/completions",
        headers={"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"},
        json=payload,
        timeout=LLM_TIMEOUT,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"LLM 意图解析失败（HTTP {resp.status_code}）")
    data = resp.json()
    message = data["choices"][0]["message"]
    content = (message.get("content") or "").strip()
    if not content:
        # 推理模型兼容：thinking 被禁用失败时回退解析 reasoning_content
        content = (message.get("reasoning_content") or "").strip()
    parsed = _safe_parse_json(content)
    return {
        "device_name": parsed.get("device_name"),
        "start_time": parsed.get("start_time"),
        "end_time": parsed.get("end_time"),
    }


# ==================== HTTP 处理器 ====================

class TestServerHandler(BaseHTTPRequestHandler):
    """测试服务 HTTP 处理器"""

    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        print(f"[HTTP] {self.client_address[0]} - {format % args}")

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Connection", "close")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def _send_html(self, html, status=200):
        body = html.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Connection", "close")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"请求体不是有效 JSON: {exc.msg}") from exc
        if not isinstance(data, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return data

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._serve_test_page()
        elif path == "/test/status":
            self._send_json({
                "status": "ok",
                "available_devices": list(TOWER_CRANE_NAME_TO_SN),
                "timestamp": datetime.now().isoformat(),
            })
        elif path == "/test/catalog":
            self._send_json({
                "endpoints": [
                    {"method": "GET", "path": "/test/status"},
                    {"method": "GET", "path": "/test/catalog"},
                    {"method": "POST", "path": "/test/taji/work-status"},
                    {"method": "POST", "path": "/test/taji/nl-query"},
                ],
            })
        else:
            self._send_json({"error": "Not Found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/test/taji/work-status":
            self._handle_work_status()
        elif path == "/test/taji/nl-query":
            self._handle_nl_query()
        else:
            self._send_json({"error": "Not Found"}, 404)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _handle_work_status(self):
        try:
            body = self._read_body()
            device_name = (
                body.get("device_name")
                or body.get("deviceName")
                or body.get("name")
            )
            if not device_name:
                self._send_json({
                    "error": "请提供 device_name，例如：向阳村4#塔机",
                    "available_devices": list(TOWER_CRANE_NAME_TO_SN),
                }, 400)
                return

            start_time = body.get("startTime") or body.get("start_time")
            end_time = body.get("endTime") or body.get("end_time")
            result = query_tower_crane_work_status(device_name, start_time, end_time)
            self._send_json({"success": True, "data": result})
        except ValueError as exc:
            self._send_json({"success": False, "error": str(exc)}, 400)
        except RuntimeError as exc:
            self._send_json({"success": False, "error": str(exc)}, 502)

    def _handle_nl_query(self):
        """自然语言查询：LLM 解析意图后查询全部或指定塔机。"""
        try:
            body = self._read_body()
            query_text = (body.get("query") or body.get("text") or "").strip()
            if not query_text:
                self._send_json({"error": "请提供 query 字段（自然语言查询）"}, 400)
                return

            parsed = {"device_name": None, "start_time": None, "end_time": None}
            llm_error = None
            try:
                parsed = llm_parse_query(query_text)
            except (requests.RequestException, RuntimeError, KeyError, ValueError) as exc:
                llm_error = str(exc)
                print(f"[LLM] 意图解析失败，降级为查询全部塔机当天数据: {exc}")

            device_name = parsed.get("device_name")
            start_time = parsed.get("start_time")
            end_time = parsed.get("end_time")

            if device_name:
                try:
                    results = [query_tower_crane_work_status(device_name, start_time, end_time)]
                except (ValueError, RuntimeError) as exc:
                    results = [{"device_name": device_name, "error": str(exc)}]
            else:
                # 查询全部塔机：按所有设备编号查询，并输出作业状态摘要字段
                results = [
                    crane_status_summary(item)
                    for item in query_all_cranes(start_time, end_time)
                ]

            self._send_json({
                "success": True,
                "query": query_text,
                "parsed_intent": {
                    "device_name": device_name,
                    "start_time": start_time,
                    "end_time": end_time,
                },
                "llm_error": llm_error,
                "data": results,
            })
        except ValueError as exc:
            self._send_json({"success": False, "error": str(exc)}, 400)
        except Exception as exc:
            self._send_json({"success": False, "error": str(exc)}, 500)

    def _serve_test_page(self):
        html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>向阳村塔机作业状态测试</title>
<style>
body { font-family: -apple-system, "PingFang SC", sans-serif; background:#f0f4f8; margin:0; padding:24px; }
h1 { font-size:20px; color:#0d47a1; }
.card { background:#fff; border-radius:12px; padding:20px; margin:16px 0; box-shadow:0 2px 12px rgba(0,0,0,0.06); }
input { padding:10px 14px; border:2px solid #e0e0e0; border-radius:8px; font-size:14px; margin:4px; }
button { padding:10px 20px; background:#1a73e8; color:#fff; border:none; border-radius:8px; cursor:pointer; font-size:14px; }
pre { background:#f6f8fa; padding:14px; border-radius:8px; white-space:pre-wrap; font-size:13px; }
</style>
</head>
<body>
<h1>🏗️ 向阳村塔机作业状态测试服务</h1>
<div class="card">
    <h2>🔍 自然语言查询</h2>
    <input id="nl" placeholder="例：查询所有塔机今天的作业状态 / 4#塔机6月20日干了多少活" style="width:70%">
    <button onclick="nlQuery()">查询</button>
</div>
<div class="card">
    <h2>📋 结构化参数查询</h2>
    <label>塔机名称</label>
    <input id="name" placeholder="向阳村4#塔机 / 4#塔机 / 塔机2" value="向阳村4#塔机">
    <label>开始时间</label>
    <input id="start" placeholder="2026-06-20 00:00:00" value="2026-06-20 00:00:00">
    <label>结束时间</label>
    <input id="end" placeholder="2026-06-20 24:00:00" value="2026-06-20 24:00:00">
    <button onclick="query()">查询</button>
</div>
<div class="card">
    <pre id="result">等待查询...</pre>
</div>
<script>
async function nlQuery() {
    const result = document.getElementById('result');
    result.textContent = 'LLM 解析中...';
    try {
        const resp = await fetch('/test/taji/nl-query', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({query: document.getElementById('nl').value.trim()}),
        });
        result.textContent = JSON.stringify(await resp.json(), null, 2);
    } catch (e) {
        result.textContent = '请求失败: ' + e.message;
    }
}
async function query() {
    const result = document.getElementById('result');
    result.textContent = '查询中...';
    const body = {
        device_name: document.getElementById('name').value.trim(),
        startTime: document.getElementById('start').value.trim(),
        endTime: document.getElementById('end').value.trim(),
    };
    try {
        const resp = await fetch('/test/taji/work-status', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(body),
        });
        result.textContent = JSON.stringify(await resp.json(), null, 2);
    } catch (e) {
        result.textContent = '请求失败: ' + e.message;
    }
}
</script>
</body>
</html>"""
        self._send_html(html)


def main():
    print("=" * 60)
    print("  向阳村塔机作业状态查询测试服务")
    print("=" * 60)
    print(f"  可用塔机: {', '.join(TOWER_CRANE_NAME_TO_SN)}")
    print(f"  服务地址: http://127.0.0.1:{SERVER_PORT}")
    print(f"  结构化查询: POST /test/taji/work-status")
    print(f"  自然语言查询: POST /test/taji/nl-query")
    print("  按 Ctrl+C 停止服务")

    server = HTTPServer(("0.0.0.0", SERVER_PORT), TestServerHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
        server.shutdown()


if __name__ == "__main__":
    main()
