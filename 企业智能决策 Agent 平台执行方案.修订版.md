# 企业智能决策 Agent 平台执行方案（修订版）

修订日期：2026-09-13  
修订依据：企业智能决策 Agent 平台可行性分析与技术栈评估  
修订原则：不推翻原方案的 Router、Skill、RAG、Text2SQL 和 InventoryRisk 主线，只修正会影响落地正确性的工程顺序和技术边界。

## 一、结论：原执行方案需要修改，但不是重做

原方案的总体方向是对的：

- 以 LangGraph 管理有状态工作流。
- 以 FastAPI 暴露服务。
- 以 Knowledge、Data、Mixed 和 InventoryRisk 作为业务能力。
- 以 Hybrid RAG 和 Text2SQL 作为核心链路。
- 以 Evidence、Review、Trace 和 Evaluation 作为工程化能力。

但原方案有八个必须修改的点：

1. 语义层和指标字典不能等 DataSkill 做完再补。
2. Evidence 不能放在答案生成之后。
3. SQL 安全不能主要依赖 SQLChecker 或 LLM，必须由 AST、只读账号和权限服务共同保证。
4. 权限过滤不能只写在文档里，必须成为检索和 SQL 的强制前置层。
5. MCP 不应在核心工具稳定之前进入主线。
6. LangSmith 不应默认作为生产 Trace 平台。
7. Mixed Planner 不能生成任意任务，只能选受控模板。
8. V0.1 不应该同时追求知识、数据、混合和完整评测。

修订后的目标是：

    先让知识检索和受控只读查询可信
    再让证据和评测可信
    再让库存规则和混合分析可信
    最后才做 MCP、多 Agent 和生产治理

## 二、原方案与修订方案的关键差异

| 主题 | 原执行方案 | 修订建议 | 原因 |
|---|---|---|---|
| 数据语义 | 先做 DataSkill，再逐步完善 | 先做 Schema Catalog、指标字典和查询约束 | 没有语义层，Text2SQL 只能猜业务口径 |
| Evidence | 视为答案后的整理模块 | 检索、SQL 和计算阶段持续生成，答案生成前进入上下文 | 事后证据不能约束模型幻觉 |
| SQL 安全 | SQL Parser、SQL Guard、Checker | SQLGlot AST、只读数据库账号、数据权限服务、执行超时和行数限制 | LLM 不是安全边界，正则也不够可靠 |
| 文档权限 | 检索时加 metadata filter | 检索前强制 ACL 过滤，并支持文档版本和生效日期 | 事后过滤既低效又有泄漏风险 |
| 行级权限 | Permission Filter 注入 SQL | 服务端受控查询层或 PostgreSQL RLS，LLM 不生成用户权限条件 | 任意 SQL 注入行级条件容易漏改和漏查 |
| ChromaDB | 第一版继续使用 | 只用于 MVP，生产前切换 pgvector 或 Qdrant | 并发、备份、过滤和多租户能力有限 |
| BM25 | BM25Retriever | MVP 可用内存实现，生产换 PostgreSQL FTS 或 OpenSearch | 动态文档和大规模场景不适合全量内存重建 |
| MCP | 第十一阶段实现 | 工具稳定后，V1.0 或更晚再 MCP 化 | MCP 会增加认证、网络、版本和可观测复杂度 |
| Planner | 生成任务列表后执行 | 固定模板加白名单，最大步骤数和计划校验 | 动态 Planner 会误调工具或死循环 |
| Review | LLM 审查并重试 | 确定性检查优先，LLM 只做辅助，最多重试一次 | Review 不能替代权限和事实校验 |
| Trace | LangSmith 作为主线 | 开发期 LangSmith，生产期 OpenTelemetry 加 Langfuse 或自托管平台 | 企业数据合规和供应商风险 |
| 前端 | 暂不清楚，复杂前端后置 | V0.2 就加入轻量对话和证据 SPA | 没有前端，业务用户无法验收 |
| 评测 | 后期统一做 | 每个阶段设置门禁，Router、RAG、SQL、Answer 分层评测 | 最后评测会把返工集中到上线前 |

## 三、修订后的技术栈

