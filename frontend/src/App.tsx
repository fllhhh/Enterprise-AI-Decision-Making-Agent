import {
  Activity,
  CheckCircle2,
  CircleDot,
  Database,
  FileText,
  History,
  GitBranch,
  LoaderCircle,
  Moon,
  Plus,
  Send,
  ShieldCheck,
  Sun,
  ThumbsDown,
  ThumbsUp,
  TriangleAlert
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

type Evidence = {
  evidence_id: string;
  kind: "document" | "data" | "risk";
  source_id: string;
  title: string;
  version: string;
  locator: string;
  excerpt: string;
  score?: number | null;
  metadata?: {
    template_id?: string;
    arguments?: Record<string, string>;
    row_count?: number;
    source?: string;
    effective_at?: string;
    items?: RiskItem[];
  };
};

type RiskItem = {
  product_id: string;
  risk_label: string;
  severity: number;
  quantity_on_hand: number;
  quantity_in_transit: number;
  average_daily_sales: number;
  days_cover: number | null;
  stale: boolean;
  reason: string;
};

type Plan = {
  plan_id: string;
  title: string;
  steps: Array<{ step_id: string; skill: string; required: boolean }>;
};

type StepResult = { step_id: string; skill: string; status: string; error_code?: string | null };
type Review = { passed: boolean; code: string; message: string; retryable: boolean };

type StreamEvent = {
  event: string;
  run_id: string;
  trace_id: string;
  thread_id: string;
  payload: Record<string, unknown>;
};

type HistoryEvent = {
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
};

const EVENT_LABELS: Record<string, string> = {
  run_started: "开始运行",
  route: "路由判断",
  retrieval_started: "检索开始",
  retrieval_completed: "检索完成",
  evidence: "证据生成",
  answer: "回答",
  completed: "完成",
  error: "错误",
  plan_created: "计划已创建",
  step_completed: "步骤完成",
  review_completed: "审校完成",
  retry_started: "自动重试"
};

function App() {
  const [token, setToken] = useState(() => localStorage.getItem("agent.token") ?? "");
  const [threadId, setThreadId] = useState(() => localStorage.getItem("agent.threadId") ?? "");
  const [query, setQuery] = useState("");
  const [answer, setAnswer] = useState("");
  const [status, setStatus] = useState<"idle" | "running" | "error">("idle");
  const [statusText, setStatusText] = useState("等待输入");
  const [route, setRoute] = useState("");
  const [traceId, setTraceId] = useState("");
  const [runId, setRunId] = useState("");
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [history, setHistory] = useState<HistoryEvent[]>([]);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [steps, setSteps] = useState<StepResult[]>([]);
  const [review, setReview] = useState<Review | null>(null);
  const [retryCount, setRetryCount] = useState(0);
  const [error, setError] = useState("");
  const [dark, setDark] = useState(() => localStorage.getItem("agent.theme") === "dark");
  const queryRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    localStorage.setItem("agent.token", token);
  }, [token]);

  useEffect(() => {
    localStorage.setItem("agent.threadId", threadId);
  }, [threadId]);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("agent.theme", dark ? "dark" : "light");
  }, [dark]);

  const evidenceByKind = useMemo(() => {
    const documents = evidence.filter((item) => item.kind === "document");
    const data = evidence.filter((item) => item.kind === "data");
    const risk = evidence.filter((item) => item.kind === "risk");
    return { documents, data, risk };
  }, [evidence]);

  const riskItems = useMemo(
    () => evidenceByKind.risk.flatMap((item) => item.metadata?.items ?? []),
    [evidenceByKind.risk]
  );

  async function sendQuery() {
    const normalizedQuery = query.trim();
    if (!normalizedQuery || status === "running") return;
    if (!token.trim()) {
      setError("请先填写身份令牌");
      return;
    }

    const nextThreadId = threadId.trim() || `thread-${Date.now()}`;
    setThreadId(nextThreadId);
    setError("");
    setAnswer("");
    setEvidence([]);
    setRoute("");
    setTraceId("");
    setRunId("");
    setPlan(null);
    setSteps([]);
    setReview(null);
    setRetryCount(0);
    setStatus("running");
    setStatusText("运行中");

    try {
      const response = await fetch("/api/v1/query/stream", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token.trim()}`,
          "Content-Type": "application/json",
          Accept: "text/event-stream"
        },
        body: JSON.stringify({ query: normalizedQuery, thread_id: nextThreadId })
      });

      if (!response.ok || !response.body) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail?.message ?? `HTTP ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const blocks = buffer.split("\n\n");
        buffer = blocks.pop() ?? "";
        blocks.forEach((block) => {
          const event = parseSseBlock(block);
          if (event) handleEvent(event);
        });
      }
      setStatus("idle");
      setStatusText("等待输入");
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "请求失败";
      setAnswer(message);
      setStatus("error");
      setStatusText("运行失败");
      setError(message);
    }
  }

  function handleEvent(event: StreamEvent) {
    if (event.event === "run_started") {
      setRunId(event.run_id);
      setTraceId(event.trace_id);
      return;
    }
    if (event.event === "route") {
      setRoute(String(event.payload.route ?? ""));
      return;
    }
    if (event.event === "plan_created") {
      setPlan((event.payload.plan as Plan) ?? null);
      return;
    }
    if (event.event === "step_completed") {
      setSteps((items) => [...items.filter((item) => item.step_id !== event.payload.step_id), event.payload as StepResult]);
      return;
    }
    if (event.event === "review_completed") {
      setReview((event.payload.review as Review) ?? null);
      return;
    }
    if (event.event === "retry_started") {
      setRetryCount(Number(event.payload.retry_count ?? 1));
      return;
    }
    if (event.event === "evidence") {
      setEvidence(event.payload.evidence as Evidence[]);
      return;
    }
    if (event.event === "answer") {
      setAnswer(String(event.payload.answer ?? ""));
      return;
    }
    if (event.event === "completed") {
      const payload = event.payload as {
        answer?: string;
        evidence?: Evidence[];
        status?: string;
        plan?: Plan | null;
        review?: Review | null;
        retry_count?: number;
      };
      setAnswer(payload.answer ?? "");
      setEvidence(payload.evidence ?? []);
      setRunId(event.run_id);
      setTraceId(event.trace_id);
      setPlan(payload.plan ?? null);
      setReview(payload.review ?? null);
      setRetryCount(payload.retry_count ?? 0);
      return;
    }
    if (event.event === "error") {
      setAnswer(String(event.payload.message ?? "服务内部错误"));
      setStatus("error");
      setStatusText("运行失败");
    }
  }

  async function loadHistory() {
    if (!token.trim() || !threadId.trim()) return;
    const response = await fetch(`/api/v1/threads/${threadId.trim()}`, {
      headers: { Authorization: `Bearer ${token.trim()}` }
    });
    if (!response.ok) {
      setHistory([]);
      return;
    }
    const payload = (await response.json()) as { events: HistoryEvent[] };
    setHistory(payload.events ?? []);
  }

  async function submitFeedback(rating: 1 | 5) {
    if (!token.trim() || !runId || !threadId.trim()) return;
    await fetch("/api/v1/feedback", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token.trim()}`,
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        run_id: runId,
        thread_id: threadId.trim(),
        rating,
        comment: ""
      })
    });
  }

  function newThread() {
    const next = `thread-${Date.now()}`;
    setThreadId(next);
    setAnswer("");
    setEvidence([]);
    setHistory([]);
    setRoute("");
    setTraceId("");
    setRunId("");
    setPlan(null);
    setSteps([]);
    setReview(null);
    setRetryCount(0);
    setError("");
    queryRef.current?.focus();
  }

  return (
    <div className="min-h-dvh bg-[var(--background)] text-[var(--foreground)] lg:grid lg:grid-cols-[320px_minmax(0,1fr)]">
      <aside className="border-b border-[var(--border)] bg-[var(--card)] p-5 lg:min-h-dvh lg:border-b-0 lg:border-r">
        <div className="flex items-center gap-3">
          <div className="grid size-10 place-items-center rounded-lg bg-[var(--accent)] text-[var(--accent-foreground)] shadow-sm">
            <ShieldCheck className="size-5" aria-hidden="true" />
          </div>
          <div>
            <div className="text-[15px] font-semibold">决策 Agent</div>
            <div className="mt-0.5 text-xs text-[var(--muted-foreground)]">v0.3 运行控制台</div>
          </div>
        </div>

        <div className="mt-6 grid gap-5">
          <label className="grid gap-2 text-sm text-[var(--muted-foreground)]">
            <span>身份令牌</span>
            <textarea
              value={token}
              onChange={(event) => setToken(event.target.value)}
              className="min-h-24 w-full resize-y rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[var(--foreground)] outline-none transition focus:border-[var(--ring)] focus:ring-2 focus:ring-[var(--ring)]/20"
              placeholder="粘贴 access_token"
              autoComplete="off"
            />
          </label>

          <label className="grid gap-2 text-sm text-[var(--muted-foreground)]">
            <span>会话 ID</span>
            <input
              value={threadId}
              onChange={(event) => setThreadId(event.target.value)}
              className="h-11 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 text-[var(--foreground)] outline-none transition focus:border-[var(--ring)] focus:ring-2 focus:ring-[var(--ring)]/20"
              placeholder="留空自动创建"
              autoComplete="off"
            />
          </label>

          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={newThread}
              className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 text-sm transition hover:bg-[var(--muted)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)]"
            >
              <Plus className="size-4" aria-hidden="true" />
              新会话
            </button>
            <button
              type="button"
              onClick={loadHistory}
              className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 text-sm transition hover:bg-[var(--muted)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)]"
            >
              <History className="size-4" aria-hidden="true" />
              历史
            </button>
          </div>
        </div>

        <div className="mt-6 max-h-64 space-y-2 overflow-auto border-t border-[var(--border)] pt-4">
          {history.length === 0 ? (
            <p className="text-sm text-[var(--muted-foreground)]">暂无会话事件</p>
          ) : (
            history.map((item, index) => (
              <div
                key={`${item.event_type}-${index}`}
                className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm"
              >
                <div className="flex items-center gap-2">
                  <CircleDot className="size-3.5 text-[var(--accent)]" aria-hidden="true" />
                  <span>{EVENT_LABELS[item.event_type] ?? item.event_type}</span>
                </div>
              </div>
            ))
          )}
        </div>

        <button
          type="button"
          onClick={() => setDark((value) => !value)}
          className="mt-6 inline-flex min-h-11 items-center gap-2 rounded-lg border border-[var(--border)] px-3 text-sm transition hover:bg-[var(--muted)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)]"
          aria-label={dark ? "切换浅色模式" : "切换深色模式"}
        >
          {dark ? <Sun className="size-4" aria-hidden="true" /> : <Moon className="size-4" aria-hidden="true" />}
          切换主题
        </button>
      </aside>

      <main className="grid min-h-dvh min-w-0 grid-rows-[auto_minmax(0,1fr)_auto]">
        <header className="flex min-h-16 flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] bg-[var(--card)] px-5 py-3">
          <div className="flex items-center gap-2.5">
            <span
              className={`size-2.5 rounded-full ${
                status === "running"
                  ? "animate-pulse bg-[var(--accent)]"
                  : status === "error"
                    ? "bg-[var(--destructive)]"
                    : "bg-[var(--muted-foreground)]"
              }`}
            />
            <span className="text-sm text-[var(--muted-foreground)]">{statusText}</span>
          </div>
          <div className="flex min-w-0 items-center gap-2">
            {route ? (
              <span className="rounded-md bg-[var(--success-soft)] px-2 py-1 text-xs font-medium text-[var(--success)]">
                {route}
              </span>
            ) : null}
            {traceId ? (
              <code className="max-w-52 truncate text-xs text-[var(--muted-foreground)]">{traceId}</code>
            ) : null}
          </div>
        </header>

        <section className="min-h-0 overflow-auto px-5 py-6 md:px-8">
          {(plan || review || retryCount > 0) ? (
            <section className="mx-auto mb-5 max-w-4xl rounded-xl border border-[var(--border)] bg-[var(--card)] p-4" aria-label="运行详情">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <Activity className="size-4 text-[var(--accent)]" aria-hidden="true" />
                  <h2 className="text-sm font-semibold">运行详情</h2>
                </div>
                <div className="flex gap-2 text-xs">
                  {retryCount > 0 ? <span className="rounded-full bg-[var(--warning-soft)] px-2.5 py-1 text-[var(--warning)]">已重试 {retryCount} 次</span> : null}
                  {review ? (
                    <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 ${review.passed ? "bg-[var(--success-soft)] text-[var(--success)]" : "bg-[var(--danger-soft)] text-[var(--destructive)]"}`}>
                      {review.passed ? <CheckCircle2 className="size-3.5" aria-hidden="true" /> : <TriangleAlert className="size-3.5" aria-hidden="true" />}
                      {review.passed ? "审校通过" : "审校未通过"}
                    </span>
                  ) : null}
                </div>
              </div>
              {plan ? (
                <div className="mt-4">
                  <div className="flex items-center gap-2 text-sm font-medium"><GitBranch className="size-4" aria-hidden="true" />{plan.title}</div>
                  <ol className="mt-3 grid gap-2 sm:grid-cols-2">
                    {plan.steps.map((step) => {
                      const result = steps.find((item) => item.step_id === step.step_id);
                      return (
                        <li key={step.step_id} className="flex min-h-11 items-center justify-between rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 text-sm">
                          <span>{step.step_id}</span>
                          <span className="text-xs text-[var(--muted-foreground)]">{result?.status ?? "运行中"}</span>
                        </li>
                      );
                    })}
                  </ol>
                </div>
              ) : null}
              {review ? <p className="mt-3 text-sm text-[var(--muted-foreground)]">{review.message}</p> : null}
            </section>
          ) : null}
          {answer ? (
            <article className="mx-auto max-w-4xl whitespace-pre-wrap break-words rounded-lg border border-[var(--border)] bg-[var(--card)] p-5 text-base leading-7">
              {answer}
            </article>
          ) : (
            <div className="mx-auto grid min-h-48 max-w-4xl place-items-center rounded-lg border border-dashed border-[var(--border)] text-sm text-[var(--muted-foreground)]">
              输入问题开始查询
            </div>
          )}

          {evidence.length > 0 ? (
            <div className="mx-auto mt-5 max-w-4xl">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-sm font-semibold">证据</h2>
                <span className="text-xs text-[var(--muted-foreground)]">{evidence.length} 条</span>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                {evidence.map((item) => (
                  <article
                    key={item.evidence_id}
                    className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-4"
                  >
                    <div className="flex items-start gap-2.5">
                      {item.kind === "data" ? (
                        <Database className="mt-0.5 size-4 shrink-0 text-[var(--warning)]" aria-hidden="true" />
                      ) : item.kind === "risk" ? (
                        <TriangleAlert className="mt-0.5 size-4 shrink-0 text-[var(--risk)]" aria-hidden="true" />
                      ) : (
                        <FileText className="mt-0.5 size-4 shrink-0 text-[var(--accent)]" aria-hidden="true" />
                      )}
                      <div className="min-w-0">
                        <div className="truncate text-sm font-medium">{item.title}</div>
                        <div className="mt-1 truncate text-xs text-[var(--muted-foreground)]">
                          {[item.source_id, item.version, item.locator].filter(Boolean).join(" · ")}
                        </div>
                      </div>
                    </div>
                    <p className="mt-3 line-clamp-4 text-sm leading-6 text-[var(--muted-foreground)]">
                      {item.excerpt}
                    </p>
                    {item.metadata?.template_id ? (
                      <code className="mt-3 block overflow-x-auto rounded-md bg-[var(--muted)] px-3 py-2 text-xs">
                        template={item.metadata.template_id}
                      </code>
                    ) : null}
                  </article>
                ))}
              </div>
            </div>
          ) : null}

          {riskItems.length > 0 ? (
            <section className="mx-auto mt-5 max-w-4xl" aria-labelledby="risk-title">
              <div className="mb-3 flex items-center justify-between">
                <h2 id="risk-title" className="text-sm font-semibold">库存风险</h2>
                <span className="text-xs text-[var(--muted-foreground)]">历史销量代理口径</span>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                {riskItems.map((item) => (
                  <article key={item.product_id} className="risk-card rounded-xl border border-[var(--border)] bg-[var(--card)] p-4" data-severity={item.severity}>
                    <div className="flex items-start justify-between gap-3">
                      <div><div className="font-semibold">{item.product_id}</div><div className="mt-1 text-sm text-[var(--muted-foreground)]">{item.reason}</div></div>
                      <span className="shrink-0 rounded-full bg-[var(--risk-soft)] px-2.5 py-1 text-xs font-semibold text-[var(--risk)]">{item.risk_label}</span>
                    </div>
                    <dl className="mt-4 grid grid-cols-3 gap-2 border-t border-[var(--border)] pt-3 text-sm tabular-nums">
                      <div><dt className="text-xs text-[var(--muted-foreground)]">在库</dt><dd className="mt-1 font-medium">{item.quantity_on_hand}</dd></div>
                      <div><dt className="text-xs text-[var(--muted-foreground)]">日均销量</dt><dd className="mt-1 font-medium">{item.average_daily_sales}</dd></div>
                      <div><dt className="text-xs text-[var(--muted-foreground)]">可售天数</dt><dd className="mt-1 font-medium">{item.days_cover ?? "—"}</dd></div>
                    </dl>
                    {item.stale ? <p className="mt-3 inline-flex items-center gap-1 text-xs text-[var(--warning)]"><TriangleAlert className="size-3.5" aria-hidden="true" />库存快照已过期</p> : null}
                  </article>
                ))}
              </div>
            </section>
          ) : null}
        </section>

        <footer className="border-t border-[var(--border)] bg-[var(--card)] px-5 py-4">
          <div className="mx-auto max-w-4xl">
            {error ? (
              <p className="mb-2 text-sm text-[var(--destructive)]">{error}</p>
            ) : null}
            <div className="rounded-lg border border-[var(--border)] bg-[var(--background)] p-2">
              <textarea
                ref={queryRef}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    sendQuery();
                  }
                }}
                className="min-h-20 w-full resize-none bg-transparent px-2 py-1 text-base outline-none placeholder:text-[var(--muted-foreground)]"
                placeholder="输入企业知识或经营数据问题"
              />
              <div className="mt-2 flex items-center justify-end gap-2">
                {answer ? (
                  <>
                    <button
                      type="button"
                      onClick={() => submitFeedback(5)}
                      className="inline-flex size-11 items-center justify-center rounded-lg border border-[var(--border)] transition hover:bg-[var(--muted)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)]"
                      aria-label="有帮助"
                    >
                      <ThumbsUp className="size-4" aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      onClick={() => submitFeedback(1)}
                      className="inline-flex size-11 items-center justify-center rounded-lg border border-[var(--border)] transition hover:bg-[var(--muted)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)]"
                      aria-label="无帮助"
                    >
                      <ThumbsDown className="size-4" aria-hidden="true" />
                    </button>
                  </>
                ) : null}
                <button
                  type="button"
                  onClick={sendQuery}
                  disabled={status === "running"}
                  className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-[var(--accent)] px-4 text-sm font-medium text-[var(--accent-foreground)] transition hover:brightness-110 disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)]"
                >
                  {status === "running" ? (
                    <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
                  ) : (
                    <Send className="size-4" aria-hidden="true" />
                  )}
                  发送
                </button>
              </div>
            </div>
          </div>
        </footer>
      </main>
    </div>
  );
}

function parseSseBlock(block: string): StreamEvent | null {
  const eventLine = block.split("\n").find((line) => line.startsWith("event:"));
  const dataLine = block.split("\n").find((line) => line.startsWith("data:"));
  if (!eventLine || !dataLine) return null;
  try {
    return JSON.parse(dataLine.slice(5).trim()) as StreamEvent;
  } catch {
    return null;
  }
}

export default App;
