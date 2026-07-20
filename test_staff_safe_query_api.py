#!/usr/bin/env python3
"""
工地安全数据智能查询接口测试

测试两种调用方式：
1. HTTP REST API 调用（POST /staff-safe/query）
2. 验证接口目录正确性

前置条件：服务已启动，LLM 已配置
"""

import json
import requests

# ==================== 配置 ====================
BASE_URL = "http://127.0.0.1:8003"

# 测试查询语句
TEST_QUERIES = [
    {"query": "查询今天人员总览", "description": "人员总览查询"},
    {"query": "看看最近告警记录", "description": "告警记录查询"},
    {"query": "今天班组出勤情况", "description": "班组出勤查询"},
    {"query": "人员定位24小时走势", "description": "人员定位查询"},
    {"query": "基站物资信息", "description": "基站物资查询"},
    {"query": "设备信息统计", "description": "设备统计查询"},
    {"query": "组织架构", "description": "组织架构查询"},
    {"query": "今天考勤统计", "description": "考勤统计查询"},
]


def test_status():
    """测试服务状态接口"""
    print("=" * 60)
    print("1. 测试服务状态接口 GET /staff-safe/status")
    print("=" * 60)
    try:
        resp = requests.get(f"{BASE_URL}/staff-safe/status", timeout=10)
        print(f"  状态码: {resp.status_code}")
        data = resp.json()
        print(f"  响应: {json.dumps(data, ensure_ascii=False, indent=2)}")
        return data.get("status") == "running"
    except requests.RequestException as e:
        print(f"  请求失败: {e}")
        return False


def test_query(query_text: str, description: str):
    """测试查询接口"""
    print(f"\n{'─' * 60}")
    print(f"测试: {description}")
    print(f"  查询内容: {query_text}")
    print(f"{'─' * 60}")

    try:
        resp = requests.post(
            f"{BASE_URL}/staff-safe/query",
            json={"query": query_text},
            timeout=120,  # LLM 调用可能需要较长时间
        )
        print(f"  状态码: {resp.status_code}")

        if resp.status_code == 200:
            data = resp.json()
            print(f"  请求内容: {data.get('请求内容', 'N/A')}")
            print(f"  请求时间: {data.get('请求时间', 'N/A')}")
            print(f"  涉及数据:")
            involved = data.get("涉及数据", {})
            for key, val in involved.items():
                print(f"    - {key}: {val}")
            print(f"  返回数据总结: {data.get('返回数据总结', 'N/A')[:200]}...")
            return True
        else:
            error_data = resp.json() if resp.text else {}
            print(f"  错误: {error_data.get('message', resp.text[:200])}")
            return False
    except requests.exceptions.Timeout:
        print(f"  请求超时（120秒）")
        return False
    except requests.RequestException as e:
        print(f"  请求失败: {e}")
        return False


def print_api_catalog():
    """打印可用的接口目录"""
    print("\n" + "=" * 60)
    print("可用接口目录")
    print("=" * 60)

    # 直接导入目录定义
    import sys
    sys.path.insert(0, "main/xiaozhi-server")

    try:
        from plugins_func.functions.staff_safe_query import API_CATALOG

        categories = {}
        for api in API_CATALOG:
            cat = api["category"]
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(api)

        for cat, apis in categories.items():
            print(f"\n【{cat}】")
            for api in apis:
                print(f"  [{api['method']}] {api['api_id']}")
                print(f"    描述: {api['description']}")
                kw = ", ".join(api.get("keywords", [])[:4])
                print(f"    关键词: {kw}")
    except ImportError as e:
        print(f"  无法导入 API_CATALOG: {e}")
        print("  接口列表:")
        for cat in [
            "大屏-首页", "大屏-告警", "大屏-作业面",
            "定位", "设备", "人员", "组织", "统计",
        ]:
            print(f"  - {cat}")


if __name__ == "__main__":
    print("=" * 60)
    print("  工地安全数据智能查询接口测试")
    print(f"  Base URL: {BASE_URL}")
    print("=" * 60)

    # 1. 显示接口目录
    print_api_catalog()

    # 2. 测试服务状态
    print("\n")
    running = test_status()

    if not running:
        print("\n⚠️  LLM 服务未就绪，跳过查询测试。")
        print("   请确认：")
        print("   1. 服务已启动（python main/xiaozhi-server/app.py）")
        print("   2. config.yaml 中的 LLM 配置正确")
        print("   3. API Key 有效")
    else:
        # 3. 测试查询接口
        print("\n")
        passed = 0
        failed = 0
        for test in TEST_QUERIES:
            success = test_query(test["query"], test["description"])
            if success:
                passed += 1
            else:
                failed += 1

        print("\n" + "=" * 60)
        print(f"  测试完成: 通过 {passed}, 失败 {failed}")
        print("=" * 60)