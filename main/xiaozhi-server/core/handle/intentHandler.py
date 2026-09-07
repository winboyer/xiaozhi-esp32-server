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

# 音量调整信号词（命中即调整，不命中再看查询信号）
_VOLUME_ADJUST_KEYWORDS = [
    "调大音量", "调小音量", "音量调", "调音量", "音量设", "设置音量", "音量改",
    "加大音量", "减小音量", "提高音量", "降低音量", "音量加", "音量减",
    "增大音量", "音量增加", "音量减少", "音量开大", "音量开小",
    "调大", "调小", "调高", "调低", "声音调", "调声音", "音量高", "音量低",
]
# 音量查询信号词（命中即查询）
_VOLUME_QUERY_KEYWORDS = [
    "查询音量", "查音量", "音量多少", "音量几", "音量是", "声音多大", "音量多大",
    "音量大小", "音量状态", "当前音量", "现在音量", "音量是多少", "声音大小",
    "声音多少", "多大声音", "音量什么", "音量多少分贝", "声音大吗", "声音小吗",
]
# 亮度调整信号词
_BRIGHTNESS_ADJUST_KEYWORDS = [
    "调亮", "调暗", "亮度调", "调亮度", "亮度设", "设置亮度", "亮度改",
    "提高亮度", "降低亮度", "亮度加", "亮度减", "亮度开大", "亮度开小",
    "屏幕调", "调屏幕", "亮度高", "亮度低", "亮点", "暗点", "亮一些", "暗一些",
]
# 亮度查询信号词
_BRIGHTNESS_QUERY_KEYWORDS = [
    "查询亮度", "查亮度", "亮度多少", "亮度几", "亮度是", "亮度状态",
    "当前亮度", "现在亮度", "亮度是多少", "屏幕亮度多少", "亮度多大",
]

# OTA 设备快速路由关键词 → 路由类型
_OTA_FAST_ROUTE_KEYWORDS = {
    # 设备信息/状态查询
    "设备信息": "device_info", "设备状态": "device_info",
    # 电量查询
    "电量": "battery", "电池": "battery", "剩余电量": "battery",
}

# 快速路由类型 → 对应的 MCP 工具名
# 查询类（音量/亮度）走 get_device_status，调整类才走 set_volume / set_brightness
_FAST_ROUTE_TOOLS = {
    "volume": "self.audio_speaker.set_volume",
    "volume_query": "self.get_device_status",
    "brightness": "self.screen.set_brightness",
    "brightness_query": "self.get_device_status",
    "device_info": "self.get_device_status",
    "battery": "self.get_device_status",
}

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
        # ---- 快速路由：天气/OTA 等通用查询直接走函数调用 ----
        # （对齐 intent_api_server.py：快速路由跳过 LLM 意图分类）
        route_type = _detect_chaobaihe_fast_route(text)
        if route_type:
            handled = await _handle_chaobaihe_fast_route(conn, text, route_type)
            if handled:
                return True
            # 快速路由处理失败时继续往下（可能是工具未就绪）
        
        # ---- 非快速路由：LLM 意图理解 + DB 命中查询 ----
        # （对齐 intent_api_server.py：classify_intent → DB 查询 → summarize_stream）
        handled = await _handle_chaobaihe_db_query(conn, text)
        if handled:
            return True

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


# 常见城市名列表（用于从用户输入中提取城市，对齐 intent_api_server.py 的 detect_location）
_COMMON_CITY_NAMES = [
    "北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "南京", "重庆",
    "西安", "天津", "苏州", "长沙", "郑州", "青岛", "大连", "厦门", "福州",
    "合肥", "济南", "沈阳", "昆明", "贵阳", "南宁", "哈尔滨", "长春", "太原",
    "石家庄", "南昌", "兰州", "海口", "拉萨", "乌鲁木齐", "呼和浩特", "银川", "西宁",
]


def _extract_city_from_text(text: str) -> str:
    """从用户输入中提取城市名"""
    if not text:
        return ""
    for city in _COMMON_CITY_NAMES:
        if city in text:
            return city
    return ""


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
    # 数字孪生推送意图处理结果（潮白河 DB 查询 / 天气 / OTA 工具调用等不走 conn.chat() 的回答）
    if text:
        conn._dt_push_speak_text(text)

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


# ==================== 潮白河项目：快速路由（天气 + OTA 设备控制/查询） ====================

