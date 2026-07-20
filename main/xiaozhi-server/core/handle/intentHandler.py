import json
import uuid
import asyncio
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler
from core.utils.dialogue import Message
from core.providers.tts.dto.dto import ContentType
from core.handle.helloHandle import checkWakeupWords
from plugins_func.register import Action, ActionResponse
from core.handle.sendAudioHandle import send_stt_message
from core.handle.reportHandle import enqueue_tool_report
from core.utils.util import remove_punctuation_and_length
from core.providers.tts.dto.dto import TTSMessageDTO, SentenceType

# 天气相关关键词，用于在 LLM 意图识别未命中时进行降级匹配
_WEATHER_KEYWORDS = [
    "天气", "下雨", "温度", "气温", "晴天", "阴天",
    "多云", "刮风", "台风", "暴雨", "下雪", "雾霾",
    "冷热", "冷不冷", "热不热", "会不会下雨",
]

TAG = __name__


def _normalize_llm_tool_name(tool_name: str, conn) -> str:
    """修正 LLM 可能漏掉下划线的工具名（如 analyzeweighbridgedata -> analyze_weighbridge_data）"""
    if not tool_name or "_" in tool_name:
        return tool_name  # 已有下划线，无需修正
    # 去掉下划线后比较：遍历所有已注册函数，找到标准化后匹配的
    normalized_input = tool_name.replace("_", "").replace("-", "").lower()
    for registered_name in conn.func_handler.tool_manager.get_all_tools().keys():
        if registered_name.replace("_", "").replace("-", "").lower() == normalized_input:
            conn.logger.bind(tag=TAG).info(
                f"LLM 输出工具名 '{tool_name}' 自动修正为 '{registered_name}'"
            )
            return registered_name
    return tool_name


async def handle_user_intent(conn: "ConnectionHandler", text):
    # 预处理输入文本，处理可能的JSON格式
    try:
        if text.strip().startswith("{") and text.strip().endswith("}"):
            parsed_data = json.loads(text)
            if isinstance(parsed_data, dict) and "content" in parsed_data:
                text = parsed_data["content"]
                conn.current_speaker = parsed_data.get("speaker")
    except (json.JSONDecodeError, TypeError):
        pass

    # 检查是否有明确的退出命令
    _, filtered_text = remove_punctuation_and_length(text)
    if await check_direct_exit(conn, filtered_text):
        return True

    # 检查是否是唤醒词
    if await checkWakeupWords(conn, filtered_text):
        return True

    # ---- 潮白河项目：监测数据库查询模式 ----
    # 使用 DataQueryEngine 进行 SQL 数据查询，不走插件函数体系
    if hasattr(conn, "_chaobaihe_db_engine") and conn._chaobaihe_db_engine is not None:
        handled = await _handle_chaobaihe_db_query(conn, text)
        if handled:
            return True
        # DB 查询未命中时，继续走正常 LLM 对话流程
        # （允许潮白河项目同时支持 DB 查询和普通对话）

    # 使用LLM进行意图分析（包括地磅数据查询、人员状态查询等）
    # LLM会根据function_call配置自动匹配并构造正确的HTTP请求参数
    intent_result = await analyze_intent_with_llm(conn, text)
    if not intent_result:
        return False

    # 天气查询降级处理：如果 LLM 未能匹配到函数（返回 continue_chat），
    # 但用户输入包含天气关键词，则检查是否有可用的天气接口
    if _is_weather_query(text) and _is_continue_chat(intent_result):
        if _has_weather_function(conn):
            # 有天气接口，手动构造 function_call 触发 get_weather
            conn.logger.bind(tag=TAG).info(
                f"LLM未匹配天气意图，降级手动触发 get_weather: {text}"
            )
            intent_result = _build_weather_intent()
        else:
            # 无天气接口，直接回复暂时无法查询
            conn.logger.bind(tag=TAG).info(
                f"天气查询但未配置 get_weather 接口: {text}"
            )
            await send_stt_message(conn, text)
            conn.client_abort = False
            conn.sentence_id = str(uuid.uuid4().hex)
            speak_txt(conn, "暂时无法查询今天天气")
            return True

    # 会话开始时生成sentence_id
    conn.sentence_id = str(uuid.uuid4().hex)
    # 处理各种意图
    return await process_intent_result(conn, intent_result, text)


