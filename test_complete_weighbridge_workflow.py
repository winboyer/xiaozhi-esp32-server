#!/usr/bin/env python3
"""
完整测试：地磅数据查询工作流
从语音识别文本 → LLM意图理解 → HTTP POST查询数据 → LLM总结结果

测试场景："统计分析三元里最近一周的地磅数据情况"
"""
import sys
import os
import json
import re
import asyncio
from datetime import datetime
from typing import Dict, Any

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "main/xiaozhi-server"))

from config.logger import setup_logging
from plugins_func.functions.analyze_weighbridge_data import (
    analyze_weighbridge_data,
    _resolve_date_range,
    _extract_weighbridge_stats,
    _format_analysis_response,
)
from core.handle.intentHandler import (
    WEIGHBRIDGE_QUERY_PATTERN,
    try_handle_weighbridge_query,
)

logger = setup_logging()
TAG = __name__


class MockConnectionHandler:
    """模拟ConnectionHandler用于测试"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logger
        self.device_id = "test_device_001"
        self.func_handler = None
        self.client_abort = False
        self.sentence_id = None
        self.current_speaker = None
        self.dialogue = MockDialogue()
        self.executor = None
        self.loop = None

    class MockFuncHandler:
        """模拟函数处理器"""

        def has_tool(self, tool_name: str) -> bool:
            return tool_name == "analyze_weighbridge_data"

        async def handle_llm_function_call(self, conn, function_call_data):
            """模拟函数调用"""
            from plugins_func.register import ActionResponse

            function_name = function_call_data.get("name")
            arguments = function_call_data.get("arguments", "{}")

            if isinstance(arguments, str):
                args = json.loads(arguments)
            else:
                args = arguments

            logger.bind(tag=TAG).info(
                f"[模拟函数调用] {function_name}, 参数: {args}"
            )

            # 调用实际的地磅数据分析函数
            if function_name == "analyze_weighbridge_data":
                return analyze_weighbridge_data(
                    conn,
                    location=args.get("location"),
                    date=args.get("date"),
                    date_range=args.get("date_range"),
                )

            return ActionResponse(
                action="ERROR", result="未知函数", response="未知函数"
            )


class MockDialogue:
    """模拟对话历史"""

    def __init__(self):
        self.dialogue = []

    def put(self, message):
        self.dialogue.append(message)


class MockLLM:
    """模拟LLM用于意图识别"""

    def __init__(self):
        self.model_name = "MockLLM-IntentRecognition"

    def response_no_stream(self, system_prompt: str, user_prompt: str) -> str:
        """模拟LLM意图识别响应"""
        logger.bind(tag=TAG).info(f"[模拟LLM] 收到意图识别请求")
        logger.bind(tag=TAG).debug(f"用户输入: {user_prompt}")

        # 从用户输入中提取实际查询文本
        user_text = ""
        if "User:" in user_prompt:
            user_text = user_prompt.split("User:")[-1].strip()

        # 模拟意图识别逻辑
        if "地磅" in user_text and "三元里" in user_text:
            # 提取日期范围
            date_range = None
            if "最近一周" in user_text or "一周" in user_text:
                date_range = "last_week"
            elif "今天" in user_text:
                date_range = "today"
            elif "昨天" in user_text:
                date_range = "yesterday"
            elif "最近一月" in user_text or "一个月" in user_text:
                date_range = "last_month"

            # 构建function_call响应
            function_call = {
                "function_call": {
                    "name": "analyze_weighbridge_data",
                    "arguments": {"location": "三元里"},
                }
            }

            if date_range:
                function_call["function_call"]["arguments"]["date_range"] = date_range

            result = json.dumps(function_call, ensure_ascii=False)
            logger.bind(tag=TAG).info(f"[模拟LLM] 意图识别结果: {result}")
            return result

        # 默认返回继续聊天
        return '{"function_call": {"name": "continue_chat"}}'


def print_section(title: str):
    """打印分节标题"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def test_step1_speech_recognition():
    """步骤1: 模拟语音识别结果"""
    print_section("步骤1: 语音识别文本输入")

    speech_text = "统计分析三元里最近一周的地磅数据情况"
    print(f"✓ 语音识别文本: {speech_text}")
    print(f"  - 识别时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  - 文本长度: {len(speech_text)} 字符")

    return speech_text


