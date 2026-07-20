#!/usr/bin/env python3
"""
工具白名单 (Tool Whitelist)
=============================
限定 AI 代理可以调用的命令和 API 端点，防止越权操作。

使用方式：
    export HARNESS_MODE=strict    # 严格模式：仅允许白名单内的操作
    export HARNESS_MODE=audit     # 审计模式：允许所有操作但记录日志
    export HARNESS_MODE=off       # 关闭（默认）

在 CI/CD 或 AI 代理环境中设置 HARNESS_MODE=strict。
"""

import os
import sys
import subprocess
import json
from pathlib import Path

HARNESS_MODE = os.environ.get("HARNESS_MODE", "off")

# ============================================================
# 1. 允许的 CLI 命令白名单
# ============================================================
ALLOWED_COMMANDS = {
    # Python 相关
    "python": {
        "allowed_args": [
            # 运行测试
            "test_skill_framework.py",
            "test_staff_safe_query_api.py",
            "test_staff_safe_data.py",
            "test_voice_intent_pipeline.py",
            "test_complete_weighbridge_workflow.py",
            "test_device_stats_workflow.py",
            "test_taji_static_data.py",
            "test_elevator_static_data.py",
            "test_staff_safe_query_server.py",
            "test_weighbridge_summary.py",
            "check_manager_llm_config.py",
            "temp_test.py",
            # 启动服务
            "app.py",
            # 语法检查
            "-m", "py_compile",
            # pip 安装（仅允许 requirements.txt）
            "-m", "pip", "install", "-r", "requirements.txt",
            # 验证工具
            ".harness/feedback/validate.py",
        ],
        "banned_args": [
            # 禁止删除操作
            "rm", "del", "remove",
            # 禁止直接操作数据目录
            "-rf", "--force",
        ]
    },
    "pip": {
        "allowed_subcommands": ["install", "list", "freeze", "show"],
        "allowed_args": ["-r", "requirements.txt", "--upgrade"],
    },
    # Git 相关（只读 + 安全写入）
    "git": {
        "allowed_subcommands": [
            "status", "diff", "log", "branch", "show",
            "add", "commit", "checkout", "stash", "pull", "push",
        ],
        "banned_subcommands": [
            "push", "--force",  # 禁止强制推送
            "reset", "--hard",  # 禁止硬重置
            "clean", "-fd",     # 禁止清理未跟踪文件
        ],
    },
    # 系统工具
    "ls": {"allowed": True},
    "cat": {"allowed": True},
    "head": {"allowed": True},
    "tail": {"allowed": True},
    "grep": {"allowed": True},
    "find": {"allowed": True},
    "wc": {"allowed": True},
    "echo": {"allowed": True},
    "mkdir": {"allowed": True},
    "curl": {
        "allowed_domains": [
            # 允许的项目 API 域名
            "dmap.cscec3bxjy.cn",
            "smarthat.lanjiansuzhou.com",
            # 允许的 LLM API 域名
            "api.deepseek.com",
            "open.bigmodel.cn",
            "dashscope.aliyuncs.com",
            "ark.cn-beijing.volces.com",
            # 本地服务
            "localhost",
            "127.0.0.1",
        ],
    },
    "docker": {
        "allowed_subcommands": [
            "ps", "images", "logs", "inspect", "stats",
            "compose", "build", "run", "start", "stop",
        ],
        "banned_args": [
            "rmi", "rm", "prune", "system", "prune",
        ],
    },
}

# 禁止的命令（即使参数在白名单中）
BANNED_COMMANDS = [
    "rm",
    "sudo",
    "su",
    "chmod", "chown",
    "kill", "killall",
    "shutdown", "reboot",
    "dd",
    "mkfs",
    "iptables",
    "useradd", "userdel",
]

# ============================================================
# 2. 允许的文件路径白名单
# ============================================================
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

ALLOWED_PATHS = [
    str(PROJECT_ROOT),                          # main/xiaozhi-server/
    str(PROJECT_ROOT / "core"),
    str(PROJECT_ROOT / "plugins_func"),
    str(PROJECT_ROOT / "config"),
    str(PROJECT_ROOT / "models"),
    str(PROJECT_ROOT / ".harness"),
    str(PROJECT_ROOT / "data"),
    str(PROJECT_ROOT / "tmp"),
    str(PROJECT_ROOT.parent / "manager-api"),   # Java 后端（关联项目）
]

BANNED_PATHS = [
    "/etc",
    "/usr",
    "/bin",
    "/sbin",
    "/var",
    "/root",
    str(Path.home() / ".ssh"),
    str(Path.home() / ".aws"),
    str(Path.home() / ".config"),
]

# ============================================================
# 3. 验证函数
# ============================================================