def _is_weather_query(text: str) -> bool:
    """检查用户输入是否包含天气相关关键词"""
    if not text:
        return False
    text_lower = text.lower()
    return any(kw in text_lower for kw in _WEATHER_KEYWORDS)


def _is_continue_chat(intent_result: str) -> bool:
    """检查意图识别结果是否为 continue_chat（即 LLM 未匹配到任何函数）"""
    try:
        intent_data = json.loads(intent_result)
        fc = intent_data.get("function_call", {})
        return fc.get("name") == "continue_chat"
    except (json.JSONDecodeError, TypeError):
        return False


def _has_weather_function(conn: "ConnectionHandler") -> bool:
    """检查当前连接是否已加载 get_weather 函数"""
    try:
        tools = conn.func_handler.tool_manager.get_all_tools()
        return "get_weather" in tools
    except Exception:
        return False


def _build_weather_intent() -> str:
    """手动构造 get_weather 的 function_call JSON"""
    return json.dumps({
        "function_call": {
            "name": "get_weather",
            "arguments": {},
        }
    })


async def check_direct_exit(conn: "ConnectionHandler", text):
    """检查是否有明确的退出命令"""
    _, text = remove_punctuation_and_length(text)
    cmd_exit = conn.cmd_exit
    for cmd in cmd_exit:
        if text == cmd:
            conn.logger.bind(tag=TAG).info(f"识别到明确的退出命令: {text}")
            await send_stt_message(conn, text)
            await conn.close()
            return True
    return False


async def analyze_intent_with_llm(conn: "ConnectionHandler", text):
    """使用LLM分析用户意图（地磅数据、人员状态等HTTP请求由LLM构造参数）"""
    if not hasattr(conn, "intent") or not conn.intent:
        conn.logger.bind(tag=TAG).warning("意图识别服务未初始化")
        return None

    # 对话历史记录
    dialogue = conn.dialogue
    try:
        intent_result = await conn.intent.detect_intent(conn, dialogue.dialogue, text)
        return intent_result
    except Exception as e:
        conn.logger.bind(tag=TAG).error(f"意图识别失败: {str(e)}")

    return None


