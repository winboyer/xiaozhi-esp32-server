#!/usr/bin/env python3
"""
电梯设备数据查询测试

查询接口: POST http://115.159.67.12:8090/api/device/query-exec
Query 参数: id=tw_lifter_0616
Body 参数 (raw-json) 格式:
  {
    "key": "tw_online",
    "params": {}
  }
  {
    "key": "tw_runtime",
    "params": {}
  }
  {
    "key": "tw_hourly_stats",
    "params": {
      "device_number": "0114004712251229001",
      "start_time": "2026-06-16 00:00:00",
      "end_time": "",
      "limit": 0,
      "offset": 0
    }
  }
  {
    "key": "tw_minute_traffic",
    "params": {
      "device_number": "0114004712251229001",
      "start_time": "2026-06-16 00:00:00",
      "end_time": "",
      "limit": 0,
      "offset": 0
    }
  }
"""

import json
from datetime import datetime
import requests

# ==================== 配置 ====================
DEVICE_QUERY_URL = "http://115.159.67.12:8090/api/device/query-exec"
DEVICE_ID = "tw_lifter_0616"
DEVICE_NUMBER = "0114004712251229001"

# ==================== 查询 Key 映射 ====================
QUERY_KEYS = {
    "tw_online": "在线状态",
    "tw_runtime": "运行数据",
    "tw_hourly_stats": "运行数据（按小时）",
    "tw_minute_traffic": "笼内人流量（按分钟）",
}


# ==================== 请求辅助 ====================
def _print_response(resp, method: str, desc: str):
    """格式化打印响应"""
    print(f"\n{'─'*60}")
    print(f"[{method}] {desc}")
    print(f"  状态码: {resp.status_code}")
    print(f"  耗时: {resp.elapsed.total_seconds():.2f}s")
    try:
        data = resp.json()
        resp_str = json.dumps(data, ensure_ascii=False, indent=2)
        if len(resp_str) > 5000:
            print(f"  响应(截取 5000 字符):\n{resp_str[:5000]}...")
        else:
            print(f"  响应:\n{resp_str}")
    except (json.JSONDecodeError, ValueError):
        text = resp.text[:3000]
        print(f"  响应(文本):\n{text}")


# ==================== 默认时间参数 ====================
def _default_start_time() -> str:
    """返回当天 00:00:00 格式的起始时间"""
    return datetime.now().strftime("%Y-%m-%d 00:00:00")


