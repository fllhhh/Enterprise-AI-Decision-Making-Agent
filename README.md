# 企业智能决策 Agent 平台 v0.2

一个可运行、可验证的企业智能决策 Agent 可信纵向切片。服务通过 JWT 识别用户，以 LangGraph 固定工作流处理知识问答和受控数据查询，在生成答案前建立 Evidence，并通过 SSE 和 React 前端暴露业务可验收界面。

## v0.2 能力

- `KnowledgeSkill`：本地 BGE Embedding、持久化 Chroma、BM25、RRF、Cross-Encoder Reranker、文档版本和 ACL 前置过滤、引用型答案。
- `DataSkill`：保留三个已审批 ORM 查询模板；所有 PostgreSQL 查询在执行前通过 SQLGlot AST 白名单校验。
- PostgreSQL 应用库：文档授权、数据授权、会话事件、审计和反馈。
- SSE 流式接口、会话历史和 React + Vite + Tailwind CSS 对话前端。
- LangGraph 固定流程：`normalize -> route -> knowledge|data|clarify|mixed_unsupported -> validate_evidence -> respond`。
- 本地 HS256 JWT，包含 `sub`、`department`、`roles`、`iss`、`aud`、`iat`、`exp`。
- 每个请求返回 `run_id`、`trace_id`、`thread_id`，并输出结构化运行日志。
- PostgreSQL 业务库使用只读账号、参数绑定、结果行数限制、查询超时和 SQLGlot 白名单。
- 112 条离线评测集，覆盖 Router、Hybrid RAG、Data、Security、SQLGlot、Reranker fallback 和 SSE。

明确不包含 Mixed、Planner、InventoryRisk、自由 Text2SQL、MCP、多 Agent、Redis、生产级数据库高可用和生产 Trace。

## 快速启动

要求 Python 3.13、PostgreSQL 16 或更高版本，以及一个 OpenAI 兼容 Chat Completion API。完整安装步骤见 [PostgreSQL 安装文档](docs/postgresql-install.md)。

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[rag,dev]"
Copy-Item .env.example .env
```

编辑 `.env`，至少配置：

```dotenv
LLM_BASE_URL=http://127.0.0.1:8001/v1
LLM_API_KEY=your-key
LLM_MODEL=qwen-plus
JWT_SECRET=replace-with-at-least-32-random-characters
POSTGRES_DSN=postgresql+asyncpg://agent_ro:agent_ro@127.0.0.1:5432/enterpriseAgent
```

为当前 PowerShell 临时加入 PostgreSQL 命令路径（当前实际安装目录为 `D:\psql\bin`）：

```powershell
$env:Path += ";D:\psql\bin"
psql --version
```

连接管理员数据库：

```powershell
psql -h 127.0.0.1 -p 5432 -U postgres -d postgres
```

如果数据库已经创建为 `enterpriseAgent`，直接切换并执行初始化脚本：

```sql
\c "enterpriseAgent"
\i D:/python/project/enterpriseAgent/database/postgres/001_schema.sql
\i D:/python/project/enterpriseAgent/database/postgres/002_seed.sql
\i D:/python/project/enterpriseAgent/database/postgres/003_app_schema.sql
```

也可以通过项目脚本交互式输入管理员密码并完成初始化：

```powershell
.\scripts\init_postgres.ps1
```

初始化脚本会创建业务表、只读视图、`agent_ro` 只读账号和演示数据。应用启动时不会自动建表。

首次启动前导入中文知识样例：

```powershell
.\.venv\Scripts\enterprise-agent.exe ingest-demo
```

签发本地演示 token：

```powershell
.\.venv\Scripts\enterprise-agent.exe issue-token `
  --user demo.sales `
  --department sales `
  --roles employee
```

启动服务：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

调用查询接口：

```powershell
$token = "<上一步输出的 access_token>"
Invoke-RestMethod `
  -Uri http://127.0.0.1:8000/api/v1/query `
  -Method Post `
  -Headers @{ Authorization = "Bearer $token"; "X-Trace-ID" = "demo-trace-001" } `
  -ContentType "application/json" `
  -Body '{"query":"统计2026年7月销售额","thread_id":"demo-thread"}'
```

OpenAPI 页面位于 `http://127.0.0.1:8000/docs`。

前端界面位于 `http://127.0.0.1:8000/ui`。在界面中填写本地 token 后可发起流式查询。

