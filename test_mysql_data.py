"""
MySQL 数据库数据读取模块
解析 monitoring_standard.sql 文件，提取表结构和数据记录。
支持读取以下8张监控数据表：
  - deform_crack_meter     (测缝计)
  - deform_gnss            (GNSS)
  - deform_pore_pressure   (渗压计)
  - deform_soil_pressure   (土压力计)
  - deform_total_station   (全站仪)
  - flow_array_radar       (阵列式雷达流量计)
  - flow_radar_level       (雷达液位计)
  - flow_tof_meter         (超声波时差流量计)
"""

import re
import json
from datetime import datetime
from decimal import Decimal


# ============================================================
# 1. SQL 文件解析
# ============================================================

def parse_sql_file(filepath: str) -> dict:
    """
    解析 MySQL 导出 SQL 文件，提取所有表的 CREATE TABLE 和 INSERT INTO 语句。
    
    Returns:
        dict: {
            "table_name": {
                "columns": [
                    {"name": "id", "type": "bigint", "comment": "..."},
                    ...
                ],
                "rows": [
                    [val1, val2, ...],  # 每行数据按列顺序排列
                    ...
                ],
                "column_names": ["id", "eid", ...],
            },
            ...
        }
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    tables = {}
    
    # ---- 提取 CREATE TABLE 语句 ----
    create_pattern = re.compile(
        r'CREATE TABLE `(\w+)`\s*\((.+?)\)\s*ENGINE',
        re.DOTALL
    )
    for match in create_pattern.finditer(content):
        table_name = match.group(1)
        col_defs_block = match.group(2)
        columns = _parse_column_definitions(col_defs_block)
        tables[table_name] = {
            'columns': columns,
            'column_names': [c['name'] for c in columns],
            'rows': [],
        }
    
    # ---- 提取 INSERT INTO 语句 ----
    insert_pattern = re.compile(
        r"INSERT INTO `(\w+)`\s+VALUES\s*(\(.+?\))\s*;",
        re.DOTALL
    )
    for match in insert_pattern.finditer(content):
        table_name = match.group(1)
        if table_name not in tables:
            continue
        values_block = match.group(2)
        rows = _parse_insert_values(values_block)
        tables[table_name]['rows'].extend(rows)
    
    return tables


def _parse_column_definitions(defs_block: str) -> list:
    """
    从 CREATE TABLE 列定义中提取字段名、类型和注释。
    排除 INDEX / PRIMARY KEY / UNIQUE KEY 等约束定义。
    """
    columns = []
    # 先按逗号拆分行，但需要处理括号嵌套
    lines = _split_top_level(defs_block, ',')
    for line in lines:
        stripped = line.strip()
        # 跳过约束定义行（PRIMARY KEY, INDEX, UNIQUE KEY 等）
        if re.match(
            r'^(PRIMARY\s+KEY|INDEX|UNIQUE\s+KEY|KEY|CONSTRAINT|FULLTEXT|SPATIAL|CHECK)',
            stripped, re.IGNORECASE
        ):
            continue
        # 匹配列定义: `col_name` col_type ... COMMENT 'comment_text'
        m = re.match(
            r"`(\w+)`\s+"                          # 字段名
            r"(\w+(?:\([^)]*\))?)"                 # 类型（如 bigint, decimal(15,6), varchar(255)）
            r"(?:.*?)?"                             # 跳过中间内容
            r"(?:COMMENT\s+'([^']*)')?",           # 注释（可选）
            stripped
        )
        if m:
            col_name = m.group(1)
            col_type = m.group(2)
            comment = m.group(3)
            columns.append({
                'name': col_name,
                'type': col_type,
                'comment': comment if comment else '',
            })
    return columns


def _split_top_level(text: str, delimiter: str) -> list:
    """
    按分隔符拆分字符串，但忽略括号内的分隔符。
    用于正确拆分 CREATE TABLE 中括号嵌套的列定义。
    """
    parts = []
    current = ''
    depth = 0
    for ch in text:
        if ch == '(' and depth >= 0:
            depth += 1
            current += ch
        elif ch == ')' and depth > 0:
            depth -= 1
            current += ch
        elif ch == delimiter and depth == 0:
            parts.append(current)
            current = ''
        else:
            current += ch
    if current.strip():
        parts.append(current)
    return parts


def _parse_insert_values(values_block: str) -> list:
    """
    解析 INSERT ... VALUES 行数据。
    处理多个值元组: (1, 'xxx', ...), (2, 'yyy', ...),
    """
    rows = []
    # 匹配每个值元组: (...)
    tuple_pattern = re.compile(r'\(([^()]*(?:\([^()]*\)[^()]*)*)\)')
    for tm in tuple_pattern.finditer(values_block):
        raw = tm.group(1)
        values = _split_values(raw)
        parsed = [_convert_value(v) for v in values]
        rows.append(parsed)
    return rows


def _split_values(raw: str) -> list:
    """
    将 VALUES 元组内的字符串拆分为各个字段值。
    处理引号内逗号、嵌套括号等情况。
    """
    values = []
    current = ''
    in_quote = False
    bracket_depth = 0
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch == "'" and not in_quote:
            in_quote = True
            current += ch
        elif ch == "'" and in_quote:
            # 检查是否为转义引号 ''
            if i + 1 < len(raw) and raw[i + 1] == "'":
                current += "''"
                i += 1
            else:
                in_quote = False
                current += ch
        elif ch == '[' and not in_quote:
            bracket_depth += 1
            current += ch
        elif ch == ']' and not in_quote:
            bracket_depth -= 1
            current += ch
        elif ch == ',' and not in_quote and bracket_depth == 0:
            values.append(current.strip())
            current = ''
        else:
            current += ch
        i += 1
    if current.strip():
        values.append(current.strip())
    return values


def _convert_value(val: str):
    """
    将 SQL 字符串值转换为 Python 类型。
    """
    v = val.strip()
    # NULL
    if v.upper() == 'NULL':
        return None
    # 字符串（单引号包围）
    if v.startswith("'") and v.endswith("'"):
        inner = v[1:-1]
        # 还原转义单引号
        inner = inner.replace("''", "'")
        return inner
    # JSON 数组
    if v.startswith('['):
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return v
    # 整数
    try:
        return int(v)
    except ValueError:
        pass
    # 浮点数 / Decimal
    try:
        # 保留精度用字符串（或转 Decimal）
        return float(v)
    except ValueError:
        pass
    return v


# ============================================================
# 2. 数据查询与导出
# ============================================================

def get_table_schema(tables: dict, table_name: str) -> list:
    """获取指定表的字段定义列表。"""
    if table_name not in tables:
        raise KeyError(f"表 '{table_name}' 不存在。可用表: {list(tables.keys())}")
    return tables[table_name]['columns']


def get_table_data(tables: dict, table_name: str) -> list:
    """获取指定表的所有数据行（每行为字典列表）。"""
    if table_name not in tables:
        raise KeyError(f"表 '{table_name}' 不存在。可用表: {list(tables.keys())}")
    info = tables[table_name]
    col_names = info['column_names']
    return [dict(zip(col_names, row)) for row in info['rows']]


def get_all_table_names(tables: dict) -> list:
    """获取所有表名。"""
    return list(tables.keys())


def print_schema_summary(tables: dict):
    """打印所有表的字段摘要。"""
    print("=" * 80)
    print("数据库表结构概览 (monitoring_standard)")
    print("=" * 80)
    for tname, info in tables.items():
        cols = info['columns']
        row_count = len(info['rows'])
        print(f"\n📋 表: {tname}  (记录数: {row_count})")
        print("-" * 60)
        for col in cols:
            comment_str = f" -- {col['comment']}" if col['comment'] else ""
            print(f"    {col['name']:25s} {col['type']:18s}{comment_str}")


def print_table_data(tables: dict, table_name: str, limit: int = 10):
    """打印指定表的数据（前 N 行）。"""
    info = tables[table_name]
    dict_rows = get_table_data(tables, table_name)
    
    print(f"\n📊 表 {table_name} 数据 (共 {len(dict_rows)} 条，显示前 {limit} 条):")
    print("-" * 80)
    
    for i, row in enumerate(dict_rows[:limit]):
        print(f"\n--- 记录 {i + 1} ---")
        for key, val in row.items():
            print(f"  {key:25s}: {val}")


# ============================================================
# 3. 数据提取工具函数
# ============================================================

def extract_unique_devices(tables: dict, table_name: str) -> list:
    """
    提取指定表中所有唯一的设备信息（按 eid 去重）。
    返回每个设备的：eid, equip_name, install_addr, lon, lat, alt
    """
    data = get_table_data(tables, table_name)
    seen = set()
    devices = []
    for row in data:
        eid = row.get('eid')
        if eid and eid not in seen:
            seen.add(eid)
            devices.append({
                'eid': eid,
                'equip_name': row.get('equip_name'),
                'install_addr': row.get('install_addr'),
                'lon': row.get('lon'),
                'lat': row.get('lat'),
                'alt': row.get('alt'),
            })
    return devices


def extract_field_values(tables: dict, table_name: str, field_name: str) -> list:
    """提取指定表中某个字段的所有值（非空）。"""
    data = get_table_data(tables, table_name)
    return [row[field_name] for row in data if row.get(field_name) is not None]


def filter_by_eid(tables: dict, table_name: str, eid: str) -> list:
    """按设备编号筛选数据。"""
    data = get_table_data(tables, table_name)
    return [row for row in data if row.get('eid') == eid]


def filter_by_timestamp_range(tables: dict, table_name: str,
                               start_ts: int, end_ts: int) -> list:
    """按时间戳范围筛选数据。"""
    data = get_table_data(tables, table_name)
    return [row for row in data
            if row.get('dt') is not None and start_ts <= row['dt'] <= end_ts]


def convert_timestamp(ts: int) -> str:
    """将 Unix 时间戳转换为可读字符串。"""
    if ts is None:
        return None
    return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')


# ============================================================
# 4. 主程序入口
# ============================================================

if __name__ == '__main__':
    # SQL 文件路径
    sql_filepath = '/Users/jinyfeng/Downloads/monitoring_standard.sql'
    
    print("正在解析 SQL 文件...")
    tables = parse_sql_file(sql_filepath)
    
    print(f"成功解析 {len(tables)} 张表: {get_all_table_names(tables)}\n")
    
    # ---- 打印表结构概览 ----
    print_schema_summary(tables)
    
    # ---- 打印每张表的数据样例 ----
    for tname in get_all_table_names(tables):
        print_table_data(tables, tname, limit=30)
    
    # ---- 示例：提取 deform_crack_meter 表中 sf_crack_width 字段 ----
    print("\n" + "=" * 80)
    print("示例：提取 deform_crack_meter 表的 sf_crack_width (裂缝宽度) 字段")
    print("-" * 40)
    crack_widths = extract_field_values(tables, 'deform_crack_meter', 'sf_crack_width')
    print(f"裂缝宽度值: {crack_widths}")
    print(f"最大裂缝宽度: {max(crack_widths):.3f} mm")
    print(f"最小裂缝宽度: {min(crack_widths):.3f} mm")
    
    # ---- 示例：按设备编号筛选 ----
    print("\n" + "=" * 80)
    print("示例：筛选设备 SF-equip001 的数据")
    print("-" * 40)
    eq1_data = filter_by_eid(tables, 'deform_crack_meter', 'SF-equip001')
    for row in eq1_data:
        print(f"  时间: {convert_timestamp(row['dt'])}, "
              f"裂缝宽度: {row['sf_crack_width']} mm, "
              f"温度: {row['sf_temp']}°C")
    
    # ---- 示例：提取所有唯一设备 ----
    print("\n" + "=" * 80)
    print("示例：deform_gnss 表中的唯一设备列表")
    print("-" * 40)
    devices = extract_unique_devices(tables, 'deform_gnss')
    for dev in devices:
        print(f"  {dev['eid']}: {dev['install_addr']} "
              f"({dev['lon']}, {dev['lat']})")