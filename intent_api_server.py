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
from datetime import datetime, timedelta
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

# 塔机历史作业接口：名称由业务侧提供，SN 用于调用第三方服务。
TOWER_CRANE_WORK_CYCLE_URL = os.environ.get(
    "TOWER_CRANE_WORK_CYCLE_URL",
    "https://tciccs.cscec3bxjy.cn:30400/api/towercranedataservice/getWorkCycleInfoHis",
)
TOWER_CRANE_NAME_TO_SN = {
    "向阳村4#塔机": "91320506MAE18ATB9XTC202606181EW4",
    "向阳村3#塔机": "91320506MAE18ATB9XTC202606181EW3",
    "向阳村2#塔机": "91320506MAE18ATB9XTC202606181EW2",
}
TOWER_CRANE_REQUEST_VERIFY_TLS = os.environ.get(
    "TOWER_CRANE_REQUEST_VERIFY_TLS", "false"
).lower() == "true"
TOWER_CRANE_REQUEST_TIMEOUT = int(
    os.environ.get("TOWER_CRANE_REQUEST_TIMEOUT", "30")
)

# 闸孔开度方案：仅用于计算和论证，不直接控制闸门。
GATE_PLAN_GRAVITY = 9.81
GATE_PLAN_KEYWORDS = (
    "开度方案", "闸门开度", "闸孔开度", "兴各庄闸", "泄洪方案", "闸门调度方案",
)

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


def calculate_gate_opening_scenarios(
    target_flow: Optional[float], flow_coefficient: Optional[float] = None,
    gate_width: Optional[float] = None, head: Optional[float] = None,
    gate_height: Optional[float] = None, minimum_opening: float = 0.0,
    flood_flow: Optional[float] = None,
) -> dict:
    """计算精确参数方案，或生成兴各庄闸的工程估算方案。"""
    # 目标流量已知但水头等率定参数未知时，使用规格书结构参数和明确标注的估算假设。
    if target_flow is not None and any(
        value is None for value in (flow_coefficient, gate_width, head, gate_height)
    ):
        if target_flow <= 0:
            return {"mode": "estimate", "error": "目标流量Q必须大于0"}
        gate_count = 9
        estimate_gate_width = 35.0
        estimate_gate_height = 5.0
        estimate_coefficient = 0.65
        head_range = (0.6, 1.0)
        opening_values = tuple(
            round(
                target_flow / gate_count
                / (estimate_coefficient * estimate_gate_width
                   * (2 * GATE_PLAN_GRAVITY * h) ** 0.5),
                3,
            )
            for h in head_range
        )
        opening_range = (min(opening_values), max(opening_values))
        recommended_opening = 0.38
        return {
            "mode": "estimate",
            "formula": "Q=μ·b·e·√(2gH)",
            "assumptions": {
                "site": "潮白河兴各庄闸",
                "gate_count": gate_count,
                "gate_width": estimate_gate_width,
                "gate_height": estimate_gate_height,
                "flow_coefficient": estimate_coefficient,
                "head_range": head_range,
                "opening_definition": "等效过水高度，不等同于液压缸行程或底轴转角",
            },
            "parameters": {
                "target_flow": target_flow,
                "gate_count": gate_count,
                "gate_width": estimate_gate_width,
                "gate_height": estimate_gate_height,
                "flow_coefficient": estimate_coefficient,
                "head_range": head_range,
            },
            "recommended": {
                "gate_count": gate_count,
                "per_gate_flow": round(target_flow / gate_count, 2),
                "equivalent_opening": recommended_opening,
                "opening_range": opening_range,
                "opening_at_heads": opening_values,
                "opening_percent": round(recommended_opening / estimate_gate_height * 100, 1),
            },
            "scenarios": {
                "保守起调": {"gate_count": 9, "opening": 0.30, "flow_range": "约240～300 m³/s（随水头变化）"},
                "初始推荐": {"gate_count": 9, "opening": 0.38, "flow_range": "约300～380 m³/s（随水头变化）"},
                "增流档位": {"gate_count": 9, "opening": 0.50, "flow_range": "约400～500 m³/s（随水头变化）"},
                "7孔备用": {"gate_count": 7, "opening": "约0.50～0.60", "flow_range": "需复核"},
                "5孔备用": {"gate_count": 5, "opening": "约0.70～0.85", "flow_range": "需复核"},
            },
        }
    required = {"目标流量Q": target_flow, "流量系数μ": flow_coefficient,
                "闸孔宽度b": gate_width, "有效水头H": head,
                "最大开度e_max": gate_height}
    missing = [name for name, value in required.items() if value is None]
    if missing:
        return {"formula": "Q=μ·b·e·√(2gH)", "missing_parameters": missing}
    if any(value <= 0 for value in (flow_coefficient, gate_width, head, gate_height)):
        return {"formula": "Q=μ·b·e·√(2gH)", "error": "μ、b、H、最大开度必须大于0"}
    if target_flow <= 0:
        return {"formula": "Q=μ·b·e·√(2gH)", "error": "目标流量Q必须大于0"}
    if minimum_opening < 0 or minimum_opening > gate_height:
        return {"formula": "Q=μ·b·e·√(2gH)", "error": "最小开度必须位于0和最大开度之间"}

    denominator = flow_coefficient * gate_width * (2 * GATE_PLAN_GRAVITY * head) ** 0.5
    scenario_flows = {"保守": target_flow * 0.7, "目标": target_flow,
                      "泄洪": flood_flow if flood_flow is not None else target_flow * 1.3}
    scenario_reasons = {
        "保守": "按目标流量的70%控制，降低过流量和运行风险",
        "目标": "按目标流量的100%控制，用于满足常规调度目标",
        "泄洪": "按指定泄洪流量或目标流量的130%控制，用于提高泄流能力",
    }
    scenarios = {}
    for name, flow in scenario_flows.items():
        calculated_opening = flow / denominator
        opening = max(minimum_opening, calculated_opening)
        scenarios[name] = {"flow": round(flow, 4),
                           "calculated_opening": round(calculated_opening, 4),
                           "opening": round(opening, 4),
                           "opening_percent": round(opening / gate_height * 100, 2),
                           "within_limit": opening <= gate_height,
                           "reason": scenario_reasons[name]}
    return {
        "mode": "calculated",
        "formula": "Q=μ·b·e·√(2gH)",
        "parameters": {"target_flow": target_flow, "flow_coefficient": flow_coefficient,
                       "gate_width": gate_width, "head": head, "gate_height": gate_height,
                       "minimum_opening": minimum_opening},
        "derivation": {
            "gravity": GATE_PLAN_GRAVITY,
            "denominator": round(denominator, 6),
            "opening_equation": "e=Q/(μ·b·√(2gH))",
            "limit_rule": "e=max(最小开度, 计算开度)，且不得超过最大开度",
        },
        "scenarios": scenarios,
        "calibration": "建议用实测流量反算μ：μ=Q/(b·e·√(2gH))，再按多组实测数据校准。",
    }