| 模块 | MVP 选择 | 生产演进 | 修订说明 |
|---|---|---|---|
| Agent 编排 | LangGraph 固定工作流 | LangGraph 加 Temporal 或 Camunda | 不让 Planner 自由生成任意流程 |
| API | FastAPI 加 Pydantic | FastAPI worker 加 API Gateway | 需要后台任务、限流和认证 |
| LLM | Qwen 或 OpenAI 兼容 API | 多模型路由和本地 vLLM | Router、SQL、Answer 使用不同模型等级 |
| Embedding | BGE | 自托管 BGE 或企业模型服务 | 需要版本和质量评测 |
| 向量 | Chroma 或 pgvector | pgvector、Qdrant 或 Milvus | Chroma 只用于 MVP |
| 全文检索 | rank_bm25 | PostgreSQL FTS、OpenSearch 或 Elasticsearch | BM25 思路保留，内存实现替换 |
| Reranker | BGE Reranker | 自托管或专用精排服务 | 控制候选数和 P95 延迟 |
| 业务数据库 | MySQL | MySQL 或企业数据平台 | 事实数据不迁移，除非企业要求 |
| 应用数据库 | PostgreSQL | PostgreSQL 高可用 | 用户、权限、审计、评测和配置 |
| 缓存和状态 | Redis | Redis Cluster 或托管 Redis | TTL 和持久化策略必须明确 |
| SQL 安全 | SQLGlot 加只读账号 | OPA 加受控数据服务 | 不允许 LLM 作为安全边界 |
| 工具层 | 内部 Tool Registry | MCP Gateway | MCP 后置 |
| Trace | Langfuse 自托管或 OTel | OpenTelemetry 加企业观测平台 | LangSmith 仅开发期 |
| 指标监控 | 结构化日志加基础指标 | Prometheus 加 Grafana | 先保证 Trace 和审计，再做大盘 |
| 前端 | React 或 Vue 3 加 TypeScript | 企业门户集成 | V0.2 开始实现 |
| 部署 | Docker Compose | Kubernetes 或云容器 | 生产再引入 Kubernetes |
| 测试 | Pytest 加契约测试 | CI 自动化回归 | 评测必须进入流水线 |

## 四、修订后的开发顺序

### 阶段 0：需求和数据基线

目标：在写 Agent 代码前确定业务口径。

交付：

- 首批用户和场景。
- Schema Catalog。
- 指标字典。
- 文档 ACL 规则。
- 数据范围规则。
- 评测集初版。
- 库存风险公式和阈值配置。

退出条件：

- 每个指标有统一公式和来源。
- 每个业务表有负责人。
- 每个文档有权限和生效时间。
- 关键字段有数据质量规则。

### 阶段 1：API 与工作流骨架

交付：

- FastAPI 项目。
- JWT 或企业身份接入。
- LangGraph 固定图。
- Router 节点。
- run_id、trace_id、thread_id。
- 基础结构化日志。
- 健康检查和错误模型。

退出条件：

- 可以返回 Knowledge、Data、Mixed 和 Clarification 结构化结果。
- 所有请求有 trace_id。
- 不调用任何高风险工具。

### 阶段 2：KnowledgeSkill 与基础 RAG

交付：

- 文档导入、版本、ACL。
- 文本清洗和 Chunk。
- Embedding 和向量检索。
- 基础引用。
- 文档 Evidence。

退出条件：

- 有权文档可以检索。
- 无权文档不能被召回。
- 每条答案有来源和页码或段落。
- RAG Recall@5 达到内部基线。

### 阶段 3：Hybrid RAG 与 Reranker

交付：

- Dense 加 BM25。
- RRF 融合。
- Cross Encoder Reranker。
- 查询改写。
- 多查询检索。
- 检索评测报告。

退出条件：

- Recall@5 达到 85% 以上。
- 引用准确率达到业务可接受水平。
- Reranker 失败可以回退到 RRF。

### 阶段 4：DataSkill 与 SQL 安全

交付：

- Schema Catalog 检索。
- 语义层和指标模板。
- SQL 生成。
- SQLGlot AST 校验。
- 只读数据库账号。
- 行数、列、表、超时和权限检查。
- SQL 执行和审计。
- SQL Evidence。

退出条件：

- 危险 SQL 拦截率 100%。
- 越权查询为 0。
- 金标准 SQL 执行正确率达到 80% 以上。
- SQL 结果能够回放。

### 阶段 5：Evidence 与 Answer

交付：

- Evidence 数据结构。
- Evidence 在 RAG、SQL 和计算阶段持续写入。
- Answer Generator 只使用 Evidence 和确定性结果。
- 引用覆盖检查。
- 无证据拒答策略。

退出条件：

