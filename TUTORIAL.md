# MewCode 使用教程

## 目录

1. [快速开始](#1-快速开始)
2. [基本对话](#2-基本对话)
3. [Provider 配置](#3-provider-配置)
4. [工具系统](#4-工具系统)
5. [命令系统](#5-命令系统)
6. [对话管理](#6-对话管理)
7. [安全系统](#7-安全系统)
8. [MCP 协议](#8-mcp-协议)
9. [Skill 技能](#9-skill-技能)
10. [Hook 钩子](#10-hook-钩子)
11. [子 Agent](#11-子-agent)
12. [工作目录隔离](#12-工作目录隔离)
13. [Agent Team](#13-agent-team)
14. [项目指令与笔记](#14-项目指令与笔记)
15. [完整快捷键](#15-完整快捷键)

---

## 1. 快速开始

### 安装

```bash
cd mewcode/
pip install -e .
```

**要求**：Python ≥ 3.10，Git ≥ 2.30

### 最小配置

在项目根目录创建 `.mewcode.yaml`：

```yaml
providers:
  - name: claude
    protocol: anthropic
    model: claude-sonnet-4-6
    api_key: sk-ant-your-key-here

active_provider: claude
```

### 启动

```bash
python -m mewcode

# 指定配置文件
MEWCODE_CONFIG=/path/to/config.yaml python -m mewcode

# 安全等级
python -m mewcode --mode strict

# 恢复上次会话
python -m mewcode --resume
```

---

## 2. 基本对话

启动后进入全屏 TUI：

```
MewCode — Provider: claude | Model: claude-sonnet-4-6 | MCP: 1 server
Ctrl+C exit | Enter submit | /help for commands
──────────────────────────────────────────────────────────────
 [Plan: OFF] [Sec: normal] | /help /clear /compress /status
>
```

### 操作

| 操作 | 方式 |
|------|------|
| 提交消息 | 输入内容 → **Enter** |
| 退出 | **Ctrl+C** |
| Tab 补全命令 | 输入 `/hel` → **Tab** → `/help` |
| 状态栏 | 底部常驻显示模式和常用命令 |

AI 会**逐字流式**输出回复。如果模型调用了工具，会在对话中显示：

```
You: 读一下 README.md

🔧 read_file(path='README.md')
  → # MewCode — 终端 AI 编程助手...

MewCode: README.md 的内容显示这是一个 AI 编程助手项目...
```

---

## 3. Provider 配置

支持三种协议，可在同一配置文件中定义多个并按需切换。

```yaml
providers:
  # Anthropic Claude
  - name: claude
    protocol: anthropic
    model: claude-sonnet-4-6
    base_url: https://api.anthropic.com      # 可选，不填用默认
    api_key: sk-ant-xxx

  # OpenAI
  - name: gpt
    protocol: openai
    model: gpt-4o
    api_key: sk-xxx

  # DeepSeek
  - name: deepseek
    protocol: deepseek
    model: deepseek-chat
    api_key: sk-xxx

  # DeepSeek 推理模型
  - name: deepseek-r1
    protocol: deepseek
    model: deepseek-reasoner
    api_key: sk-xxx

  # 本地模型（Ollama / vLLM / LiteLLM）
  - name: local
    protocol: openai
    model: llama-3
    base_url: http://localhost:11434/v1
    api_key: ollama

active_provider: claude   # ← 当前使用哪个
```

**配置文件发现顺序**（优先级从高到低）：
1. 环境变量 `MEWCODE_CONFIG` 指向的路径
2. 当前目录 `.mewcode.yaml`
3. `~/.mewcode/config.yaml`

**Claude Extended Thinking**：在代码中通过 `provider.enable_thinking(budget_tokens=8192)` 开启。Thinking 内容在 TUI 中以 `[Thinking]` 灰色斜体渲染。

**DeepSeek Reasoner**：`deepseek-reasoner` 模型的推理过程自动以 `[Reasoning]` 标签渲染。

---

## 4. 工具系统

MewCode 内置 6 个工具，Agent 可以自主选择使用。

| 工具 | 功能 | 类型 |
|------|------|------|
| `read_file` | 读取文件内容（UTF-8/GBK/Latin-1 自动尝试） | 读 |
| `write_file` | 写入新文件（已存在则报错） | 写 |
| `edit_file` | 精确匹配替换（原文必须唯一出现） | 写 |
| `run_command` | 执行 Shell 命令（工作目录内） | 写 |
| `glob` | 按模式查找文件（如 `**/*.py`） | 读 |
| `grep` | 正则搜索代码内容 | 读 |

### 工具调用示例

```
> 帮我在 src/ 下找到所有定义了 main 函数的文件

🔧 grep(pattern='def main')
  → src/cli.py:42: def main():
  → src/server.py:15: def main():

MewCode: 找到了两个文件：src/cli.py:42 和 src/server.py:15
```

### 工具截断

单个工具结果超过 **50K 字符**时，完整内容写入 `~/.mewcode/tool_results/`，对话中只保留 2K 字符预览：

```
📎 read_file 结果过大（125,000 字符）→ 存盘 ~/.mewcode/tool_results/20260601_read_file.txt
```

---

## 5. 命令系统

输入 `/` 开头触发命令，Tab 可补全。未知命令自动引导到 `/help`。

| 命令 | 别名 | 用途 |
|------|------|------|
| `/help [命令]` | `h ?` | 列出命令或查看详情 |
| `/clear` | `cls reset` | 清空当前对话 |
| `/compress` | `zip` | 手动触发上下文压缩 |
| `/mode [plan\|security]` | — | 切换模式 |
| `/status` | `st info` | 显示综合状态 |
| `/session [list\|switch]` | `sess` | 管理会话 |
| `/memory [show\|clear\|edit]` | `mem notes` | 管理自动笔记 |
| `/permission` | `perm acl` | 安全权限状态 |
| `/review [路径]` | `cr audit` | 请求代码审查 |
| `/skill [list\|reload\|clear]` | `skills` | Skill 管理 |
| `/tasks [list\|detail\|kill]` | `bg` | 后台任务管理 |
| `/worktree [status\|list\|create\|enter\|exit]` | `wt` | Git 工作目录 |
| `/team [list\|show\|dir]` | `tm` | Team 管理 |

---

## 6. 对话管理

### 上下文压缩

对话 token 达到模型窗口 **70%** 时发出警告，达到 **90%** 时自动压缩。

压缩产出一个 **9 段结构化摘要**：主要请求、关键概念、文件与代码、错误与修复、解决过程、用户原话、待办事项、当前工作、下一步。

压缩后附加边界消息提示模型重新读取文件而非脑补细节。

**手动触发**：`/compress` 或 **Ctrl+Q**

**熔断保护**：连续 2 次摘要失败自动停止自动压缩。

### 会话持久化

每轮对话后自动保存到 `~/.mewcode/sessions/{id}.jsonl`（追加写，O(1)）。

恢复时自动处理：
- 损坏行跳过
- 未配对的 tool_use 截断
- 时间跨度 > 30 分钟注入提醒

```bash
# 恢复上次会话
python -m mewcode --resume
```

---

## 7. 安全系统

三层权限档位：**Ctrl+S** 循环切换，或 `/mode security <level>`。

| 档位 | 读类工具 | 写类工具 | 路径限制 |
|------|---------|---------|---------|
| **严格** | 仅白名单路径 | 全部询问 | `.mewcode-security.yaml` 声明的路径 |
| **默认** | 直接放行 | 写入时询问 | 项目目录内放行 |
| **放行** | 直接放行 | 直接放行 | 仅禁止 `..` 遍历 |

### 人在回路（HITL）

当安全策略无法自动判断时，弹出确认提示：

```
⚠ 安全确认: run_command(command='pip install pandas')
  当前模式: normal
  [A]llow once  [S]ession allow  [P]ermanent allow  [D]eny
```

- **A**：本次允许
- **S**：会话允许（本次启动内有效）
- **P**：永久允许（写入 `.mewcode-security.yaml`）
- **D**：拒绝

### 安全规则文件

```yaml
# .mewcode-security.yaml
rules:
  - tool: run_command
    command_pattern: "pip install *"
    action: allow

  - tool: write_file
    path_pattern: "*.env"
    action: deny
```

优先级：会话级 > 项目级 > 全局级

---

## 8. MCP 协议

连接外部 MCP Server，扩展工具集。

### 配置

```yaml
# .mewcode-mcp.yaml（项目级，覆盖全局 ~/.mewcode/mcp.yaml）
servers:
  # Stdio 传输：本地子进程
  - name: filesystem
    transport: stdio
    command: npx
    args: [-y, "@anthropic/mcp-filesystem", /allowed/path]
    timeout: 30

  # HTTP 传输：远程服务
  - name: remote
    transport: http
    url: http://localhost:8080
    headers:
      Authorization: Bearer xxx
    timeout: 30
```

### 工具命名

MCP 工具自动注册为 `{server_name}/{tool_name}` 格式：

```
filesystem/read_file
filesystem/write_file
remote/search
```

启动时并行连接所有 Server，失败的不阻塞启动。欢迎信息显示 `MCP: N servers`。

---

## 9. Skill 技能

Skill 是用 YAML frontmatter + Markdown 正文定义的专业 SOP。

### 创建 Skill

```markdown
---
name: my-skill
description: 我的自定义技能
mode: shared
tools: [read_file, glob, grep]
---

# My Skill SOP

1. 使用 glob 了解项目结构
2. 使用 grep 搜索关键模式
3. 输出分析报告
```

### 存放位置

| 优先级 | 路径 |
|--------|------|
| 项目级 | `.mewcode/skills/*.md` |
| 用户级 | `~/.mewcode/skills/*.md` |
| 内置 | `mewcode/skills/builtin/*.md` |

同名 Skill 按优先级覆盖。

### 内置 Skill

| Skill | 模式 | 描述 |
|-------|------|------|
| `commit` | shared | 生成 Conventional Commits 提交信息 |
| `review` | isolated | 全面代码审查（正确性/安全/性能/风格） |
| `test` | shared | 分析变更并生成/运行测试 |

### 使用 Skill

Agent 调用 `skill_loader(name="commit")` 激活 Skill，或使用命令：

```
/skill list              # 列出可用 Skill
/skill commit            # 查看 Skill 详情
/commit                  # 自动注册的命令，激活并执行
```

激活后 Skill 指令**钉在环境上下文**中，每轮 LLM 调用都可见。

---

## 10. Hook 钩子

事件驱动的自动化规则。

### 配置

```yaml
# .mewcode-hooks.yaml
hooks:
  - name: block-rm-rf
    event: tool_pre_exec
    condition:
      match: ALL
      rules:
        - field: tool_name
          operator: exact
          value: run_command
        - field: params.command
          operator: regex
          value: "rm\\s+-rf"
    actions:
      - type: prompt_inject
        text: "拦截: '{{params.command}}' 包含危险操作"
    control:
      async: false

  - name: log-writes
    event: tool_post_exec
    condition:
      match: ANY
      rules:
        - field: tool_name
          operator: exact
          value: write_file
    actions:
      - type: shell
        command: "echo {{tool_name}} {{params.path}} >> ~/.mewcode/log.txt"
    control:
      async: true
      once: false
```

### 12 种事件

| 层级 | 事件 | 可拦截 |
|------|------|--------|
| 会话 | `session_start` `session_end` | — |
| 轮次 | `round_start` `round_end` | — |
| 消息 | `message_pre_send` `message_post_receive` | — |
| 工具 | `tool_pre_exec` | **✓** |
| 工具 | `tool_post_exec` | — |
| 系统 | `system_startup` `system_shutdown` `system_error` `system_compress` | — |

### 四种动作

| 动作类型 | 用途 |
|---------|------|
| `shell` | 执行命令 |
| `prompt_inject` | 向 LLM 注入文本（拦截事件用此反馈拒绝原因） |
| `http` | 发起 HTTP 请求 |
| `sub_agent` | 启动子 Agent（占位） |

---

## 11. 子 Agent

### 定义模式（指定角色）

```
> 用 explorer 角色探索项目结构

🔧 sub_agent(task='探索项目结构', role='explorer')
  → ## 项目结构 / ## 关键模块 / ## 代码模式...
```

### Fork 模式（继承当前对话）

不指定 `role` 参数，自动继承当前对话历史 + 复用工具集：

```
> 帮我分析刚才读到的所有文件

🔧 sub_agent(task='分析刚才读到的文件')
  → [Fork 模式] 分析结果...
```

Fork 模式**强制后台运行**，完成结果自动注入对话。

### 内置角色

| 角色 | 工具 | 用途 |
|------|------|------|
| `explorer` | read_file, glob, grep | 探索代码结构 |
| `planner` | + run_command | 制定执行计划 |
| `general` | 全部 | 通用综合任务 |

### 自定义角色

在 `.mewcode/roles/` 下创建 Markdown 文件（同名覆盖内置）：

```markdown
---
name: my-role
description: 自定义角色
tools_allow: [read_file, glob, grep, run_command]
max_rounds: 5
---

# My Role SOP
...
```

### 后台任务管理

```
/tasks list       # 列出所有后台任务
/tasks detail id  # 查看详情
/tasks kill id    # 终止任务
```

---

## 12. 工作目录隔离

基于 `git worktree` 的物理隔离，每个子 Agent 可在独立工作目录中操作。

### 命令

```
/worktree status                  # 当前状态
/worktree list                    # 列出所有工作目录
/worktree create fix-bug          # 创建 worktree（自动复制配置+链接依赖）
/worktree enter fix-bug           # 切换到工作目录
/worktree exit fix-bug            # 退出（有修改默认拒绝删除）
/worktree exit fix-bug --force    # 强制退出
```

### 变更保护

退出 worktree 时，默认检查 `git status`：

- **有未提交修改** → 拒绝删除，提示用 `--force`
- **无修改** → 正常删除 worktree + 分支

### 后台清理

每 5 分钟自动清理过期（24h+）且无修改的 worktree。

### 恢复

```bash
python -m mewcode --resume
# → 恢复到上次的 worktree 会话
```

---

## 13. Agent Team

长期存在的协作小组，Leader 拆解目标、分配成员、合并结果。

### Team 定义

```json
// ~/.mewcode/teams/example.json
{
  "name": "example",
  "description": "示例 Team",
  "lead_role": "general",
  "members": [
    {"name": "alice", "role": "explorer", "worktree": "alice-wt", "backend": "coro"},
    {"name": "bob", "role": "planner", "worktree": "bob-wt", "backend": "coro"},
    {"name": "carol", "role": "general", "worktree": "carol-wt", "backend": "coro"}
  ],
  "dispatch_mode": false
}
```

### 协作工具

Team 成员拥有专属的 6 个协作工具（主 Agent 不可见）：

| 工具 | 用途 |
|------|------|
| `team_create_task` | 创建任务（可指定依赖） |
| `team_list_tasks` | 列出所有任务及状态 |
| `team_view_task` | 查看单任务详情 |
| `team_update_task` | 更新任务状态/结果 |
| `team_send_message` | 点对点消息 |
| `team_broadcast` | 广播到全组 |

### 纯调度模式

双锁机制（`/mode dispatch` + `--dispatch` CLI 参数）同时开启后：

- Lead 失去文件读写/命令执行工具
- 只保留 `sub_agent`、`team_*` 工具
- 注入 10 阶段工作流指引

### 合并策略

成员完成 → Lead 增量合并 worktree：
- 无冲突 → 自动 `git merge --commit`
- 有冲突 → LLM 逐文件裁决
- 裁决失败 → 回滚，记录不可解决的冲突

---

## 14. 项目指令与笔记

### 项目指令

在项目根目录创建 `MEWCODE.md`：

```markdown
# 项目规范
- 使用 Python 3.12+，类型注解必须完整
- 测试用 pytest，覆盖率 ≥ 80%
- 禁止使用 `print`，统一走 `logging`

@include(sub/ci-rules.md)
```

`@include` 支持最大 3 层嵌套，拒绝越界路径。

启动时自动读取并作为 System 消息注入对话开头。

全局指令放在 `~/.mewcode/instructions.md`（优先级低于项目级）。

### 自动笔记

每 5 轮对话自动调 LLM 更新笔记，四个分类分别存储：

| 分类 | 存放位置 |
|------|---------|
| 用户偏好 | `~/.mewcode/notes/user_preferences.md` |
| 纠正反馈 | `~/.mewcode/notes/corrections.md` |
| 项目知识 | `.mewcode/notes/project_knowledge.md` |
| 参考资料 | `.mewcode/notes/references.md` |

```
/memory show                # 查看各分类大小
/memory show 项目知识        # 查看具体内容
/memory clear 纠正反馈       # 清空
/memory edit 用户偏好        # 显示文件路径
```

---

## 15. 完整快捷键

| 按键 | 功能 |
|------|------|
| **Enter** | 提交消息 / 执行命令 |
| **Ctrl+C** | 退出（自动保存+笔记更新） |
| **Ctrl+P** | 切换 plan-only 模式 |
| **Ctrl+S** | 循环切换安全等级 |
| **Ctrl+Q** | 手动触发上下文压缩 |
| **Tab** | 补全 `/` 开头的命令名 |
| **A/S/P/D** | HITL 确认（允许/会话/永久/拒绝） |

### 启动参数

```bash
python -m mewcode --mode strict     # 安全等级
python -m mewcode --resume          # 恢复上次会话
MEWCODE_CONFIG=/path/to/config.yaml python -m mewcode
```