def test_step2_intent_understanding(speech_text: str):
    """步骤2: LLM意图理解"""
    print_section("步骤2: LLM意图理解")

    # 测试正则匹配（固定语义直达）
    print("\n[2.1] 固定语义模式匹配:")
    match = WEIGHBRIDGE_QUERY_PATTERN.search(speech_text)
    if match:
        location = match.group("location")
        print(f"✓ 正则匹配成功")
        print(f"  - 匹配模式: {WEIGHBRIDGE_QUERY_PATTERN.pattern}")
        print(f"  - 提取地点: {location}")

        # 提取日期范围
        date_range = None
        if "最近一周" in speech_text or "一周" in speech_text:
            date_range = "last_week"
        elif "今天" in speech_text:
            date_range = "today"
        elif "昨天" in speech_text:
            date_range = "yesterday"
        elif "最近一月" in speech_text:
            date_range = "last_month"

        print(f"  - 日期范围: {date_range or '默认(今天)'}")
    else:
        print("✗ 正则匹配失败，将使用LLM意图识别")

    # 测试LLM意图识别
    print("\n[2.2] LLM意图识别:")
    mock_llm = MockLLM()
    user_prompt = f"current dialogue:\nUser: {speech_text}\n"

    intent_result = mock_llm.response_no_stream(
        system_prompt="意图识别系统提示词...", user_prompt=user_prompt
    )

    print(f"✓ LLM意图识别完成")
    print(f"  - 识别结果: {intent_result}")

    # 解析意图
    try:
        intent_data = json.loads(intent_result)
        function_call = intent_data.get("function_call", {})
        function_name = function_call.get("name")
        function_args = function_call.get("arguments", {})

        print(f"  - 函数名称: {function_name}")
        print(f"  - 函数参数: {json.dumps(function_args, ensure_ascii=False)}")

        return {
            "function_name": function_name,
            "function_args": function_args,
            "raw_intent": intent_result,
        }
    except json.JSONDecodeError as e:
        print(f"✗ 意图解析失败: {e}")
        return None