async def process_intent_result(
    conn: "ConnectionHandler", intent_result, original_text
):
    """处理意图识别结果"""
    try:
        # 尝试将结果解析为JSON
        intent_data = json.loads(intent_result)

        # 检查是否有function_call
        if "function_call" in intent_data:
            # 直接从意图识别获取了function_call
            conn.logger.bind(tag=TAG).debug(
                f"检测到function_call格式的意图结果: {intent_data['function_call']['name']}"
            )
            function_name = intent_data["function_call"]["name"]
            function_name = _normalize_llm_tool_name(function_name, conn)
            if function_name == "continue_chat":
                return False

            if function_name == "result_for_context":
                await send_stt_message(conn, original_text)
                conn.client_abort = False

                def process_context_result():
                    conn.dialogue.put(Message(role="user", content=original_text))

                    from core.utils.current_time import get_current_time_info

                    current_time, today_date, today_weekday, lunar_date = (
                        get_current_time_info()
                    )

                    # 构建带上下文的基础提示
                    context_prompt = f"""当前时间：{current_time}
                                        今天日期：{today_date} ({today_weekday})
                                        今天农历：{lunar_date}

                                        请根据以上信息回答用户的问题：{original_text}"""

                    response = conn.intent.replyResult(context_prompt, original_text)
                    speak_txt(conn, response)

                conn.executor.submit(process_context_result)
                return True

            function_args = {}
            if "arguments" in intent_data["function_call"]:
                function_args = intent_data["function_call"]["arguments"]
                if function_args is None:
                    function_args = {}
            # 确保参数是字符串格式的JSON
            if isinstance(function_args, dict):
                function_args = json.dumps(function_args)

            function_call_data = {
                "name": function_name,
                "id": str(uuid.uuid4().hex),
                "arguments": function_args,
            }

            await send_stt_message(conn, original_text)
            conn.client_abort = False

            # 准备工具调用参数
            tool_input = {}
            if function_args:
                if isinstance(function_args, str):
                    tool_input = json.loads(function_args) if function_args else {}
                elif isinstance(function_args, dict):
                    tool_input = function_args

            # 上报工具调用
            enqueue_tool_report(conn, function_name, tool_input)

            # 使用executor执行函数调用和结果处理
            def process_function_call():
                conn.dialogue.put(Message(role="user", content=original_text))
                
                # 工具调用超时时间
                tool_call_timeout = int(conn.config.get("tool_call_timeout", 30))
                # 使用统一工具处理器处理所有工具调用
                try:
                    result = asyncio.run_coroutine_threadsafe(
                        conn.func_handler.handle_llm_function_call(
                            conn, function_call_data
                        ),
                        conn.loop,
                    ).result(timeout=tool_call_timeout)
                except Exception as e:
                    import traceback
                    conn.logger.bind(tag=TAG).error(f"工具调用失败: {e}\n{traceback.format_exc()}")
                    result = ActionResponse(
                        action=Action.ERROR, result="工具调用超时，请一会再试下哈", response="工具调用超时，请一会再试下哈"
                    )

                # 上报工具调用结果
                if result:
                    enqueue_tool_report(conn, function_name, tool_input, str(result.result) if result.result else None, report_tool_call=False)

                    if result.action == Action.RESPONSE:  # 直接回复前端
                        text = result.response
                        if text is not None:
                            speak_txt(conn, text)
                    elif result.action == Action.REQLLM:  # 调用函数后再请求llm生成回复
                        text = result.result
                        conn.dialogue.put(Message(role="tool", content=text))
                        # 使用技能感知的摘要方法（如果有注册 summary_prompt 则使用自定义提示词）
                        if hasattr(conn.intent, "reply_result_with_skill_summary"):
                            llm_result = conn.intent.reply_result_with_skill_summary(
                                text, original_text, function_name
                            )
                        else:
                            llm_result = conn.intent.replyResult(text, original_text)
                        if llm_result is None:
                            llm_result = text
                        speak_txt(conn, llm_result)
                    elif (
                        result.action == Action.NOTFOUND
                        or result.action == Action.ERROR
                    ):
                        text = result.response if result.response else result.result
                        if text is not None:
                            speak_txt(conn, text)
                    elif function_name != "play_music":
                        # For backward compatibility with original code
                        # 获取当前最新的文本索引
                        text = result.response
                        if text is None:
                            text = result.result
                        if text is not None:
                            speak_txt(conn, text)

            # 将函数执行放在线程池中
            conn.executor.submit(process_function_call)
            return True
        return False
    except json.JSONDecodeError as e:
        conn.logger.bind(tag=TAG).error(f"处理意图结果时出错: {e}")
        return False


def speak_txt(conn: "ConnectionHandler", text):
    # 记录文本到 sentence_id 映射
    conn.tts.store_tts_text(conn.sentence_id, text)

    conn.tts.tts_text_queue.put(
        TTSMessageDTO(
            sentence_id=conn.sentence_id,
            sentence_type=SentenceType.FIRST,
            content_type=ContentType.ACTION,
        )
    )
    conn.tts.tts_one_sentence(conn, ContentType.TEXT, content_detail=text)
    conn.tts.tts_text_queue.put(
        TTSMessageDTO(
            sentence_id=conn.sentence_id,
            sentence_type=SentenceType.LAST,
            content_type=ContentType.ACTION,
        )
    )
    conn.dialogue.put(Message(role="assistant", content=text))


# ==================== 潮白河项目：监测数据库查询 ====================

# DB 查询关键词（用于快速判断是否走 DB 查询路径，避免每次都调 LLM 分类）
_DB_QUERY_KEYWORDS = [
    "测缝", "裂缝", "gnss", "GNSS", "卫星",
    "渗压", "孔隙", "土压力", "土压",
    "全站仪", "全站", "棱镜", "位移", "坐标",
    "雷达", "液位", "阵列", "流量计", "流量", "流速",
    "时差", "超声波", "水位", "断面",
    "监测", "传感器", "设备数据", "统计", "概览", "总览", "概况",
    "数据", "查询", "异常", "告警", "阈值",
]