# ==================== 通用查询函数 ====================
def query_device(key: str, query_params: dict = None):
    """
    发起设备查询请求

    POST /api/device/query-exec?id=tw_lifter_0616

    Body 格式:
      {
        "key": "tw_xxx",
        "params": { ... }
      }

    Args:
        key: 查询字段名 (tw_online / tw_runtime / tw_hourly_stats / tw_minute_traffic)
        query_params: params 字典, 默认为空 {}

    Returns:
        响应 JSON 数据, 失败返回 None
    """
    url = DEVICE_QUERY_URL
    query_string = {"id": DEVICE_ID}
    if query_params is None:
        query_params = {}
    body = {"key": key, "params": query_params}

    desc = QUERY_KEYS.get(key, key)
    print(f"\n{'█'*50}")
    print(f"█  查询: {desc}")
    print(f"█  POST {url}")
    print(f"█  Query Params: {json.dumps(query_string)}")
    print(f"█  Body: {json.dumps(body, ensure_ascii=False)}")
    print(f"{'█'*50}")

    headers = {
        "accept": "application/json",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(
            url,
            params=query_string,
            json=body,
            headers=headers,
            timeout=30,
        )
        _print_response(resp, "POST", desc)

        if resp.status_code != 200:
            print(f"  ⚠ 请求失败, 状态码: {resp.status_code}")
            return None

        return resp.json()

    except requests.RequestException as e:
        print(f"  请求失败: {e}")
        return None


# ==================== 各查询函数 ====================
def query_online_status():
    """
    查询电梯在线状态 (tw_online)

    Body: {"key": "tw_online", "params": {}}
    """
    return query_device("tw_online", {})


def query_runtime():
    """
    查询电梯运行数据 (tw_runtime)

    Body: {"key": "tw_runtime", "params": {}}
    """
    return query_device("tw_runtime", {})


def query_hourly_stats(
    device_number: str = DEVICE_NUMBER,
    start_time: str = None,
    end_time: str = "",
    limit: int = 0,
    offset: int = 0,
):
    """
    查询电梯运行数据-按小时 (tw_hourly_stats)

    Body: {"key": "tw_hourly_stats", "params": { device_number, start_time, end_time, limit, offset }}

    Args:
        device_number: 设备编号
        start_time: 起始时间 (格式: YYYY-MM-DD HH:MM:SS), 默认当天 00:00:00
        end_time: 结束时间 (格式: YYYY-MM-DD HH:MM:SS), 默认空字符串
        limit: 分页条数, 0 表示不限制
        offset: 分页偏移量
    """
    if start_time is None:
        start_time = _default_start_time()
    params = {
        "device_number": device_number,
        "start_time": start_time,
        "end_time": end_time,
        "limit": limit,
        "offset": offset,
    }
    return query_device("tw_hourly_stats", params)


def query_minute_traffic(
    device_number: str = DEVICE_NUMBER,
    start_time: str = None,
    end_time: str = "",
    limit: int = 0,
    offset: int = 0,
):
    """
    查询笼内人流量-按分钟 (tw_minute_traffic)

    Body: {"key": "tw_minute_traffic", "params": { device_number, start_time, end_time, limit, offset }}

    Args:
        device_number: 设备编号
        start_time: 起始时间 (格式: YYYY-MM-DD HH:MM:SS), 默认当天 00:00:00
        end_time: 结束时间 (格式: YYYY-MM-DD HH:MM:SS), 默认空字符串
        limit: 分页条数, 0 表示不限制
        offset: 分页偏移量
    """
    if start_time is None:
        start_time = _default_start_time()
    params = {
        "device_number": device_number,
        "start_time": start_time,
        "end_time": end_time,
        "limit": limit,
        "offset": offset,
    }
    return query_device("tw_minute_traffic", params)


# ==================== 主流程 ====================
def run_all_queries():
    """执行所有电梯设备查询"""
    print("=" * 60)
    print("  电梯设备数据查询测试")
    print(f"  查询接口: {DEVICE_QUERY_URL}")
    print(f"  设备 ID : {DEVICE_ID}")
    print("=" * 60)

    # ---- 1. 在线状态 ----
    result_online = query_online_status()

    # ---- 2. 运行数据 ----
    result_runtime = query_runtime()

    # ---- 3. 运行数据（按小时） ----
    result_hourly = query_hourly_stats()

    # ---- 4. 笼内人流量（按分钟） ----
    result_traffic = query_minute_traffic()

    # ---- 汇总 ----
    print("\n" + "=" * 60)
    print("  查询执行完毕!")
    print(f"  在线状态         : {'✓ 成功' if result_online else '✗ 失败'}")
    print(f"  运行数据         : {'✓ 成功' if result_runtime else '✗ 失败'}")
    print(f"  运行数据(按小时)  : {'✓ 成功' if result_hourly else '✗ 失败'}")
    print(f"  笼内人流量(按分钟): {'✓ 成功' if result_traffic else '✗ 失败'}")
    print("=" * 60)


def run_single_query(key: str):
    """执行单个查询"""
    print("=" * 60)
    print(f"  电梯设备数据查询测试 - {QUERY_KEYS.get(key, key)}")
    print(f"  查询接口: {DEVICE_QUERY_URL}")
    print(f"  设备 ID : {DEVICE_ID}")
    print("=" * 60)

    query_device(key)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        key_arg = sys.argv[1]
        if key_arg in QUERY_KEYS:
            run_single_query(key_arg)
        elif key_arg == "--all" or key_arg == "-a":
            run_all_queries()
        else:
            print(f"用法: python {sys.argv[0]} [tw_online|tw_runtime|tw_hourly_stats|tw_minute_traffic|--all]")
            print(f"可选 key: {list(QUERY_KEYS.keys())}")
            print(f"默认执行全部查询: python {sys.argv[0]} --all")
    else:
        # 默认执行全部查询
        run_all_queries()