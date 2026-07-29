#!/usr/bin/env python3
"""
监控数据智能分析 HTTP 服务 —— 意图识别接口

提供基于 LLM 的自然语言查询能力，支持：
  1. 意图理解：解析用户自然语言，确定查询目标（表、字段、时间范围、分析类型）
  2. 数据查询：从 monitoring_standard.sql 文件中读取对应数据
  3. 智能分析：利用 LLM 对查询结果进行统计分析和总结
  4. 联网查询（可选）：当用户意图涉及外部信息时，触发联网搜索

启动方式：
    python intent_api_server.py

配置方式：
    通过环境变量设置 LLM 参数，默认使用 config.yaml 中的 DeepSeek 配置：
      LLM_BASE_URL: LLM API 地址
      LLM_API_KEY:  API 密钥
      LLM_MODEL:    模型名称

接口：
    POST /api/v1/intent/analyze  - 意图分析（核心接口）
    GET  /api/v1/health           - 健康检查
    GET  /                          - 交互式测试页面
"""

import json
import os
import re
import sys
import time
import logging
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

import requests

# ==================== 日志 ====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("intent_api")

# ==================== 配置 ====================
SERVER_HOST = os.environ.get("INTENT_API_HOST", "0.0.0.0")
SERVER_PORT = int(os.environ.get("INTENT_API_PORT", "8005"))

# LLM 配置（DeepSeek / OpenAI 兼容接口）
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "sk-655f2d0a7fa64b089c9155ce8931bb3b")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-v4-flash")
LLM_MAX_RETRIES = int(os.environ.get("LLM_MAX_RETRIES", "2"))
LLM_RETRY_BACKOFF_SECONDS = float(os.environ.get("LLM_RETRY_BACKOFF_SECONDS", "0.8"))
LLM_RETRY_STATUS_CODES = {408, 429, 500, 502, 503, 504}

# SQL 文件路径
SQL_FILEPATH = os.environ.get(
    "SQL_FILEPATH",
    "/Users/jinyfeng/Downloads/monitoring_standard.sql",
)

# ==================== SQL 文件解析 ====================

def parse_sql_file(filepath: str) -> dict:
    """解析 MySQL 导出 SQL 文件"""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    tables = {}

    # 提取 CREATE TABLE
    create_pattern = re.compile(
        r"CREATE TABLE `(\w+)`\s*\((.+?)\)\s*ENGINE", re.DOTALL
    )
    for match in create_pattern.finditer(content):
        table_name = match.group(1)
        col_defs_block = match.group(2)
        columns = _parse_column_definitions(col_defs_block)
        tables[table_name] = {
            "columns": columns,
            "column_names": [c["name"] for c in columns],
            "rows": [],
        }

    # 提取 INSERT INTO
    insert_pattern = re.compile(
        r"INSERT INTO `(\w+)`\s+VALUES\s*(\(.+?\))\s*;", re.DOTALL
    )
    for match in insert_pattern.finditer(content):
        table_name = match.group(1)
        if table_name not in tables:
            continue
        values_block = match.group(2)
        rows = _parse_insert_values(values_block)
        tables[table_name]["rows"].extend(rows)

    return tables


def _parse_column_definitions(defs_block: str) -> list:
    """解析列定义"""
    columns = []
    lines = _split_top_level(defs_block, ",")
    for line in lines:
        stripped = line.strip()
        if re.match(
            r"^(PRIMARY\s+KEY|INDEX|UNIQUE\s+KEY|KEY|CONSTRAINT|FULLTEXT|SPATIAL|CHECK)",
            stripped,
            re.IGNORECASE,
        ):
            continue
        m = re.match(
            r"`(\w+)`\s+"
            r"(\w+(?:\([^)]*\))?)"
            r"(?:.*?)?"
            r"(?:COMMENT\s+'([^']*)')?",
            stripped,
        )
        if m:
            columns.append({
                "name": m.group(1),
                "type": m.group(2),
                "comment": m.group(3) if m.group(3) else "",
            })
    return columns


def _split_top_level(text: str, delimiter: str) -> list:
    """按分隔符拆分（忽略括号内的分隔符）"""
    parts = []
    current = ""
    depth = 0
    for ch in text:
        if ch == "(" and depth >= 0:
            depth += 1
            current += ch
        elif ch == ")" and depth > 0:
            depth -= 1
            current += ch
        elif ch == delimiter and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += ch
    if current.strip():
        parts.append(current)
    return parts


def _parse_insert_values(values_block: str) -> list:
    """解析 INSERT VALUES 行"""
    rows = []
    tuple_pattern = re.compile(r"\(([^()]*(?:\([^()]*\)[^()]*)*)\)")
    for tm in tuple_pattern.finditer(values_block):
        raw = tm.group(1)
        values = _split_values(raw)
        parsed = [_convert_value(v) for v in values]
        rows.append(parsed)
    return rows


def _split_values(raw: str) -> list:
    """拆分 VALUES 元组字段"""
    values = []
    current = ""
    in_quote = False
    bracket_depth = 0
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch == "'" and not in_quote:
            in_quote = True
            current += ch
        elif ch == "'" and in_quote:
            if i + 1 < len(raw) and raw[i + 1] == "'":
                current += "''"
                i += 1
            else:
                in_quote = False
                current += ch
        elif ch == "[" and not in_quote:
            bracket_depth += 1
            current += ch
        elif ch == "]" and not in_quote:
            bracket_depth -= 1
            current += ch
        elif ch == "," and not in_quote and bracket_depth == 0:
            values.append(current.strip())
            current = ""
        else:
            current += ch
        i += 1
    if current.strip():
        values.append(current.strip())
    return values


def _convert_value(val: str):
    """SQL 值 → Python 类型"""
    v = val.strip()
    if v.upper() == "NULL":
        return None
    if v.startswith("'") and v.endswith("'"):
        return v[1:-1].replace("''", "'")
    if v.startswith("["):
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return v
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


# ==================== 数据库查询引擎 ====================

# 表 → 中文名映射
TABLE_CN_NAMES = {
    "deform_crack_meter": "测缝计",
    "deform_gnss": "GNSS",
    "deform_pore_pressure": "渗压计",
    "deform_soil_pressure": "土压力计",
    "deform_total_station": "全站仪",
    "flow_array_radar": "阵列式雷达流量计",
    "flow_radar_level": "雷达液位计",
    "flow_tof_meter": "超声波时差流量计",
}