async def _handle_chaobaihe_db_query(conn: "ConnectionHandler", text: str) -> bool:
    """潮白河项目：监测数据库查询处理
    
    使用 DataQueryEngine + LLM 进行意图分类 → 数据查询 → 智能总结。
    
    流程：
    1. 关键词预判：快速判断用户查询是否与 DB 数据相关
    2. LLM 意图分类：确定查询目标和数据表
    3. DataQueryEngine 查询：执行数据查询
    4. LLM 智能总结：对查询结果进行统计分析和自然语言总结
    
    Returns:
        True: DB 查询已处理
        False: 非 DB 查询，应走正常 LLM 对话流程
    """
    engine = conn._chaobaihe_db_engine
    if engine is None:
        return False
    
    # 1. 关键词预判：快速过滤明显非 DB 的查询
    if not _is_likely_db_query(text):
        conn.logger.bind(tag=TAG).debug(f"潮白河: 非DB查询，走正常对话: {text}")
        return False
    
    conn.logger.bind(tag=TAG).info(f"潮白河 DB 查询: {text}")
    
    try:
        # 2. LLM 意图分类 + 数据查询 + 智能总结
        # 导入 intent_api_server.py（项目根目录，从 core/handle/ 需向上 5 层）
        try:
            import sys, os
            # core/handle/intentHandler.py → 向上 5 层到项目根目录
            _here = os.path.abspath(__file__)
            for _ in range(5):
                _here = os.path.dirname(_here)
            project_root = _here
            if project_root not in sys.path:
                sys.path.insert(0, project_root)
            from intent_api_server import (
                classify_intent,
                build_context_for_llm,
                match_intent,
                summarize_stream,
            )
            _has_intent_api = True
        except ImportError:
            _has_intent_api = False
            conn.logger.bind(tag=TAG).warning("无法导入 intent_api_server，使用简化 DB 查询")
        
        if _has_intent_api:
            # --- 使用 intent_api_server 的完整流程 ---
            # LLM 分类：确定查询哪些表（同步 HTTP 调用，必须在 executor 中运行，避免阻塞事件循环）
            def do_classify():
                return classify_intent(text, engine)
            
            classification = await asyncio.get_event_loop().run_in_executor(
                conn.executor, do_classify
            )
            cat = classification.get("cat", "other")
            
            if cat != "db":
                conn.logger.bind(tag=TAG).debug(
                    f"潮白河: LLM 分类为非 DB 查询 (cat={cat})，走正常对话"
                )
                return False
            
            tables = classification.get("tbls", [])
            if not tables:
                tables = list(engine.all_stats.keys())
            
            # 关键词匹配：确定关注的指标字段
            matched = match_intent(text, engine)
            matched_fields = [m[1] for m in matched.get("metrics", []) if m[1]]
            
            # LLM 流式总结（在 executor 中运行以生成完整文本）
            def generate_summary():
                result_parts = []
                for chunk in summarize_stream(text, tables, matched_fields, engine):
                    result_parts.append(chunk)
                return "".join(result_parts)
            
            # 在线程池中执行同步 LLM 调用，避免阻塞事件循环
            summary = await asyncio.get_event_loop().run_in_executor(
                conn.executor, generate_summary
            )
            
            if summary:
                speak_txt(conn, summary)
                return True
            else:
                conn.logger.bind(tag=TAG).warning("潮白河 DB 总结生成失败")
                return False
        else:
            # --- 简化模式：直接使用 DataQueryEngine 的预计算统计 ---
            system_prompt = engine.build_cached_system_prompt()
            
            def query_simple():
                # 使用 conn.intent.llm 的同步调用
                if hasattr(conn.intent, 'llm') and conn.intent.llm:
                    return conn.intent.llm.response_no_stream(
                        system_prompt=system_prompt,
                        user_prompt=text,
                    )
                return None
            
            result = await asyncio.get_event_loop().run_in_executor(
                conn.executor, query_simple
            )
            
            if result:
                speak_txt(conn, result)
                return True
            
            return False
            
    except Exception as e:
        conn.logger.bind(tag=TAG).error(f"潮白河 DB 查询异常: {e}")
        # 异常时降级为普通对话
        return False


def _is_likely_db_query(text: str) -> bool:
    """快速判断用户查询是否可能涉及数据库查询"""
    if not text:
        return False
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in _DB_QUERY_KEYWORDS)