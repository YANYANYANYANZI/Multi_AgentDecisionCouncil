# Multi_AgentDecisionCouncil

一个面向复杂议题讨论的多 Agent 决策控制台，采用 `FastAPI + Vue 3` 架构，支持三位 Agent 串行讨论、流式输出、会话存档、文件挂载和 Markdown 导出。

## 当前版本结构

- `backend/api.py`
  - API 服务入口
  - 提供启动、模型探测、会话流式执行、文件解析、存档和导出接口
- `frontend/`
  - Vue 3 + Vite 前端
  - 包含侧栏配置、主时间线、底部输入区和主题样式系统
- `agents.py`
  - Agent 规格、流式回复和导出逻辑
- `graph.py`
  - 多 Agent 执行图编排
- `skill_registry.py`
  - 技能注册与版本选择
- `skills/`
  - 当前内置技能包
- `hub/`
  - 公共配置与模型辅助逻辑

## 已清理内容

仓库已移除旧版 Streamlit UI 及其启动脚本说明，当前仅保留 `FastAPI + Vue` 这条运行链路。

同时建议不要提交以下本地产物：

- `.env`
- `frontend/node_modules`
- `frontend/dist`
- `__pycache__`
- `sessions/*.json`

## 环境要求

- Python 3.11
- Node.js 18+
- npm 9+

## 安装

### 后端

```bash
pip install -r requirements.txt
```

### 前端

```bash
cd frontend
npm install
```

## 配置

复制 `.env.example` 为 `.env`：

```bash
cp .env.example .env
```

核心变量：

- `SHARED_DEEPSEEK_API_KEY`
- `ARK_API_KEY`
- `AGENT_A_MODEL`
- `AGENT_B_MODEL`
- `AGENT_C_MODEL`
- `SUMMARY_MODEL`

默认情况下：

- DeepSeek 模型读取 `SHARED_DEEPSEEK_API_KEY`
- 豆包 / Ark 模型读取 `ARK_API_KEY`

## 启动

### API

```bash
./start_api.sh
```

默认地址：

- `http://127.0.0.1:8000`

### Frontend

```bash
./start_frontend.sh
```

默认地址：

- `http://127.0.0.1:5173`

## 功能说明

- 三位 Agent 独立配置模型、技能和附加提示词
- 主区实时展示多轮讨论、推理内容和摘要
- 支持上传 `txt / md / pdf / docx / csv / json / yaml`
- 支持会话存档与再次加载
- 支持导出 Markdown 与 Mermaid
- 支持浅色 / 深色主题切换

## 前端构建

```bash
cd frontend
npm run build
```

## 目录建议

如果需要继续扩展，建议保持以下边界：

- API 接口集中在 `backend/api.py`
- Agent 运行逻辑集中在 `agents.py` 和 `graph.py`
- 技能元数据集中在 `skills/` 与 `skill_registry.py`
- 界面组件集中在 `frontend/src/components/`

