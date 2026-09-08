"""
工程建设项目配置模块

定义支持的项目名称枚举、各项目对应的函数组、以及项目感知的工具过滤逻辑。
后续新增项目只需在此文件添加枚举值和函数组配置即可。
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, FrozenSet, Optional, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

# ==================== 项目名称枚举 ====================

class ProjectName(str, Enum):
    """支持的工程建设项目名称
    
    每个枚举值对应一个中文项目名称。使用 str + Enum 确保可以直接与字符串比较。
    新增项目时只需在此添加枚举值，并在 PROJECT_FUNCTION_GROUPS 中配置函数组。
    """
    SANYUANLI = "三元里"          # 人员状态（定位）+ 地磅数据
    JIANGJUNCI = "将军祠"         # 三元里之外的所有数据接口
    CHAOBAIHE = "潮白河"           # 数据库查询（监测数据）
    XIANGYANGCUN = "向阳村"        # 塔机历史作业状态 + 人员数据查询

    @classmethod
    def from_string(cls, name: str) -> Optional["ProjectName"]:
        """从字符串精确匹配项目名称
        
        Args:
            name: 用户输入的项目名称
            
        Returns:
            匹配的 ProjectName 枚举值，未匹配则返回 None
        """
        if not name:
            return None
        name = name.strip()
        for proj in cls:
            if proj.value == name:
                return proj
        return None

    @classmethod
    def all_values(cls) -> Set[str]:
        """获取所有支持的项目名称集合（用于帮助文本）"""
        return {p.value for p in cls}
    
    @classmethod
    def choices_help(cls) -> str:
        """生成命令行帮助文本"""
        return "、".join(sorted(cls.all_values()))


# ==================== 项目 → 函数组映射 ====================

# 三元里项目：人员定位（staff_safe_query）+ 地磅数据（analyze_weighbridge_data）
_SANYUANLI_FUNCTIONS: FrozenSet[str] = frozenset({
    "staff_safe_query",           # 现场人员状态（定位）查询
    "analyze_weighbridge_data",   # 地磅数据分析（含车牌统计）
    "query_plate_records",        # 车牌号记录查询
})

# 将军祠项目：三元里之外的所有数据接口
# 注意：query_plate_records 是三元里专属（地磅车牌数据），不属于将军祠
_JIANGJUNCI_FUNCTIONS: FrozenSet[str] = frozenset({
    "staff_safe_query",           # 设备/告警/物资等数据查询（API_CATALOG 中非三元里的接口）
    "query_elevator_data",        # 电梯/升降机数据
    "query_device_status",        # 设备状态查询
    "query_building_progress",    # 建设进度查询
    "query_taji_height",          # 塔机高度数据
    "analyze_personnel_data",     # 人员数据分析
})

# 潮白河项目：数据库查询模式，不走插件函数
# 使用 intent_api_server 的 DataQueryEngine 进行监测数据查询
_CHAOBAIHE_FUNCTIONS: FrozenSet[str] = frozenset()

# 向阳村项目：塔机历史作业状态 + 人员数据查询
_XIANGYANGCUN_FUNCTIONS: FrozenSet[str] = frozenset({
    "query_taji_work_status",         # 塔机历史作业状态查询
    "query_xiangyangcun_personnel",   # 向阳村项目人员数据查询
})

# 通用工具函数（所有项目都需要的非数据接口工具）
_COMMON_FUNCTIONS: FrozenSet[str] = frozenset({
    "handle_exit_intent",         # 退出会话
    "get_weather",                # 天气查询
    "get_time",                   # 时间查询
    "web_search",                 # 联网搜索
    "get_news_from_newsnow",      # 新闻查询
    "search_from_ragflow",        # RAG知识库搜索
})

# 项目 → 函数组映射（不含通用函数，通用函数始终加载）
PROJECT_FUNCTION_GROUPS: Dict[ProjectName, FrozenSet[str]] = {
    ProjectName.SANYUANLI: _SANYUANLI_FUNCTIONS,
    ProjectName.JIANGJUNCI: _JIANGJUNCI_FUNCTIONS,
    ProjectName.CHAOBAIHE: _CHAOBAIHE_FUNCTIONS,
    ProjectName.XIANGYANGCUN: _XIANGYANGCUN_FUNCTIONS,
}

# 项目描述（用于日志和帮助信息）
PROJECT_DESCRIPTIONS: Dict[ProjectName, str] = {
    ProjectName.SANYUANLI: "人员定位 + 地磅数据 + 车牌分析",
    ProjectName.JIANGJUNCI: "施工数据接口（设备/告警/物资/塔机/电梯/人员分析）",
    ProjectName.CHAOBAIHE: "监测数据库查询（测缝计/GNSS/渗压计/流量计等）",
    ProjectName.XIANGYANGCUN: "塔机历史作业状态 + 人员数据查询",
}

# ==================== staff_safe_query API 级别隔离 ====================
# 每个项目通过 staff_safe_query 能访问的 API_CATALOG 接口 ID 集合。
# 三元里：人员状态、定位、班组、考勤等人员相关接口
# 将军祠：告警、设备、物资等三元里之外的所有接口
# 未列出的项目或无项目：返回空（不暴露任何 staff_safe_query 接口）

_SANYUANLI_STAFF_API_IDS: FrozenSet[str] = frozenset({
    # 大屏-首页（人员相关）
    "personOverall",              # 首页人数总览
    "todayPersonHourStat",        # 当天人员时间分布
    "todayTeamsAtteStat",         # 今日班组出勤情况
    "weekEnterpriseAtteStat",     # 近七日参建方人员出勤
    # 大屏-作业面
    "layerAreaPersonList",        # 作业面人员列表
    # 定位相关
    "snapshootProjectPersonCountV3",  # 人员定位-24H走势图
    "personCurLocationV2",        # 人员定位-人员列表
    "track",                      # 人员轨迹查询
    # 人员/组织/统计
    "personPage",                 # 分页获取人员库
    "organTree",                  # 参建公司及班组架构
    "attendanceDay",              # 作业面日考勤统计
})

_JIANGJUNCI_STAFF_API_IDS: FrozenSet[str] = frozenset({
    # 大屏-告警
    "getAlarmRecord",             # 分页获取告警记录
    "getMonthRecordSubType",      # 近三十天预警类型分析
    "getMonthRecordStatus",       # 近三十日报警处理情况
    "getMonthEnterpriseRecordNum",  # 近三十天参建公司告警数量
    "getMonthOrganRecordNum",     # 近三十天班组告警数量
    # 设备/物资
    "gatewayPageByProjectId",     # 基站物资信息
    "assetQuantityStatistics",    # 设备信息统计
    "gatewayPage",                # 主基站信息（分页）
    "labelPage",                  # 标签信息（分页）
})

# 项目 → staff_safe_query 可用的 API ID 集合
PROJECT_STAFF_SAFE_API_IDS: Dict[ProjectName, FrozenSet[str]] = {
    ProjectName.SANYUANLI: _SANYUANLI_STAFF_API_IDS,
    ProjectName.JIANGJUNCI: _JIANGJUNCI_STAFF_API_IDS,
}


def get_staff_safe_api_ids(project: Optional[ProjectName]) -> FrozenSet[str]:
    """获取指定项目在 staff_safe_query 中可用的 API ID 集合
    
    Args:
        project: 项目名称，None 表示无项目（不暴露任何 API）
        
    Returns:
        允许的 API ID 集合，无项目时返回空集合
    """
    if project is None:
        return frozenset()
    return PROJECT_STAFF_SAFE_API_IDS.get(project, frozenset())

# 潮白河数据库配置
CHAOBAIHE_DB_CONFIG = {
    "sql_filepath": "/Users/jinyfeng/Downloads/monitoring_standard.sql",
}


# ==================== 工具过滤逻辑 ====================

def get_allowed_functions(project: Optional[ProjectName]) -> Optional[FrozenSet[str]]:
    """获取指定项目允许的函数名集合
    
    Args:
        project: 项目名称，None 表示普通 LLM 对话模式（不启用数据查询工具）
        
    Returns:
        允许的函数名集合。None 表示不进行过滤（普通模式加载全部通用工具）。
        空 frozenset 表示只加载通用工具（如潮白河）。
    """
    if project is None:
        # 无项目：普通 LLM 对话，不进行数据接口/数据库查询
        # 返回 None 表示使用默认行为（所有已注册函数）
        return None
    
    project_funcs = PROJECT_FUNCTION_GROUPS.get(project, frozenset())
    return project_funcs | _COMMON_FUNCTIONS


def apply_project_filter(conn: "ConnectionHandler") -> None:
    """根据连接的项目配置过滤可用工具函数
    
    在 ConnectionHandler 初始化完成后调用，从 ToolManager 缓存中移除
    不属于当前项目的函数，确保 LLM 意图识别时只能看到项目相关的工具。
    
    采用「缓存过滤」而非「全局注册表修改」策略，避免影响其他连接。
    
    对于潮白河项目，额外初始化 DataQueryEngine。
    
    Args:
        conn: 当前连接的 ConnectionHandler 实例
    """
    from config.logger import setup_logging
    logger = setup_logging()
    TAG = "project_config"
    
    project: Optional[ProjectName] = conn.config.get("project")
    
    if project is None:
        # 无项目 → 普通 LLM 对话，移除所有数据查询工具
        logger.bind(tag=TAG).info("无项目配置，启用普通 LLM 对话模式")
        _filter_tool_manager(conn, _COMMON_FUNCTIONS, logger, TAG)
        return
    
    logger.bind(tag=TAG).info(
        f"项目模式: {project.value} ({PROJECT_DESCRIPTIONS.get(project, '未知')})"
    )
    
    if project == ProjectName.CHAOBAIHE:
        # 潮白河：数据库查询模式，只保留通用工具 + 设备控制工具
        # 设备端 IoT/MCP 工具（音量、亮度、状态等）为通用能力，不随项目禁用
        _filter_tool_manager(
            conn,
            _COMMON_FUNCTIONS,
            logger,
            TAG,
            disallowed_tool_types=frozenset({
                "mcp_endpoint",
                "server_mcp",
            }),
        )
        _setup_chaobaihe_mode(conn, logger, TAG)
    else:
        # 三元里 / 将军祠：API 数据接口模式
        allowed = get_allowed_functions(project)
        _filter_tool_manager(conn, allowed, logger, TAG)


def _filter_tool_manager(
    conn: "ConnectionHandler",
    allowed: FrozenSet[str],
    logger,
    TAG: str,
    disallowed_tool_types: Optional[FrozenSet[str]] = None,
) -> None:
    """过滤 ToolManager 中的工具，仅保留白名单内的
    
    采用两层策略确保过滤持久生效：
    1. 直接过滤当前缓存（_cached_tools / _cached_function_descriptions）
    2. Monkey-patch refresh_tools()，使后续任何缓存刷新后自动重新过滤
    
    不修改全局 all_function_registry（避免影响其他连接）。
    """
    if not hasattr(conn, "func_handler") or conn.func_handler is None:
        logger.bind(tag=TAG).warning("func_handler 未初始化，跳过工具过滤")
        return
    
    try:
        tm = conn.func_handler.tool_manager
        
        # 存储允许的工具名集合和禁用的工具类型，供 monkey-patched refresh_tools 使用
        tm._project_allowed_tools = allowed
        tm._project_disallowed_tool_types = disallowed_tool_types or frozenset()
        
        # ---- 应用当前过滤 ----
        _apply_tool_cache_filter(
            tm,
            allowed,
            logger,
            TAG,
            disallowed_tool_types=disallowed_tool_types,
        )
        
        # ---- Monkey-patch refresh_tools：确保后续缓存刷新后自动重新过滤 ----
        # 代码中 MCP 初始化、设备连接等场景会调用 refresh_tools() 重置缓存，
        # 如果不拦截，项目过滤会在这些时机失效
        if not getattr(tm, '_refresh_tools_patched', False):
            _original_refresh = tm.refresh_tools
            
            def _filtered_refresh():
                _original_refresh()  # 先执行原始刷新（清缓存）
                # 缓存清空后立即重新填充并过滤
                tm.get_all_tools()   # 触发重新填充
                _apply_tool_cache_filter(
                    tm,
                    tm._project_allowed_tools,
                    logger,
                    TAG,
                    disallowed_tool_types=tm._project_disallowed_tool_types,
                )
            
            tm.refresh_tools = _filtered_refresh
            tm._refresh_tools_patched = True
            logger.bind(tag=TAG).debug("已安装 refresh_tools 拦截器，项目过滤将持续生效")
        
    except Exception as e:
        logger.bind(tag=TAG).error(f"工具过滤失败: {e}")


def _apply_tool_cache_filter(
    tm,
    allowed: FrozenSet[str],
    logger,
    TAG: str,
    disallowed_tool_types: Optional[FrozenSet[str]] = None,
) -> None:
    """对 ToolManager 当前缓存执行白名单过滤

    默认只过滤 SERVER_PLUGIN 类型的工具，保留其他工具；当显式传入
    disallowed_tool_types 时，额外移除指定类型的工具，避免设备控制等能力
    在项目限定模式下被错误暴露。
    """
    from core.providers.tools.base import ToolType

    disallowed_tool_types = disallowed_tool_types or frozenset()

    all_tools = tm._cached_tools
    if all_tools is None:
        all_tools = tm.get_all_tools()

    plugin_tools = {
        name for name, defn in all_tools.items()
        if defn.tool_type == ToolType.SERVER_PLUGIN
    }
    other_tools = {
        name for name, defn in all_tools.items()
        if defn.tool_type != ToolType.SERVER_PLUGIN
    }

    tools_to_remove = plugin_tools - allowed

    if tools_to_remove:
        logger.bind(tag=TAG).info(
            f"工具过滤: 移除 {len(tools_to_remove)} 个插件工具, "
            f"保留 {len(allowed & plugin_tools)} 个插件工具, "
            f"保留其他工具 {len(other_tools)} 个"
        )
    else:
        logger.bind(tag=TAG).info(
            f"工具过滤: 保留 {len(allowed & plugin_tools)} 个插件工具, "
            f"保留其他工具 {len(other_tools)} 个"
        )

    # 1. 先按白名单过滤所有工具（保持与旧代码兼容的行为）
    filtered_tools = {
        name: definition
        for name, definition in all_tools.items()
        if name in allowed
    }

    # 2. 将非 SERVER_PLUGIN 工具补回（除非其类型被明确禁用）
    #    这是为了兼容 IoT/MCP 等设备端动态注册的工具，它们不应受项目白名单限制
    non_plugin_added = 0
    for name, definition in all_tools.items():
        if name in filtered_tools:
            continue
        if definition.tool_type == ToolType.SERVER_PLUGIN:
            continue
        # 检查该工具类型是否在禁用列表中
        if disallowed_tool_types and definition.tool_type.value in disallowed_tool_types:
            continue
        filtered_tools[name] = definition
        non_plugin_added += 1

    if non_plugin_added:
        logger.bind(tag=TAG).info(
            f"补回非插件工具 {non_plugin_added} 个: "
            f"{sorted([n for n, d in filtered_tools.items() if d.tool_type != ToolType.SERVER_PLUGIN])}"
        )

    tm._cached_tools = filtered_tools

    if tm._cached_function_descriptions is not None:
        tm._cached_function_descriptions = [
            desc for desc in tm._cached_function_descriptions
            if desc.get("function", {}).get("name") in filtered_tools
        ]

    remaining = list(filtered_tools.keys())
    logger.bind(tag=TAG).info(
        f"当前可用工具 ({len(remaining)}): {sorted(remaining)}"
    )


def _setup_chaobaihe_mode(conn: "ConnectionHandler", logger, TAG: str) -> None:
    """设置潮白河项目模式：初始化 DataQueryEngine
    
    潮白河使用 intent_api_server.py 的 DataQueryEngine 进行监测数据库查询，
    不走插件函数体系（工具已在 _filter_tool_manager 中限制为通用工具）。
    """
    try:
        import sys
        import os
        
        # 将项目根目录加入路径（intent_api_server.py 在项目根目录）
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )))
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        
        from intent_api_server import DataQueryEngine
        
        sql_filepath = CHAOBAIHE_DB_CONFIG.get("sql_filepath")
        if sql_filepath and os.path.exists(sql_filepath):
            engine = DataQueryEngine(sql_filepath)
            conn._chaobaihe_db_engine = engine
            logger.bind(tag=TAG).info(
                f"潮白河项目: DataQueryEngine 初始化完成，"
                f"共 {len(engine.tables)} 张表"
            )
        else:
            logger.bind(tag=TAG).warning(
                f"潮白河项目: SQL 文件不存在或未配置: {sql_filepath}"
            )
            conn._chaobaihe_db_engine = None
            
    except Exception as e:
        logger.bind(tag=TAG).error(f"潮白河项目: DataQueryEngine 初始化失败: {e}")
        conn._chaobaihe_db_engine = None