- 答案中的关键数字都能追溯到 SQL 或规则。
- 无证据问题不会编造事实。
- 证据覆盖率达到 90% 以上。

### 阶段 6：Review、权限和 Trace

交付：

- 确定性 Review 检查。
- LLM Review 作为补充。
- 权限矩阵。
- 文档 ACL 前置过滤。
- SQL 行级和列级约束。
- Trace 和审计落库。
- 敏感字段脱敏。

退出条件：

- 越权成功率为 0。
- Review 最多重试一次。
- 全链路可回放。
- 审计记录不可被普通用户修改。

### 阶段 7：InventoryRiskSkill

交付：

- 库存、在途、销售和预测数据接入。
- 风险系数计算。
- ABC 分类和周转天数。
- 阈值配置。
- 预测缺失时的降级策略。
- 风险原因和建议模板。

退出条件：

- 公式经过业务确认。
- 分母为零和缺数据有明确行为。
- 风险结果可解释、可复算。

### 阶段 8：Mixed Agent

交付：

- 固定 Mixed 模板。
- 受控 Planner。
- 并行执行 Reducer。
- 部分失败处理。
- RAG 和 SQL 证据合并。

退出条件：

- Planner 只能使用白名单任务。
- 最大步骤数可控。
- 分支失败不会污染主状态。
- Mixed 问题可以通过评测集。

### 阶段 9：前端和 SSE

交付：

- 对话页。
- 流式进度。
- Evidence 面板。
- SQL 查看。
- 会话历史。
- 反馈入口。

退出条件：

- 业务用户可以完成问题、查看证据和提交反馈。
- POST 流式请求在主流浏览器可用。
- 刷新和断线后可以恢复 run 状态。

### 阶段 10：MCP 与生产化

交付：

- Tool Registry 稳定版本。
- MCP Server 或 MCP Gateway。
- 工具认证和授权。
- 版本管理。
- OpenTelemetry。
- CI/CD、备份、告警和容量测试。

退出条件：

- 外部系统需要复用工具。
- MCP 有独立的安全和审计设计。
- 生产回滚和降级方案通过演练。

## 五、修订后的 Agent 设计

### 5.1 Router

Router 使用三层策略：

1. 规则和显式意图。
2. 语义缓存。
3. LLM Structured Output。

输出：

    {
      "route": "Knowledge | Data | Mixed | Clarify",
      "confidence": 0.0,
      "reason": "..."
    }

条件：

- confidence 低于阈值时进入 Clarify。
- 多轮追问必须带入会话摘要和已填充槽位。
- Router 不决定权限，只决定流程。

### 5.2 Planner

Planner 只处理 Mixed，并且只能输出：

- 已注册任务名称。
- 固定参数。
- 最大步骤数内的依赖关系。

禁止：

- 动态新增工具。
- 动态执行写操作。
- 任意 SQL 或多 Agent 递归。
- 无法验证的自然语言步骤。

### 5.3 State

LangGraph 状态建议区分：

- query：当前问题。
- conversation_summary：会话摘要。
- slots：已识别业务槽位。
- route：路由结果。
- plan：受限计划。
- evidence：证据列表。
- documents：检索结果。
- sql：SQL。
- sql_result：结构化结果。
- inventory_result：规则结果。
- answer：答案。
- review：审查结果。
- error：错误。
- trace_id、run_id、thread_id。

并发分支必须使用 Reducer，例如列表追加、去重和优先级合并。禁止两个节点直接修改同一个可变列表。

### 5.4 Tool Registry

每个工具必须包含：

- name。
- version。
- description。
- input_schema。
- output_schema。
- permission_scope。
- timeout。
- retry_policy。
- idempotency。
- audit_policy。

MVP 先使用内部注册表。工具稳定并需要被其他系统复用时，再映射到 MCP。

## 六、修订后的 RAG 执行方案

    用户问题
      |
    查询改写和多查询
      |
    ACL 和版本预过滤
      |
    Dense 检索 + BM25 检索
      |
    RRF 融合
      |
    Reranker 精排
      |
    Evidence 生成
      |
    Answer 生成

强制规则：

- 权限过滤在检索前执行。
- 文档必须带 version、effective_at、acl。
- 表格和扫描件需要单独解析。
- 无证据时不生成事实性回答。
- 引用必须指向文档版本和页级或段级位置。
- 旧版本文档不可默认进入 Top-K。

