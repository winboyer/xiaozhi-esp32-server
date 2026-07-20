# .harness/ — AI 代理约束与协作体系

> **设计目标**：在不增加响应时间的前提下，为 AI 代理提供操作边界、环境一致性和进度可恢复性。

---

## 架构概览

```
main/xiaozhi-server/
├── AGENTS.md              ← 1. 指令：项目约定与操作手册
├── PROGRESS.md            ← 4. 状态：AI 工作进度持久化
└── .harness/
    ├── README.md          ← 本文件
    ├── tools/
    │   └── whitelist.py   ← 2. 工具：命令/API 白名单
    ├── environment/
    │   ├── env.json       ← 3. 环境：锁定运行时配置
    │   └── requirements.lock ← 3. 环境：锁定依赖版本
    └── feedback/
        └── validate.py    ← 5. 反馈：多级验证脚本
```

---

## 五个维度详解

### 1. 指令 (Instructions) — `AGENTS.md`

**解决问题**：新 AI 会话不知道项目有什么约定

**内容**：
- 项目架构说明（链路、技术栈、目录结构）
- 开发规范（配置、插件、测试、API 调用）
- 项目接口清单（当前已接入的项目和 Function）
- AI 操作边界（允许/禁止的操作）

**使用方式**：AI 代理启动时首先读取此文件

---

### 2. 工具 (Tools) — `whitelist.py`

**解决问题**：AI 可能执行危险命令（rm -rf、DROP TABLE 等）

**核心原则**：**默认拒绝，显式允许**

**三级模式**：
```bash
export HARNESS_MODE=off      # 关闭约束（默认）
export HARNESS_MODE=audit    # 审计模式：允许所有但记录日志
export HARNESS_MODE=strict   # 严格模式：仅允许白名单内的操作
```

**白名单内容**：
- 允许的 CLI 命令（python、git、pip、curl 等）
- 允许的 API 域名（项目接口 + LLM 服务）
- 允许的文件路径（项目目录内）
- 禁止的命令（rm、sudo、chmod 等）

**验证方式**：
```bash
python .harness/tools/whitelist.py   # 自测白名单逻辑
```

---

### 3. 环境 (Environment) — `environment/`

**解决问题**：不同机器依赖版本不一致导致"能在我这跑"

**env.json** — 运行环境配置：
- Python 版本要求
- 依赖安装命令和镜像源
- 外部服务端点（LLM API、项目 API）
- 必要的目录结构
- 运行时环境变量

**requirements.lock** — 依赖版本锁定：
- 所有核心依赖的具体版本号
- 防止 `pip install -r requirements.txt` 随机拉取最新版本

**使用方式**：
```bash
# 安装锁定版本的依赖
pip install -r .harness/environment/requirements.lock -i https://pypi.tuna.tsinghua.edu.cn/simple
```

---

### 4. 状态 (State) — `PROGRESS.md`

**解决问题**：AI 跨会话失忆，不知道上次做到哪里

**内容结构**：
- 会话信息（ID、时间、状态）
- 任务进度（Markdown checklist，`[x]`/`[~]`/`[ ]`）
- 遗留问题列表
- 变更文件清单
- 设计决策记录

**使用规则**：
1. AI 会话开始时：读取 `PROGRESS.md` 了解当前状态
2. AI 会话结束时：更新 `PROGRESS.md` 归档进度
3. 开发者也可以手动更新

---

### 5. 反馈 (Feedback) — `validate.py`

**解决问题**：AI 过早宣布胜利，实际上代码有问题

**六级验证层次**：

| 级别 | 检查内容 | 阻止的问题 |
|------|----------|-----------|
| L1 | 语法检查 (py_compile) | 语法错误 |
| L2 | 框架测试 (test_skill_framework.py) | 插件核心异常 |
| L3 | 函数测试 (逐 Function 测试) | 单个 Function 不可用 |
| L4 | Skill 完整性 | Function 缺少 Skill 注册 |
| L5 | 配置一致性 | config.yaml 与代码不一致 |
| L6 | Harness 自检 | Harness 文件缺失 |

**使用方式**：
```bash
python .harness/feedback/validate.py            # 全量验证
python .harness/feedback/validate.py --quick    # 快速验证 (仅 L1-L2)
python .harness/feedback/validate.py --func staff_safe_query  # 验证单个函数
```

**AI 代理规则**：提交代码前必须运行全量验证并全部通过

---

## 快速上手

### 新 AI 会话启动流程

```bash
# 1. 读取约定
cat main/xiaozhi-server/AGENTS.md

# 2. 读取进度
cat main/xiaozhi-server/PROGRESS.md

# 3. 设置工作环境
cd main/xiaozhi-server
export PYTHONPATH=$(pwd)

# 4. 快速验证当前状态
python .harness/feedback/validate.py --quick

# 5. 开始工作...
```

### AI 会话结束流程

```bash
# 1. 运行全量验证
python .harness/feedback/validate.py

# 2. 确保全部通过后，更新 PROGRESS.md
# （在 PROGRESS.md 中勾选已完成项、记录决策）

# 3. 提交代码
git add -A
git commit -m "feat: 完成 XXX 功能"
```

---

## 新增项目接口时的更新清单

当接入新项目（如将军祠）时，需要同步更新的 harness 文件：

| 文件 | 更新内容 |
|------|----------|
| `AGENTS.md` | 更新「项目接口清单」表格 |
| `config.yaml` | 添加新项目的 `location_project_map` |
| `.harness/tools/whitelist.py` | 添加新项目的 API 域名到 `allowed_domains` |
| `.harness/environment/env.json` | 添加新项目 API 端点到 `project_apis` |
| `.harness/feedback/validate.py` | 如果有新函数文件，添加到 `FUNCTION_FILES` |
| `PROGRESS.md` | 记录新任务 |

---

## 设计原则

1. **零依赖**：harness 文件只使用 Python 标准库 + 项目已有依赖（yaml）
2. **渐进式**：默认关闭，不影响现有流程；需要时可逐步启用
3. **声明式**：通过配置声明约束，而非硬编码到代码中
4. **可验证**：每个约束都有对应的验证方式