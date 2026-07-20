#!/usr/bin/env python3
"""
反馈验证脚本 (Feedback & Validation)
======================================
AI 代理完成代码修改后，必须通过此脚本的全部验证才算完成任务。

验证层次：
    L1: 语法检查 (py_compile) → 阻止语法错误提交
    L2: 框架测试 (test_skill_framework.py) → 确保插件核心正常
    L3: 函数测试 (逐个 function 测试) → 确保每个 Function 可用
    L4: Skill 完整性 → 确保每个 Function 有配套 Skill
    L5: 配置一致性 → 确保 config.yaml 与代码注册一致

使用方式：
    python .harness/feedback/validate.py            # 全量验证
    python .harness/feedback/validate.py --quick    # 快速验证 (仅 L1-L2)
    python .harness/feedback/validate.py --func staff_safe_query  # 验证单个函数

退出码:
    0 = 全部通过
    1 = 存在失败项
"""

import sys
import os
import json
import subprocess
import argparse
from pathlib import Path

# 设置工作目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

# 切到项目根目录执行
REPO_ROOT = PROJECT_ROOT.parent.parent  # xiaozhi-esp32-server/
os.chdir(REPO_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================
# 配置
# ============================================================

# 需要语法检查的 Python 文件
CRITICAL_FILES = [
    "main/xiaozhi-server/app.py",
    "main/xiaozhi-server/config/config_loader.py",
    "main/xiaozhi-server/core/connection.py",
    "main/xiaozhi-server/core/http_server.py",
    "main/xiaozhi-server/core/handle/intentHandler.py",
    "main/xiaozhi-server/core/providers/intent/intent_llm/intent_llm.py",
    "main/xiaozhi-server/core/providers/llm/openai/openai.py",
    "main/xiaozhi-server/core/providers/tools/unified_tool_manager.py",
    "main/xiaozhi-server/core/providers/tools/unified_tool_handler.py",
    "main/xiaozhi-server/core/providers/tools/server_plugins/plugin_executor.py",
    "main/xiaozhi-server/plugins_func/register.py",
    "main/xiaozhi-server/plugins_func/loadplugins.py",
]

# 所有 Function 文件
FUNCTION_FILES = [
    "main/xiaozhi-server/plugins_func/functions/staff_safe_query.py",
    "main/xiaozhi-server/plugins_func/functions/analyze_weighbridge_data.py",
    "main/xiaozhi-server/plugins_func/functions/analyze_personnel_data.py",
    "main/xiaozhi-server/plugins_func/functions/query_plate_records.py",
    "main/xiaozhi-server/plugins_func/functions/query_building_progress.py",
    "main/xiaozhi-server/plugins_func/functions/query_device_status.py",
    "main/xiaozhi-server/plugins_func/functions/query_elevator_data.py",
    "main/xiaozhi-server/plugins_func/functions/query_taji_height.py",
    "main/xiaozhi-server/plugins_func/functions/taji_auth.py",
    "main/xiaozhi-server/plugins_func/functions/change_role.py",
    "main/xiaozhi-server/plugins_func/functions/get_weather.py",
    "main/xiaozhi-server/plugins_func/functions/get_news_from_newsnow.py",
    "main/xiaozhi-server/plugins_func/functions/get_news_from_chinanews.py",
    "main/xiaozhi-server/plugins_func/functions/get_time.py",
    "main/xiaozhi-server/plugins_func/functions/handle_exit_intent.py",
    "main/xiaozhi-server/plugins_func/functions/play_music.py",
    "main/xiaozhi-server/plugins_func/functions/web_search.py",
    "main/xiaozhi-server/plugins_func/functions/search_from_ragflow.py",
]

# 所有 Skill 文件
SKILL_FILES = [
    "main/xiaozhi-server/plugins_func/skills/staff_safe_skill.py",
    "main/xiaozhi-server/plugins_func/skills/weighbridge_skill.py",
    "main/xiaozhi-server/plugins_func/skills/personnel_skill.py",
    "main/xiaozhi-server/plugins_func/skills/plate_records_skill.py",
    "main/xiaozhi-server/plugins_func/skills/building_progress_skill.py",
    "main/xiaozhi-server/plugins_func/skills/device_status_skill.py",
    "main/xiaozhi-server/plugins_func/skills/elevator_skill.py",
    "main/xiaozhi-server/plugins_func/skills/taji_static_skill.py",
]

# 所有测试文件
TEST_FILES = [
    "test_skill_framework.py",
    "test_staff_safe_query_api.py",
    "test_staff_safe_data.py",
    "test_voice_intent_pipeline.py",
    "test_complete_weighbridge_workflow.py",
    "test_device_stats_workflow.py",
    "test_taji_static_data.py",
    "test_elevator_static_data.py",
    "test_weighbridge_summary.py",
]


# ============================================================
# 验证函数
# ============================================================

class Validator:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def check(self, name: str, success: bool, detail: str = ""):
        """记录一次检查结果"""
        if success:
            self.passed += 1
            print(f"  ✓ {name}")
        else:
            self.failed += 1
            self.errors.append(f"  ✗ {name}: {detail}")
            print(f"  ✗ {name}: {detail}")

    def summary(self) -> int:
        """输出总结，返回退出码"""
        total = self.passed + self.failed
        print(f"\n{'='*60}")
        print(f"验证完成: {self.passed}/{total} 通过, {self.failed} 失败")
        if self.failed == 0:
            print("✓ 全部验证通过，可以提交！")
        else:
            print("✗ 存在失败项，请修复后重新验证：")
            for err in self.errors:
                print(err)
        return 0 if self.failed == 0 else 1


def L1_syntax_check(v: Validator, files: list):
    """L1: 语法检查"""
    print("\n--- L1: 语法检查 (py_compile) ---")
    for f in files:
        path = REPO_ROOT / f
        if not path.exists():
            v.check(f, False, "文件不存在")
            continue
        try:
            subprocess.run(
                [sys.executable, "-m", "py_compile", str(path)],
                check=True, capture_output=True, timeout=10
            )
            v.check(f"语法: {f}", True)
        except subprocess.CalledProcessError as e:
            v.check(f"语法: {f}", False, e.stderr.decode()[:200])
        except subprocess.TimeoutExpired:
            v.check(f"语法: {f}", False, "超时")
        except Exception as e:
            v.check(f"语法: {f}", False, str(e))


def L2_framework_test(v: Validator):
    """L2: 框架测试"""
    print("\n--- L2: 框架测试 (test_skill_framework.py) ---")
    try:
        result = subprocess.run(
            [sys.executable, "test_skill_framework.py"],
            capture_output=True, text=True, timeout=30, cwd=str(REPO_ROOT)
        )
        if result.returncode == 0:
            v.check("test_skill_framework.py", True)
        else:
            v.check(
                "test_skill_framework.py", False,
                f"退出码={result.returncode}\n{result.stderr[:300]}"
            )
    except subprocess.TimeoutExpired:
        v.check("test_skill_framework.py", False, "超时")
    except Exception as e:
        v.check("test_skill_framework.py", False, str(e))


def L3_function_tests(v: Validator, test_files: list):
    """L3: 函数测试"""
    print("\n--- L3: 函数测试 ---")
    for tf in test_files:
        path = REPO_ROOT / tf
        if not path.exists():
            v.check(tf, False, "测试文件不存在")
            continue
        try:
            result = subprocess.run(
                [sys.executable, str(path)],
                capture_output=True, text=True, timeout=60, cwd=str(REPO_ROOT)
            )
            if result.returncode == 0:
                v.check(tf, True)
            else:
                # 截取最后几行错误信息
                stderr_tail = "\n".join(result.stderr.strip().split("\n")[-5:])
                v.check(tf, False, f"退出码={result.returncode}\n{stderr_tail[:300]}")
        except subprocess.TimeoutExpired:
            v.check(tf, False, "超时 (>60s)")
        except Exception as e:
            v.check(tf, False, str(e))


def L4_skill_completeness(v: Validator):
    """L4: Skill 完整性检查"""
    print("\n--- L4: Skill 完整性 ---")

    # 从 agent-base-prompt.txt 中读取预期的函数列表
    try:
        import yaml
        config_path = PROJECT_ROOT / "config.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

        # 获取 function_call 模式下的函数列表
        fc_config = config.get("Intent", {}).get("function_call", {})
        expected_funcs = fc_config.get("functions", [])

        # 获取 intent_llm 模式下的函数列表
        il_config = config.get("Intent", {}).get("intent_llm", {})
        expected_funcs += il_config.get("functions", [])

        # 去重
        expected_funcs = list(set(expected_funcs))
    except Exception as e:
        v.check("读取 config.yaml", False, str(e))
        return

    # 检查每个 Function 是否有对应 Skill
    for func_name in expected_funcs:
        # 跳过不需要 Skill 的基础函数
        if func_name in (
            "handle_exit_intent", "play_music", "change_role",
            "get_lunar", "hass_get_state", "hass_set_state",
            "hass_play_music", "search_from_ragflow",
        ):
            continue

        skill_file = f"main/xiaozhi-server/plugins_func/skills/{func_name.replace('analyze_', '').replace('query_', '')}_skill.py"

        # 尝试多种命名模式匹配
        found = False
        for sf in SKILL_FILES:
            # 通过语法分析检查 skill 文件是否注册了该 function_name
            sf_path = REPO_ROOT / sf
            if not sf_path.exists():
                continue
            content = sf_path.read_text()
            if f'function_name="{func_name}"' in content or f"function_name='{func_name}'" in content:
                found = True
                break

        if found:
            v.check(f"Skill 配对: {func_name}", True)
        else:
            v.check(f"Skill 配对: {func_name}", False, "未找到配套 Skill 注册")


def L5_config_consistency(v: Validator):
    """L5: 配置一致性检查"""
    print("\n--- L5: 配置一致性 ---")

    try:
        import yaml
        config_path = PROJECT_ROOT / "config.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)
    except Exception as e:
        v.check("读取 config.yaml", False, str(e))
        return

    # 检查 config.yaml 中 plugins 配置是否与实际代码一致
    plugins_config = config.get("plugins", {})

    # 获取 function_call 中的函数列表
    fc_config = config.get("Intent", {}).get("function_call", {})
    func_list = fc_config.get("functions", [])

    for func_name in func_list:
        # 检查是否有对应的 plugins 配置
        # 不需要配置的函数：weather, news, music, role 等
        if func_name in (
            "handle_exit_intent", "play_music", "change_role",
            "get_lunar", "get_weather", "get_news_from_newsnow",
            "get_news_from_chinanews", "hass_get_state", "hass_set_state",
            "hass_play_music", "web_search", "search_from_ragflow",
        ):
            continue

        # 需要外部 API 配置的函数
        if func_name in plugins_config:
            plugin_cfg = plugins_config[func_name]
            has_api = "api_url" in plugin_cfg or "base_url" in plugin_cfg
            has_map = "location_project_map" in plugin_cfg or "default_project_id" in plugin_cfg
            if has_api and has_map:
                v.check(f"配置块: {func_name}", True, "api_url + project_map 完整")
            elif has_api:
                v.check(f"配置块: {func_name}", True, "api_url 存在 (缺少 project_map)")
            else:
                v.check(f"配置块: {func_name}", True, "基础配置存在")
        else:
            v.check(f"配置块: {func_name}", False, "config.yaml 中缺少 plugins.{func_name} 配置")

    # 检查 config.yaml 格式有效性
    v.check("config.yaml 格式", isinstance(config, dict), "非 dict 类型" if not isinstance(config, dict) else "")
    v.check("selected_module.LLM", "LLM" in config.get("selected_module", {}), "缺少 LLM 配置")
    v.check("selected_module.Intent", "Intent" in config.get("selected_module", {}), "缺少 Intent 配置")


def L6_harness_self_check(v: Validator):
    """L6: Harness 自检"""
    print("\n--- L6: Harness 自检 ---")

    harness_dir = PROJECT_ROOT / ".harness"

    # 检查核心文件是否存在
    required_files = [
        "AGENTS.md",
        "PROGRESS.md",
        ".harness/tools/whitelist.py",
        ".harness/environment/env.json",
        ".harness/environment/requirements.lock",
        ".harness/feedback/validate.py",
        ".harness/README.md",
    ]

    for rf in required_files:
        path = PROJECT_ROOT / rf
        if path.exists():
            v.check(f"Harness 文件: {rf}", True)
        else:
            v.check(f"Harness 文件: {rf}", False, "文件缺失")

    # 运行 whitelist 自测
    try:
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / ".harness/tools/whitelist.py")],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and "FAIL" not in result.stdout:
            v.check("whitelist.py 自测", True)
        else:
            v.check("whitelist.py 自测", False, result.stdout[-200:])
    except Exception as e:
        v.check("whitelist.py 自测", False, str(e))


# ============================================================
# 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="xiaozhi-server Harness 验证脚本")
    parser.add_argument("--quick", action="store_true", help="快速验证 (仅 L1-L2)")
    parser.add_argument("--func", type=str, help="验证单个函数 (如 staff_safe_query)")
    args = parser.parse_args()

    print("=" * 60)
    print("xiaozhi-server Harness 验证")
    print(f"项目根目录: {REPO_ROOT}")
    print(f"Python: {sys.version}")
    print("=" * 60)

    v = Validator()

    if args.func:
        # 单函数验证
        func_file = f"main/xiaozhi-server/plugins_func/functions/{args.func}.py"
        L1_syntax_check(v, [func_file])
    elif args.quick:
        L1_syntax_check(v, CRITICAL_FILES)
        L2_framework_test(v)
    else:
        # 全量验证
        L1_syntax_check(v, CRITICAL_FILES + FUNCTION_FILES + SKILL_FILES)
        L2_framework_test(v)
        L3_function_tests(v, [t for t in TEST_FILES if Path(REPO_ROOT / t).exists()])
        L4_skill_completeness(v)
        L5_config_consistency(v)
        L6_harness_self_check(v)

    return v.summary()


if __name__ == "__main__":
    sys.exit(main())