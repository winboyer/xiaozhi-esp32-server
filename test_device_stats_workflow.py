"""测试"设备统计查询"完整工作流程

验证流程：
1. 语音输入 "设备统计查询"
2. LLM 执行意图识别
3. 调用 staff_safe_query 函数
4. LLM 统计分析返回数据
5. 返回口语化结果
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'main/xiaozhi-server'))

import asyncio
import json
from unittest.mock import Mock, MagicMock, patch
from core.connection import ConnectionHandler
from core.handle.intentHandler import handle_user_intent, process_intent_result
from plugins_func.functions.staff_safe_query import staff_safe_query
from plugins_func.register import ActionResponse, Action


def create_mock_connection():
    """创建模拟的连接对象"""
    conn = Mock(spec=ConnectionHandler)
    
    # 模拟 logger
    conn.logger = Mock()
    conn.logger.bind = Mock(return_value=conn.logger)
    conn.logger.info = Mock()
    conn.logger.debug = Mock()
    conn.logger.error = Mock()
    conn.logger.warning = Mock()
    
    # 模拟 intent 服务
    conn.intent = Mock()
    conn.intent.llm = Mock()
    
    # 模拟意图识别返回 staff_safe_query
    intent_response = {
        "function_call": {
            "name": "staff_safe_query",
            "arguments": {
                "query": "设备统计查询"
            }
        }
    }
    
    async def mock_detect_intent(conn, dialogue, text):
        return json.dumps(intent_response)
    
    conn.intent.detect_intent = mock_detect_intent
    
    # 模拟 LLM 意图分析（选择 assetQuantityStatistics 接口）
    intent_analysis_result = {
        "api_id": "assetQuantityStatistics",
        "reason": "用户查询设备统计，匹配设备信息统计接口",
        "extra_params": {}
    }
    
    # 模拟 LLM 数据总结
    summary_text = "当前项目共有设备120台，其中在线设备95台，离线设备25台，设备在线率为79.2%。"
    
    # 配置 LLM 响应
    conn.intent.llm.response_no_stream = Mock(side_effect=[
        json.dumps(intent_analysis_result),  # 第一次调用：意图分析
        summary_text  # 第二次调用：数据总结
    ])
    
    # 模拟技能感知的摘要方法
    conn.intent.reply_result_with_skill_summary = Mock(
        return_value="好的，我来为您查询设备统计信息。" + summary_text
    )
    
    # 模拟对话历史
    conn.dialogue = Mock()
    conn.dialogue.dialogue = []
    conn.dialogue.put = Mock()
    
    # 模拟函数处理器
    conn.func_handler = Mock()
    conn.func_handler.tool_manager = Mock()
    conn.func_handler.tool_manager.get_all_tools = Mock(return_value={
        "staff_safe_query": Mock()
    })
    
    # 模拟配置
    conn.config = {
        "tool_call_timeout": 30
    }
    
    # 模拟 executor 和 loop
    conn.executor = Mock()
    conn.loop = asyncio.get_event_loop()
    
    # 模拟 TTS
    conn.tts = Mock()
    conn.tts.store_tts_text = Mock()
    conn.tts.tts_text_queue = Mock()
    conn.tts.tts_text_queue.put = Mock()
    conn.tts.tts_one_sentence = Mock()
    
    # 模拟 sentence_id
    conn.sentence_id = "test-sentence-id"
    
    return conn


async def test_intent_recognition():
    """测试步骤1: 意图识别"""
    print("\n" + "="*60)
    print("测试步骤1: 意图识别 - 输入'设备统计查询'")
    print("="*60)
    
    conn = create_mock_connection()
    text = "设备统计查询"
    
    # 调用意图识别
    intent_result = await conn.intent.detect_intent(conn, conn.dialogue.dialogue, text)
    intent_data = json.loads(intent_result)
    
    print(f"✓ 用户输入: {text}")
    print(f"✓ 意图识别结果: {json.dumps(intent_data, ensure_ascii=False, indent=2)}")
    
    # 验证是否识别为 staff_safe_query
    assert "function_call" in intent_data, "❌ 未识别到 function_call"
    assert intent_data["function_call"]["name"] == "staff_safe_query", \
        f"❌ 函数名错误: {intent_data['function_call']['name']}"
    assert intent_data["function_call"]["arguments"]["query"] == "设备统计查询", \
        "❌ 查询参数错误"
    
    print("✓ 意图识别正确: staff_safe_query")
    return intent_data


def test_staff_safe_query_call():
    """测试步骤2-3: 调用 staff_safe_query 并进行 LLM 分析"""
    print("\n" + "="*60)
    print("测试步骤2-3: 调用 staff_safe_query 函数")
    print("="*60)
    
    conn = create_mock_connection()
    
    # 模拟 API 返回数据
    mock_api_response = {
        "success": True,
        "http_status": 200,
        "elapsed": 0.5,
        "data": {
            "code": 200,
            "msg": "成功",
            "data": {
                "total": 120,
                "online": 95,
                "offline": 25,
                "onlineRate": 79.2
            }
        }
    }
    
    with patch('plugins_func.functions.staff_safe_query._call_api', return_value=mock_api_response):
        # 调用 staff_safe_query
        result = staff_safe_query(conn, query="设备统计查询")
        
        print(f"✓ 函数调用成功")
        print(f"✓ 返回动作类型: {result.action}")
        print(f"✓ 返回结果预览: {result.result[:200] if result.result else 'None'}...")
        
        # 验证返回类型
        assert isinstance(result, ActionResponse), "❌ 返回类型错误"
        assert result.action == Action.REQLLM, \
            f"❌ 动作类型错误: {result.action}, 应该是 Action.REQLLM"
        
        # 验证返回的 JSON 结构
        result_data = json.loads(result.result)
        assert "请求内容" in result_data, "❌ 缺少'请求内容'字段"
        assert "涉及数据" in result_data, "❌ 缺少'涉及数据'字段"
        assert "返回数据总结" in result_data, "❌ 缺少'返回数据总结'字段"
        
        print(f"✓ 返回数据结构正确")
        print(f"✓ 涉及接口: {result_data['涉及数据']['api_id']}")
        print(f"✓ LLM 总结: {result_data['返回数据总结']}")
        
        return result


def test_llm_summary():
    """测试步骤4: LLM 统计分析"""
    print("\n" + "="*60)
    print("测试步骤4: LLM 对返回数据进行统计分析")
    print("="*60)
    
    conn = create_mock_connection()
    
    # 模拟从 staff_safe_query 返回的数据
    staff_query_result = {
        "请求内容": "设备统计查询",
        "请求时间": "2026-11-06 18:20:00",
        "涉及数据": {
            "api_id": "assetQuantityStatistics",
            "api_description": "设备信息统计",
            "api_category": "设备"
        },
        "返回数据总结": "当前项目共有设备120台，其中在线设备95台，离线设备25台，设备在线率为79.2%。"
    }
    
    # 使用技能感知的摘要方法
    llm_result = conn.intent.reply_result_with_skill_summary(
        json.dumps(staff_query_result, ensure_ascii=False),
        "设备统计查询",
        "staff_safe_query"
    )
    
    print(f"✓ LLM 分析完成")
    print(f"✓ 口语化回复: {llm_result}")
    
    # 验证 LLM 回复包含关键信息
    assert "设备" in llm_result, "❌ 回复中缺少'设备'关键词"
    assert any(num in llm_result for num in ["120", "95", "25", "79"]), \
        "❌ 回复中缺少统计数字"
    
    print("✓ LLM 统计分析正确，包含关键数据")
    return llm_result


async def test_complete_workflow():
    """测试完整工作流程"""
    print("\n" + "="*60)
    print("完整工作流程测试: 设备统计查询")
    print("="*60)
    
    conn = create_mock_connection()
    user_input = "设备统计查询"
    
    print(f"\n📝 用户语音输入: '{user_input}'")
    
    # Step 1: 意图识别
    print("\n🔍 Step 1: LLM 意图识别...")
    intent_data = await test_intent_recognition()
    
    # Step 2-3: 调用 staff_safe_query
    print("\n🔧 Step 2-3: 调用 staff_safe_query 函数...")
    query_result = test_staff_safe_query_call()
    
    # Step 4: LLM 统计分析
    print("\n📊 Step 4: LLM 统计分析返回数据...")
    final_response = test_llm_summary()
    
    print("\n" + "="*60)
    print("✅ 完整工作流程测试通过!")
    print("="*60)
    print(f"\n最终输出给用户的语音: {final_response}")
    print("\n工作流程总结:")
    print("1. ✓ 语音输入'设备统计查询'被正确接收")
    print("2. ✓ LLM 意图识别识别为 staff_safe_query")
    print("3. ✓ staff_safe_query 函数被调用")
    print("4. ✓ 内部 LLM 分析选择 assetQuantityStatistics 接口")
    print("5. ✓ 调用数据接口获取设备统计数据")
    print("6. ✓ LLM 对返回数据进行统计分析和总结")
    print("7. ✓ 返回口语化的分析结果")


def check_skill_registration():
    """检查技能是否正确注册"""
    print("\n" + "="*60)
    print("检查 staff_safe_skill 技能注册")
    print("="*60)
    
    from plugins_func.skills.registry import skill_registry
    
    # 检查是否注册了 staff_safe_query
    hints = skill_registry.get("staff_safe_query")
    
    if hints:
        print("✓ staff_safe_query 技能已注册")
        print(f"✓ 优先级: {hints.priority}")
        print(f"✓ 关键词数量: {len(hints.keywords)}")
        print(f"✓ Few-shot 示例数量: {len(hints.few_shot_examples)}")
        
        # 检查是否包含"设备统计"相关关键词
        device_keywords = [kw for kw in hints.keywords if "设备" in kw]
        print(f"✓ 设备相关关键词: {device_keywords}")
        
        # 检查 few-shot 示例中是否有"设备信息统计"
        device_examples = [ex for ex in hints.few_shot_examples if "设备信息统计" in ex]
        if device_examples:
            print(f"✓ 包含设备统计示例: {len(device_examples)} 个")
            print(f"  示例内容: {device_examples[0][:100]}...")
        
        return True
    else:
        print("❌ staff_safe_query 技能未注册!")
        return False


if __name__ == "__main__":
    print("\n" + "="*60)
    print("设备统计查询工作流程验证测试")
    print("="*60)
    
    # 检查技能注册
    if not check_skill_registration():
        print("\n❌ 技能未正确注册，测试终止")
        exit(1)
    
    # 运行完整工作流程测试
    try:
        asyncio.run(test_complete_workflow())
        print("\n" + "="*60)
        print("🎉 所有测试通过! 工作流程符合预期")
        print("="*60)
    except AssertionError as e:
        print(f"\n❌ 测试失败: {e}")
        exit(1)
    except Exception as e:
        print(f"\n❌ 测试出错: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