# 每张表的"核心监测指标"字段（即去除了 id/eid/通用字段后的业务字段）
TABLE_METRIC_FIELDS = {
    "deform_crack_meter": ["sf_crack_width", "sf_temp"],
    "deform_gnss": [
        "gnss_position_x", "gnss_position_y", "gnss_position_h",
        "gnss_horizontal_dis_n", "gnss_horizontal_dis_e", "gnss_vertical_dis",
    ],
    "deform_pore_pressure": ["pz_pressure", "pz_temp", "pz_depth"],
    "deform_soil_pressure": [
        "sp_pressure", "sp_freq", "sp_temp", "sp_depth",
        "sp_calib_time", "sp_direction",
    ],
    "deform_total_station": [
        "X", "Y", "Z", "hrz_dis_n", "hrz_dis_e", "vrt_dis",
        "ts_prism_id", "ts_hrz_angle", "ts_vrt_angle",
        "ts_slope_dist", "ts_hrz_dist", "ts_vrt_dist",
    ],
    "flow_array_radar": [
        "Q_inst", "Q_total", "V_avg", "ar_array_num",
        "ar_beam_angle", "ar_freq", "ar_v_array",
        "ar_water_level", "ar_section_area", "ar_flow_dir",
    ],
    "flow_radar_level": ["SSP", "RV", "L"],
    "flow_tof_meter": [
        "Q_inst", "Q_total", "V_avg", "td_channel_num", "td_media_temp",
    ],
}


class DataQueryEngine:
    """基于 SQL dump 文件的内存数据查询引擎"""

    def __init__(self, sql_filepath: str):
        logger.info(f"正在解析 SQL 文件: {sql_filepath}")
        self.tables = parse_sql_file(sql_filepath)
        self._build_index()
        self._precompute_all_stats()
        logger.info(
            f"解析完成，共 {len(self.tables)} 张表: {list(self.tables.keys())}"
        )

    def _build_index(self):
        """为每张表构建 eid 索引以加速查询"""
        self._eid_index = {}
        for tname, info in self.tables.items():
            idx = {}
            col_names = info["column_names"]
            for row in info["rows"]:
                row_dict = dict(zip(col_names, row))
                eid = row_dict.get("eid")
                if eid:
                    idx.setdefault(eid, []).append(row_dict)
            self._eid_index[tname] = idx

    def _precompute_all_stats(self):
        """预计算所有表的全部指标统计，避免查询时重复计算"""
        self.all_stats = {}  # {tname: {field: {min,max,avg,count,sum}}}
        self.all_devices = {}  # {tname: [{eid, equip_name, install_addr}]}
        for tname in self.tables:
            data = self.query_table(tname)
            # 设备列表
            seen = set()
            devices = []
            for r in data:
                eid = r.get("eid")
                if eid and eid not in seen:
                    seen.add(eid)
                    devices.append({
                        "eid": eid,
                        "equip_name": r.get("equip_name"),
                        "install_addr": r.get("install_addr"),
                    })
            self.all_devices[tname] = devices
            # 字段统计
            field_stats = {}
            cols = self.tables[tname]["columns"]
            for c in cols:
                fname = c["name"]
                vals = [r[fname] for r in data
                        if r.get(fname) is not None and isinstance(r[fname], (int, float))]
                if vals:
                    field_stats[fname] = {
                        "min": round(min(vals), 4),
                        "max": round(max(vals), 4),
                        "avg": round(sum(vals) / len(vals), 4),
                        "count": len(vals),
                    }
            self.all_stats[tname] = field_stats

    def get_all_table_names(self) -> list:
        return list(self.tables.keys())

    def get_joined_stats(self, tables: list, max_locations: int = 3) -> str:
        """
        按 install_addr 跨表 JOIN：同一位置的多个设备指标合并展示。
        max_locations 限制输出位置数，防止 prompt 过大。
        """
        location_data = {}
        for tname in tables:
            if tname not in self.tables:
                continue
            for row in self.query_table(tname):
                addr = row.get("install_addr", "未知位置")
                if addr not in location_data:
                    location_data[addr] = {}
                if tname not in location_data[addr]:
                    location_data[addr][tname] = {}
                cn = TABLE_CN_NAMES.get(tname, tname)
                location_data[addr][tname]["_cn"] = cn
                for fname in TABLE_METRIC_FIELDS.get(tname, []):
                    val = row.get(fname)
                    if val is not None and isinstance(val, (int, float)):
                        location_data[addr][tname].setdefault(fname, []).append(val)

        lines = []
        for addr, tables_data in sorted(location_data.items())[:max_locations]:
            parts = []
            for tname, fields in tables_data.items():
                cn = fields.pop("_cn", tname)
                field_strs = []
                for fname, vals in fields.items():
                    if vals:
                        field_strs.append(
                            f"{fname}={min(vals):.4g}~{max(vals):.4g}(avg:{sum(vals)/len(vals):.4g})"
                        )
                if field_strs:
                    parts.append(f"{cn}: {'; '.join(field_strs)}")
            if parts:
                lines.append(f"[{addr}] {' | '.join(parts)}")
        return "\n".join(lines) if lines else "无匹配数据"

    def build_cached_system_prompt(self) -> str:
        """
        构建固定的系统提示词（含全部表的全部统计数据）。
        放在 system message 中，DeepSeek 可对其 KV cache 进行前缀复用。
        后续请求只需发送变化的 user message，首 token 延迟大幅降低。
        """
        lines = [
            "你是工程监测数据分析师。根据用户查询和下方数据库统计，直接给出简洁总结（不超过300字，纯中文）。",
            "格式：先1-2句结论，再列出关键数据(max/min/avg)，有异常则指出。不要标题、不要markdown。",
            "",
            "=== 数据库全量统计（8张表） ===",
        ]
        for tname in sorted(self.all_stats.keys()):
            cn = TABLE_CN_NAMES.get(tname, tname)
            stats = self.all_stats[tname]
            devices = self.all_devices.get(tname, [])
            dev_str = ", ".join(d["eid"] for d in devices[:5])
            stat_parts = []
            for fname, fstats in stats.items():
                stat_parts.append(f"{fname}={fstats['min']}~{fstats['max']}(avg:{fstats['avg']})")
            lines.append(f"{tname}({cn}) 设备:[{dev_str}] | {'; '.join(stat_parts)}")
        return "\n".join(lines)

    def get_schema_summary(self) -> list:
        """获取所有表的字段摘要"""
        result = []
        for tname, info in self.tables.items():
            result.append({
                "table_name": tname,
                "cn_name": TABLE_CN_NAMES.get(tname, tname),
                "row_count": len(info["rows"]),
                "columns": [
                    {"name": c["name"], "type": c["type"], "comment": c["comment"]}
                    for c in info["columns"]
                ],
            })
        return result

    def get_schema_for_llm(self) -> str:
        """生成供 LLM 理解的紧凑表结构描述"""
        lines = []
        for tname, info in self.tables.items():
            cn = TABLE_CN_NAMES.get(tname, tname)
            cols = [c["name"] for c in info["columns"]]
            lines.append(f"{tname}({cn}): {', '.join(cols)}")
        return "\n".join(lines)

    def query_table(self, table_name: str) -> list:
        """获取表中所有数据（字典列表）"""
        if table_name not in self.tables:
            raise KeyError(f"表 '{table_name}' 不存在")
        info = self.tables[table_name]
        return [dict(zip(info["column_names"], row)) for row in info["rows"]]

    def query_by_eid(self, table_name: str, eid: str) -> list:
        """按设备编号查询"""
        return self._eid_index.get(table_name, {}).get(eid, [])

    def query_by_timerange(
        self, table_name: str, start_ts: int, end_ts: int
    ) -> list:
        """按时间戳范围查询"""
        data = self.query_table(table_name)
        return [r for r in data if r.get("dt") and start_ts <= r["dt"] <= end_ts]

    def get_unique_devices(self, table_name: str) -> list:
        """获取表中所有唯一设备"""
        data = self.query_table(table_name)
        seen = set()
        devices = []
        for row in data:
            eid = row.get("eid")
            if eid and eid not in seen:
                seen.add(eid)
                devices.append({
                    "eid": eid,
                    "equip_name": row.get("equip_name"),
                    "install_addr": row.get("install_addr"),
                    "lon": row.get("lon"),
                    "lat": row.get("lat"),
                    "alt": row.get("alt"),
                })
        return devices

    def compute_statistics(self, table_name: str, field_name: str) -> dict:
        """计算指定表、指定字段的统计值 (min/max/avg/count)"""
        data = self.query_table(table_name)
        values = [
            r[field_name]
            for r in data
            if r.get(field_name) is not None and isinstance(r[field_name], (int, float))
        ]
        if not values:
            return {"count": 0, "error": "无有效数据"}

        return {
            "count": len(values),
            "min": round(min(values), 6),
            "max": round(max(values), 6),
            "avg": round(sum(values) / len(values), 6),
            "sum": round(sum(values), 6),
        }

    def execute_query_plan(self, plan: dict) -> dict:
        """
        执行 LLM 生成的查询计划并返回原始数据。

        plan 格式:
        {
            "target_tables": ["deform_crack_meter"],
            "filters": {
                "eid": "SF-equip001",       // 可选
                "start_time": "2026-06-20",  // 可选
                "end_time": "2026-06-21",    // 可选
            },
            "fields_of_interest": ["sf_crack_width", "sf_temp"],
            "analysis_type": "trend|statistics|comparison|anomaly",
        }
        """
        results = {}
        for tname in plan.get("target_tables", []):
            if tname not in self.tables:
                results[tname] = {"error": f"表 '{tname}' 不存在"}
                continue

            rows = self.query_table(tname)
            filters = plan.get("filters", {})

            # 按 eid 过滤
            eid = filters.get("eid")
            if eid:
                rows = [r for r in rows if r.get("eid") == eid]

            # 按时间过滤
            start = filters.get("start_time")
            end = filters.get("end_time")
            if start:
                start_ts = _parse_time_to_ts(start)
                if start_ts:
                    rows = [r for r in rows if r.get("dt") and r["dt"] >= start_ts]
            if end:
                end_ts = _parse_time_to_ts(end)
                if end_ts:
                    rows = [r for r in rows if r.get("dt") and r["dt"] <= end_ts]

            # 提取关注的字段
            fields = plan.get("fields_of_interest", [])
            if fields:
                rows = [
                    {k: v for k, v in r.items() if k in fields or k in ("eid", "dt", "equip_name", "install_addr")}
                    for r in rows
                ]

            # 计算统计值
            stats = {}
            for f in (fields or []):
                stats[f] = self.compute_statistics(tname, f)

            results[tname] = {
                "cn_name": TABLE_CN_NAMES.get(tname, tname),
                "total_rows": len(rows),
                "sample_rows": rows[:5],
                "statistics": stats,
            }

        return results


