# MewCode

终端 AI 编程助手（类似 Claude Code），用 Python 开发。

## 特性

- **多 Provider 支持**：Anthropic Claude / OpenAI / DeepSeek，通过 YAML 配置切换
- **流式 TUI**：基于 Prompt Toolkit 的全屏终端界面，逐字渲染
- **7 种内置工具**：读/写/编辑文件、执行命令、Glob/Grep 搜索、子 Agent
- **16 条斜杠命令**：`/help` `/clear` `/compress` `/mode` `/status` `/review` 等
- **纵深安全防御**：黑名单拦截、路径沙箱、人在回路确认、三档权限模式
- **MCP 协议**：支持 Stdio 和 HTTP 传输，连接外部工具服务器
- **YAML+MD Skill 系统**：可编程 SOP 指令，三级优先级覆盖
- **事件 Hook 引擎**：12 种生命周期事件 + 条件匹配 + 4 种动作
- **子 Agent + Team 编排**：Fork 模式继承上下文、后台任务、共享任务清单
- **Git Worktree 隔离**：子 Agent 在独立工作目录中操作，退出自动清理
- **两层 Token 管理**：工具结果截断（层1）+ 结构化 LLM 摘要（层2）
- **JSONL 会话持久化**：追加写 O(1)、崩溃恢复、损坏行跳过

## 快速开始

```bash
pip install -e .
cp example.mewcode.yaml .mewcode.yaml
# 编辑 .mewcode.yaml 填入 API key
python -m mewcode
```

## 项目结构

```
mewcode/
├── main.py              # 启动编排
├── config/              # YAML 配置
├── providers/           # LLM 后端（Anthropic/OpenAI/DeepSeek）
├── agent/               # ReAct 循环 + 事件流
├── conversation/        # 历史/截断/摘要/压缩
├── prompts/             # 模块化 Prompt
├── tools/               # 内置工具 + 注册中心
├── tui/                 # 全屏终端界面
├── storage/             # JSONL 会话存储
├── security/            # 纵深防御
├── mcp/                 # MCP 协议客户端
├── commands/            # 16 条斜杠命令
├── skills/              # YAML+MD Skill 系统
├── hooks/               # 事件 Hook 引擎
├── subagent/            # 子 Agent 系统
├── worktree/            # Git 工作目录管理
├── teams/               # Agent Team 编排
├── instructions/        # 项目指令加载
└── notes/               # 自动笔记
```

## 文档

- [使用教程](TUTORIAL.md)
- [Spec](spec.md)
- [任务列表](tasks.md)
- [验收清单](checklist.md)

## 要求

- Python ≥ 3.10
- Git ≥ 2.30（Worktree 功能需要）