def extract_gate_plan_parameters(text: str) -> dict:
    """从自然语言提取闸门方案参数，支持“过流300m³/s”等常用表达。"""
    text = text or ""

    def number(patterns):
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return float(match.group(1))
        return None

    return {
        "target_flow": number([
            r"(?:目标流量|过闸流量|过流|流量Q|流量|Q)\s*[:：=]?\s*(\d+(?:\.\d+)?)\s*(?:m³/?s|m3/?s|立方米/?秒)?",
        ]),
        "flow_coefficient": number([r"(?:流量系数|系数|μ|u)\s*[:：=]?\s*(\d+(?:\.\d+)?)"]),
        "gate_width": number([r"(?:闸孔宽度|闸宽|单孔宽度|宽度|b)\s*[:：=]?\s*(\d+(?:\.\d+)?)"]),
        "head": number([r"(?:有效水头|水头|落差|H)\s*[:：=]?\s*(\d+(?:\.\d+)?)"]),
        "gate_height": number([r"(?:最大开度|闸高|闸门高度|最大高度|e_max)\s*[:：=]?\s*(\d+(?:\.\d+)?)"]),
        "minimum_opening": number([r"(?:最小开度|下限)\s*[:：=]?\s*(\d+(?:\.\d+)?)"]) or 0.0,
        "flood_flow": number([r"(?:泄洪流量|洪峰流量)\s*[:：=]?\s*(\d+(?:\.\d+)?)"]),
    }


def is_gate_opening_plan_query(text: str) -> bool:
    """识别兴各庄闸开度或调度方案请求，优先于普通 LLM 意图分类。"""
    normalized = (text or "").lower()
    return any(keyword.lower() in normalized for keyword in GATE_PLAN_KEYWORDS)


