"""查询管理端 LLM 配置并与本地 config.yaml 对比验证"""
import asyncio
import json
import sys
import os
from urllib.parse import urlparse

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'main/xiaozhi-server'))

import yaml
import httpx

# ==================== 本地 config.yaml 配置 ====================
LOCAL_CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'main/xiaozhi-server/config.yaml')
CUSTOM_CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'main/xiaozhi-server/data/.config.yaml')

# 管理员 API 密钥
MANAGER_API_URL = "http://127.0.0.1:8001/xiaozhi"
MANAGER_API_SECRET = "a721d626-33a0-43ad-b82f-2af9b210f651"

# ==================== 读取本地配置 ====================
def load_local_llm_config():
    """从 config.yaml 读取 LLM 配置"""
    with open(LOCAL_CONFIG_PATH, 'r', encoding='utf-8') as f:
        local = yaml.safe_load(f)

    selected = local.get("selected_module", {}).get("LLM", "")
    llm_configs = local.get("LLM", {})
    llm_cfg = llm_configs.get(selected, {})

    return {
        "selected": selected,
        "model_name": llm_cfg.get("model_name", ""),
        "url": llm_cfg.get("url") or llm_cfg.get("base_url", ""),
        "api_key": llm_cfg.get("api_key", ""),
        "type": llm_cfg.get("type", ""),
    }

# ==================== 查询管理端配置 ====================
async def fetch_manager_config():
    """从管理端 API 获取服务端配置"""
    client = httpx.AsyncClient(
        base_url=MANAGER_API_URL,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {MANAGER_API_SECRET}",
        },
        timeout=30,
    )

    try:
        resp = await client.post("/config/server-base")
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            return {"error": f"API 返回错误: {data.get('msg', '未知')}", "code": data.get("code")}
        return data.get("data", {})
    except httpx.ConnectError:
        return {"error": f"无法连接到管理端 {MANAGER_API_URL}，请确认管理端服务是否已启动"}
    except Exception as e:
        return {"error": str(e)}
    finally:
        await client.aclose()

# ==================== 获取管理端 LLM 配置 ====================
def extract_manager_llm_config(config_data):
    """从管理端返回数据中提取 LLM 配置"""
    selected = config_data.get("selected_module", {}).get("LLM", "")
    llm_configs = config_data.get("LLM", {})
    llm_cfg = llm_configs.get(selected, {})

    intent_config = config_data.get("Intent", {})
    intent_llm = intent_config.get("intent_llm", {}).get("llm", "")

    return {
        "selected": selected,
        "model_name": llm_cfg.get("model_name", ""),
        "url": llm_cfg.get("url") or llm_cfg.get("base_url", ""),
        "api_key": llm_cfg.get("api_key", ""),
        "type": llm_cfg.get("type", ""),
        "intent_llm": intent_llm,
    }

