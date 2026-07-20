import pymysql
conn = pymysql.connect(host='127.0.0.1', user='root', password='123456', database='xiaozhi_esp32_server')
cursor = conn.cursor()

# 检查 ChatGLMLLM 配置
cursor.execute("SELECT id, model_code, config_json FROM ai_model_config WHERE id = 'LLM_ChatGLMLLM' ")
row = cursor.fetchone()
if row:
    print(f'=== ChatGLMLLM ===')
    print(f'ID: {row[0]}, Code: {row[1]}')
    print(f'Config: {row[2]}')

# 检查所有 LLM 类型的配置
cursor.execute("SELECT id, model_code, config_json FROM ai_model_config WHERE model_type = 'LLM' ")
print()
print('=== All LLM Models ===')
for row in cursor.fetchall():
    import json
    cfg = json.loads(row[2])
    url = cfg.get('base_url', cfg.get('url', 'N/A'))
    print(f'{row[0]} | {row[1]} | url={url} | api_key={"SET" if cfg.get("api_key", "") else "EMPTY"}')

# 检查 sys_params 中 selected_module 或 device 配置
cursor.execute("SELECT param_code, param_value FROM sys_params WHERE param_code LIKE '%selected%' OR param_code LIKE '%llm%' OR param_code LIKE '%LLM%' LIMIT 20")
print()
print('=== Sys Params ===')
for row in cursor.fetchall():
    print(f'{row[0]} = {row[1][:200] if len(row[1]) > 200 else row[1]}')

conn.close()