def is_command_allowed(cmd: list) -> bool:
    """检查命令是否在白名单中"""
    if not cmd:
        return False

    base_cmd = cmd[0]
    args = cmd[1:] if len(cmd) > 1 else []

    # 检查禁止命令
    if base_cmd in BANNED_COMMANDS:
        _log_reject(f"BANNED command: {base_cmd}")
        return False

    # 检查命令是否在允许列表中
    if base_cmd not in ALLOWED_COMMANDS:
        _log_reject(f"Unknown command: {base_cmd}")
        return False

    cmd_config = ALLOWED_COMMANDS[base_cmd]

    # 简单允许
    if cmd_config.get("allowed"):
        return True

    # 检查子命令
    if "allowed_subcommands" in cmd_config and args:
        if args[0] not in cmd_config["allowed_subcommands"]:
            _log_reject(f"Banned subcommand: {base_cmd} {args[0]}")
            return False

    # 检查禁止子命令
    if "banned_subcommands" in cmd_config:
        for banned in cmd_config["banned_subcommands"]:
            banned_parts = banned.split()
            if _list_starts_with(cmd, banned_parts):
                _log_reject(f"Banned subcommand sequence: {' '.join(banned_parts)}")
                return False

    # 检查参数
    if "banned_args" in cmd_config:
        for arg in args:
            if arg in cmd_config["banned_args"]:
                _log_reject(f"Banned argument: {arg}")
                return False

    # curl 域名检查
    if base_cmd == "curl" and "allowed_domains" in cmd_config:
        for arg in args:
            if arg.startswith("http"):
                domain = _extract_domain(arg)
                if domain and domain not in cmd_config["allowed_domains"]:
                    _log_reject(f"Banned domain: {domain}")
                    return False

    return True


def is_path_allowed(path: str) -> bool:
    """检查文件路径是否在白名单中"""
    resolved = str(Path(path).resolve())

    # 检查禁止路径
    for banned in BANNED_PATHS:
        if resolved.startswith(banned):
            _log_reject(f"BANNED path access: {resolved}")
            return False

    # 检查允许路径
    for allowed in ALLOWED_PATHS:
        if resolved.startswith(allowed):
            return True

    _log_reject(f"Path not in allowed list: {resolved}")
    return False


# ============================================================
# 4. 装饰器：Wrapped Subprocess
# ============================================================

def safe_run(cmd: list, **kwargs) -> subprocess.CompletedProcess:
    """安全执行命令，自动检查白名单"""
    if HARNESS_MODE == "off":
        return subprocess.run(cmd, **kwargs)

    if not is_command_allowed(cmd):
        raise PermissionError(
            f"Harness blocked command: {' '.join(cmd)}"
        )

    if HARNESS_MODE == "audit":
        _log_audit(f"ALLOWED: {' '.join(cmd)}")

    return subprocess.run(cmd, **kwargs)


def safe_check_output(cmd: list, **kwargs) -> str:
    """安全执行命令并返回输出"""
    if HARNESS_MODE == "off":
        return subprocess.check_output(cmd, **kwargs).decode()

    if not is_command_allowed(cmd):
        raise PermissionError(
            f"Harness blocked command: {' '.join(cmd)}"
        )

    if HARNESS_MODE == "audit":
        _log_audit(f"ALLOWED: {' '.join(cmd)}")

    return subprocess.check_output(cmd, **kwargs).decode()


# ============================================================
# 5. 辅助函数
# ============================================================

def _log_reject(msg: str):
    """记录拒绝日志"""
    log_entry = {
        "type": "REJECT",
        "message": msg,
    }
    _write_log(log_entry)


def _log_audit(msg: str):
    """记录审计日志"""
    log_entry = {
        "type": "AUDIT",
        "message": msg,
    }
    _write_log(log_entry)


def _write_log(entry: dict):
    """写入 harness 日志"""
    log_dir = PROJECT_ROOT / ".harness" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "harness.log"

    import datetime
    entry["timestamp"] = datetime.datetime.now().isoformat()

    with open(log_file, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _list_starts_with(full: list, prefix: list) -> bool:
    """检查列表 full 是否以 prefix 开头（顺序匹配）"""
    if len(full) < len(prefix):
        return False
    # 检查是否存在连续的 prefix 序列
    for i in range(len(full) - len(prefix) + 1):
        if full[i:i + len(prefix)] == prefix:
            return True
    return False


def _extract_domain(url: str) -> str | None:
    """从 URL 中提取域名"""
    try:
        from urllib.parse import urlparse
        return urlparse(url).hostname
    except Exception:
        return None


# ============================================================
# 6. CLI 入口
# ============================================================

if __name__ == "__main__":
    # 测试白名单
    test_cases = [
        (["python", "test_skill_framework.py"], True),
        (["git", "status"], True),
        (["rm", "-rf", "/"], False),
        (["curl", "https://api.deepseek.com/v1/chat"], True),
        (["curl", "https://evil.com/hack"], False),
        (["sudo", "ls"], False),
    ]

    for cmd, expected in test_cases:
        result = is_command_allowed(cmd)
        status = "✓" if result == expected else "✗ FAIL"
        print(f"{status} {' '.join(cmd)} -> allowed={result} (expected={expected})")

    # 测试路径白名单
    print()
    path_tests = [
        (str(PROJECT_ROOT / "core" / "connection.py"), True),
        ("/etc/passwd", False),
        (str(PROJECT_ROOT / "data" / ".config.yaml"), True),
    ]
    for path, expected in path_tests:
        result = is_path_allowed(path)
        status = "✓" if result == expected else "✗ FAIL"
        print(f"{status} {path} -> allowed={result} (expected={expected})")