def _parse_time_to_ts(time_str: str) -> Optional[int]:
    """将时间字符串转为 Unix 时间戳（秒）"""
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
    ]
    for fmt in formats:
        try:
            return int(datetime.strptime(time_str, fmt).timestamp())
        except ValueError:
            continue
    return None


# ==================== LLM 调用 ====================

# ==================== LLM HTTP 客户端（连接池复用） ====================

# 使用 Session 保持 HTTP 连接池，消除每次请求的 TCP/TLS 握手开销（节省 200-500ms）
_llm_session = None

def _get_llm_session() -> requests.Session:
    global _llm_session
    if _llm_session is None:
        _llm_session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=4,
            pool_maxsize=4,
            max_retries=1,
        )
        _llm_session.mount("https://", adapter)
        _llm_session.mount("http://", adapter)
    return _llm_session


def warmup_llm_connection():
    """
    预热 LLM API 连接：发送一次极小请求建立 TCP+TLS 连接。
    后续用户请求无需等待握手，可节省 500ms-1s。
    """
    logger.info("预热 LLM 连接...")
    try:
        start = time.time()
        call_llm_sync(
            system_prompt="只回复ok",
            user_message="hi",
            temperature=0,
            max_tokens=5,
        )
        logger.info(f"LLM 连接预热完成, 耗时: {time.time() - start:.2f}s")
    except Exception as e:
        logger.warning(f"LLM 连接预热失败（不影响服务）: {e}")


def _llm_should_retry_status(status_code: int) -> bool:
    return status_code in LLM_RETRY_STATUS_CODES


def _llm_backoff_seconds(attempt: int) -> float:
    return LLM_RETRY_BACKOFF_SECONDS * max(1, attempt)


def _extract_llm_error_body(resp: requests.Response, limit: int = 500) -> str:
    try:
        text = resp.text
    except Exception:
        text = "<no response body>"
    return text[:limit]


