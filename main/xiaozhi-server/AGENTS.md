# AGENTS.md — 项目约定与操作手册

> **阅读对象**：AI 编程代理、新加入的开发者  
> **目的**：统一开发规范，降低 AI 越权操作风险，确保代码质量一致性  
> **更新频率**：每次新增项目接口或约定的变更时同步更新

---

## 1. 项目概述

**xiaozhi-esp32-server** 是一个智能语音助手后端服务，基于 Python 异步框架构建。

### 1.1 核心功能链路

```
ESP32 设备 ←→ WebSocket ←→ ASR(语音识别) → LLM(大语言模型) → TTS(语音合成)
                                    ↑
                              Intent(意图识别)
                              Function Call(插件调用)
```

### 1.2 技术栈

| 层次 | 技术 |
|------|------|
| 语言 | Python 3.10+ |
| 异步框架 | asyncio + websockets |
| 配置管理 | YAML (config.yaml + data/.config.yaml 覆盖机制) |
| LLM 适配 | OpenAI-compatible API (DeepSeek/GLM/Doubao 等) |
| 插件系统 | 装饰器注册 + ToolType 枚举分类 |

### 1.3 关键目录结构

```
main/xiaozhi-server/
├── app.py                  # 入口：启动 HTTP + WebSocket 服务
├── config.yaml             # 默认配置（不可直接修改）
├── data/.config.yaml       # 本地覆盖配置（密钥等敏感信息）
├── AGENTS.md               # ← 本文件
├── PROGRESS.md             # ← AI 工作进度持久化
├── .harness/               # ← Harness 约束体系
│   ├── tools/              # 工具白名单
│   ├── environment/        # 环境锁定
│   └── feedback/           # 验证反馈
├── core/                   # 核心框架
│   ├── connection.py       # WebSocket 连接处理
│   ├── handle/             # 意图处理 + 会话管理
│   └── providers/          # LLM/ASR/TTS 适配器
├── plugins_func/           # 插件系统
│   ├── register.py         # 函数注册中心 + ToolType 枚举
│   ├── loadplugins.py      # 自动导入
│   ├── functions/          # 工具函数（可执行代码）
│   │   ├── staff_safe_query.py
│   │   ├── analyze_weighbridge_data.py
│   │   └── ...
│   └── skills/             # 技能提示（LLM 引导元数据）
│       ├── base.py         # SkillHints + SkillRegistry
│       ├── registry.py     # 全局 skill_registry
│       └── ...
└── config/
    └── config_loader.py    # 配置加载器
```

---

## 2. 核心约定

### 2.1 配置管理规则

- **`config.yaml`** 是默认配置模板，**禁止**直接修改
- 本地覆盖配置写在 **`data/.config.yaml`**，系统优先读取
- 密钥、Token 等敏感信息**只能**出现在 `data/.config.yaml`，严禁写入 `config.yaml`
- 新增插件配置项必须同步更新 `config.yaml` 中的注释说明

### 2.2 插件开发规范

#### 2.2.1 Function（工具函数）

所有工具函数必须使用 `@register_function` 装饰器注册：

```python
from plugins_func.register import register_function, ToolType, ActionResponse, Action

STAFF_SAFE_QUERY_FUNCTION_DESC = {
    "type": "function",
    "function": {
        "name": "staff_safe_query",
        "description": "查询工地安全数据，支持多维度条件查询...",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "自然语言查询描述"}
            },
            "required": ["query"]
        }
    }
}

@register_function("staff_safe_query", STAFF_SAFE_QUERY_FUNCTION_DESC, ToolType.SYSTEM_CTL)
def staff_safe_query(conn, query: str = None) -> ActionResponse:
    ...
```

**规则**：
- ToolType 选择：`SYSTEM_CTL`（需要 conn 参数）、`WAIT`（无 conn 参数）、`CHANGE_SYS_PROMPT`（角色切换）
- 返回类型必须是 `ActionResponse`，包含 `action` 和 `result`/`response`
- 函数名必须与 `config.yaml` 中 `Intent.function_call.functions` 列表中的名称一致

#### 2.2.2 Skill（技能提示）

每个 Function 应配套一个 Skill 注册：

