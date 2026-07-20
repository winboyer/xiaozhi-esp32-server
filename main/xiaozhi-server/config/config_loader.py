import os
import asyncio
import yaml
from collections.abc import Mapping
from urllib.parse import urlparse
from config.manage_api_client import (
    init_service,
    get_server_config,
    get_agent_models,
    get_correct_words,
    DeviceNotFoundException,
    DeviceBindException,
)


def get_project_dir():
    """获取项目根目录"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/"


def read_config(config_path):
    with open(config_path, "r", encoding="utf-8") as file:
        config = yaml.safe_load(file)
    return config


def load_config():
    """加载配置文件"""
    from core.utils.cache.manager import cache_manager, CacheType

    # 检查缓存
    cached_config = cache_manager.get(CacheType.CONFIG, "main_config")
    if cached_config is not None:
        return cached_config

    default_config_path = get_project_dir() + "config.yaml"
    custom_config_path = get_project_dir() + "data/.config.yaml"

    # 加载默认配置
    default_config = read_config(default_config_path)
    custom_config = read_config(custom_config_path)

    if custom_config.get("manager-api", {}).get("url"):
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            # 如果已经在事件循环中，使用异步版本
            config = asyncio.run_coroutine_threadsafe(
                get_config_from_api_async(custom_config), loop
            ).result()
        except RuntimeError:
            # 如果不在事件循环中（启动时），创建新的事件循环
            config = asyncio.run(get_config_from_api_async(custom_config))
    else:
        # 合并配置
        config = merge_configs(default_config, custom_config)
    # 初始化目录
    ensure_directories(config)

    # 缓存配置
    cache_manager.set(CacheType.CONFIG, "main_config", config)
    return config


def _load_local_config_from_disk():
    """直接从磁盘加载本地 config.yaml，用于 manager-api 配置缺失时的回退"""
    local_path = os.path.join(get_project_dir(), "config.yaml")
    if os.path.exists(local_path):
        try:
            return yaml.safe_load(open(local_path, "r", encoding="utf-8"))
        except Exception:
            pass
    return {}


def _normalize_llm_module_name(name):
    """把管理端和本地配置里的 LLM 名称归一化到同一比较口径。"""
    if not name:
        return ""
    name = str(name).strip()
    return name[4:] if name.startswith("LLM_") else name


def _resolve_llm_config_entry(llm_configs, selected_name):
    """根据 selected_name 在 LLM 配置字典里找到实际条目。"""
    if not isinstance(llm_configs, Mapping):
        return "", {}

    if selected_name in llm_configs and isinstance(llm_configs[selected_name], dict):
        return selected_name, llm_configs[selected_name]

    normalized_selected = _normalize_llm_module_name(selected_name)
    if not normalized_selected:
        return "", {}

    for name, cfg in llm_configs.items():
        if isinstance(cfg, dict) and _normalize_llm_module_name(name) == normalized_selected:
            return name, cfg

    return "", {}


def _llm_module_names_match(left, right):
    return _normalize_llm_module_name(left) == _normalize_llm_module_name(right)


async def get_config_from_api_async(config, default_config=None):
    """从Java API获取配置（异步版本）
    
    如果管理端返回的 LLM 配置缺失或无效（api_key 为占位符），
    则参照 staff_safe_handler 的方式直接从磁盘读取本地 config.yaml 回退。
    """
    # 初始化API客户端
    init_service(config)

    # 获取服务器配置
    config_data = await get_server_config()
    if config_data is None:
        raise Exception("Failed to fetch server config from API")

    config_data["read_config_from_api"] = True
    config_data["manager-api"] = {
        "url": config["manager-api"].get("url", ""),
        "secret": config["manager-api"].get("secret", ""),
    }
    auth_enabled = config_data.get("server", {}).get("auth", {}).get("enabled", False)
    # server的配置以本地为准
    if config.get("server"):
        config_data["server"] = {
            "ip": config["server"].get("ip", ""),
            "port": config["server"].get("port", ""),
            "http_port": config["server"].get("http_port", ""),
            "vision_explain": config["server"].get("vision_explain", ""),
            "auth_key": config["server"].get("auth_key", ""),
        }
    config_data["server"]["auth"] = {"enabled": auth_enabled}
    # 如果服务器没有prompt_template，则从本地配置读取
    if not config_data.get("prompt_template"):
        config_data["prompt_template"] = config.get("prompt_template")

    # ---- 验证管理端 LLM 配置 ----
    # 参照 staff_safe_handler 的回退策略：
    # 如果管理端返回的 LLM 配置缺失或 api_key 无效，直接从磁盘读取本地 config.yaml
    remote_selected_raw = config_data.get("selected_module", {}).get("LLM", "")
    remote_selected, remote_llm_cfg = _resolve_llm_config_entry(
        config_data.get("LLM", {}), remote_selected_raw
    )
    if remote_selected and remote_selected != remote_selected_raw:
        config_data["selected_module"]["LLM"] = remote_selected
    remote_api_key = remote_llm_cfg.get("api_key", "")

    invalid_key = (
        not remote_api_key
        or "你" in str(remote_api_key)
        or "your" in str(remote_api_key).lower()
    )

    should_fallback = invalid_key
    fallback_reason = "api_key 无效"

    # 即使远程 api_key 有效，如果本地 config.yaml 里配置了不同的模型且有有效凭据，
    # 也应优先使用本地配置（与 staff_safe_handler 行为一致）
    if not should_fallback:
        local_cfg = _load_local_config_from_disk()
        local_selected_raw = local_cfg.get("selected_module", {}).get("LLM", "")
        local_selected, local_llm_cfg = _resolve_llm_config_entry(
            local_cfg.get("LLM", {}), local_selected_raw
        )
        local_key = local_llm_cfg.get("api_key", "")
        local_valid = (
            local_selected
            and local_key
            and "你" not in str(local_key)
            and "your" not in str(local_key).lower()
        )
        if local_valid and not _llm_module_names_match(local_selected, remote_selected):
            should_fallback = True
            fallback_reason = (
                f"远程模型 ({remote_selected_raw or remote_selected}) 与本地配置 "
                f"({local_selected_raw or local_selected}) 不一致"
            )
        elif local_valid and _llm_module_names_match(local_selected, remote_selected):
            # 模型名称一致时，验证远程 URL 域名是否与本地一致
            # 管理端可能存储了旧的/错误的 URL（如指向 bigmodel.cn 的 DeepSeekLLM）
            remote_url = remote_llm_cfg.get("url") or remote_llm_cfg.get("base_url", "")
            local_url = local_llm_cfg.get("url") or local_llm_cfg.get("base_url", "")
            if remote_url and local_url:
                remote_domain = urlparse(remote_url).netloc
                local_domain = urlparse(local_url).netloc
                if remote_domain and local_domain and remote_domain != local_domain:
                    should_fallback = True
                    fallback_reason = f"远程 URL 域名 ({remote_domain}) 与本地 ({local_domain}) 不一致，管理端数据可能过期"

    if should_fallback:
        # 直接从磁盘加载本地 config.yaml（与 staff_safe_handler 行为一致）
        local_cfg = _load_local_config_from_disk()
        local_llm = local_cfg.get("LLM", {})
        local_selected_raw = local_cfg.get("selected_module", {}).get("LLM", "")
        local_selected, _ = _resolve_llm_config_entry(local_llm, local_selected_raw)
        fallback_llm = None
        fallback_selected = None

        if local_selected and local_llm.get(local_selected):
            fb_key = local_llm[local_selected].get("api_key", "")
            if fb_key and "你" not in str(fb_key) and "your" not in str(fb_key).lower():
                fallback_llm = local_llm
                fallback_selected = local_selected
                fallback_source = f"本地 config.yaml → {local_selected}"

        # 如果 selected_module 里指定的没效，遍历所有 LLM 取第一个有效的
        if fallback_llm is None:
            for name, cfg in local_llm.items():
                if (
                    isinstance(cfg, dict)
                    and cfg.get("api_key")
                    and "你" not in str(cfg.get("api_key", ""))
                    and "your" not in str(cfg.get("api_key", "")).lower()
                ):
                    fallback_llm = local_llm
                    fallback_selected = name
                    fallback_source = f"本地 config.yaml → {name}"
                    break

        if fallback_llm and fallback_selected:
            config_data["LLM"] = fallback_llm
            config_data["selected_module"]["LLM"] = fallback_selected
            # 同步更新 Intent.intent_llm.llm（如果远程也设置了且不一致）
            intent_llm_remote = (
                config_data.get("Intent", {}).get("intent_llm", {}).get("llm", "")
            )
            if intent_llm_remote and intent_llm_remote != fallback_selected:
                if "Intent" not in config_data:
                    config_data["Intent"] = {}
                if "intent_llm" not in config_data["Intent"]:
                    config_data["Intent"]["intent_llm"] = {}
                config_data["Intent"]["intent_llm"]["llm"] = fallback_selected
            print(
                f"[config] 管理端 LLM ({remote_selected_raw or remote_selected}) {fallback_reason}，"
                f"回退到 {fallback_source}"
            )
        else:
            print(
                f"[config] 管理端 LLM ({remote_selected_raw or remote_selected}) {fallback_reason}，"
                f"且本地 config.yaml 中无可用回退配置"
            )

    # 统一意图识别使用的 llm，避免管理端历史配置把 intent_llm 切到其他提供商
    selected_llm = config_data.get("selected_module", {}).get("LLM", "")
    intent_selected = config_data.get("selected_module", {}).get("Intent", "")
    intent_cfg = config_data.get("Intent", {}).get(intent_selected, {})
    if isinstance(intent_cfg, dict) and intent_cfg.get("type") == "intent_llm":
        intent_llm_name = intent_cfg.get("llm", "")
        if selected_llm and intent_llm_name and not _llm_module_names_match(intent_llm_name, selected_llm):
            intent_cfg["llm"] = selected_llm
            print(
                f"[config] 管理端 intent_llm ({intent_llm_name}) 与当前主 LLM ({selected_llm}) 不一致，"
                f"已同步为主 LLM"
            )

    return config_data


async def get_private_config_from_api(config, device_id, client_id):
    """从Java API获取私有配置"""
    results = await asyncio.gather(
        get_agent_models(device_id, client_id, config["selected_module"]),
        get_correct_words(device_id),
        return_exceptions=True,
    )
    agent_result = results[0]
    correct_words = results[1] if not isinstance(results[1], Exception) else None

    # 抛出业务异常
    if isinstance(agent_result, DeviceNotFoundException):
        raise agent_result
    if isinstance(agent_result, DeviceBindException):
        raise agent_result

    private_config = agent_result if not isinstance(agent_result, Exception) else {}
    if correct_words:
        private_config["correct_words"] = correct_words
    return private_config


def ensure_directories(config):
    """确保所有配置路径存在"""
    dirs_to_create = set()
    project_dir = get_project_dir()  # 获取项目根目录
    # 日志文件目录
    log_dir = config.get("log", {}).get("log_dir", "tmp")
    dirs_to_create.add(os.path.join(project_dir, log_dir))

    # ASR/TTS模块输出目录
    for module in ["ASR", "TTS"]:
        if config.get(module) is None:
            continue
        for provider in config.get(module, {}).values():
            output_dir = provider.get("output_dir", "")
            if output_dir:
                dirs_to_create.add(output_dir)

    # 根据selected_module创建模型目录
    selected_modules = config.get("selected_module", {})
    for module_type in ["ASR", "LLM", "TTS"]:
        selected_provider = selected_modules.get(module_type)
        if not selected_provider:
            continue
        if config.get(module) is None:
            continue
        if config.get(selected_provider) is None:
            continue
        provider_config = config.get(module_type, {}).get(selected_provider, {})
        output_dir = provider_config.get("output_dir")
        if output_dir:
            full_model_dir = os.path.join(project_dir, output_dir)
            dirs_to_create.add(full_model_dir)

    # 统一创建目录（保留原data目录创建）
    for dir_path in dirs_to_create:
        try:
            os.makedirs(dir_path, exist_ok=True)
        except PermissionError:
            print(f"警告：无法创建目录 {dir_path}，请检查写入权限")


def merge_configs(default_config, custom_config):
    """
    递归合并配置，custom_config优先级更高

    Args:
        default_config: 默认配置
        custom_config: 用户自定义配置

    Returns:
        合并后的配置
    """
    if not isinstance(default_config, Mapping) or not isinstance(
        custom_config, Mapping
    ):
        return custom_config

    merged = dict(default_config)

    for key, value in custom_config.items():
        if (
            key in merged
            and isinstance(merged[key], Mapping)
            and isinstance(value, Mapping)
        ):
            merged[key] = merge_configs(merged[key], value)
        else:
            merged[key] = value

    return merged