def _post_llm_with_retry(payload: dict, stream: bool = False, timeout: int = 30) -> requests.Response:
    """发送 LLM 请求并在临时错误（如 502）时自动重试。"""
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    session = _get_llm_session()
    last_exc = None

    for attempt in range(1, LLM_MAX_RETRIES + 2):
        try:
            resp = session.post(
                f"{LLM_BASE_URL}/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=timeout,
                stream=stream,
            )

            if resp.status_code == 200:
                return resp

            body = _extract_llm_error_body(resp)
            err = RuntimeError(f"LLM API 错误 ({resp.status_code}): {body}")
            last_exc = err
            if attempt <= LLM_MAX_RETRIES and _llm_should_retry_status(resp.status_code):
                wait_s = _llm_backoff_seconds(attempt)
                logger.warning(
                    f"LLM 请求失败 status={resp.status_code}，第 {attempt}/{LLM_MAX_RETRIES + 1} 次重试，"
                    f"{wait_s:.1f}s 后重试"
                )
                time.sleep(wait_s)
                continue
            raise err
        except (requests.Timeout, requests.ConnectionError) as e:
            last_exc = e
            if attempt <= LLM_MAX_RETRIES:
                wait_s = _llm_backoff_seconds(attempt)
                logger.warning(
                    f"LLM 请求网络异常: {e}，第 {attempt}/{LLM_MAX_RETRIES + 1} 次重试，"
                    f"{wait_s:.1f}s 后重试"
                )
                time.sleep(wait_s)
                continue
            raise RuntimeError(f"LLM API 请求失败: {e}") from e

    if last_exc:
        raise RuntimeError(f"LLM API 请求失败: {last_exc}")
    raise RuntimeError("LLM API 请求失败: 未知错误")


def _build_stats_fallback_summary(
    user_query: str,
    tables: list,
    matched_fields: list,
    engine: "DataQueryEngine",
) -> str:
    """在 LLM 不可用时，基于预计算统计返回简要可读结果。"""
    del user_query  # 预留后续按问题细化降级逻辑

    fallback_tables = [t for t in (tables or []) if t in engine.all_stats]
    if not fallback_tables:
        fallback_tables = list(engine.all_stats.keys())[:2]

    wanted_fields = [f for f in (matched_fields or []) if isinstance(f, str) and f]
    lines = ["上游分析服务暂时不可用，以下为数据库统计降级结果："]

    for tname in fallback_tables[:2]:
        stats = engine.all_stats.get(tname, {})
        if not stats:
            continue
        cn_name = TABLE_CN_NAMES.get(tname, tname)
        table_fields = [f for f in wanted_fields if f in stats] or list(stats.keys())[:3]
        if not table_fields:
            continue

        parts = []
        for fname in table_fields[:3]:
            fs = stats[fname]
            parts.append(f"{fname}最小{fs['min']}，最大{fs['max']}，均值{fs['avg']}")
        lines.append(f"{cn_name}：" + "；".join(parts))

    if len(lines) == 1:
        lines.append("当前没有可用统计数据，请稍后重试。")

    return "\n".join(lines)


def call_llm_stream(
    system_prompt: str,
    user_message: str,
    temperature: float = 0,
    max_tokens: int = 250,
):
    """
    流式调用 LLM API，逐 chunk yield 文本。
    使用连接池复用 HTTP 连接。
    """
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }

    logger.info(f"调用 LLM (stream): {LLM_MODEL}")
    start = time.time()

    with _post_llm_with_retry(payload, stream=True, timeout=30) as resp:

        first_token = True
        chunk_count = 0
        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            data_str = line[6:]
            if data_str == "[DONE]":
                break
            chunk_count += 1
            try:
                chunk = json.loads(data_str)
                delta = chunk["choices"][0].get("delta", {})
                content = delta.get("content", "")
                if content:
                    if first_token:
                        ttft = time.time() - start
                        logger.info(f"LLM 首 token 耗时: {ttft:.2f}s")
                        first_token = False
                    yield content
            except (json.JSONDecodeError, KeyError, IndexError):
                continue

    elapsed = time.time() - start
    if first_token:
        logger.warning(f"LLM 流式完成, 但无 token 输出, 耗时: {elapsed:.2f}s, 收到 {chunk_count} 个 chunk")
    else:
        logger.info(f"LLM 流式完成, 总耗时: {elapsed:.2f}s")


def call_llm_sync(
    system_prompt: str,
    user_message: str,
    temperature: float = 0,
    max_tokens: int = 200,
    response_format: Optional[dict] = None,
) -> str:
    """
    同步调用 LLM API（非流式），用于意图分类等短响应场景。
    使用连接池复用 HTTP 连接。
    """
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format:
        payload["response_format"] = response_format

    logger.info(f"调用 LLM (sync): {LLM_MODEL}")
    start = time.time()
    resp = _post_llm_with_retry(payload, stream=False, timeout=30)

    elapsed = time.time() - start
    logger.info(f"LLM sync 完成, 耗时: {elapsed:.2f}s, status={resp.status_code}")
    try:
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        raise RuntimeError(f"LLM API 响应解析失败: {e}") from e


# ==================== 关键词匹配（备用，用于非 DB 意图快速路由） ====================

# 设备关键词 → 表名
DEVICE_KEYWORDS = {
    "测缝": "deform_crack_meter", "裂缝": "deform_crack_meter",
    "gnss": "deform_gnss", "GNSS": "deform_gnss", "卫星": "deform_gnss",
    "渗压": "deform_pore_pressure", "孔隙": "deform_pore_pressure",
    "土压力": "deform_soil_pressure", "土压": "deform_soil_pressure",
    "全站仪": "deform_total_station", "全站": "deform_total_station", "棱镜": "deform_total_station",
    "雷达液位": "flow_radar_level", "液位": "flow_radar_level",
    "阵列雷达": "flow_array_radar", "阵列": "flow_array_radar", "流量计": "flow_array_radar",
    "时差": "flow_tof_meter", "超声波": "flow_tof_meter",
}

# 指标关键词 → (表名, 字段名)
METRIC_KEYWORDS = {
    "裂缝宽度": ("deform_crack_meter", "sf_crack_width"),
    "裂缝温度": ("deform_crack_meter", "sf_temp"),
    "渗压值": ("deform_pore_pressure", "pz_pressure"),
    "渗压温度": ("deform_pore_pressure", "pz_temp"),
    "埋设深度": ("deform_pore_pressure", "pz_depth"),
    "土压力值": ("deform_soil_pressure", "sp_pressure"),
    "振弦频率": ("deform_soil_pressure", "sp_freq"),
    "土压温度": ("deform_soil_pressure", "sp_temp"),
    "坐标": ("deform_total_station", None),
    "位移": ("deform_gnss", None),
    "流量": ("flow_array_radar", "Q_inst"),
    "瞬时流量": ("flow_array_radar", "Q_inst"),
    "累计流量": ("flow_array_radar", "Q_total"),
    "流速": ("flow_array_radar", "V_avg"),
    "水位": ("flow_array_radar", "ar_water_level"),
    "断面面积": ("flow_array_radar", "ar_section_area"),
    "液位值": ("flow_radar_level", "L"),
    "雷达流速": ("flow_radar_level", "RV"),
    "电量": (None, "E"),
    "电压": (None, "EV"),
    "状态": (None, "st"),
    "温度": (None, "sf_temp"),
}