def build_gate_dispatch_monitoring_context(engine: "DataQueryEngine") -> dict:
    """提取最新水位和流量记录，并明确其与兴各庄闸的匹配范围。"""
    records = []
    for table_name, fields in (
        ("flow_radar_level", ("L", "RV", "SSP")),
        ("flow_array_radar", ("Q_inst", "V_avg", "ar_water_level")),
        ("flow_tof_meter", ("Q_inst", "V_avg")),
    ):
        if table_name not in engine.tables:
            continue
        rows = engine.query_table(table_name)
        if not rows:
            continue
        latest = max(rows, key=lambda row: row.get("dt") or 0)
        values = {
            field: latest.get(field)
            for field in fields
            if latest.get(field) is not None
        }
        if values:
            records.append({
                "table": table_name,
                "device_name": latest.get("equip_name") or "未命名设备",
                "install_address": latest.get("install_addr") or "未标注位置",
                "timestamp": latest.get("time") or latest.get("dt"),
                "values": values,
            })

    has_xinggezhuang = any(
        "兴各庄" in f"{record['device_name']}{record['install_address']}"
        for record in records
    )
    missing = ["9孔当前开度", "闸门设备状态", "厂家泄流曲线或现场率定参数"]
    if not has_xinggezhuang:
        missing.insert(0, "兴各庄闸上游/下游明确点位水位")
    return {
        "data_scope": "xinggezhuang_monitoring_data" if has_xinggezhuang else "generic_monitoring_data",
        "latest_records": records,
        "missing_data": missing,
    }


def build_llm_gate_dispatch_prompt(
    user_query: str, parameters: dict, monitoring_context: dict,
) -> tuple[str, str]:
    """构造每次均调用大模型的闸门调度分析提示词。"""
    system_prompt = """你是潮白河兴各庄闸的水利工程调度辅助分析师。每次必须基于用户问题、规格书确认参数和提供的监测上下文重新分析，禁止套用固定答案。

兴各庄闸已确认固定参数：9孔翻板式平面钢闸门；单孔净宽35m；闸门高度5m；闸底板顶高程9.00m。闸门调度只输出辅助建议，不得下发控制指令。

必须严格使用并原样保留以下七个标题：
【1、已知条件和数据】
【2、推荐的估算方案】
【3、估算推理过程】
【4、建议采用的开度估算档位】
【5、优先推荐方案的原因】
【6、现场调度步骤】
【7、最终估算结论】

核心原则：当监测上下文中缺少必要数据（水位、流量系数等）时，可以给出合理假定值用于估算，但必须明确标注为"假定"而非真实数据。这是辅助分析，所有数字都可能需要现场复核。

规则（按重要性排序）：
1. 数据来源必须三分类并原样标注：①【规格书参数】=规格书中已确认的固定值；②【实时监测】=监测上下文中明确给出的最新读数；③【估算假定】=因数据缺失而由模型给出的合理默认值。每一条数值在【1、已知条件和数据】中必须标明属于哪一类。
2. 缺少上游/下游明确点位水位时，可假定一个合理值（如基于闸底板高程9.00m推算），但必须在【1、已知条件和数据】中标注"【估算假定】上游水位=X.XXm（模型根据闸底板高程推定，需现场确认）"。同理，缺少流量系数时可假定μ=0.65～0.75，也必须标注为假定。
3. data_scope=generic_monitoring_data 时，监测记录仅为通用示例数据，绝不能称为兴各庄闸实时数据，必须在第1节显著注明。
4. 不得虚构某一孔的"实际开度""当前状态"（如"3号孔已开启"）。可以给出候选开度范围和公式推理。
5. 缺少9孔当前开度、闸门设备状态、泄流率定曲线时，必须在第1节和第7节说明缺失项及其对方案置信度的影响。
6. 绝不能说"直接执行""自动开启""已验证安全""已核实"等肯定性措辞；必须使用"建议""辅助分析""需人工复核"。
7. 结论必须随本次用户目标流量和监测上下文变化，不要输出与本次数据无关的固定表述。
8. 若用户输入中包含目标流量，可以基于假定值完成水力公式估算并给出推荐方案（孔数、开度范围、经验系数），但必须在每处使用假定值的地方标注"【估算假定】"。"""
    user_prompt = (
        f"用户问题：{user_query}\n"
        f"解析参数：{json.dumps(parameters, ensure_ascii=False)}\n"
        f"监测上下文：{json.dumps(monitoring_context, ensure_ascii=False)}\n"
        "请生成完整七段式闸门调度辅助分析。"
    )
    return system_prompt, user_prompt


