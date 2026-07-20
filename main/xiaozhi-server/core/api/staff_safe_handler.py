"""
工地安全数据查询 HTTP REST API 接口

提供独立的 HTTP 服务端点，接受用户查询请求，
通过 LLM 分析意图并调用对应的数据接口，返回结构化 JSON 结果。

接口：
  POST /staff-safe/query  - 提交查询请求
  GET  /staff-safe/status - 服务状态检查
"""

import json
import sys
import os
import asyncio
from datetime import datetime
from typing import Optional
from aiohttp import web

from config.logger import setup_logging
from core.api.base_handler import BaseHandler

TAG = __name__


class StaffSafeHandler(BaseHandler):
    """工地安全数据查询 HTTP 接口处理器"""

    def __init__(self, config: dict):
        super().__init__(config)
        self._llm_client = None

    @staticmethod
    def _get_local_config_path():
        """获取本地 config.yaml 的绝对路径
        
        当前文件位于 core/api/staff_safe_handler.py，
        需要上溯 3 级目录到达 main/xiaozhi-server/，config.yaml 位于该目录下。
        """
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "config.yaml",
        )

    @staticmethod
    def _load_local_config():
        """加载本地 config.yaml，用于 manager-api 配置缺失时的回退"""
        import yaml as _yaml

        config_path = StaffSafeHandler._get_local_config_path()
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                return _yaml.safe_load(f)
        return {}

    def _get_llm_client(self):
        """懒加载获取 LLM 客户端
        
        按优先级尝试：
        1. 当前内存配置 selected_module.LLM
        2. 当前内存配置 Intent.intent_llm.llm  
        3. 遍历当前内存配置中所有 LLM，取第一个有效配置
        4. 回退读取本地 config.yaml 中 selected_module.LLM
        5. 遍历本地 config.yaml 中所有 LLM，取第一个有效配置
        """
        if self._llm_client is not None:
            return self._llm_client

        llm_config = None
        candidate_name = None

        # ---- 优先级 1: selected_module.LLM ----
        selected_llm = self.config.get("selected_module", {}).get("LLM", "")
        if selected_llm:
            llm_config = self.config.get("LLM", {}).get(selected_llm, {})
            if llm_config:
                candidate_name = selected_llm

        # ---- 优先级 2: Intent.intent_llm.llm ----
        if not llm_config:
            intent_config = self.config.get("Intent", {}).get("intent_llm", {})
            intent_llm_name = intent_config.get("llm", "")
            if intent_llm_name:
                llm_config = self.config.get("LLM", {}).get(intent_llm_name, {})
                if llm_config:
                    candidate_name = intent_llm_name

        # ---- 优先级 3: 遍历当前内存中所有 LLM 配置，取第一个有效的 ----
        if not llm_config:
            all_llm_configs = self.config.get("LLM", {})
            for name, cfg in all_llm_configs.items():
                if (
                    isinstance(cfg, dict)
                    and cfg.get("api_key")
                    and "你" not in str(cfg.get("api_key", ""))
                ):
                    llm_config = cfg
                    candidate_name = name
                    self.logger.bind(tag=TAG).info(
                        f"内存配置中 selected_module.LLM 缺失，回退使用: {name}"
                    )
                    break

        # ---- 优先级 4: 回退读取本地 config.yaml（manager-api 返回的配置缺失 LLM 段时） ----
        if not llm_config:
            try:
                local_config = self._load_local_config()
                local_llm = local_config.get("LLM", {})
                local_selected = local_config.get("selected_module", {}).get("LLM", "")
                if local_selected and local_llm.get(local_selected):
                    llm_config = local_llm[local_selected]
                    candidate_name = f"本地 config.yaml → {local_selected}"
                    self.logger.bind(tag=TAG).info(
                        f"manager-api 返回的配置缺失 LLM 段，回退读取本地 config.yaml: {local_selected}"
                    )
            except Exception as e:
                self.logger.bind(tag=TAG).warning(f"回退读取本地 config.yaml 失败: {e}")

        # ---- 优先级 5: 遍历本地 config.yaml 中所有 LLM ----
        if not llm_config:
            try:
                local_config = self._load_local_config()
                local_llm = local_config.get("LLM", {})
                for name, cfg in local_llm.items():
                    if (
                        isinstance(cfg, dict)
                        and cfg.get("api_key")
                        and "你" not in str(cfg.get("api_key", ""))
                    ):
                        llm_config = cfg
                        candidate_name = f"本地 config.yaml → {name}"
                        self.logger.bind(tag=TAG).info(
                            f"回退使用本地 config.yaml 中第一个有效 LLM: {name}"
                        )
                        break
            except Exception as e:
                self.logger.bind(tag=TAG).warning(f"回退读取本地 config.yaml 失败: {e}")

        if not llm_config:
            self.logger.bind(tag=TAG).error(
                "未找到 LLM 配置，请检查 config.yaml 或 data/.config.yaml 中的 LLM 段"
            )
            return None

        # 使用 LLM 工厂创建实例
        from core.utils.llm import create_instance

        try:
            self._llm_client = create_instance(
                llm_config.get("type", "openai"), llm_config
            )
            self.logger.bind(tag=TAG).info(
                f"LLM 客户端初始化成功: {llm_config.get('model_name', 'unknown')} (配置来源: {candidate_name})"
            )
            return self._llm_client
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"LLM 客户端初始化失败: {e}")
            return None

    async def _run_sync_in_executor(self, func, *args, **kwargs):
        """在线程池中运行同步函数"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

    async def handle_status(self, request: web.Request) -> web.Response:
        """GET /staff-safe/status - 服务状态检查"""
        llm_client = self._get_llm_client()
        status = {
            "service": "staff-safe-query",
            "status": "running" if llm_client else "degraded",
            "llm_available": llm_client is not None,
            "timestamp": datetime.now().isoformat(),
            "supported_categories": [
                "大屏-首页", "大屏-告警", "大屏-作业面",
                "定位", "设备", "人员", "组织", "统计",
            ],
        }
        response = web.Response(
            text=json.dumps(status, ensure_ascii=False, indent=2),
            content_type="application/json",
        )
        self._add_cors_headers(response)
        return response

    async def handle_query(self, request: web.Request) -> web.Response:
        """POST /staff-safe/query - 提交查询请求

        Request Body (JSON):
        {
            "query": "查询今天人员总览"
        }

        Response (JSON):
        {
            "请求内容": "...",
            "请求时间": "2026-06-09 18:00:00",
            "涉及数据": { ... },
            "返回数据总结": "..."
        }
        """
        try:
            body = await request.json()
            query = body.get("query", "").strip()
            if not query:
                return self._error_response("缺少 query 参数", 400)

            self.logger.bind(tag=TAG).info(f"收到查询请求: {query}")

            # 获取 LLM 客户端
            llm_client = self._get_llm_client()
            if llm_client is None:
                return self._error_response("LLM 服务未就绪", 503)

            request_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # ---- Step 1: 导入查询逻辑 ----
            from plugins_func.functions.staff_safe_query import (
                _build_intent_prompt,
                _build_summary_prompt,
                _call_api,
                _find_person_location,
                _select_api_by_intent,
                _truncate_data,
                API_CATALOG,
            )

            # ---- Step 2: LLM 意图分析 ----
            intent_prompt = _build_intent_prompt(query)
            intent_raw = await self._run_sync_in_executor(
                llm_client.response_no_stream,
                system_prompt=intent_prompt,
                user_prompt=query,
            )

            # 解析意图结果
            intent_raw = intent_raw.strip()
            import re as _re
            match = _re.search(r"\{.*\}", intent_raw, _re.DOTALL)
            if match:
                intent_raw = match.group(0)
            intent_result = json.loads(intent_raw)
            self.logger.bind(tag=TAG).info(f"意图分析: {intent_result}")

            # ---- Step 3: 调用数据接口 ----
            api_info = _select_api_by_intent(intent_result)
            if api_info is None:
                self.logger.bind(tag=TAG).warning(
                    f"意图分析未匹配到接口, 识别ID={intent_result.get('api_id', '未知')}, query={query}"
                )
                return self._error_response(
                    "暂时无法查询相关信息",
                    200,
                )

            extra_params = intent_result.get("extra_params", {})
            api_path = api_info["path"]
            if "date" in extra_params:
                date_val = extra_params.pop("date")
                if "snapshoot" in api_path:
                    extra_params["startDate"] = f"{date_val} 00:00:00"
                    extra_params["endDate"] = f"{date_val} 23:59:59"
                elif "track" in api_path:
                    extra_params["day"] = date_val
                elif "attendance" in api_path:
                    extra_params["date"] = date_val
            # snapshoot 接口强制需要 startDate/endDate，没有则默认今天
            if "snapshoot" in api_path and "startDate" not in extra_params:
                today = datetime.now().strftime("%Y-%m-%d")
                extra_params["startDate"] = f"{today} 00:00:00"
                extra_params["endDate"] = f"{today} 23:59:59"
            # attendance 接口需要 date 参数，没有则默认今天
            if "attendance" in api_path and "date" not in extra_params:
                extra_params["date"] = datetime.now().strftime("%Y-%m-%d")

            api_result = _call_api(api_info, extra_params)

            if not api_result["success"]:
                return self._error_response(
                    f"数据接口调用失败: {api_result.get('error', '未知错误')}",
                    502,
                )

            # ---- 人员位置查询后处理：如果是 personCurLocationV2 且指定了 personName ----
            person_name = extra_params.get("personName", "")
            if api_info["api_id"] == "personCurLocationV2" and person_name:
                location_name = _find_person_location(api_result["data"], person_name)
                if location_name:
                    result = {
                        "查询内容": query,
                        "请求时间": request_time,
                        "人员姓名": person_name,
                        "所在位置": location_name,
                        "返回数据总结": f"{person_name}目前位于{location_name}。",
                    }
                else:
                    result = {
                        "查询内容": query,
                        "请求时间": request_time,
                        "人员姓名": person_name,
                        "所在位置": "未找到",
                        "返回数据总结": f"未在今日人员定位列表中找到{person_name}，请确认姓名是否正确或该人员是否在场。",
                    }
                response = web.Response(
                    text=json.dumps(result, ensure_ascii=False, indent=2),
                    content_type="application/json",
                )
                self._add_cors_headers(response)
                return response

            # ---- Step 4: 构建涉及数据 ----
            data_truncated = _truncate_data(api_result["data"])
            involved_data = {
                "api_id": api_info["api_id"],
                "api_description": api_info["description"],
                "api_category": api_info["category"],
                "api_path": api_info["path"],
                "http_status": api_result["http_status"],
                "elapsed_seconds": api_result["elapsed"],
            }

            # ---- Step 5: LLM 数据总结 ----
            summary_prompt = _build_summary_prompt(
                api_info["description"],
                data_truncated,
                query,
                api_info["category"],
            )
            summary_text = await self._run_sync_in_executor(
                llm_client.response_no_stream,
                system_prompt=summary_prompt,
                user_prompt="请生成数据总结",
            )

            # ---- Step 6: 构建最终响应 ----
            final_result = {
                "请求内容": query,
                "请求时间": request_time,
                "涉及数据": involved_data,
                "返回数据总结": summary_text.strip(),
            }

            response = web.Response(
                text=json.dumps(final_result, ensure_ascii=False, indent=2),
                content_type="application/json",
            )
            self._add_cors_headers(response)
            return response

        except json.JSONDecodeError:
            return self._error_response("请求体必须是有效的 JSON", 400)
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"查询处理异常: {e}")
            import traceback
            self.logger.bind(tag=TAG).error(traceback.format_exc())
            return self._error_response(f"服务器内部错误: {str(e)}", 500)

    def _error_response(self, message: str, status: int = 500) -> web.Response:
        """构建错误响应"""
        result = {
            "success": False,
            "message": message,
            "timestamp": datetime.now().isoformat(),
        }
        return web.Response(
            text=json.dumps(result, ensure_ascii=False, indent=2),
            content_type="application/json",
            status=status,
        )