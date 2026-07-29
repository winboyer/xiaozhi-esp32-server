from typing import List, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler
from ..base import IntentProviderBase
from plugins_func.functions.play_music import initialize_music_handler
from config.logger import setup_logging
from core.utils.util import get_system_error_response
import re
import json
import hashlib
import time
from datetime import datetime, timedelta

# 动态技能提示注册中心
from plugins_func.skills.registry import skill_registry



TAG = __name__
logger = setup_logging()


class IntentProvider(IntentProviderBase):
    def __init__(self, config):
        super().__init__(config)
        self.llm = None
        self.promot = ""
        # 导入全局缓存管理器
        from core.utils.cache.manager import cache_manager, CacheType

        self.cache_manager = cache_manager
        self.CacheType = CacheType
        self.history_count = 4  # 默认使用最近4条对话记录

    def get_intent_system_prompt(self, functions_list: str) -> str:
        """
        根据配置的意图选项和可用函数动态生成系统提示词。
        技能相关的关键词匹配规则和 few-shot 示例从 skill_registry 动态收集，
        不再硬编码在意图识别模块中。
        Args:
            functions: 可用的函数列表，JSON格式字符串
        Returns:
            格式化后的系统提示词
        """

        # 构建函数说明部分
        functions_desc = "可用的函数列表：\n"
        for func in functions_list:
            func_info = func.get("function", {})
            name = func_info.get("name", "")
            desc = func_info.get("description", "")
            params = func_info.get("parameters", {})

            functions_desc += f"\n函数名: {name}\n"
            functions_desc += f"描述: {desc}\n"

            if params:
                functions_desc += "参数:\n"
                for param_name, param_info in params.get("properties", {}).items():
                    param_desc = param_info.get("description", "")
                    param_type = param_info.get("type", "")
                    functions_desc += f"- {param_name} ({param_type}): {param_desc}\n"

            functions_desc += "---\n"

        # 动态计算今天、昨天和上周最后一天的最后时刻，用于 few-shot 示例
        now = datetime.now()
        today_end = now.strftime("%Y-%m-%d") + " 23:59:59"
        yesterday_end = (now - timedelta(days=1)).strftime("%Y-%m-%d") + " 23:59:59"
        last_week_end = (now - timedelta(days=now.weekday() + 1)).strftime("%Y-%m-%d") + " 23:59:59"

        # ---- 动态收集技能提示 ----
        keyword_table = skill_registry.build_keyword_table()
        few_shot_examples = skill_registry.build_few_shot_examples()

        # 仅当存在技能提示时才显示关键词匹配规则
        keyword_section = ""
        if keyword_table:
            keyword_section = (
                "【关键词模糊匹配规则】如果用户输入中包含以下关键词或词组，请直接匹配对应的函数，无需精确匹配句式：\n"
                + keyword_table
                + "\n\n"
            )

        # 仅当存在 few-shot 示例时才显示示例部分
        few_shot_section = ""
        if few_shot_examples:
            few_shot_section = (
                "【技能匹配示例】\n"
                + few_shot_examples
                + "\n\n"
            )

        # 构建提示词（base 部分保持稳定，skill 部分动态注入）
        prompt = (
            "【严格格式要求】你必须只能返回JSON格式，绝对不能返回任何自然语言！\n\n"
            "你是一个意图识别助手。请分析用户的最后一句话，判断用户意图并调用相应的函数。\n\n"
            "【重要规则】以下类型的查询请直接返回result_for_context，无需调用函数：\n"
            "- 询问当前时间（如：现在几点、当前时间、查询时间等）\n"
            "- 询问今天日期（如：今天几号、今天星期几、今天是什么日期等）\n"
            "- 询问今天农历（如：今天农历几号、今天什么节气等）\n"
            "- 询问所在城市（如：我现在在哪里、你知道我在哪个城市吗等）\n"
            "- 系统会根据上下文信息直接构建回答。\n\n"
            "- 如果用户使用疑问词（如'怎么'、'为什么'、'如何'）询问退出相关的问题（例如'怎么退出了？'），注意这不是让你退出，请返回 {'function_call': {'name': 'continue_chat'}\n"
            "- 仅当用户明确使用'退出系统'、'结束对话'、'我不想和你说话了'等指令时，才触发 handle_exit_intent\n\n"
            f"当前时间参考：今天是 {now.strftime('%Y-%m-%d')}，当前时间是 {now.strftime('%H:%M:%S')}。\n"
            f"今天截止时间为 {today_end}，昨天截止时间为 {yesterday_end}，上周最后一天截止时间为 {last_week_end}。\n\n"
            f"{functions_desc}\n"
            f"{keyword_section}"
            f"{few_shot_section}"
            "处理步骤:\n"
            "1. 先用关键词模糊匹配规则检查用户输入，命中则直接调用对应函数\n"
            "2. 再检查是否为上述基础信息查询（时间、日期等），如是则返回result_for_context\n"
            "3. 从可用函数列表中选择最匹配的函数\n"
            "4. 如果找到匹配的函数，生成对应的function_call 格式\n"
            '5. 如果没有找到匹配的函数，返回{"function_call": {"name": "continue_chat"}}\n\n'
            "返回格式要求：\n"
            "1. 必须返回纯JSON格式，不要包含任何其他文字\n"
            "2. 必须包含function_call字段\n"
            "3. function_call必须包含name字段\n"
            "4. 如果函数需要参数，必须包含arguments字段\n\n"
            "基础示例：\n"
            "```\n"
            "用户: 现在几点了？\n"
            '返回: {"function_call": {"name": "result_for_context"}}\n'
            "```\n"
            "```\n"
            "用户: 当前电池电量是多少？\n"
            '返回: {"function_call": {"name": "get_battery_level", "arguments": {"response_success": "当前电池电量为{value}%", "response_failure": "无法获取Battery的当前电量百分比"}}}\n'
            "```\n"
            "```\n"
            "用户: 当前屏幕亮度是多少？\n"
            '返回: {"function_call": {"name": "self_screen_get_brightness"}}\n'
            "```\n"
            "```\n"
            "用户: 设置屏幕亮度为50%\n"
            '返回: {"function_call": {"name": "self_screen_set_brightness", "arguments": {"brightness": 50}}}\n'
            "```\n"
            "```\n"
            "用户: 我想结束对话\n"
            '返回: {"function_call": {"name": "handle_exit_intent", "arguments": {"say_goodbye": "goodbye"}}}\n'
            "```\n"
            "```\n"
            "用户: 你好啊\n"
            '返回: {"function_call": {"name": "continue_chat"}}\n'
            "```\n\n"
            "注意：\n"
            "1. 只返回JSON格式，不要包含任何其他文字\n"
            '2. 优先检查用户查询是否为基础信息（时间、日期等），如是则返回{"function_call": {"name": "result_for_context"}}，不需要arguments参数\n'
            '3. 如果没有找到匹配的函数，返回{"function_call": {"name": "continue_chat"}}\n'
            "4. 确保返回的JSON格式正确，包含所有必要的字段\n"
            "5. result_for_context不需要任何参数，系统会自动从上下文获取信息\n"
            "特殊说明：\n"
            "- 当用户单次输入包含多个指令时（如'打开灯并且调高音量'）\n"
            "- 请返回多个function_call组成的JSON数组\n"
            "- 示例：{'function_calls': [{name:'light_on'}, {name:'volume_up'}]}\n\n"
            "【最终警告】绝对禁止输出任何自然语言、表情符号或解释文字！只能输出有效JSON格式！违反此规则将导致系统错误！"
        )
        return prompt

    def reply_result_with_skill_summary(
        self, text: str, original_text: str, function_name: str = None
    ):
        """
        使用技能特定的摘要提示词生成回复（用于 REQLLM 模式）。
        当函数返回 Action.REQLLM 时，使用注册的 summary_prompt 指导 LLM 生成总结。

        Args:
            text: 函数返回的原始数据（用作 data 占位符填充）
            original_text: 用户原始输入
            function_name: 触发的函数名，用于查找对应的 summary_prompt
        """
        try:
            # 尝试获取技能特定的摘要提示词
            summary_prompt = skill_registry.get_summary_prompt(function_name) if function_name else None

            if summary_prompt and "{data}" in summary_prompt:
                # 有自定义摘要提示词，用数据填充
                formatted_prompt = summary_prompt.replace("{data}", text)
            else:
                # 回退到通用摘要提示词
                formatted_prompt = (
                    "你是一个智能数据助手。请根据以下查询结果，用口语化、简洁的语言回复用户的问题。\n\n"
                    f"用户的问题：{original_text}\n\n"
                    f"查询结果数据：\n{text}\n\n"
                    "要求：\n"
                    "1. 用自然的口语描述数据情况，像人类汇报一样\n"
                    "2. 突出关键数字和信息\n"
                    "3. 回复长度控制在50-150字\n"
                    "4. 不要使用任何 Markdown 格式\n"
                    "5. 不要添加「根据数据分析」等套话\n\n"
                    "请直接返回总结文本："
                )

            llm_result = self.llm.response_no_stream(
                system_prompt=formatted_prompt,
                user_prompt=original_text,
            )
            return llm_result
        except Exception as e:
            logger.bind(tag=TAG).error(f"Error in generating skill summary: {e}")
            return get_system_error_response(self.config)

    def replyResult(self, text: str, original_text: str):
        try:
            llm_result = self.llm.response_no_stream(
                system_prompt=text,
                user_prompt="请根据以上内容，像人类一样说话的口吻回复用户，要求简洁，请直接返回结果。用户现在说："
                + original_text,
            )
            return llm_result
        except Exception as e:
            logger.bind(tag=TAG).error(f"Error in generating reply result: {e}")
            return get_system_error_response(self.config)

    async def detect_intent(
        self, conn: "ConnectionHandler", dialogue_history: List[Dict], text: str
    ) -> str:
        if not self.llm:
            raise ValueError("LLM provider not set")
        if conn.func_handler is None:
            return '{"function_call": {"name": "continue_chat"}}'

        # 记录整体开始时间
        total_start_time = time.time()

        # 打印使用的模型信息
        model_info = getattr(self.llm, "model_name", str(self.llm.__class__.__name__))
        logger.bind(tag=TAG).debug(f"使用意图识别模型: {model_info}")

        # 计算缓存键
        cache_key = hashlib.md5((conn.device_id + text).encode()).hexdigest()

        # 检查缓存
        cached_intent = self.cache_manager.get(self.CacheType.INTENT, cache_key)
        if cached_intent is not None:
            cache_time = time.time() - total_start_time
            logger.bind(tag=TAG).debug(
                f"使用缓存的意图: {cache_key} -> {cached_intent}, 耗时: {cache_time:.4f}秒"
            )
            return cached_intent

        if self.promot == "" or getattr(self, "_prompt_mcp_tool_count", 0) != (
            len(conn.mcp_client.tools) if hasattr(conn, "mcp_client") and conn.mcp_client else 0
        ):
            functions = conn.func_handler.get_functions()
            if hasattr(conn, "mcp_client"):
                mcp_tools = conn.mcp_client.get_available_tools()
                if mcp_tools is not None and len(mcp_tools) > 0:
                    if functions is None:
                        functions = []
                    functions.extend(mcp_tools)
                # 记录当前 MCP 工具数量，用于检测工具列表变化
                self._prompt_mcp_tool_count = len(conn.mcp_client.tools)
            else:
                self._prompt_mcp_tool_count = 0

            self.promot = self.get_intent_system_prompt(functions)

        music_config = initialize_music_handler(conn)
        music_file_names = music_config["music_file_names"]
        prompt_music = f"{self.promot}\n<musicNames>{music_file_names}\n</musicNames>"

        home_assistant_cfg = conn.config["plugins"].get("home_assistant")
        if home_assistant_cfg:
            devices = home_assistant_cfg.get("devices", [])
        else:
            devices = []
        if len(devices) > 0:
            hass_prompt = "\n下面是我家智能设备列表（位置，设备名，entity_id），可以通过homeassistant控制\n"
            for device in devices:
                hass_prompt += device + "\n"
            prompt_music += hass_prompt

        logger.bind(tag=TAG).debug(f"User prompt: {prompt_music}")

        # 构建用户对话历史的提示
        msgStr = ""

        # 获取最近的对话历史
        start_idx = max(0, len(dialogue_history) - self.history_count)
        for i in range(start_idx, len(dialogue_history)):
            msgStr += f"{dialogue_history[i].role}: {dialogue_history[i].content}\n"

        msgStr += f"User: {text}\n"
        user_prompt = f"current dialogue:\n{msgStr}"

        # 记录预处理完成时间
        preprocess_time = time.time() - total_start_time
        logger.bind(tag=TAG).debug(f"意图识别预处理耗时: {preprocess_time:.4f}秒")

        # 使用LLM进行意图识别
        llm_start_time = time.time()
        logger.bind(tag=TAG).debug(f"开始LLM意图识别调用, 模型: {model_info}")

        try:
            intent = self.llm.response_no_stream(
                system_prompt=prompt_music, user_prompt=user_prompt
            )
        except Exception as e:
            logger.bind(tag=TAG).error(f"Error in intent detection LLM call: {e}")
            return '{"function_call": {"name": "continue_chat"}}'

        # 记录LLM调用完成时间
        llm_time = time.time() - llm_start_time
        logger.bind(tag=TAG).debug(
            f"外挂的大模型意图识别完成, 模型: {model_info}, 调用耗时: {llm_time:.4f}秒"
        )

        # 记录后处理开始时间
        postprocess_start_time = time.time()

        # 清理和解析响应
        intent = intent.strip()
        # 尝试提取JSON部分
        match = re.search(r"\{.*\}", intent, re.DOTALL)
        if match:
            intent = match.group(0)

        # 记录总处理时间
        total_time = time.time() - total_start_time
        logger.bind(tag=TAG).debug(
            f"【意图识别性能】模型: {model_info}, 总耗时: {total_time:.4f}秒, LLM调用: {llm_time:.4f}秒, 查询: '{text[:20]}...'"
        )

        # 尝试解析为JSON
        try:
            intent_data = json.loads(intent)
            # 如果包含function_call，则格式化为适合处理的格式
            if "function_call" in intent_data:
                function_data = intent_data["function_call"]
                function_name = function_data.get("name")
                function_args = function_data.get("arguments", {})

                # 记录识别到的function call
                logger.bind(tag=TAG).info(
                    f"llm 识别到意图: {function_name}, 参数: {function_args}"
                )

                # 处理不同类型的意图
                if function_name == "result_for_context":
                    # 处理基础信息查询，直接从context构建结果
                    logger.bind(tag=TAG).info(
                        "检测到result_for_context意图，将使用上下文信息直接回答"
                    )

                elif function_name == "continue_chat":
                    # 处理普通对话
                    # 保留非工具相关的消息
                    clean_history = [
                        msg
                        for msg in conn.dialogue.dialogue
                        if msg.role not in ["tool", "function"]
                    ]
                    conn.dialogue.dialogue = clean_history

                else:
                    # 处理函数调用
                    logger.bind(tag=TAG).info(f"检测到函数调用意图: {function_name}")

            # 统一缓存处理和返回
            self.cache_manager.set(self.CacheType.INTENT, cache_key, intent)
            postprocess_time = time.time() - postprocess_start_time
            logger.bind(tag=TAG).debug(f"意图后处理耗时: {postprocess_time:.4f}秒")
            return intent
        except json.JSONDecodeError:
            # 后处理时间
            postprocess_time = time.time() - postprocess_start_time
            logger.bind(tag=TAG).error(
                f"无法解析意图JSON: {intent}, 后处理耗时: {postprocess_time:.4f}秒"
            )
            # 如果解析失败，默认返回继续聊天意图
            return '{"function_call": {"name": "continue_chat"}}'