def format_gate_opening_analysis_process(calculation: dict) -> str:
    """格式化开度方案；估算模式固定输出七个业务段落。"""
    if calculation.get("mode") == "estimate":
        return _format_estimated_gate_plan(calculation)
    lines = ["【分析过程】", f"采用公式：{calculation['formula']}"]
    missing = calculation.get("missing_parameters")
    if missing:
        lines.append("缺少必要参数：" + "、".join(missing))
        lines.append("因此暂不计算具体开度，补齐参数后再生成方案。")
        return "\n".join(lines)
    if calculation.get("error"):
        lines.append("参数校验失败：" + calculation["error"])
        return "\n".join(lines)

    params = calculation["parameters"]
    derivation = calculation["derivation"]
    lines.append(
        "参数：Q目标={target_flow}，μ={flow_coefficient}，b={gate_width}，"
        "H={head}，最大开度={gate_height}，最小开度={minimum_opening}".format(**params)
    )
    lines.append(
        "代入：e=Q/(μ·b·√(2gH))，分母={denominator}，g={gravity}".format(**derivation)
    )
    lines.append("限幅规则：" + derivation["limit_rule"])
    for name, scenario in calculation["scenarios"].items():
        limit_note = "未超过最大开度" if scenario["within_limit"] else "超过最大开度，不能直接采用"
        lines.append(
            f"{name}：Q={scenario['flow']}，理论e={scenario['calculated_opening']}，"
            f"建议e={scenario['opening']}（{scenario['opening_percent']}%），{limit_note}。"
        )
    lines.append("校验：" + calculation["calibration"])
    return "\n".join(lines)


def _format_estimated_gate_plan(calculation: dict) -> str:
    """输出透明的工程估算方案，明确假设、范围和人工复核边界。"""
    params = calculation["parameters"]
    recommended = calculation["recommended"]
    assumptions = calculation["assumptions"]
    lines = [
        "【1、已知条件和数据】",
        f"工程对象：{assumptions['site']}；工作闸门为翻板式平面钢闸门，共{params['gate_count']}孔，单孔净宽{params['gate_width']}m，闸门高度{params['gate_height']}m。",
        f"目标过闸流量：{params['target_flow']}m³/s；总过流宽度={params['gate_count']}×{params['gate_width']}={params['gate_count'] * params['gate_width']:.0f}m。",
        "规格书同时配置上下游水位、流量监测、视频测流和PLC开度调节，可用于后续现场率定。",
        "当前未提供实测上下游水位和厂家泄流曲线，以下为估算方案，不作为直接控制指令。",
        "",
        "【2、推荐的估算方案】",
        f"优先采用{recommended['gate_count']}孔全部参与过流、左右对称、基本等开度运行；单孔目标流量约{recommended['per_gate_flow']}m³/s。",
        f"按有效水头{params['head_range'][0]}～{params['head_range'][1]}m、流量系数μ={params['flow_coefficient']}估算，单孔等效过水高度约{recommended['opening_range'][0]}～{recommended['opening_range'][1]}m，建议以{recommended['equivalent_opening']:.2f}m作为初始计算点。",
        "等效过水高度不等同于液压缸行程、底轴转角或门顶高程，实际控制量需按闸门几何关系换算。",
        "",
        "【3、估算推理过程】",
        "采用闸孔出流估算公式：Q=μ·b·e·√(2gH)。其中Q为总流量，μ为流量系数，b为单孔净宽，e为等效过水高度，H为有效水头。",
        f"先按均匀分配计算单孔流量：Q单=Q总/{params['gate_count']}={recommended['per_gate_flow']}m³/s；再按 e=Q单/(μ·b·√(2gH)) 反算开度。",
        f"当H={params['head_range'][0]}m时，e约{recommended['opening_at_heads'][0]}m；当H={params['head_range'][1]}m时，e约{recommended['opening_at_heads'][1]}m。考虑局部损失、收缩、下游顶托和测量误差，将约{recommended['opening_range'][0]}～{recommended['opening_range'][1]}m作为工程估算范围。",
        "",
        "【4、建议采用的开度估算档位】",
        "保守起调：9孔，单孔等效开度约0.30m，预计约240～300m³/s；初始推荐：9孔，约0.38m，预计约300～380m³/s；增流档位：9孔，约0.50m，预计约400～500m³/s。以上流量随有效水头变化，仅作档位估算。",
        "备用方案：7孔对称开启时约0.50～0.60m，5孔中部对称开启时约0.70～0.85m，均需重点复核流态、消能和冲刷。",
        "",
        "【5、优先推荐方案的原因】",
        "9孔等开度方案可使单孔流量较小且横向分布均匀，有利于降低局部高速射流、偏流、闸墩附近水力冲击和下游河床局部冲刷风险，也便于液压系统同步控制和通过实测流量闭环修正。",
        "少孔大开度仅作为检修、设备故障或调节灵敏度不足时的备用方案，不建议在缺少泄流曲线和消能校核时作为首选。",
        "",
        "【6、现场调度步骤】",
        "1. 核对上下游水位、来水流量、下游河道及消能条件，确认设备无故障。\n2. 9孔同步小幅开启，初始按约0.30m等效开度估算。\n3. 等待水位、流量和闸门状态稳定，检查开度反馈、液压站压力、振动、异响、下游流态和冲刷。\n4. 若流量不足，每次整体增加约0.05m，按0.35→0.40→0.45m逐级调整。\n5. 接近300m³/s后，以实测流量为主进行微调，不通过单孔大幅开度补偿。\n6. 任何异常或上下游水位明显变化时暂停调整，重新计算有效水头并由运行人员复核。",
        "",
        "【7、最终估算结论】",
        f"针对{params['target_flow']}m³/s目标流量，推荐9孔全部参与过流，单孔约{recommended['per_gate_flow']}m³/s，以约{recommended['equivalent_opening']:.2f}m等效过水高度作为初始估算点，合理估算范围约{recommended['opening_range'][0]}～{recommended['opening_range'][1]}m。该结果仅用于方案比选、算法原型和现场试调初值；正式运行前必须结合实测上下游水位、厂家泄流曲线或现场率定结果，并经有权限的水闸运行人员确认。",
    ]
    return "\n".join(lines)