前端开发模式：

```powershell
cd frontend
npm install
npm run dev
```

Vite 默认监听 `http://127.0.0.1:5173`，并把 `/api` 和 `/health` 代理到 `http://127.0.0.1:8000`。

生产构建：

```powershell
cd frontend
npm run build
```

构建产物位于 `frontend/dist`，FastAPI 会自动从该目录托管 `/ui`。

## API

### `POST /api/v1/query`

```json
{
  "query": "销售总额按哪个日期统计？",
  "thread_id": "demo-thread"
}
```

响应状态固定为：

- `answered`：已生成有证据的答案。
- `clarify`：信息不足、没有模板或没有可访问证据。
- `unsupported`：请求属于当前版本明确不支持的 Mixed 场景。
- `error`：保留给结构化错误响应。

### `POST /api/v1/query/stream`

请求体与非流式接口相同，响应为 `text/event-stream`。事件包括 `run_started`、`route`、`retrieval_started`、`evidence`、`answer`、`retrieval_completed`、`completed` 和 `error`。

### 会话和反馈

- `GET /api/v1/threads/{thread_id}`：读取会话事件。
- `POST /api/v1/feedback`：提交 1 到 5 分反馈。

### 健康检查

- `GET /health/live`：进程存活。
- `GET /health/ready`：检查 Embedding、Chroma 和 PostgreSQL，任一失败返回 HTTP 503。

## 测试与评测

不安装本地 BGE 和 Chroma，只运行单元、契约和 Fake 端到端测试：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
```

运行 112 条离线评测：

```powershell
.\.venv\Scripts\enterprise-agent.exe evaluate --mode fake
```

评测报告默认写入 `reports/v0.2-evaluation.json`，验收门禁为：

- Router accuracy 大于等于 90%。
- Hybrid Recall@5 大于等于 85%。
- 支持的数据模板正确率大于等于 90%。
- 越权或无证据事实回答成功数为 0。
- SQLGlot 危险 SQL 拦截率等于 100%。
- Reranker fallback 成功率等于 100%。
- SSE 事件契约通过率等于 100%。
- Evidence 覆盖率大于等于 90%。
- 全部响应具有 trace_id。

真实模式：

```powershell
.\.venv\Scripts\enterprise-agent.exe evaluate --mode real
```

真实模式要求 `.env`、PostgreSQL、BGE 和 Chat API 均可用。

已准备好 PostgreSQL 实例时，可以运行显式集成测试：

```powershell
$env:POSTGRES_TEST_DSN = "postgresql+asyncpg://agent_ro:agent_ro@127.0.0.1:5432/enterpriseAgent"
.\.venv\Scripts\python.exe -m pytest -m integration -q
```

## 数据与安全边界

- LLM 不生成 ORM 表达式、表名、权限条件或文档 ACL。
- DataSkill 只能选择服务端注册的模板，未知参数和越界日期会被拒绝。
- 所有 PostgreSQL 查询必须通过 SQLGlot 表、列、`SELECT`、`LIMIT` 白名单校验。
- 部门范围由 JWT 可信 claim 和服务端模板注入，客户端不能自行指定。
- 知识检索先执行部门、角色、生效时间和激活版本过滤，再做向量检索。
- 低于 `RETRIEVAL_MIN_SCORE` 的片段不会进入 Answer 上下文。
- 数据答案由确定性渲染器生成，不经过自由文本数字改写。

PostgreSQL 必须提供字段兼容的只读视图：

- `v_ai_sales_orders(order_id, order_date, department_id, region, customer_id, product_id, quantity, amount)`
- `v_ai_inventory_snapshots(snapshot_date, department_id, warehouse_id, product_id, quantity_on_hand, quantity_in_transit)`

## 项目结构

```text
app/
  api/           FastAPI 路由和认证依赖
  domain/        公共数据契约与错误类型
  evaluation/    v0.1 和 v0.2 评测集及运行器
  graph/         LangGraph 状态与固定工作流
  infra/         Hybrid RAG、SQLGlot、权限、应用库、日志和测试替身
  resources/     演示知识文档
  security/      JWT 签发与验证
  skills/        Router、KnowledgeSkill、DataSkill
database/postgres/  PostgreSQL Schema、视图、账号和演示数据
frontend/           React + Vite + Tailwind CSS 对话前端
tests/           单元、ACL、API 和评测门禁测试
```
