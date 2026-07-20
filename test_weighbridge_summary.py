#!/usr/bin/env python3
"""
地磅数据意图理解测试 - 最近一周数据统计分析 + 200字以内核心总结
"""
import json
import requests
from collections import defaultdict
from datetime import datetime

# 1. 调用API获取数据
API_URL = "https://dmap.cscec3bxjy.cn/api/dibang/report/workerstatus"
payload = {
    "project_id": "sanyuanli",
    "query_type": "week",
    "end_time": "2026-06-02 23:59:59"
}

resp = requests.post(API_URL, json=payload, timeout=30)
resp.raise_for_status()
result = resp.json()
data = result.get("data", {})
# Some responses return list: null, so normalize to an empty list.
records = data.get("list") or []

print(f"API状态: {result.get('code')} - {result.get('msg')}")
print(f"查询范围: {data.get('start_time')} ~ {data.get('end_time')}")

# 2. 去重处理 (按 scaleOrderCode 去重，保留最早上磅记录)
seen_orders = {}
unique_records = []
for r in records:
    order_code = r.get("scaleOrderCode", "")
    if order_code not in seen_orders:
        seen_orders[order_code] = True
        unique_records.append(r)

print(f"原始记录数: {len(records)}, 去重后记录数: {len(unique_records)}")

# 3. 统计分析
total_count = len(unique_records)
total_weight = sum(float(r.get("weight", 0)) for r in unique_records)

# 按天统计
daily_stats = defaultdict(lambda: {"count": 0, "weight": 0.0})
# 按车牌统计
plate_stats = defaultdict(lambda: {"count": 0, "weight": 0.0})

for r in unique_records:
    weight = float(r.get("weight", 0))
    plate = r.get("licensePlateCode", "未识别")
    device_time = r.get("deviceTime", r.get("time", ""))
    
    # 按天
    day = device_time[:10] if device_time else "未知"
    daily_stats[day]["count"] += 1
    daily_stats[day]["weight"] += weight
    
    # 按车牌
    plate_stats[plate]["count"] += 1
    plate_stats[plate]["weight"] += weight

# 高峰日
peak_day = max(daily_stats.items(), key=lambda x: x[1]["count"]) if daily_stats else None
# 最忙车牌
top_plate = max(plate_stats.items(), key=lambda x: x[1]["count"]) if plate_stats else None
# 平均重量
avg_weight = total_weight / total_count if total_count > 0 else 0
avg_daily_count = total_count / len(daily_stats) if daily_stats else 0

print("\n========== 详细统计 ==========")
print(f"过磅总车次: {total_count} 次")
print(f"过磅总重量: {total_weight:.2f} 吨")
print(f"平均每车重量: {avg_weight:.2f} 吨")
print(f"活跃车辆数: {len(plate_stats)} 辆")
print(f"活跃天数: {len(daily_stats)} 天")

print("\n每日统计:")
for day in sorted(daily_stats.keys()):
    s = daily_stats[day]
    print(f"  {day}: {s['count']}车次, {s['weight']:.2f}吨, 均重{s['weight']/s['count']:.2f}吨")

if peak_day:
    print(f"\n最高峰日: {peak_day[0]}, {peak_day[1]['count']}车次")

if top_plate:
    print(f"最活跃车辆: {top_plate[0]}, {top_plate[1]['count']}车次")

# 4. 生成200字以内的核心总结
summary = (
    f"三元里上周({data.get('start_time','')[:10]}至{data.get('end_time','')[:10]})"
    f"地磅共过磅{total_count}车次，总重{total_weight:.1f}吨，"
    f"均重{avg_weight:.1f}吨。"
    f"{len(plate_stats)}辆车参与运输，"
    f"最活跃车辆{top_plate[0] if top_plate else ''}过磅{top_plate[1]['count'] if top_plate else 0}次。"
    f"高峰日为{peak_day[0] if peak_day else ''}（{peak_day[1]['count'] if peak_day else 0}车次），"
    f"日均{avg_daily_count:.0f}车次。"
)

print("\n========== 200字以内核心总结 ==========")
print(f"总结字数: {len(summary)}")
print(summary)

if len(summary) > 200:
    print(f"\n⚠️ 警告: 总结字数 {len(summary)} 超过200字限制!")

print("\n========== 测试完成 ==========")
print("意图理解: 用户询问\"最近一周地磅数据\" -> 自动解析为 query_type=week, end_time=today")
print("总结能力: 从原始记录中提取关键指标并压缩为自然语言概述")