def build_gate_opening_plan_prompt(user_query: str, calculation: dict) -> str:
    """构造开度方案 LLM 提示，限制其只能解释计算结果。"""
    return (
        "你是潮白河项目水闸运行方案分析师。根据闸孔出流公式 "
        "Q=μ·b·e·√(2gH) 审核并整理开度建议。只能使用用户参数和计算结果，"
        "不得臆造现场数据，不得声称已完成实际安全验证，不得下发控制指令。"
        "程序会单独展示确定性的计算过程。你只需补充三种方案的业务原因、"
        "风险、适用场景、假设和实测反算μ的校验建议；不要重复编造计算步骤，"
        "不要输出无法核验的内部思维链。明确标注‘建议值，需人工复核’。"
        f"\n用户问题：{user_query}\n计算结果：{json.dumps(calculation, ensure_ascii=False)}"
    )


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
        "thinking": {"type": "disabled"},
        "stream": True,
        "thinking": {"type": "disabled"},
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
                text = delta.get("content", "")
                if text and text.strip():
                    if first_token:
                        ttft = time.time() - start
                        logger.info(f"LLM 首 token 耗时: {ttft:.2f}s")
                        first_token = False
                    yield text
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
    timeout: int = 30,
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
        "thinking": {"type": "disabled"},
    }
    if response_format:
        payload["response_format"] = response_format

    logger.info(f"调用 LLM (sync): {LLM_MODEL}")
    start = time.time()
    resp = _post_llm_with_retry(payload, stream=False, timeout=timeout)

    elapsed = time.time() - start
    logger.info(f"LLM sync 完成, 耗时: {elapsed:.2f}s, status={resp.status_code}")
    try:
        data = resp.json()
        message = data["choices"][0]["message"]
        content = (message.get("content") or "").strip()
        if not content:
            logger.warning(f"LLM sync 返回空 content，完整 message keys: {list(message.keys())}")
            raise RuntimeError("LLM未生成可展示文本")
        return content
    except Exception as e:
        if isinstance(e, RuntimeError):
            raise
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


