// Typed client for the controller API. Requests go to same-origin /api/*,
// which app/api/[...path]/route.ts proxies to the backend.

export type Json = null | boolean | number | string | Json[] | { [k: string]: Json };

export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export type InvokeSpec = {
  method: HttpMethod;
  url: string;
  headers?: Record<string, string>;
  body_template?: Json;
  timeout_s?: number;
};

export type PollSpec = {
  method?: "GET" | "POST";
  url_template: string;
  headers?: Record<string, string>;
  body_template?: Json;
  interval_s?: number;
  timeout_s?: number;
  done_when: string;
  failed_when?: string | null;
  extract?: Record<string, string>;
};

export type Contract = {
  invoke: InvokeSpec;
  poll?: PollSpec | null;
  extract?: Record<string, string>;
};

export type Agent = {
  id: string;
  name: string;
  description: string;
  contract: Contract;
  params: Record<string, Json>;
  enabled: boolean;
  created_at: string | null;
  updated_at: string | null;
};

export type Preset = {
  id: string;
  name: string;
  description?: string;
  category?: "demo" | "template";
  contract: Contract;
  params?: Record<string, Json>;
};

export type Expectations = {
  equals?: Json;
  contains?: string[];
  not_contains?: string[];
  regex?: string;
  jsonpath_equals?: Record<string, Json>;
  max_latency_ms?: number;
};

export type Case = { id: string; input: Json; expected: Expectations | null; tags: string[] };

export type Dataset = {
  id: string;
  name: string;
  description: string;
  source_type: "local" | "uri";
  uri: string | null;
  case_count: number;
  tags: string[];
  created_at: string | null;
  updated_at: string | null;
};

export type ParseError = { line?: number | null; message: string };
export type ParseResult = { format: string | null; count: number; preview: Case[]; errors: ParseError[] };

export type ScalarStats = {
  count: number;
  mean: number | null;
  std: number | null;
  min: number | null;
  max: number | null;
  p50: number | null;
  p90: number | null;
  p95: number | null;
  p99: number | null;
};

export type AgentSummary = {
  agent_id: string;
  agent_name: string;
  n_results: number;
  n_cases: number;
  trials: number;
  outcome_counts: Record<string, number>;
  outcome_rates: Record<string, number>;
  n_scored: number;
  pass_rate: number | null;
  pass_rate_ci95: [number, number] | null;
  success_rate: number | null;
  error_rate: number | null;
  scalars: Record<string, ScalarStats>;
  latency_histogram?: { edges: number[]; counts: number[]; overflow: number } | null;
  consistency: {
    basis: "passed" | "success";
    pass_all_trials_rate: number;
    pass_any_trial_rate: number;
    flaky_cases: number;
    flaky_case_ids: string[];
  } | null;
  by_tag: Record<string, { n: number; pass_rate: number | null; error_rate: number | null; latency_p50: number | null }>;
};

export type RunStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export type RunOptions = {
  concurrency?: number;
  repeats?: number;
  score_expectations?: boolean;
  body_truncate_chars?: number;
};

export type Run = {
  id: string;
  name: string | null;
  status: RunStatus;
  dataset_id: string | null;
  dataset_name: string | null;
  dataset_uri: string | null;
  agents: { id: string; name: string }[];
  options: RunOptions;
  progress: { completed: number; total: number };
  summary: Record<string, AgentSummary> | null;
  error: string | null;
  tester_version: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
};

export type ResultRow = {
  id: number;
  agent_id: string;
  agent_name: string | null;
  case_id: string;
  trial: number;
  tags: string[];
  outcome_class: string;
  passed: boolean | null;
  failures: string[];
  latency_ms: number | null;
  status_code: number | null;
  error: string | null;
  final_text_preview: string | null;
};

export type TrajectoryStep = {
  phase: "invoke" | "poll";
  attempt?: number;
  method?: string;
  url?: string;
  request_headers?: Record<string, string>;
  request_body?: Json;
  status_code?: number;
  content_type?: string | null;
  response_body?: string;
  started_ms?: number;
  latency_ms?: number;
  error?: string;
};

export type Trajectory = { steps?: TrajectoryStep[]; warnings?: string[]; poll_steps_omitted?: number };

export type ResultDetail = ResultRow & {
  input: Json;
  expected: Expectations | null;
  final_text: string | null;
  metrics: Record<string, number>;
  extracted: Record<string, Json>;
  trajectory: Trajectory;
};

/** Shape returned by POST /api/agents/test (the runner's CaseResult). */
export type TestResult = Omit<ResultDetail, "id" | "final_text_preview">;

export type Page<T> = { items: T[]; total: number; limit: number; offset: number };

export type Meta = {
  version: string;
  tester_version: string;
  runner_mode: "inprocess" | "docker";
  auth_enabled: boolean;
  max_concurrent_runs: number;
  outcome_classes: Record<string, string>;
  allow_literal_secrets: boolean;
};