def match_intent(user_query: str, engine: DataQueryEngine) -> dict:
    """
    关键词匹配：从用户查询中提取目标表和指标。
    返回匹配结果，用于构建 LLM 提示的上下文。
    """
    matched_tables = set()
    matched_metrics = []  # [(table, field), ...]

    # 设备关键词匹配
    for kw, tname in DEVICE_KEYWORDS.items():
        if kw in user_query:
            matched_tables.add(tname)

    # 指标关键词匹配
    for kw, (tname, field) in METRIC_KEYWORDS.items():
        if kw in user_query:
            if tname:
                matched_tables.add(tname)
            matched_metrics.append((tname, field, kw))

    # 如果用户说"全部"/"所有"/"所有设备"/"概览"，查所有表
    if any(w in user_query for w in ["全部", "所有", "概览", "总览", "概况"]):
        matched_tables = set(engine.all_stats.keys())

    # 如果没有匹配到任何表，默认查所有
    if not matched_tables:
        matched_tables = set(engine.all_stats.keys())

    return {
        "tables": list(matched_tables),
        "metrics": matched_metrics,
    }


def build_context_for_llm(matched: dict, engine: DataQueryEngine) -> str:
    """根据匹配结果，构建发送给 LLM 的紧凑上下文"""
    lines = []
    for tname in matched["tables"]:
        cn = TABLE_CN_NAMES.get(tname, tname)
        stats = engine.all_stats.get(tname, {})
        devices = engine.all_devices.get(tname, [])
        # 紧凑格式: 表名(中文): 设备列表 | 字段=min~max(avg)
        dev_str = ", ".join(d["eid"] for d in devices[:5])
        stat_parts = []
        for fname, fstats in stats.items():
            stat_parts.append(f"{fname}={fstats['min']}~{fstats['max']}(avg:{fstats['avg']})")
        lines.append(f"{tname}({cn}) 设备:{dev_str} | {'; '.join(stat_parts)}")
    return "\n".join(lines)


# ==================== 紧凑表映射（供 LLM 意图分类用，非完整 schema） ====================

def build_table_mapping(engine: DataQueryEngine) -> str:
    """
    超紧凑映射：仅表名+中文名，一行一个。LLM 只需选表，字段由代码关键词匹配。
    """
    lines = []
    for tname in sorted(engine.all_stats.keys()):
        cn = TABLE_CN_NAMES.get(tname, tname)
        lines.append(f"{tname}({cn})")
    return "\n".join(lines)


# ==================== 第1次 LLM 调用：超快意图分类 ====================

INTENT_CLASSIFY_PROMPT = (
    "你是数据查询路由。只返回JSON: {\"cat\":\"db|other\",\"tbls\":[\"表名\"]}。"
    "cat: 查数据库→db, 其他→other。tbls: 从下方表列表选相关的。"
)


def classify_intent(user_query: str, engine: DataQueryEngine) -> dict:
    """
    第1次 LLM 调用：超快意图分类。LLM 只选表，字段由代码匹配。
    max_tokens=60，输入~100 tokens，目标 1.5-2s。
    """
    mapping = build_table_mapping(engine)
    user_message = f"可选表:\n{mapping}\n\n问题: {user_query}"
    try:
        raw = call_llm_sync(
            system_prompt=INTENT_CLASSIFY_PROMPT,
            user_message=user_message,
            temperature=0,
            max_tokens=300,
            response_format={"type": "json_object"},
        )
        raw = raw.strip()
        # 防御解析：尝试多种方式提取 JSON
        result = _safe_parse_json(raw)
        result.setdefault("cat", "db")
        result.setdefault("tbls", [])
        return result
    except Exception as e:
        logger.warning(f"意图分类失败，降级为 DB 查询: {e}")
        return {"cat": "db", "tbls": []}


