"""
小智 AI 服务主入口

支持启动参数：
    --project / -p : 项目名称，指定后启用对应项目的数据查询能力
                     不指定则为普通 LLM 对话服务（无数据接口/数据库调用）

支持的项目：
    三元里 - 人员状态（定位）+ 地磅数据分析
    将军祠 - 施工数据接口（设备/进度/人员/塔机/车牌等）
    潮白河 - 监测数据库查询（测缝计/GNSS/渗压计/流量计等）
    向阳村 - 塔机历史作业状态查询

示例：
    python app.py                        # 普通 LLM 对话模式
    python app.py --project 三元里       # 三元里项目模式
    python app.py -p 将军祠              # 将军祠项目模式
    python app.py -p 潮白河              # 潮白河项目模式
    python app.py -p 向阳村              # 向阳村项目模式
"""

import sys
import uuid
import signal
import asyncio
import argparse
from aioconsole import ainput
from config.settings import load_config
from config.logger import setup_logging
from core.utils.util import get_local_ip, validate_mcp_endpoint
from core.http_server import SimpleHttpServer
from core.websocket_server import WebSocketServer
from core.utils.util import check_ffmpeg_installed
from core.utils.gc_manager import get_gc_manager
from core.project_config import ProjectName, PROJECT_DESCRIPTIONS

TAG = __name__
logger = setup_logging()


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="小智 AI 服务 - 支持多项目数据查询",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "支持的项目名称:\n"
            f"  三元里    - {PROJECT_DESCRIPTIONS.get(ProjectName.SANYUANLI, '')}\n"
            f"  将军祠    - {PROJECT_DESCRIPTIONS.get(ProjectName.JIANGJUNCI, '')}\n"
            f"  潮白河    - {PROJECT_DESCRIPTIONS.get(ProjectName.CHAOBAIHE, '')}\n"
            f"  向阳村    - {PROJECT_DESCRIPTIONS.get(ProjectName.XIANGYANGCUN, '')}\n"
            "\n不指定 --project 时，启动普通 LLM 对话服务（不进行数据接口/数据库调用）。"
        ),
    )
    parser.add_argument(
        "--project", "-p",
        type=str,
        default=None,
        metavar="NAME",
        help=f"项目名称: {' / '.join(sorted(ProjectName.all_values()))}",
    )
    return parser.parse_args()


async def wait_for_exit() -> None:
    """
    阻塞直到收到 Ctrl‑C / SIGTERM。
    - Unix: 使用 add_signal_handler
    - Windows: 依赖 KeyboardInterrupt
    """
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    if sys.platform != "win32":  # Unix / macOS
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)
        await stop_event.wait()
    else:
        # Windows：await一个永远pending的fut，
        # 让 KeyboardInterrupt 冒泡到 asyncio.run，以此消除遗留普通线程导致进程退出阻塞的问题
        try:
            await asyncio.Future()
        except KeyboardInterrupt:  # Ctrl‑C
            pass


async def monitor_stdin():
    """监控标准输入，消费回车键"""
    while True:
        await ainput()  # 异步等待输入，消费回车


def resolve_project(args: argparse.Namespace) -> ProjectName | None:
    """解析并验证项目名称
    
    Returns:
        ProjectName 枚举值，无项目或验证失败返回 None
    """
    if not args.project:
        return None
    
    project = ProjectName.from_string(args.project)
    if project is None:
        logger.bind(tag=TAG).error(
            f"不支持的项目名称: '{args.project}'，"
            f"支持: {ProjectName.choices_help()}"
        )
        logger.bind(tag=TAG).info(
            "将以普通 LLM 对话模式启动。"
            "如需指定项目，请使用 --project 参数并输入正确的项目名称。"
        )
        return None
    
    return project


