# PROGRESS.md — AI 工作进度持久化

> **用途**：实现 AI 代理"断点续传"，解决跨会话失忆问题  
> **更新规则**：每次 AI 会话结束时自动写入进度；下次会话开始时首先读取  
> **格式约定**：Markdown checklist，已完成项 `[x]`，进行中 `[~]`，未开始 `[ ]`

---

## 当前会话信息

| 字段 | 值 |
|------|-----|
| 会话 ID | `session-20260618-harness-init` |
| 开始时间 | 2026-06-18T16:00:00+08:00 |
| 最后更新 | 2026-06-18T17:05:00+08:00 |
| 当前阶段 | Harness 体系初始化 |
| 状态 | COMPLETED |

---

## 任务进度

### Phase 1: Harness 体系搭建

- [x] 1.1 创建 AGENTS.md 指令文件
- [x] 1.2 创建 .harness/tools/whitelist.py 工具白名单
- [x] 1.3 创建 .harness/environment/env.json 环境锁定
- [x] 1.4 创建 .harness/environment/requirements.lock 依赖锁定
- [x] 1.5 创建 PROGRESS.md 本文件
- [x] 1.6 创建 .harness/feedback/validate.py 验证脚本
- [x] 1.7 创建 .harness/README.md 总览文档

### Phase 2: 验证与集成

- [x] 2.1 运行 whitelist.py 自测 (9/9 通过)
- [x] 2.2 运行 validate.py 快速验证 (13/13 通过)
- [x] 2.3 验证所有核心语法检查通过
- [ ] 2.4 更新 .gitignore 添加 harness 日志

### Phase 3: 后续任务（待规划）

- [ ] 3.1 新增项目接口时更新 AGENTS.md 项目清单
- [ ] 3.2 新增 Function 时更新 config.yaml 和 Skill
- [ ] 3.3 定期运行 validate.py 确保代码健康

---

## 上次会话遗留问题

| 问题 | 优先级 | 状态 |
|------|--------|------|
| （暂无） | - | - |

---

## 变更文件清单（本次会话）

| 文件 | 操作 | 说明 |
|------|------|------|
| `AGENTS.md` | 新建 | 项目约定与操作手册 |
| `.harness/tools/whitelist.py` | 新建 | 工具命令白名单 |
| `.harness/environment/env.json` | 新建 | 环境锁定配置 |
| `.harness/environment/requirements.lock` | 新建 | 依赖版本锁定 |
| `PROGRESS.md` | 新建 | 本文件 |
| `.harness/feedback/validate.py` | 新建 | 验证脚本 |
| `.harness/README.md` | 新建 | Harness 总览 |

---

## 设计决策记录

### 为什么选择 harness 模式？

1. **项目接口增长快**：从三元里开始已接入 8+ 个 Function，后续还会增加更多项目接口
2. **AI 跨会话失忆**：每次新 AI 会话不知道上次做到了哪里、有什么约定
3. **防止越权操作**：没有工具白名单时 AI 可能执行危险命令
4. **环境不一致**：不同开发者机器依赖版本不同导致"能在我这跑"

### harness 五个维度的设计原则

| 维度 | 文件 | 核心原则 |
|------|------|----------|
| 指令 (Instructions) | `AGENTS.md` | 项目约定优先，先读约定再写代码 |
| 工具 (Tools) | `.harness/tools/whitelist.py` | 默认拒绝，显式允许 |
| 环境 (Environment) | `.harness/environment/` | 锁定版本，拒绝漂移 |
| 状态 (State) | `PROGRESS.md` | 每次会话结束存档，开始时恢复 |
| 反馈 (Feedback) | `.harness/feedback/validate.py` | 不通过验证不算完成 |