def _detect_chaobaihe_fast_route(text: str) -> str:
    """检测用户输入是否命中快速路由（天气/OTA设备控制/查询）
    
    Returns:
        路由类型字符串（"weather" / "volume" / "volume_query" / "brightness" / "brightness_query" / "device_info" / "battery"）
        空字符串表示未命中快速路由
    """
    if not text:
        return ""
    
    # 天气快速路由
    if _is_weather_query(text):
        return "weather"
    
    # 音量路由：先判断调整信号，再判断查询信号；只有"音量/声音"无明确信号时默认查询（避免误调设备）
    if "音量" in text or "声音" in text:
        for kw in _VOLUME_ADJUST_KEYWORDS:
            if kw in text:
                return "volume"
        for kw in _VOLUME_QUERY_KEYWORDS:
            if kw in text:
                return "volume_query"
        # 无明确调整信号 → 默认查询
        return "volume_query"
    
    # 亮度路由
    if "亮度" in text or "屏幕" in text:
        for kw in _BRIGHTNESS_ADJUST_KEYWORDS:
            if kw in text:
                return "brightness"
        for kw in _BRIGHTNESS_QUERY_KEYWORDS:
            if kw in text:
                return "brightness_query"
        # 无明确调整信号 → 默认查询
        return "brightness_query"
    
    # 其他 OTA 设备快速路由（设备信息/电量）
    text_lower = text.lower()
    for kw, route_type in _OTA_FAST_ROUTE_KEYWORDS.items():
        if kw in text_lower:
            return route_type
    
    return ""


async def _handle_chaobaihe_fast_route(conn: "ConnectionHandler", text: str, route_type: str) -> bool:
    """潮白河项目快速路由统一入口
    
    Args:
        route_type: 路由类型（"weather" / "volume" / "brightness" / "device_info" / "battery"）
    """
    if route_type == "weather":
        return await _handle_chaobaihe_weather(conn, text)
    
    # OTA 设备类快速路由
    tool_name = _FAST_ROUTE_TOOLS.get(route_type)
    if not tool_name:
        return False
    
    # 检查工具是否可用
    if not _has_tool(conn, tool_name):
        conn.logger.bind(tag=TAG).warning(f"快速路由 {route_type} 工具 {tool_name} 不可用")
        return False
    
    conn.logger.bind(tag=TAG).info(f"潮白河快速路由 {route_type} → {tool_name}: {text}")
    await send_stt_message(conn, text)
    conn.client_abort = False
    conn.sentence_id = str(uuid.uuid4().hex)
    
    # 简单参数提取（音量/亮度数值）
    args = _extract_ota_args(text, route_type)
    function_call_data = {
        "name": tool_name,
        "id": str(uuid.uuid4().hex),
        "arguments": json.dumps(args),
    }
    
    # 在线程池中执行
    def process_ota():
        conn.dialogue.put(Message(role="user", content=text))
        try:
            result = asyncio.run_coroutine_threadsafe(
                conn.func_handler.handle_llm_function_call(conn, function_call_data),
                conn.loop,
            ).result(timeout=30)
        except Exception as e:
            conn.logger.bind(tag=TAG).error(f"OTA 快速路由 {route_type} 调用失败: {e}")
            speak_txt(conn, f"设备{route_type}操作暂时不可用，请稍后再试")
            return
        
        if result and result.action == Action.REQLLM:
            llm_result = conn.intent.replyResult(result.result, text)
            speak_txt(conn, llm_result or str(result.result))
        elif result and result.response:
            speak_txt(conn, result.response)
        elif result and result.result:
            speak_txt(conn, str(result.result))
        else:
            speak_txt(conn, "操作已完成")
    
    conn.executor.submit(process_ota)
    return True


def _extract_ota_args(text: str, route_type: str) -> dict:
    """从用户输入中提取 OTA 工具参数"""
    args = {}
    
    if route_type == "volume":
        # 音量数值提取: "音量调到50", "音量50%"
        m = re.search(r'(\d+)\s*(?:%|百分之)?', text)
        if m:
            args["volume"] = int(m.group(1))
    elif route_type == "brightness":
        # 亮度数值提取: "亮度调到80", "亮度50%"
        m = re.search(r'(\d+)\s*(?:%|百分之)?', text)
        if m:
            args["brightness"] = int(m.group(1))
    
    return args


def _has_tool(conn: "ConnectionHandler", tool_name: str) -> bool:
    """检查工具是否可用（模糊匹配，兼容下划线/点号变化）"""
    try:
        tools = conn.func_handler.tool_manager.get_all_tools()
        if tool_name in tools:
            return True
        # 模糊匹配
        sanitized = tool_name.replace(".", "").replace("_", "").lower()
        for name in tools:
            if name.replace(".", "").replace("_", "").lower() == sanitized:
                return True
        return False
    except Exception:
        return False


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
    # 以下为潮白河测试问题中出现的分析类关键词，避免漏过滤
    "安全", "评估", "电量", "趋势", "响应",
    "电压", "状态", "维护", "风险", "沉降",
    "分区", "安全等级", "加速", "减缓", "同步",
    "坝体", "变化", "当前值", "当前", "最大", "最小",
]