async def main():
    # ---- 解析命令行参数 ----
    args = parse_args()
    project = resolve_project(args)

    check_ffmpeg_installed()
    config = await load_config()

    # ---- 注入项目配置 ----
    config["project"] = project

    # auth_key优先级：配置文件server.auth_key > manager-api.secret > 自动生成
    # auth_key用于jwt认证，比如视觉分析接口的jwt认证、ota接口的token生成与websocket认证
    # 获取配置文件中的auth_key
    auth_key = config["server"].get("auth_key", "")
    
    # 验证auth_key，无效则尝试使用manager-api.secret
    if not auth_key or len(auth_key) == 0 or "你" in auth_key:
        auth_key = config.get("manager-api", {}).get("secret", "")
        # 验证secret，无效则生成随机密钥
        if not auth_key or len(auth_key) == 0 or "你" in auth_key:
            auth_key = str(uuid.uuid4().hex)
    
    config["server"]["auth_key"] = auth_key

    # ---- 启动信息日志 ----
    if project is not None:
        desc = PROJECT_DESCRIPTIONS.get(project, "未知项目")
        logger.bind(tag=TAG).info("=" * 60)
        logger.bind(tag=TAG).info(f"  项目模式: {project.value} ({desc})")
        logger.bind(tag=TAG).info("=" * 60)
    else:
        logger.bind(tag=TAG).info("=" * 60)
        logger.bind(tag=TAG).info("  普通 LLM 对话模式（无数据接口/数据库调用）")
        logger.bind(tag=TAG).info("=" * 60)

    # 添加 stdin 监控任务
    stdin_task = asyncio.create_task(monitor_stdin())

    # 启动全局GC管理器（5分钟清理一次）
    gc_manager = get_gc_manager(interval_seconds=300)
    await gc_manager.start()

    # 启动 WebSocket 服务器
    ws_server = WebSocketServer(config)
    ws_task = asyncio.create_task(ws_server.start())
    # 启动 Simple http 服务器
    ota_server = SimpleHttpServer(config)
    ota_task = asyncio.create_task(ota_server.start())

    read_config_from_api = config.get("read_config_from_api", False)
    port = int(config["server"].get("http_port", 8003))
    if not read_config_from_api:
        logger.bind(tag=TAG).info(
            "OTA接口是\t\thttp://{}:{}/xiaozhi/ota/",
            get_local_ip(),
            port,
        )
    logger.bind(tag=TAG).info(
        "视觉分析接口是\thttp://{}:{}/mcp/vision/explain",
        get_local_ip(),
        port,
    )
    mcp_endpoint = config.get("mcp_endpoint", None)
    if mcp_endpoint is not None and "你" not in mcp_endpoint:
        # 校验MCP接入点格式
        if validate_mcp_endpoint(mcp_endpoint):
            logger.bind(tag=TAG).info("mcp接入点是\t{}", mcp_endpoint)
            # 将mcp计入点地址转成调用点
            mcp_endpoint = mcp_endpoint.replace("/mcp/", "/call/")
            config["mcp_endpoint"] = mcp_endpoint
        else:
            logger.bind(tag=TAG).error("mcp接入点不符合规范")
            config["mcp_endpoint"] = "你的接入点 websocket地址"

    # 获取WebSocket配置，使用安全的默认值
    websocket_port = 8000
    server_config = config.get("server", {})
    if isinstance(server_config, dict):
        websocket_port = int(server_config.get("port", 8000))

    logger.bind(tag=TAG).info(
        "Websocket地址是\tws://{}:{}/xiaozhi/v1/",
        get_local_ip(),
        websocket_port,
    )

    logger.bind(tag=TAG).info(
        "=======上面的地址是websocket协议地址，请勿用浏览器访问======="
    )
    logger.bind(tag=TAG).info(
        "如想测试websocket请启动digital-human模块，打开浏览器交互测试"
    )
    logger.bind(tag=TAG).info(
        "=============================================================\n"
    )

    try:
        await wait_for_exit()  # 阻塞直到收到退出信号
    except asyncio.CancelledError:
        print("任务被取消，清理资源中...")
    finally:
        # 停止全局GC管理器
        await gc_manager.stop()

        # 取消所有任务（关键修复点）
        stdin_task.cancel()
        ws_task.cancel()
        if ota_task:
            ota_task.cancel()

        # 等待任务终止（必须加超时）
        await asyncio.wait(
            [stdin_task, ws_task, ota_task] if ota_task else [stdin_task, ws_task],
            timeout=3.0,
            return_when=asyncio.ALL_COMPLETED,
        )
        print("服务器已关闭，程序退出。")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("手动中断，程序终止。")