## 七、修订后的 SQL 执行方案

    用户问题
      |
    指标识别和 Schema 检索
      |
    语义层模板或 SQL 生成
      |
    SQLGlot AST 校验
      |
    表、列、行和租户权限检查
      |
    只读数据库执行
      |
    结果聚合和缓存
      |
    SQL Evidence
      |
    Answer

必须禁止：

- INSERT、UPDATE、DELETE、DROP、ALTER、TRUNCATE、CREATE。
- SELECT 星号。
- 无 LIMIT 的大明细查询。
- 不在 Schema Catalog 中的表。
- 未经语义层定义的指标公式。
- LLM 生成的权限条件。
- 未超时控制的 SQL。

建议增加：

- 查询模板库。
- 指标级 Few-shot。
- EXPLAIN 预估。
- 结果行数上限。
- 结果缓存。
- SQL 执行结果业务正确性评测。

## 八、修订后的评测计划

### 8.1 评测集

- Router Set：100 到 300 条。
- RAG Set：100 到 300 条。
- SQL Set：100 到 500 条。
- Inventory Set：50 到 150 条。
- Security Set：50 到 200 条。
- Conversation Set：50 到 100 条。

### 8.2 阶段门禁

| 阶段 | 门禁 |
|---|---|
| Router | 准确率大于 90% |
| RAG | Recall@5 大于 85% |
| SQL | 执行正确率大于 80%，危险 SQL 拦截 100% |
| Evidence | 证据覆盖率大于 90% |
| Permission | 越权成功率为 0 |
| Inventory | 业务专家确认公式和结果 |
| Mixed | 白名单计划全部通过 |
| 生产 | P95 延迟小于 5 秒，审计和备份通过 |

## 九、修订后的 V0.1 到 V1.0

### V0.1

只包含：

- FastAPI。
- LangGraph 固定图。
- Router。
- KnowledgeSkill。
- 基础 RAG。
- 只读 DataSkill，限单库或少量表。
- Evidence。
- trace_id。
- 50 到 100 条评测用例。

不包含：

- MCP。
- 多 Agent。
- 动态 Planner。
- InventoryRisk。
- 复杂前端。

### V0.2

新增：

- Hybrid RAG。
- Reranker。
- SQLGlot。
- 权限服务。
- PostgreSQL 应用库。
- 轻量前端。
- SSE。
- 离线评测门禁。

### V0.3

新增：

- InventoryRiskSkill。
- Mixed 固定模板。
- Planner 白名单。
- Review。
- 并发 Reducer。
- 运行监控。

### V1.0

新增：

- MCP。
- OpenTelemetry 和 Langfuse。
- CI/CD。
- 备份、回滚和容量测试。
- 生产权限审计。
- 可选 Kubernetes。

## 十、最终的修改清单

必须修改：

1. DataSkill 前增加语义层和 Schema Catalog。
2. Evidence 放到 Answer 之前生成。
3. SQL 安全改为 SQLGlot、只读账号和权限服务。
4. 前端从可选项改为 V0.2 交付项。
5. MCP 从第十一阶段后移到 V1.0。
6. LangSmith 仅保留开发期，生产使用 OTel 加 Langfuse。
7. Chroma 和 rank_bm25 增加生产迁移条件。
8. Mixed Planner 改为白名单模板。
9. 权限矩阵和越权测试加入验收门禁。
10. InventoryRisk 增加预测缺失、分母为零和数据新鲜度处理。
11. V0.1 范围缩小为知识和受控只读数据。
12. 评测从最后阶段前移到每个阶段。

可以保留：

- FastAPI。
- LangGraph。
- Pydantic。
- Hybrid RAG。
- BGE Embedding 和 Reranker。
- Redis Checkpointer。
- MySQL 作为业务数据源。
- Docker Compose。

建议删除或后置：

- 第一版 MCP。
- 第一版多 Agent。
- 第一版长期记忆。
- 第一版复杂 Planner。
- 第一版 Prometheus 和 Grafana。
- 第一版 Kubernetes。

## 十一、修订后的最终建议

执行方案不需要推翻，但必须从“功能堆叠顺序”改成“可信决策顺序”。

正确顺序是：

    需求和数据口径
      |
    语义层和权限
      |
    Router 与固定工作流
      |
    Knowledge RAG
      |
    受控 SQL
      |
    Evidence
      |
    评测门禁
      |
    InventoryRisk
      |
    Mixed
      |
    MCP 和生产化

只要按这个顺序推进，项目的技术风险会明显低于原方案。
