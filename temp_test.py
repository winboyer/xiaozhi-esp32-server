import re
with open('test_staff_safe_query_server.py', 'r') as f:
    content = f.read()

# Match from 'from datetime import' to the line before '# 生成口语化摘要'
old = re.compile(
    r'(    from datetime import datetime, timedelta\n)'
    r'(.*?)'
    r'(    # 生成口语化摘要)',
    re.DOTALL
)

new = '''    from datetime import datetime, timedelta

    start_time = time.time()
    now = datetime.now()

    # 一次无参 API 调用获取所有设备的全量数据（传 device_number 会导致 records 为 null）
    raw_result = query_elevator_raw(\"elevator_traffic\")
    if not raw_result.get(\"success\"):
        return {\"success\": False, \"error\": raw_result.get(\"error\", \"电梯当前笼内人数查询失败\"), \"elapsed_seconds\": round(time.time() - start_time, 2)}

    api_data = raw_result.get(\"data\", {})
    all_records = None
    if isinstance(api_data, dict):
        inner = api_data.get(\"data\")
        if isinstance(inner, dict):
            std = inner.get(\"std\")
            if isinstance(std, dict):
                all_records = std.get(\"records\")
            if all_records is None:
                all_records = inner.get(\"records\")
        elif isinstance(inner, list):
            all_records = inner
        if all_records is None:
            all_records = api_data.get(\"records\")

    if not isinstance(all_records, list) or len(all_records) == 0:
        return {\"success\": False, \"error\": \"未获取到电梯 records 数据\", \"elapsed_seconds\": round(time.time() - start_time, 2)}

    def _safe_get(d, *keys):
        for k in keys:
            v = d.get(k)
            if v is not None:
                return v
        return None

    # 按 DeviceNumber 分组，每组取最新一条
    device_groups = {}
    for r in all_records:
        if not isinstance(r, dict):
            continue
        dn = r.get(\"DeviceNumber\", \"\")
        if not dn:
            continue
        minute = r.get(\"Minute\", \"\")
        if dn not in device_groups or minute > device_groups[dn].get(\"Minute\", \"\"):
            device_groups[dn] = r

    device_results = []
    total_people = 0.0

    for dev in ELEVATOR_DEVICES:
        dn = dev[\"device_number\"]
        building = dev[\"building\"]
        cage = dev[\"cage\"]
        label = f\"{building}{cage}\"

        latest = device_groups.get(dn)

        if latest is not None:
            avg_person_num = _safe_get(latest, \"AvgPersonNum\", \"avgPersonNum\", \"avg_person_num\")
            record_minute = _safe_get(latest, \"Minute\", \"minute\")
            max_person_num = _safe_get(latest, \"MaxPersonNum\", \"maxPersonNum\", \"max_person_num\")
            min_person_num = _safe_get(latest, \"MinPersonNum\", \"minPersonNum\", \"min_person_num\")
            sample_count = _safe_get(latest, \"SampleCount\", \"sampleCount\", \"sample_count\")

            if avg_person_num is not None:
                try:
                    avg_person_num = float(avg_person_num)
                except (ValueError, TypeError):
                    avg_person_num = None
            if max_person_num is not None and not isinstance(max_person_num, (int, float)):
                try:
                    max_person_num = int(max_person_num)
                except (ValueError, TypeError):
                    pass
            if min_person_num is not None and not isinstance(min_person_num, (int, float)):
                try:
                    min_person_num = int(min_person_num)
                except (ValueError, TypeError):
                    pass
            if sample_count is not None and not isinstance(sample_count, (int, float)):
                try:
                    sample_count = int(sample_count)
                except (ValueError, TypeError):
                    pass

            if avg_person_num is not None:
                total_people += avg_person_num
                device_results.append({
                    \"building\": building,
                    \"cage\": cage,
                    \"label\": label,
                    \"DeviceNumber\": dn,
                    \"AvgPersonNum\": avg_person_num,
                    \"MaxPersonNum\": max_person_num,
                    \"MinPersonNum\": min_person_num,
                    \"SampleCount\": sample_count,
                    \"Minute\": record_minute,
                    \"status\": \"ok\",
                })
            else:
                device_results.append({
                    \"building\": building, \"cage\": cage, \"label\": label,
                    \"DeviceNumber\": dn,
                    \"AvgPersonNum\": None, \"MaxPersonNum\": None, \"MinPersonNum\": None,
                    \"SampleCount\": None, \"Minute\": None,
                    \"status\": \"no_data\",
                })
        else:
            device_results.append({
                \"building\": building, \"cage\": cage, \"label\": label,
                \"DeviceNumber\": dn,
                \"AvgPersonNum\": None, \"MaxPersonNum\": None, \"MinPersonNum\": None,
                \"SampleCount\": None, \"Minute\": None,
                \"status\": \"no_data\",
            })

    # 生成口语化摘要'''

result = old.sub(r'\1' + new + r'\3', content, count=1)
if result != content:
    with open('test_staff_safe_query_server.py', 'w') as f:
        f.write(result)
    print('OK: replaced')
else:
    print('FAIL: pattern not matched')