# 字段中文名映射（用于统计摘要）
FIELD_CN_NAMES = {
    "sf_crack_width": "裂缝宽度(mm)", "sf_temp": "温度(℃)",
    "gnss_horizontal_dis_n": "水平位移N(mm)", "gnss_horizontal_dis_e": "水平位移E(mm)", "gnss_vertical_dis": "垂直位移(mm)",
    "pz_pressure": "渗压(kPa)", "pz_temp": "温度(℃)", "pz_depth": "埋深(m)",
    "sp_pressure": "土压力(kPa)", "sp_temp": "温度(℃)", "sp_depth": "埋深(m)",
    "Q_inst": "瞬时流量(m³/s)", "Q_total": "累积流量(m³)", "V_avg": "平均流速(m/s)", "ar_water_level": "水位(m)",
    "L": "液位(m)", "E": "电量(%)",
    "st": "状态", "EV": "电压(V)",
    "hrz_dis_n": "水平位移N(mm)", "hrz_dis_e": "水平位移E(mm)", "vrt_dis": "垂直位移(mm)",
}


def _cn_field(fname: str) -> str:
    """返回字段的中文名，无映射时返回原名"""
    return FIELD_CN_NAMES.get(fname, fname)


# ==================== 第2次 LLM 调用：简要总结 ====================

SUMMARY_BRIEF_PROMPT = (
    "你是监控数据总结器。严格只输出最终结论，不要任何推理、分析、解释、前缀、模板、示例或多句描述。"
    "直接输出 1 句简洁结论，长度尽量控制在 30~50 字。"
)


def _strip_reasoning(text: str) -> str:
    """去除 LLM 输出中的推理前缀、元指令和多余解释，只保留最终结论。"""
    if not text:
        return ""

    text = text.strip()
    text = re.sub(r"^```(?:json|text)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.replace("\u200b", "").strip()

    # 去掉常见的前缀提示和标签
    text = re.sub(r"^(分析|总结|结论|结果|回答|报告|说明|判断|简要结论)[:：]\s*", "", text)
    text = re.sub(r"^[^：:。！？\n]*[：:]\s*", "", text)

    # 迭代剥离，直到没有更多匹配（处理多层嵌套推理）
    reasoning_starts = [
        r'^我们(被问到|根据|分析|需要|被要求|来看|可以)[^。！？\n]*[。！？]?\s*',
        r'^根据(提供|数据|用户)[^。！？\n]*[。！？]?\s*',
        r'^(按照|格式|注意|提示|示例)[^。！？\n]*[。！？]?\s*',
        r'^(用户|问题)[^。！？\n]*(问的是|涉及)[^。！？\n]*[。！？]?\s*',
        r'^(直接给出最终答案|禁止推理过程|禁止分析步骤|禁止"我们"开头|只输出最终结论|只输出 1 句简洁结论)[^。！？\n]*[。！？]?\s*',
        r'^(需要根据|需要基于|先|接着|然后|最后)[^。！？\n]*[。！？]?\s*',
        r'^(我先|我们先|我会|我们会|我建议|我们建议)[^。！？\n]*[。！？]?\s*',
    ]
    changed = True
    while changed:
        changed = False
        for pat in reasoning_starts:
            new_text = re.sub(pat, '', text)
            if new_text != text and len(new_text) > 15:
                text = new_text
                changed = True
                break

    # 去掉尾部的客套/追问内容
    text = re.sub(r'(?:\s*(请问|还有什么|还有|如需|如果需要|欢迎|谢谢|可以继续).*)$', '', text)

    # 去掉引用用户问题的部分（"原文..."、引号包裹的问题重复）
    text = re.sub(r'^["\u201c\u201d](.+?)["\u201c\u201d]\s*[，,]?\s*', '', text)
    text = re.sub(r"^['\u2018\u2019](.+?)['\u2018\u2019]\s*[，,]?\s*", '', text)

    # 如果仍然有推理痕迹，尝试提取最后一句结论
    # 常见的推理标记："所以"、"因此"、"综上"、"结论是"、"最终"、"输出"
    concluding_markers = [
        r'(?:所以|因此|综上|综上所[述说]|结论[是为]|最终|输出一句话结论)[：:]?\s*([^。！？\n，,]+[。！？]?)',
    ]
    for pat in concluding_markers:
        m = re.search(pat, text)
        if m:
            candidate = m.group(1).strip()
            if len(candidate) >= 5:
                text = candidate
                break

    # 兜底：尝试提取引号内的结论内容（"xxx" / “xxx” / 'xxx' / ‘xxx’）
    if len(text) > 50 or any(kw in text for kw in ["直接输出", "不要", "禁止", "只输出"]):
        # 优先取最后一对引号的内容（左右引号成对匹配，避免单字符索引越界）
        for qm in ['""', '“”', "''", '‘’']:
            quoted = re.findall(rf'{re.escape(qm[0])}([^{re.escape(qm[1])}]+?){re.escape(qm[1])}', text)
            for part in reversed(quoted):
                part = part.strip()
                if re.search(r'\d', part) and len(part) >= 4:
                    text = part
                    break
            if len(text) <= 50:
                break

    return text.strip(" \t\r\n：:;；")


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
            cn = _cn_field(fname)
            parts.append(f"{cn}={fs['min']}~{fs['max']}(均值{fs['avg']})")
        lines.append(f"{tname}({cn}): {'; '.join(parts)}")
    return "\n".join(lines) if lines else "无匹配数据"


def summarize_stream(user_query: str, tables: list, matched_fields: list, engine: DataQueryEngine):
    """
    第2次 LLM 调用：根据 LLM 选表 + 代码选字段，流式生成简要总结。
    """
    stats_text = extract_relevant_stats(tables, matched_fields, engine)
    user_message = f"数据:\n{stats_text}\n\n问题: {user_query}\n直接输出："
    try:
        raw = []
        for token in call_llm_stream(
            system_prompt=SUMMARY_BRIEF_PROMPT,
            user_message=user_message,
            temperature=0,
            max_tokens=150,
        ):
            raw.append(token)
        full = _strip_reasoning("".join(raw))
        if not full:
            full = _build_stats_fallback_summary(user_query, tables, matched_fields, engine)
        raw_text = "".join(raw)
        logger.info(f"LLM 总结原始: {raw_text[:100]}, 清洗后: {full[:100]}")
        yield full
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


# ==================== 塔机作业状态查询 ====================

def _resolve_tower_crane_name(value: str) -> tuple[str, str]:
    """按塔机名称解析 deviceSN，支持自然语言中的名称片段。"""
    text = re.sub(r"\s+", "", str(value or ""))
    if text in TOWER_CRANE_NAME_TO_SN:
        return text, TOWER_CRANE_NAME_TO_SN[text]
    for name, device_sn in TOWER_CRANE_NAME_TO_SN.items():
        if name in text or text in name:
            return name, device_sn
    raise ValueError(
        "未找到塔机名称，请使用：" + "、".join(TOWER_CRANE_NAME_TO_SN)
    )


def _validate_tower_crane_time(value: str, field_name: str) -> str:
    """校验第三方接口要求的时间格式，允许日终 24:00:00。"""
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2} (?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d|\d{4}-\d{2}-\d{2} 24:00:00",
        value,
    ):
        raise ValueError(f"{field_name} 必须使用 YYYY-MM-DD HH:MM:SS 格式")
    return value


