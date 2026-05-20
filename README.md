# Multi_AgentDecisionCouncil

一个基于 `Vue 3 + FastAPI` 的通用多 Agent 决策工作台。

## 当前交互设计

- 首屏只保留两个核心输入：
  - `项目全局约束`
  - `Judge 判断标准`
- `S/A/B/C` Agent 仍然完整保留。
- Agent 编排不在首屏展开，但可以在 `高级设置 -> Agent 编排` 中完整配置：
  - 启用/禁用 S/A/B/C
  - 模型选择
  - skill / 人设选择
  - 局部 Prompt
- `智能默认配置` 只做摘要展示，不会覆盖用户手动配置。

## 主要能力

- Workspace 切换与保存
- S/A/B/C 多 Agent 串行讨论
- Judge 收敛与结构化决策记忆
- 文档挂载、编辑、选择进入上下文
- 自动模式决定 round mode
- 手动压缩上下文
- 自动阈值压缩上下文

## 启动

后端：

```bash
python -m uvicorn backend.api:app --host 127.0.0.1 --port 8000 --reload
```

前端：

```bash
cd frontend
npm install
npm run dev
```

## 验证要点

- 打开页面后，首屏仍然简洁。
- 点击 `智能默认配置` 里的 `编辑 Agent`，会自动展开高级设置并定位到 Agent 编排。
- 在 `高级设置 -> Agent 编排` 中修改某个 Agent 的启用状态、模型、skill、局部 Prompt 后，保存到 workspace/session。
- 压缩上下文后，`Compact Context` 会在时间线中显示。