export type FieldError = { loc?: string; line?: number | null; message: string };

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
    public errors: FieldError[] = [],
  ) {
    super(detail);
  }

  /** Errors whose location starts with `prefix`, keyed by the remainder. */
  fieldErrors(prefix = ""): Record<string, string> {
    const out: Record<string, string> = {};
    for (const e of this.errors) {
      if (e.loc && e.loc.startsWith(prefix)) out[e.loc.slice(prefix.length).replace(/^\./, "")] = e.message;
    }
    return out;
  }
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.detail;
  if (e instanceof Error) return e.message;
  return String(e);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      ...init,
      headers: {
        ...(init.body && !(init.body instanceof FormData) ? { "Content-Type": "application/json" } : {}),
        ...init.headers,
      },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "Cannot reach the Agent Tester API. Is the controller running?");
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!res.ok) {
    const b = (body ?? {}) as { detail?: unknown; errors?: FieldError[] };
    const detail = typeof b.detail === "string" ? b.detail : res.statusText || `HTTP ${res.status}`;
    throw new ApiError(res.status, detail, Array.isArray(b.errors) ? b.errors : []);
  }
  return body as T;
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  body: body === undefined ? undefined : JSON.stringify(body),
});

function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

export type AgentInput = Pick<Agent, "name" | "description" | "contract" | "params" | "enabled">;

export const api = {
  meta: () => request<Meta>("/meta"),
  presets: () => request<Preset[]>("/presets"),
  demo: () => request<{ agent_ids: string[]; dataset_id: string }>("/demo", json("POST")),

  agents: () => request<Agent[]>("/agents"),
  agent: (id: string) => request<Agent>(`/agents/${id}`),
  createAgent: (body: AgentInput) => request<Agent>("/agents", json("POST", body)),
  updateAgent: (id: string, body: Partial<AgentInput>) => request<Agent>(`/agents/${id}`, json("PATCH", body)),
  duplicateAgent: (id: string) => request<Agent>(`/agents/${id}/duplicate`, json("POST")),
  deleteAgent: (id: string) => request<void>(`/agents/${id}`, json("DELETE")),
  testAgent: (body: { contract: Contract; params: Record<string, Json>; input: Json; expected?: Expectations | null }) =>
    request<TestResult>("/agents/test", json("POST", body)),

  datasets: () => request<Dataset[]>("/datasets"),
  dataset: (id: string) => request<Dataset>(`/datasets/${id}`),
  createDataset: (body: { name: string; description?: string; source_type: "local" | "uri"; uri?: string | null }) =>
    request<Dataset>("/datasets", json("POST", body)),
  updateDataset: (id: string, body: { name?: string; description?: string; uri?: string }) =>
    request<Dataset>(`/datasets/${id}`, json("PATCH", body)),
  deleteDataset: (id: string) => request<void>(`/datasets/${id}`, json("DELETE")),
  parseDataset: (text: string, filename?: string) =>
    request<ParseResult>("/datasets/parse", json("POST", { text, filename })),
  importDataset: (id: string, file: File, mode: "replace" | "append") => {
    const fd = new FormData();
    fd.append("file", file);
    return request<Dataset>(`/datasets/${id}/import${qs({ mode })}`, { method: "POST", body: fd });
  },
  cases: (id: string, params: { q?: string; limit?: number; offset?: number }) =>
    request<Page<Case>>(`/datasets/${id}/cases${qs(params)}`),
  datasetExportUrl: (id: string) => `/api/datasets/${id}/export`,

  runs: (params: { q?: string; status?: string; limit?: number; offset?: number } = {}) =>
    request<Page<Run>>(`/runs${qs(params)}`),
  run: (id: string) => request<Run>(`/runs/${id}`),
  createRun: (body: {
    name?: string | null;
    agent_ids: string[];
    dataset_id?: string | null;
    dataset_uri?: string | null;
    options: RunOptions;
  }) => request<Run>("/runs", json("POST", body)),
  cancelRun: (id: string) => request<Run>(`/runs/${id}/cancel`, json("POST")),
  rerun: (id: string) => request<Run>(`/runs/${id}/rerun`, json("POST")),
  deleteRun: (id: string) => request<void>(`/runs/${id}`, json("DELETE")),
  results: (
    id: string,
    params: { agent_id?: string; outcome?: string; q?: string; sort?: string; limit?: number; offset?: number },
  ) => request<Page<ResultRow>>(`/runs/${id}/results${qs(params)}`),
  result: (runId: string, resultId: number) => request<ResultDetail>(`/runs/${runId}/results/${resultId}`),
  runExportUrl: (id: string, format: "json" | "csv" | "junit") => `/api/runs/${id}/export${qs({ format })}`,
};