def _safe_parse_json(raw: str) -> dict:
    """安全解析 JSON，兼容 LLM 可能的多余输出"""
    # 去掉 markdown 包裹
    if raw.startswith("```"):
        raw = re.sub(r"^```\w*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
    raw = raw.strip()
    # 直接解析
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # 尝试提取 {...} 块
    m = re.search(r'\{[^{}]*\}', raw)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    # 兜底：返回默认值
    logger.warning(f"无法解析 LLM 分类结果: {raw[:100]}")
    return {"cat": "db", "tbls": []}


def _normalize_table_list(raw_tables, engine: "DataQueryEngine") -> list:
    """规范化 LLM 返回的表名列表，避免异常类型导致调用失败。"""
    if raw_tables is None:
        return []

    candidates = []
    if isinstance(raw_tables, str):
        text = raw_tables.strip()
        if text:
            if text in ("all", "ALL", "全部", "所有"):
                candidates = list(engine.tables.keys())
            else:
                # 兼容 "a,b" / "a，b" / "[a,b]" 这类非标准输出
                text = text.strip("[]")
                candidates = [s.strip().strip("\"'") for s in re.split(r"[,，;；\s]+", text) if s.strip()]
    elif isinstance(raw_tables, (list, tuple, set)):
        candidates = [x for x in raw_tables if isinstance(x, str) and x.strip()]

    valid_tables = set(engine.tables.keys())
    normalized = []
    seen = set()
    for name in candidates:
        if name in valid_tables and name not in seen:
            seen.add(name)
            normalized.append(name)
    return normalized


# ==================== 第2次 LLM 调用：简要总结 ====================

SUMMARY_BRIEF_PROMPT = (
    "你是工程监测数据分析师。根据数据统计给出核心报告。"
    "要求：≤200字，直接列关键数值和简要判断，有异常才指出。不要标题、不用markdown。"
)


def extract_relevant_stats(tables: list, matched_fields: list, engine: DataQueryEngine) -> str:
    """
    根据 LLM 选中的表 + 关键词匹配的字段，提取相关统计数据。
    仅发送相关表的统计，最小化第2次调用的 prompt。
    """
    field_set = set(matched_fields)
    lines = []
    for tname in tables:
        if tname not in engine.all_stats:
            continue
        cn = TABLE_CN_NAMES.get(tname, tname)
        all_stats = engine.all_stats[tname]
        # 有关键词匹配字段时用关键词匹配的，否则用全部
        fields_to_report = (
            [f for f in field_set if f in all_stats]
            if field_set else list(all_stats.keys())
        )
        if not fields_to_report:
            continue
        parts = []
        for fname in fields_to_report:
            fs = all_stats[fname]
            parts.append(f"{fname}={fs['min']}~{fs['max']}(avg:{fs['avg']})")
        lines.append(f"{tname}({cn}): {'; '.join(parts)}")
    return "\n".join(lines) if lines else "无匹配数据"


def summarize_stream(user_query: str, tables: list, matched_fields: list, engine: DataQueryEngine):
    """
    第2次 LLM 调用：根据 LLM 选表 + 代码选字段，流式生成简要总结。
    """
    stats_text = extract_relevant_stats(tables, matched_fields, engine)
    user_message = f"数据:\n{stats_text}\n\n用户问: {user_query}\n简要报告:"
    try:
        yield from call_llm_stream(
            system_prompt=SUMMARY_BRIEF_PROMPT,
            user_message=user_message,
            temperature=0,
            max_tokens=300,
        )
    except Exception as e:
        logger.warning(f"LLM 总结失败，使用本地统计降级: {e}")
        yield _build_stats_fallback_summary(user_query, tables, matched_fields, engine)


# ==================== 天气查询（和风天气 API） ====================

QWEATHER_HOST = "https://mx3v59pgjm.re.qweatherapi.com"
QWEATHER_KEY = "49d53330fd4f48e78e99eea3aa13f329"

# 城市 → 和风天气 LocationID
CITY_LOCATION_MAP = {
    "北京": "101010100", "上海": "101020100", "广州": "101280101",
    "深圳": "101280601", "杭州": "101210101", "成都": "101270101",
    "武汉": "101200101", "南京": "101190101", "重庆": "101040100",
    "西安": "101110101", "天津": "101030100", "苏州": "101190401",
    "长沙": "101250101", "郑州": "101180101", "青岛": "101120201",
    "大连": "101070201", "厦门": "101230201", "福州": "101230101",
    "合肥": "101220101", "济南": "101120101", "沈阳": "101070101",
    "昆明": "101290101", "贵阳": "101260101", "南宁": "101300101",
    "哈尔滨": "101050101", "长春": "101060101", "太原": "101100101",
    "石家庄": "101090101", "南昌": "101240101", "兰州": "101160101",
    "海口": "101310101", "拉萨": "101140101", "乌鲁木齐": "101130101",
    "呼和浩特": "101080101", "银川": "101170101", "西宁": "101150101",
}


def _lookup_location_id(city: str) -> str:
    """通过城市名查 和风天气 LocationID，失败则用 City Lookup API"""
    for cn, lid in CITY_LOCATION_MAP.items():
        if cn in city or city in cn:
            return lid
    # 调用和风天气城市搜索 API
    try:
        resp = requests.get(
            f"{QWEATHER_HOST}/v2/city/lookup",
            params={"location": city, "key": QWEATHER_KEY},
            timeout=5,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("code") == "200" and data.get("location"):
                return data["location"][0]["id"]
    except Exception:
        pass
    return None


def detect_location(query: str) -> str:
    """从用户查询中提取城市（优先用 LocationID 映射表）"""
    for cn in CITY_LOCATION_MAP:
        if cn in query:
            return cn
    return None


def get_ip_location() -> str:
    """通过 IP 获取本机城市名，失败返回 '北京'"""
    try:
        resp = requests.get("http://ip-api.com/json/?lang=zh-CN", timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            city = data.get("city", "")
            for cn in CITY_LOCATION_MAP:
                if cn in city or city in cn:
                    return cn
            return city or "北京"
    except Exception:
        pass
    return "北京"


def fetch_weather(city: str) -> dict:
    """
    调用和风天气 API 获取实时天气 + 当日预报。
    """
    lid = _lookup_location_id(city)
    if not lid:
        logger.warning(f"无法找到城市 {city} 的 LocationID")
        return None

    try:
        # 同时获取实时天气和3日预报
        now_resp = requests.get(
            f"{QWEATHER_HOST}/v7/weather/now",
            params={"location": lid, "key": QWEATHER_KEY},
            timeout=5,
        )
        forecast_resp = requests.get(
            f"{QWEATHER_HOST}/v7/weather/3d",
            params={"location": lid, "key": QWEATHER_KEY},
            timeout=5,
        )
    except Exception as e:
        logger.warning(f"和风天气 API 请求失败: {e}")
        return None

    if now_resp.status_code != 200:
        return None

    now_data = now_resp.json()
    if now_data.get("code") != "200":
        logger.warning(f"和风天气 API 错误: {now_data.get('code')}")
        return None

    now = now_data["now"]
    result = {
        "city": city,
        "temp": now.get("temp", "?"),
        "feels_like": now.get("feelsLike", "?"),
        "text": now.get("text", "?"),
        "humidity": now.get("humidity", "?"),
        "wind_dir": now.get("windDir", "?"),
        "wind_scale": now.get("windScale", "?"),
    }

    # 解析预报数据
    if forecast_resp.status_code == 200:
        fc_data = forecast_resp.json()
        if fc_data.get("code") == "200" and fc_data.get("daily"):
            today = fc_data["daily"][0]
            result["max_temp"] = today.get("tempMax", "?")
            result["min_temp"] = today.get("tempMin", "?")

    return result


def handle_weather_query(user_query: str):
    """
    天气查询：地址检测 → 和风天气 API → LLM 总结
    """
    city = detect_location(user_query)
    if not city:
        city = get_ip_location()

    logger.info(f"天气查询: city={city}")
    weather = fetch_weather(city)

    if not weather:
        yield f"抱歉，无法获取 {city} 的天气数据，请稍后重试。"
        return

    weather_text = (
        f"{weather['city']}: {weather['text']}, "
        f"当前 {weather['temp']}°C（体感 {weather['feels_like']}°C）, "
        f"湿度 {weather['humidity']}%, "
        f"{weather['wind_dir']} {weather['wind_scale']}级"
    )
    if "max_temp" in weather:
        weather_text += f", 今日 {weather['min_temp']}~{weather['max_temp']}°C"

    user_message = f"天气数据: {weather_text}\n\n用户问: {user_query}\n用中文简要回答:"
    yield from call_llm_stream(
        system_prompt="你是天气助手。根据天气数据用中文简要回答，不超过100字。",
        user_message=user_message,
        temperature=0,
        max_tokens=150,
    )


# ==================== 联网搜索（占位） ====================

def web_search(query: str) -> dict:
    """
    联网搜索（占位实现）。
    实际项目接入时可替换为 SearXNG、Bing API 等。
    """
    logger.info(f"[WebSearch] 查询: {query}")
    # 占位：返回提示信息
    return {
        "query": query,
        "status": "placeholder",
        "message": "联网搜索功能尚未接入实际搜索引擎，当前返回占位结果。请接入 SearXNG 或 Bing Search API。",
        "results": [],
    }


# ==================== HTTP 请求处理器 ====================

class IntentAPIHandler(BaseHTTPRequestHandler):
    """HTTP 请求处理器"""

    engine: DataQueryEngine = None  # 由外部注入
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        logger.info(f"[HTTP] {self.client_address[0]} - {format % args}")

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Connection", "close")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def _send_html(self, html: str, status: int = 200):
        body = html.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Connection", "close")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"请求体不是有效 JSON: {e.msg}") from e
        if not isinstance(data, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return data

    # ---- 路由 ----

    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/" or path == "/index.html":
            self._serve_test_page()
        elif path == "/api/v1/health":
            self._send_json({
                "status": "ok",
                "tables": self.engine.get_all_table_names(),
                "timestamp": datetime.now().isoformat(),
            })
        else:
            self._send_json({"error": "Not Found"}, 404)

    def do_POST(self):
        path = self.path.split("?")[0]

        if path == "/api/v1/intent/analyze":
            self._handle_analyze()
        else:
            self._send_json({"error": "Not Found"}, 404)

    def do_OPTIONS(self):
        """处理 CORS 预检"""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # ---- 处理方法 ----

    def _handle_analyze(self):
        """
        2次 LLM 调用：
          第1次：快速意图分类（JSON 输出，仅发表名映射）
          第2次：流式简要总结（仅发相关字段数据）
        """
        sse_started = False
        try:
            body = self._read_body()
            user_query = body.get("query", "").strip()
            if not user_query:
                self._send_json({"error": "请提供 query 参数"}, 400)
                return

            start_time = time.time()
            logger.info(f"收到查询: {user_query}")

            # ---- SSE 响应头（提前发送，避免后续等待） ----
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            sse_started = True

            # ---- 快速路由：天气关键词直接跳过 LLM 分类 ----
            if any(kw in user_query for kw in ["天气", "气温", "下雨", "刮风", "雾霾", "台风"]):
                self._stream_weather(user_query, start_time)
                return

            # ---- 第1次 LLM：意图分类 ----
            intent = classify_intent(user_query, self.engine)
            if not isinstance(intent, dict):
                intent = {"cat": "db", "tbls": []}

            category = str(intent.get("cat", "db")).strip().lower()
            tables = _normalize_table_list(intent.get("tbls", []), self.engine)
            logger.info(f"意图分类: cat={category}, tbls={tables}")

            if category != "db":
                total_time = round(time.time() - start_time, 2)
                done = json.dumps({
                    "summary": f"当前仅支持数据库查询。您的意图为「{category}」，暂不支持。",
                    "elapsed_seconds": total_time,
                }, ensure_ascii=False)
                self.wfile.write(f"data: {done}\n\n".encode())
                self.wfile.write("data: [DONE]\n\n".encode())
                self.wfile.flush()
                logger.info(f"非DB意图, 耗时: {total_time}s")
                return

            if not tables:
                tables = list(self.engine.all_stats.keys())

            # ---- 关键词匹配字段（LLM 不再选字段） ----
            matched_fields = []
            for kw, (tname, field) in METRIC_KEYWORDS.items():
                if kw in user_query:
                    matched_fields.append(field)

            # ---- 多表时用 JOIN 替代独立查询 ----
            if len(tables) > 1:
                self._stream_joined(tables, user_query, start_time)
                return

            # ---- 单表：流式简要总结 ----
            self._stream_single_table(user_query, tables[0] if tables else None, matched_fields, start_time)

        except ValueError as e:
            self._send_json({"error": str(e)}, 400)
        except Exception as e:
            logger.exception("分析失败")
            try:
                if sse_started:
                    err = json.dumps({"error": str(e)}, ensure_ascii=False)
                    self.wfile.write(f"data: {err}\n\n".encode())
                    self.wfile.write("data: [DONE]\n\n".encode())
                    self.wfile.flush()
                else:
                    self._send_json({"error": str(e)}, 500)
            except Exception:
                pass

    def _stream_weather(self, user_query: str, start_time: float):
        """流式输出天气查询结果"""
        full_text = ""
        for token in handle_weather_query(user_query):
            full_text += token
            try:
                self.wfile.write(
                    f"data: {json.dumps({'token': token}, ensure_ascii=False)}\n\n".encode()
                )
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
        total_time = round(time.time() - start_time, 2)
        self._send_sse_done(total_time, full_text.strip())

    def _stream_joined(self, tables: list, user_query: str, start_time: float):
        """多表 JOIN 后用同步 LLM 生成总结，再逐步推流"""
        joined_text = self.engine.get_joined_stats(tables)
        user_message = f"数据（按位置合并多表）:\n{joined_text}\n\n用户问: {user_query}\n简要报告:"
        # 用同步调用避免流式偶发的空 token 问题
        try:
            summary = call_llm_sync(
                system_prompt=SUMMARY_BRIEF_PROMPT,
                user_message=user_message,
                temperature=0,
                max_tokens=300,
            ).strip()
        except Exception as e:
            logger.warning(f"JOIN 总结失败，使用本地统计降级: {e}")
            summary = _build_stats_fallback_summary(user_query, tables, [], self.engine)
        if not summary:
            logger.warning(f"JOIN LLM 返回空, prompt_len={len(user_message)}")
            summary = "数据量较大，请缩小查询范围（如指定具体设备或位置）。"
        # 逐字推流（模拟 SSE token 效果）
        for ch in summary:
            try:
                self.wfile.write(
                    f"data: {json.dumps({'token': ch}, ensure_ascii=False)}\n\n".encode()
                )
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
        total_time = round(time.time() - start_time, 2)
        self._send_sse_done(total_time, summary)

    def _stream_single_table(self, user_query: str, table: str, matched_fields: list, start_time: float):
        """单表查询流式输出"""
        full_text = ""
        for token in summarize_stream(user_query, [table] if table else [], matched_fields, self.engine):
            full_text += token
            try:
                self.wfile.write(
                    f"data: {json.dumps({'token': token}, ensure_ascii=False)}\n\n".encode()
                )
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
        total_time = round(time.time() - start_time, 2)
        self._send_sse_done(total_time, full_text.strip())

    def _send_sse_done(self, elapsed: float, summary: str = ""):
        """发送 SSE 完成事件"""
        done = json.dumps({
            "summary": summary,
            "elapsed_seconds": elapsed,
        }, ensure_ascii=False)
        try:
            self.wfile.write(f"data: {done}\n\n".encode())
            self.wfile.write("data: [DONE]\n\n".encode())
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self.close_connection = True

    def _serve_test_page(self):
        """提供交互式测试页面"""
        html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>监控数据智能分析</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background:#f0f4f8; min-height:100vh; }
.header { background: linear-gradient(135deg, #1a73e8, #0d47a1); color:#fff; padding:24px 32px; }
.header h1 { font-size:22px; }
.header p { opacity:0.8; margin-top:4px; font-size:14px; }
.container { max-width:800px; margin:0 auto; padding:24px; }
.card { background:#fff; border-radius:12px; padding:24px; box-shadow:0 2px 12px rgba(0,0,0,0.06); margin-bottom:20px; }
.card h2 { font-size:16px; margin-bottom:12px; color:#333; }
.input-row { display:flex; gap:12px; }
.input-row input { flex:1; padding:12px 16px; border:2px solid #e0e0e0; border-radius:8px; font-size:15px; outline:none; }
.input-row input:focus { border-color:#1a73e8; }
.input-row button { padding:12px 24px; background:#1a73e8; color:#fff; border:none; border-radius:8px; font-size:15px; cursor:pointer; font-weight:500; }
.input-row button:hover { background:#1557b0; }
.input-row button:disabled { background:#b0bec5; cursor:not-allowed; }
.quick { display:flex; flex-wrap:wrap; gap:8px; margin-top:12px; }
.quick button { padding:6px 16px; background:#e8f0fe; color:#1a73e8; border:1px solid #c5d9f7; border-radius:20px; font-size:13px; cursor:pointer; }
.quick button:hover { background:#d2e3fc; }
.summary-card { background: linear-gradient(135deg, #f8f9fa, #e8f0fe); border-left:4px solid #1a73e8; }
.summary-content { font-size:15px; line-height:1.8; color:#333; white-space:pre-wrap; }
.loading { display:none; text-align:center; padding:30px; }
.loading.active { display:block; }
.spinner { width:36px; height:36px; border:3px solid #e0e0e0; border-top-color:#1a73e8; border-radius:50%; animation:spin .8s linear infinite; margin:0 auto 12px; }
@keyframes spin { to { transform:rotate(360deg); } }
.elapsed { font-size:12px; color:#999; margin-top:8px; }
.error { color:#d32f2f; background:#ffebee; padding:12px; border-radius:8px; }
</style>
</head>
<body>
<div class="header">
    <h1>📊 监控数据智能分析</h1>
    <p>基于 LLM 的自然语言数据库查询 | 端口: """ + str(SERVER_PORT) + """</p>
</div>

<div class="container">
    <div class="card">
        <h2>🔍 输入查询</h2>
        <div class="input-row">
            <input type="text" id="q" placeholder="例：查询大坝1#裂缝的最大宽度、所有渗压计渗压值统计..."
                   onkeydown="if(event.key==='Enter')go()">
            <button id="btn" onclick="go()">分析</button>
        </div>
        <div class="quick">
            <button onclick="q('查询测缝计 SF-equip001 裂缝宽度变化')">📏 裂缝宽度</button>
            <button onclick="q('统计所有渗压计的渗压值最大最小值')">💧 渗压统计</button>
            <button onclick="q('GNSS 所有设备位移数据')">🛰️ GNSS位移</button>
            <button onclick="q('阵列雷达流量计的流量统计')">🌊 雷达流量</button>
            <button onclick="q('所有设备运行状态（电量和状态码）')">🔋 设备状态</button>
            <button onclick="q('全站仪三维坐标数据概览')">📍 全站仪</button>
        </div>
    </div>

    <div class="loading" id="ld"><div class="spinner"></div>分析中...</div>

    <div class="card summary-card" id="result" style="display:none;">
        <h2>📝 分析结果</h2>
        <div class="summary-content" id="summary"></div>
        <div class="elapsed" id="time"></div>
    </div>
</div>

<script>
function q(t) { document.getElementById('q').value = t; go(); }
async function go() {
    const query = document.getElementById('q').value.trim();
    if (!query) return;
    const btn = document.getElementById('btn');
    const ld = document.getElementById('ld');
    const result = document.getElementById('result');
    const summaryEl = document.getElementById('summary');
    const timeEl = document.getElementById('time');
    btn.disabled = true;
    ld.classList.add('active');
    result.style.display = 'none';
    summaryEl.textContent = '';
    timeEl.textContent = '';
    try {
        const resp = await fetch('/api/v1/intent/analyze', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({query})
        });
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (true) {
            const {done, value} = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, {stream: true});
            const lines = buffer.split('\\n');
            buffer = lines.pop();
            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                const jsonStr = line.slice(6);
                if (jsonStr === '[DONE]') continue;
                try {
                    const data = JSON.parse(jsonStr);
                    if (data.token) {
                        if (!result.style.display || result.style.display==='none') {
                            result.style.display = '';
                            ld.classList.remove('active');
                        }
                        summaryEl.textContent += data.token;
                    } else if (data.summary !== undefined) {
                        summaryEl.textContent = data.summary;
                        timeEl.textContent = '⏱ '+data.elapsed_seconds+'秒';
                    } else if (data.error) {
                        summaryEl.innerHTML = '<div class="error">'+data.error+'</div>';
                        result.style.display = '';
                        ld.classList.remove('active');
                    }
                } catch(e) {}
            }
        }
    } catch(e) {
        summaryEl.innerHTML = '<div class="error">请求失败: '+e.message+'</div>';
        result.style.display = '';
    } finally {
        btn.disabled = false;
        ld.classList.remove('active');
    }
}
</script>
</body>
</html>"""
        self._send_html(html)


# ==================== 启动服务 ====================

def main():
    logger.info("=" * 60)
    logger.info("  监控数据智能分析 HTTP 服务")
    logger.info("=" * 60)

    # 初始化数据引擎
    if not os.path.exists(SQL_FILEPATH):
        logger.error(f"SQL 文件不存在: {SQL_FILEPATH}")
        logger.error("请设置 SQL_FILEPATH 环境变量或确保文件存在")
        sys.exit(1)

    engine = DataQueryEngine(SQL_FILEPATH)
    IntentAPIHandler.engine = engine

    # 预热连接，避免首次用户请求支付 TCP+TLS 握手开销
    warmup_llm_connection()

    logger.info(f"LLM 配置: {LLM_MODEL} @ {LLM_BASE_URL}（HTTP 连接池复用）")
    logger.info(f"服务地址: http://{SERVER_HOST}:{SERVER_PORT}")

    server = ThreadingHTTPServer((SERVER_HOST, SERVER_PORT), IntentAPIHandler)
    logger.info(f"✅ 服务已启动，访问 http://localhost:{SERVER_PORT} 打开测试页面")
    logger.info("按 Ctrl+C 停止服务")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("服务已停止")
        server.shutdown()


if __name__ == "__main__":
    main()