# ==================== 验证分析 ====================
def validate_configs(local, manager):
    """对比本地与管理端 LLM 配置，输出分析结果"""

    print("\n" + "=" * 70)
    print("                    LLM 配置对比分析")
    print("=" * 70)

    # ---- 1. 显示双方配置 ----
    print(f"\n{'─' * 70}")
    print(f"📁 本地 config.yaml LLM 配置")
    print(f"{'─' * 70}")
    print(f"   selected_module:    {local['selected']}")
    print(f"   model_name:         {local['model_name']}")
    print(f"   url/base_url:       {local['url']}")
    print(f"   api_key:            {local['api_key'][:12]}...{local['api_key'][-4:]}"
          if len(local['api_key']) > 16 else f"   api_key:            {local['api_key']}")
    print(f"   type:               {local['type']}")

    print(f"\n{'─' * 70}")
    print(f"🌐 管理端 API 返回的 LLM 配置")
    print(f"{'─' * 70}")
    if "error" in manager:
        print(f"   ⚠️  管理端不可用: {manager['error']}")
        print(f"\n   → 结论: 管理端无法访问，将使用本地 config.yaml 完全生效")
        return
    print(f"   selected_module:    {manager['selected']}")
    print(f"   model_name:         {manager['model_name']}")
    print(f"   url/base_url:       {manager['url']}")
    api_key = manager.get('api_key', '')
    print(f"   api_key:            {api_key[:12]}...{api_key[-4:]}" if len(api_key) > 16 else f"   api_key:            {api_key}")
    print(f"   type:               {manager.get('type', '')}")
    print(f"   intent_llm:         {manager.get('intent_llm', '(未设置)')}")

    # ---- 2. 验证管理端 api_key 有效性 ----
    print(f"\n{'─' * 70}")
    print(f"🔍 有效性验证")
    print(f"{'─' * 70}")

    api_key = manager.get('api_key', '')
    is_placeholder = "你" in api_key or "your" in api_key.lower()
    is_empty = not api_key

    if is_empty:
        print(f"  ❌ 管理端 api_key 为空")
        key_valid = False
    elif is_placeholder:
        print(f'  ❌ 管理端 api_key 为占位符（包含"你"或"your"）')
        key_valid = False
    else:
        print(f"  ✅ 管理端 api_key 有效")
        key_valid = True

    # ---- 3. 模型名对比 ----
    print(f"\n{'─' * 70}")
    print(f"🔍 模型名对比")
    print(f"{'─' * 70}")

    local_model = local['selected']
    manager_model = manager['selected']
    model_match = local_model == manager_model

    if model_match:
        print(f"  ✅ 模型名一致: 都是 {local_model}")
    else:
        print(f"  ❌ 模型名不一致:")
        print(f"     本地: {local_model}")
        print(f"     管理端: {manager_model}")

    # ---- 4. URL 域名对比 ----
    print(f"\n{'─' * 70}")
    print(f"🔍 URL 域名对比")
    print(f"{'─' * 70}")

    local_url = local['url']
    manager_url = manager['url']

    local_domain = urlparse(local_url).netloc if local_url else ""
    manager_domain = urlparse(manager_url).netloc if manager_url else ""

    print(f"  本地 URL 域名:     {local_domain or '(空)'}")
    print(f"  管理端 URL 域名:   {manager_domain or '(空)'}")

    if not manager_domain:
        print(f"  ⚠️  管理端 URL 为空")
        url_match = False
    elif local_domain == manager_domain:
        print(f"  ✅ URL 域名一致")
        url_match = True
    else:
        print(f"  ❌ URL 域名不一致！管理端数据可能过期")
        url_match = False

    # ---- 5. 综合判定 ----
    print(f"\n{'=' * 70}")
    print(f"📊 综合判定（模拟 config_loader.py 回退逻辑）")
    print(f"{'=' * 70}")

    should_fallback = False
    reasons = []

    if not key_valid:
        should_fallback = True
        reasons.append("管理端 api_key 无效")

    if key_valid and not model_match:
        should_fallback = True
        reasons.append(f"管理端模型 ({manager_model}) 与本地 ({local_model}) 不一致")

    if key_valid and model_match and not url_match:
        should_fallback = True
        reasons.append(f"管理端 URL 域名 ({manager_domain}) 与本地 ({local_domain}) 不一致")

    if should_fallback:
        print(f"  🔄 将回退到本地 config.yaml")
        for r in reasons:
            print(f"     原因: {r}")
        print(f"\n  ✅ 最终生效的 LLM 配置: 本地 {local['selected']}")
        print(f"     model: {local['model_name']}")
        print(f"     url:   {local_domain}")
    else:
        print(f"  ✅ 管理端配置有效且一致，将使用管理端配置")
        print(f"     最终生效: {manager['selected']} @ {manager_domain}")

    # ---- 6. 额外信息 ----
    print(f"\n{'─' * 70}")
    print(f"📋 管理端完整 LLM 配置列表")
    print(f"{'─' * 70}")

    # 需要重新获取完整数据
    return should_fallback, reasons

# ==================== 查询管理端完整 LLM 列表 ====================
async def fetch_full_manager_llm_list(config_data):
    """显示管理端返回的所有 LLM 提供者"""
    llm_configs = config_data.get("LLM", {})
    print(f"\n  管理端已配置的 LLM 提供者:")
    for name, cfg in llm_configs.items():
        if isinstance(cfg, dict):
            key = cfg.get("api_key", "")
            key_status = "✅ 有效" if key and "你" not in key and "your" not in key.lower() else "❌ 无效"
            print(f"    • {name}: type={cfg.get('type', '')}, "
                  f"model={cfg.get('model_name', '')}, "
                  f"url={cfg.get('url', cfg.get('base_url', ''))}, "
                  f"api_key={key_status}")


async def main():
    print("=" * 70)
    print("  管理端 vs 本地 LLM 配置对比验证工具")
    print("=" * 70)

    # 1. 读取本地配置
    local_llm = load_local_llm_config()
    print(f"\n✅ 已加载本地 config.yaml LLM 配置")

    # 2. 查询管理端配置
    print(f"⏳ 正在连接管理端 {MANAGER_API_URL} ...")
    manager_data = await fetch_manager_config()

    if "error" in manager_data:
        # 管理端不可用
        validate_configs(local_llm, manager_data)
        return

    print(f"✅ 管理端配置获取成功")
    
    # 3. 提取管理端 LLM 配置
    manager_llm = extract_manager_llm_config(manager_data)

    # 4. 执行对比验证
    validate_configs(local_llm, manager_llm)

    # 5. 显示管理端完整 LLM 列表
    await fetch_full_manager_llm_list(manager_data)

    print(f"\n{'=' * 70}")
    print(f"  分析完成")
    print(f"{'=' * 70}\n")

if __name__ == "__main__":
    asyncio.run(main())