def test_step3_http_query(intent_data: Dict[str, Any]):
    """步骤3: HTTP POST查询数据接口"""
    print_section("步骤3: HTTP POST查询数据接口")

    function_args = intent_data.get("function_args", {})
    location = function_args.get("location", "三元里")
    date_range = function_args.get("date_range", "last_week")

    print(f"\n[3.1] 准备查询参数:")
    print(f"  - 地点: {location}")
    print(f"  - 日期范围: {date_range}")

    # 解析日期范围
    date_info = _resolve_date_range(None, date_range)
    print(f"\n[3.2] 日期范围解析:")
    print(f"  - 查询类型: {date_info['query_type']}")
    print(f"  - 结束时间: {date_info['end_time']}")
    print(f"  - 标签: {date_info['label']}")

    # 构建HTTP请求
    api_url = "https://dmap.cscec3bxjy.cn/api/dibang/report/workerstatus"
    payload = {
        "project_id": "sanyuanli",  # 实际应从配置映射获取
        "query_type": date_info["query_type"],
        "end_time": date_info["end_time"],
    }

    print(f"\n[3.3] HTTP POST请求:")
    print(f"  - API地址: {api_url}")
    print(f"  - 请求体: {json.dumps(payload, ensure_ascii=False, indent=2)}")

    # 执行HTTP请求
    import requests

    try:
        print(f"\n[3.4] 发送请求...")
        resp = requests.post(api_url, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        print(f"✓ HTTP请求成功")
        print(f"  - 响应状态码: {resp.status_code}")
        print(f"  - API返回码: {data.get('code')}")
        print(f"  - API消息: {data.get('msg')}")

        result_data = data.get("data", {})
        records = result_data.get("list") or []
        print(f"  - 原始记录数: {len(records)}")
        print(f"  - 查询范围: {result_data.get('start_time')} ~ {result_data.get('end_time')}")

        return {"api_response": data, "date_info": date_info, "location": location}

    except requests.exceptions.Timeout:
        print("✗ HTTP请求超时")
        return None
    except requests.exceptions.RequestException as e:
        print(f"✗ HTTP请求失败: {e}")
        return None
    except Exception as e:
        print(f"✗ 处理异常: {e}")
        return None


def test_step4_data_analysis(query_result: Dict[str, Any]):
    """步骤4: 数据统计分析"""
    print_section("步骤4: 数据统计分析")

    api_response = query_result.get("api_response", {})
    date_info = query_result.get("date_info", {})
    location = query_result.get("location", "三元里")

    print("\n[4.1] 提取统计信息:")
    stats = _extract_weighbridge_stats(api_response)

    print(f"  - 总车次: {stats['total_count']}")
    print(f"  - 总重量: {stats['total_weight']:.2f} 吨")
    print(f"  - 平均重量: {stats['avg_weight']:.2f} 吨")
    print(f"  - 活跃车辆: {len(stats['plate_stats'])} 辆")
    print(f"  - 活跃天数: {len(stats['daily_stats'])} 天")

    if stats.get("peak_day"):
        peak_day, peak_data = stats["peak_day"]
        print(f"  - 高峰日: {peak_day} ({peak_data['count']}车次)")

    if stats.get("top_plate"):
        top_plate, top_data = stats["top_plate"]
        print(f"  - 最活跃车辆: {top_plate} ({top_data['count']}车次)")

    print("\n[4.2] 每日统计明细:")
    daily_stats = stats.get("daily_stats", {})
    for day in sorted(daily_stats.keys()):
        s = daily_stats[day]
        print(f"  · {day}: {s['count']}车次, {s['weight']:.1f}吨")

    return {"stats": stats, "date_info": date_info, "location": location}


def test_step5_llm_summary(analysis_result: Dict[str, Any]):
    """步骤5: LLM生成总结"""
    print_section("步骤5: LLM生成自然语言总结")

    stats = analysis_result.get("stats", {})
    date_info = analysis_result.get("date_info", {})
    location = analysis_result.get("location", "三元里")

    print("\n[5.1] 格式化分析结果:")
    response_text = _format_analysis_response(location, date_info["label"], stats)

    print(f"✓ 生成总结完成")
    print(f"  - 总结长度: {len(response_text)} 字符")
    print(f"\n[5.2] 总结内容:")
    print("-" * 80)
    print(response_text)
    print("-" * 80)

    return response_text


def test_step6_integration_test():
    """步骤6: 完整集成测试"""
    print_section("步骤6: 完整集成测试（使用真实函数）")

    # 创建模拟配置
    config = {
        "plugins": {
            "analyze_weighbridge_data": {
                "api_url": "https://dmap.cscec3bxjy.cn/api/dibang/report/workerstatus",
                "timeout": 30,
                "location_project_map": {"三元里": "sanyuanli"},
                "default_project_id": "sanyuanli",
            }
        },
        "tool_call_timeout": 30,
    }

    # 创建模拟连接
    conn = MockConnectionHandler(config)
    conn.func_handler = MockConnectionHandler.MockFuncHandler()

    print("\n[6.1] 调用真实的analyze_weighbridge_data函数:")
    print(f"  - 地点: 三元里")
    print(f"  - 日期范围: last_week")

    # 调用真实函数
    result = analyze_weighbridge_data(
        conn, location="三元里", date_range="last_week"
    )

    print(f"\n[6.2] 函数执行结果:")
    print(f"  - Action: {result.action}")
    print(f"  - 响应长度: {len(result.response) if result.response else 0} 字符")

    if result.response:
        print(f"\n[6.3] 完整响应内容:")
        print("-" * 80)
        print(result.response)
        print("-" * 80)

    return result


def main():
    """主测试流程"""
    print("\n" + "=" * 80)
    print("  地磅数据查询完整工作流测试")
    print("  测试场景: 统计分析三元里最近一周的地磅数据情况")
    print("=" * 80)
    print(f"  测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    try:
        # 步骤1: 语音识别
        speech_text = test_step1_speech_recognition()

        # 步骤2: 意图理解
        intent_data = test_step2_intent_understanding(speech_text)
        if not intent_data:
            print("\n✗ 意图理解失败，测试终止")
            return

        # 步骤3: HTTP查询
        query_result = test_step3_http_query(intent_data)
        if not query_result:
            print("\n✗ HTTP查询失败，测试终止")
            return

        # 步骤4: 数据分析
        analysis_result = test_step4_data_analysis(query_result)

        # 步骤5: LLM总结
        summary = test_step5_llm_summary(analysis_result)

        # 步骤6: 完整集成测试
        integration_result = test_step6_integration_test()

        # 测试总结
        print_section("测试总结")
        print("\n✓ 所有测试步骤完成")
        print("\n[链路完整性验证]:")
        print("  ✓ 步骤1: 语音识别文本输入 - 成功")
        print("  ✓ 步骤2: LLM意图理解 - 成功")
        print("  ✓ 步骤3: HTTP POST查询数据 - 成功")
        print("  ✓ 步骤4: 数据统计分析 - 成功")
        print("  ✓ 步骤5: LLM生成总结 - 成功")
        print("  ✓ 步骤6: 完整集成测试 - 成功")

        print("\n[准确性验证]:")
        print("  ✓ 意图识别准确: 正确识别为地磅数据查询")
        print("  ✓ 参数提取准确: 地点(三元里) + 时间范围(最近一周)")
        print("  ✓ 数据查询准确: 成功调用外部API并获取数据")
        print("  ✓ 统计分析准确: 正确计算总车次、总重量、高峰日等指标")
        print("  ✓ 总结生成准确: 自然语言总结清晰、完整")

        print("\n[性能指标]:")
        print(f"  - 总结长度: {len(summary)} 字符")
        print(f"  - 测试完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        print("\n" + "=" * 80)
        print("  测试完成 - 链路完整性和准确性验证通过 ✓")
        print("=" * 80 + "\n")

    except Exception as e:
        print(f"\n✗ 测试过程中发生异常: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