async def _handle_chaobaihe_weather(conn: "ConnectionHandler", text: str) -> bool:
    """潮白河项目：天气查询直接调用 get_weather 函数
    
    function_call 意图提供者永远返回 continue_chat，不依赖 LLM 匹配，
    因此天气等通用查询需要在 DB 查询未命中后直接调用对应函数。
    """
    if not _has_weather_function(conn):
        conn.logger.bind(tag=TAG).info(f"天气查询但未配置 get_weather 接口: {text}")
        await send_stt_message(conn, text)
        conn.client_abort = False
        conn.sentence_id = str(uuid.uuid4().hex)
        speak_txt(conn, "暂时无法查询今天天气")
        return True
    
    conn.logger.bind(tag=TAG).info(f"潮白河天气查询，直接调用 get_weather: {text}")
    await send_stt_message(conn, text)
    conn.client_abort = False
    conn.sentence_id = str(uuid.uuid4().hex)
    
    # 从用户输入中提取城市名（对齐 intent_api_server.py 的 detect_location）
    city = _extract_city_from_text(text)
    weather_args = {"location": city} if city else {}
    function_call_data = {
        "name": "get_weather",
        "id": str(uuid.uuid4().hex),
        "arguments": json.dumps(weather_args),
    }
    
    # 在线程池中执行函数调用
    def process_weather():
        conn.dialogue.put(Message(role="user", content=text))
        try:
            result = asyncio.run_coroutine_threadsafe(
                conn.func_handler.handle_llm_function_call(conn, function_call_data),
                conn.loop,
            ).result(timeout=30)
        except Exception as e:
            conn.logger.bind(tag=TAG).error(f"get_weather 调用失败: {e}")
            speak_txt(conn, "天气查询暂时不可用，请稍后再试")
            return
        
        if result and result.action == Action.REQLLM:
            # 天气数据需要 LLM 润色
            llm_result = conn.intent.replyResult(result.result, text)
            speak_txt(conn, llm_result or result.result)
        elif result and result.response:
            speak_txt(conn, result.response)
        elif result and result.result:
            speak_txt(conn, str(result.result))
        else:
            speak_txt(conn, "天气查询暂时不可用")
    
    conn.executor.submit(process_weather)
    return True


async def _handle_chaobaihe_db_query(conn: "ConnectionHandler", text: str) -> bool:
    """潮白河项目：监测数据库查询处理（对齐 intent_api_server.py）
    
    使用 DataQueryEngine + LLM 进行意图分类 → 数据查询 → 智能总结。
    
    流程：
    1. LLM 意图分类：确定是否 DB 查询、选表
    2. 关键词匹配字段
    3. DataQueryEngine 提取数据
    4. LLM 流式总结（summarize_stream）
    
    Note: 快速路由（天气/OTA）已在 handle_user_intent 中优先处理，
          此处只处理 DB 相关查询。
    
    Returns:
        True: 查询已处理（DB 查询或已返回提示）
        False: LLM 分类异常，应降级到普通对话
    """
    engine = conn._chaobaihe_db_engine
    if engine is None:
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
                _normalize_table_list,
                METRIC_KEYWORDS,
            )
            _has_intent_api = True
        except ImportError:
            _has_intent_api = False
            conn.logger.bind(tag=TAG).warning("无法导入 intent_api_server，使用简化 DB 查询")
        
        if _has_intent_api:
            # --- 使用 intent_api_server 的完整流程（对齐 HTTP API /api/v1/intent/analyze） ---
            # LLM 分类：确定查询哪些表（同步 HTTP 调用，必须在 executor 中运行，避免阻塞事件循环）
            def do_classify():
                return classify_intent(text, engine)
            
            classification = await asyncio.get_event_loop().run_in_executor(
                conn.executor, do_classify
            )
            
            if not isinstance(classification, dict):
                classification = {"cat": "other", "tbls": []}
            
            cat = classification.get("cat", "other")
            
            if cat != "db":
                # 对齐 HTTP API：非DB意图返回明确提示，而不是降级到普通对话
                await send_stt_message(conn, text)
                conn.client_abort = False
                conn.sentence_id = str(uuid.uuid4().hex)
                msg = f"当前仅支持数据库查询。您的意图为「{cat}」，暂不支持。"
                conn.logger.bind(tag=TAG).debug(f"潮白河: 非DB意图 -> {msg}")
                speak_txt(conn, msg)
                return True
            
            # 规范化 LLM 返回的表名列表
            tables = _normalize_table_list(classification.get("tbls", []), engine)
            conn.logger.bind(tag=TAG).info(f"潮白河 LLM 分类结果: cat={cat}, tbls={tables}")
            
            # 表名 fallback：LLM 没选出表时用关键词匹配兜底
            if not tables:
                kw_match = match_intent(text, engine)
                tables = kw_match.get("tables", [])
                if not tables:
                    tables = list(engine.all_stats.keys())
                conn.logger.bind(tag=TAG).info(f"潮白河 表名 fallback: tbls={tables}")
            
            # ---- 关键词匹配字段（对齐 HTTP API，使用 METRIC_KEYWORDS）----
            matched_fields = []
            for kw, (tname, field) in METRIC_KEYWORDS.items():
                if kw in text:
                    matched_fields.append(field)
            
            # 同时也用 match_intent 的 metrics 结果补充
            matched = match_intent(text, engine)
            for m in matched.get("metrics", []):
                if m[1] and m[1] not in matched_fields:
                    matched_fields.append(m[1])
            
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
                await send_stt_message(conn, text)
                conn.client_abort = False
                conn.sentence_id = str(uuid.uuid4().hex)
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
                await send_stt_message(conn, text)
                conn.client_abort = False
                conn.sentence_id = str(uuid.uuid4().hex)
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