def _default_tower_crane_time_range() -> tuple[str, str]:
    """默认查询最近 24 小时，避免查询范围无限扩大。"""
    end = datetime.now()
    start = end - timedelta(days=1)
    return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")


def query_tower_crane_work_status(
    device_name: str, start_time: Optional[str] = None, end_time: Optional[str] = None,
) -> dict:
    """查询指定塔机的历史作业记录并生成状态摘要。"""
    resolved_name, device_sn = _resolve_tower_crane_name(device_name)
    default_start, default_end = _default_tower_crane_time_range()
    start_time = _validate_tower_crane_time(start_time or default_start, "startTime")
    end_time = _validate_tower_crane_time(end_time or default_end, "endTime")

    try:
        response = requests.post(
            TOWER_CRANE_WORK_CYCLE_URL,
            json={"deviceSN": device_sn, "startTime": start_time, "endTime": end_time},
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=TOWER_CRANE_REQUEST_TIMEOUT,
            verify=TOWER_CRANE_REQUEST_VERIFY_TLS,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"塔机数据接口请求失败: {exc}") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"塔机数据接口返回非 JSON（HTTP {response.status_code}）") from exc

    if response.status_code != 200 or not payload.get("success"):
        message = payload.get("msg") or f"HTTP {response.status_code}"
        raise RuntimeError(f"塔机数据接口查询失败: {message}")

    cycles = payload.get("data") or []
    if not isinstance(cycles, list):
        raise RuntimeError("塔机数据接口返回的 data 不是数组")
    latest = max(cycles, key=lambda item: item.get("endTime") or item.get("startTime") or "") if cycles else None
    return {
        "device_name": resolved_name,
        "device_sn": device_sn,
        "start_time": start_time,
        "end_time": end_time,
        "status": "有作业记录" if cycles else "查询范围内无作业记录",
        "work_cycle_count": len(cycles),
        "latest_cycle": latest,
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

        if path == "/api/v1/taji/work-status":
            self._handle_tower_crane_work_status()
        elif path == "/api/v1/intent/analyze":
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

    def _handle_tower_crane_work_status(self):
        """按塔机名称查询历史作业状态，不经过 LLM。"""
        try:
            body = self._read_body()
            device_name = (
                body.get("device_name")
                or body.get("deviceName")
                or body.get("name")
                or body.get("query")
            )
            if not device_name:
                self._send_json({
                    "error": "请提供 device_name，例如：向阳村4#塔机",
                    "available_devices": list(TOWER_CRANE_NAME_TO_SN),
                }, 400)
                return

            result = query_tower_crane_work_status(
                device_name=device_name,
                start_time=body.get("startTime") or body.get("start_time"),
                end_time=body.get("endTime") or body.get("end_time"),
            )
            self._send_json({"success": True, "data": result})
        except ValueError as exc:
            self._send_json({"success": False, "error": str(exc)}, 400)
        except RuntimeError as exc:
            logger.warning(f"塔机作业状态查询失败: {exc}")
            self._send_json({"success": False, "error": str(exc)}, 502)

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

            # ---- 闸门调度方案：确定性估算输出，禁止进入普通 LLM 分类/总结 ----
            if is_gate_opening_plan_query(user_query):
                params = extract_gate_plan_parameters(user_query)
                monitoring_context = build_gate_dispatch_monitoring_context(self.engine)
                system_prompt, llm_prompt = build_llm_gate_dispatch_prompt(
                    user_query, params, monitoring_context,
                )
                try:
                    summary = call_llm_sync(
                        system_prompt=system_prompt,
                        user_message=llm_prompt,
                        temperature=0.2,
                        max_tokens=5000,
                        timeout=120,
                    ).strip()
                except Exception as exc:
                    summary = (
                        "闸门调度分析服务不可用，未生成模型建议。\n"
                        f"监测数据范围：{monitoring_context['data_scope']}。\n"
                        "缺失数据：" + "、".join(monitoring_context["missing_data"]) + "。\n"
                        "请检查LLM服务和兴各庄闸实时监测接入后重试。"
                    )
                    logger.error(f"闸门调度LLM分析失败: {exc}")
                self._send_sse_done(round(time.time() - start_time, 2), summary)
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
                # LLM 分类失败：用关键词匹配兜底，避免全表查询导致上下文过大
                kw_match = match_intent(user_query, self.engine)
                tables = kw_match.get("tables", [])
                if not tables:
                    tables = list(self.engine.all_stats.keys())
                logger.info(f"意图分类失败，关键词兜底: tbls={tables}")

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
        total_time = round(time.time() - start_time, 2)
        self._send_sse_done(total_time, full_text.strip())

    def _stream_joined(self, tables: list, user_query: str, start_time: float):
        """多表 JOIN 后用 summarize_stream 生成总结（统一走 _strip_reasoning 后处理）"""
        summary = ""
        for piece in summarize_stream(user_query, tables, [], self.engine):
            summary = piece
        total_time = round(time.time() - start_time, 2)
        self._send_sse_done(total_time, summary.strip())

    def _stream_single_table(self, user_query: str, table: str, matched_fields: list, start_time: float):
        """单表查询流式输出"""
        summary = ""
        for piece in summarize_stream(user_query, [table] if table else [], matched_fields, self.engine):
            summary = piece
        total_time = round(time.time() - start_time, 2)
        self._send_sse_done(total_time, summary.strip())

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
    function cleanSummary(text) {
        return (text || '').replace(/\s+/g, ' ').trim();
    }
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
                        const cleaned = cleanSummary(data.token);
                        if (cleaned) {
                            summaryEl.textContent += cleaned;
                        }
                    } else if (data.summary !== undefined) {
                        result.style.display = '';
                        ld.classList.remove('active');
                        summaryEl.textContent = cleanSummary(data.summary);
                        timeEl.textContent = '⏱ ' + data.elapsed_seconds + '秒';
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