```python
from plugins_func.skills.base import SkillHints

def register_weighbridge_skill():
    hints = SkillHints(
        function_name="analyze_weighbridge_data",
        keywords=["地磅", "过磅", "称重", "混凝土"],
        few_shot_examples=[
            "用户: 查一下今天地磅数据\n助手: 【调用 analyze_weighbridge_data】→ ..."
        ],
        summary_prompt="基于地磅数据，总结今日{data}...",
        priority=5
    )
    skill_registry.register(hints)
```

**规则**：
- `function_name` 必须与 Function 注册名完全匹配
- 关键词应覆盖用户常用的口语表达
- `few_shot_examples` 至少 2 个示例

### 2.3 测试规范

- 新增/修改 Function 必须同步更新对应测试文件
- 测试文件命名：`test_<功能名>.py` 放在项目根目录
- 测试模式：`py_compile` 语法检查 + 逻辑断言 + 集成测试
- 提交前必须运行：`python test_skill_framework.py` 和 `python <相关测试>.py`

### 2.4 代码风格

- 遵循 PEP 8
- 日志使用 `from config.logger import setup_logging` 统一输出
- 类型注解必须包含（Python 3.10+ 语法）
- 异步函数使用 `async def`，阻塞操作用 `run_in_executor`

### 2.5 API 调用规范

- 所有外部 API 调用配置写在 `config.yaml` 的 `plugins.<function_name>` 下
- 支持 `location_project_map` 进行项目/地点映射
- 超时时间统一设置，默认 30 秒

---

## 3. 项目接口清单

### 3.1 当前已集成项目

| 项目 | 项目 ID | 接口 |
|------|---------|------|
| 三元里 | `sanyuanli` / `61455993-...` | workerstatus, present_worker/list |
| 将军祠 | 待添加 | 待添加 |

### 3.2 当前已注册 Function

| Function 名称 | 用途 | ToolType | 配套 Skill |
|---|---|---|---|
| `staff_safe_query` | 工地安全数据智能查询 | SYSTEM_CTL | `staff_safe_skill.py` |
| `analyze_weighbridge_data` | 地磅数据分析 | SYSTEM_CTL | `weighbridge_skill.py` |
| `analyze_personnel_data` | 现场人员状态分析 | SYSTEM_CTL | `personnel_skill.py` |
| `query_plate_records` | 车牌记录查询 | SYSTEM_CTL | `plate_records_skill.py` |
| `query_building_progress` | 建筑施工进度查询 | SYSTEM_CTL | `building_progress_skill.py` |
| `query_device_status` | 设备状态查询 | SYSTEM_CTL | `device_status_skill.py` |
| `query_elevator_data` | 电梯数据查询 | SYSTEM_CTL | `elevator_skill.py` |
| `query_taji_height` | 塔机高度查询 | SYSTEM_CTL | `taji_static_skill.py` |
| `taji_auth` | 塔机认证 | SYSTEM_CTL | - |

### 3.3 新增项目接口步骤

1. 在 `config.yaml` 的 `plugins.<function_name>` 下添加 `location_project_map` 映射
2. 在对应 Function 代码中处理新项目的参数
3. 在对应 Skill 的关键词中添加新项目名称
4. 更新本文件的「项目接口清单」
5. 运行语法检查和测试验证

---

## 4. AI 操作边界

### 4.1 允许的操作

- 读取/编辑 `main/xiaozhi-server/` 下的 `.py`、`.yaml`、`.md`、`.txt` 文件
- 执行 `python` 命令运行测试和语法检查
- 执行 `git` 命令查看状态和差异
- 执行 `pip` 安装 `requirements.txt` 中的依赖

### 4.2 禁止的操作

- 修改项目根目录外的系统文件
- 修改 `config.yaml` 中的密钥和 Token
- 删除 `data/` 目录下的数据文件
- 执行 `rm -rf`、`DROP TABLE` 等破坏性命令
- 调用生产环境的 API（除非明确允许）

### 4.3 新增工具函数时需要检查

1. `config.yaml` 中是否有对应配置块
2. 是否注册了对应的 Skill（`skills/` 目录）
3. 测试文件是否同步更新
4. `agent-base-prompt.txt` 是否需要更新工具描述

---

## 5. 变更记录

| 日期 | 变更内容 | 操作者 |
|------|----------|--------|
| 2026-06-18 | 初始创建 AGENTS.md + Harness 体系 | AI 代理 |