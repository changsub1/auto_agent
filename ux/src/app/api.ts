export type AppConfig = {
  routing_modes: string[];
  dashboard_modes: string[];
  reasoning_efforts: string[];
  reference_profiles: Record<string, string>;
  defaults: {
    dashboard_mode?: string | null;
    routing_mode?: string | null;
    planner_count?: number;
    code_agent_count?: number;
    qa_agent_count?: number;
    model?: string | null;
    reasoning_effort?: string | null;
    max_fix_iterations?: number;
    timeout_seconds?: number;
    codex_homes?: Record<string, unknown>;
  };
  providers: Array<{
    name: string;
    account: string;
    configured: boolean;
    status: string;
    display_only: boolean;
  }>;
};

export type ProviderCliStatus = {
  provider: string;
  installed: boolean;
  executable?: string | null;
  version?: string | null;
  logged_in?: boolean | null;
  account?: string | null;
  plan?: string | null;
  status: string;
  detail: string;
};

export type ProviderReasoningLevel = {
  effort: string;
  description: string;
};

export type ProviderModelInfo = {
  id: string;
  display_name: string;
  description: string;
  default_reasoning_level?: string | null;
  supported_reasoning_levels: ProviderReasoningLevel[];
  visibility?: string | null;
  supported_in_api?: boolean | null;
};

export type ProviderModelCatalog = {
  provider: string;
  ok: boolean;
  source: string;
  models: ProviderModelInfo[];
  error: string;
};

export type UsageLimitInfo = {
  name: string;
  available: boolean;
  used_percent?: number | null;
  remaining_percent?: number | null;
  reset_at?: string | null;
  reset_at_epoch?: number | null;
  window_duration_mins?: number | null;
  raw: string;
};

export type RuntimeUsageSnapshot = {
  provider: string;
  source: string;
  ok: boolean;
  limits: UsageLimitInfo[];
  message: string;
};

export type RuntimeHealthSnapshot = {
  status: string;
  codex: ProviderCliStatus;
  claude: ProviderCliStatus;
  discord_token_configured: boolean;
  executable_qa_enabled: boolean;
  codex_child_windows_sandbox?: string | null;
};

export type AgentProviderConfig = {
  agent_id: string;
  provider?: string;
  account?: string | null;
  codex_home?: string | null;
  model?: string | null;
  reasoning_effort?: string | null;
  enabled?: boolean;
};

export type LocalAppSettings = {
  default_provider?: string;
  default_account?: string | null;
  default_codex_home?: string | null;
  default_model?: string | null;
  default_reasoning_effort?: string | null;
  agent_configs: AgentProviderConfig[];
};

export type WorkflowStage = {
  id: string;
  type: "planning" | "approval" | "contract" | "scaffold" | "code" | "integration" | "qa" | "fix";
  agents?: string[];
  after?: string[];
  parallel?: boolean;
};

export type WorkflowGraph = {
  mode: "manual";
  stages: WorkflowStage[];
};

export type RunSummary = {
  run_id: string;
  status: string;
  user_request: string;
  created_at?: string | null;
  updated_at?: string | null;
  route_mode?: string | null;
  dashboard_mode?: string | null;
  run_dir: string;
  artifact_count: number;
};

export type RunDetail = RunSummary & {
  state: {
    routing?: {
      mode?: string;
      requested_mode?: string;
      pipeline?: string[];
      code_agent_count?: number;
      qa_agent_count?: number;
    };
    parallel?: {
      code_agent_count?: number;
      qa_agent_count?: number;
    };
    agent_sessions?: Record<
      string,
      {
        session_id?: string | null;
        codex_home?: string | null;
        model?: string | null;
        reasoning_effort?: string | null;
        last_step?: string | null;
      }
    >;
    artifacts?: Record<string, string>;
    approval_history?: Array<Record<string, string>>;
    dashboard_config?: Record<string, unknown>;
    [key: string]: unknown;
  };
};

export type TimelineEvent = {
  id: string;
  run_id: string;
  kind: "system" | "agent" | "user" | "approval" | "error" | string;
  actor: string;
  who: string;
  at: string;
  time: string;
  status: "idle" | "ready" | "running" | "waiting" | "error" | "done" | "paused" | "queued" | string;
  title: string;
  summary: string;
  details: string[];
  artifacts: Array<{ name: string; path: string; type: "file" | "image" | "log" | "directory" | "unknown" }>;
  raw: Record<string, unknown>;
};

export type ArtifactInfo = {
  path: string;
  name: string;
  kind: "file" | "image" | "log" | "directory" | "unknown";
  type?: "file" | "image" | "log" | "directory" | "unknown";
  size_bytes?: number | null;
  modified_at?: string | null;
  updated_at?: string | null;
  media_type?: string | null;
  source: string;
  exists?: boolean;
  stage?: string | null;
  role?: string | null;
};

export type ArtifactContent = {
  path: string;
  name: string;
  kind: string;
  media_type?: string | null;
  size_bytes: number;
  encoding: "utf-8" | "base64" | string;
  content: string;
  truncated: boolean;
};

export type ActiveStepInfo = {
  run_id: string;
  status: string;
  stage?: string | null;
  agent_id?: string | null;
  pid?: number | null;
  started_at?: string | null;
  interruptible: boolean;
  active: boolean;
  label: string;
  updated_at?: string | null;
  raw: Record<string, unknown>;
};

export type LogFileInfo = {
  path: string;
  name: string;
  size_bytes: number;
  modified_at: string;
  updated_at: string;
  stage?: string | null;
  agent_id?: string | null;
  stream?: string | null;
};

export type LogTail = {
  path: string;
  name: string;
  size_bytes: number;
  modified_at: string;
  updated_at: string;
  line_count: number;
  encoding: "utf-8" | string;
  content: string;
  truncated: boolean;
};

export type CreateRunInput = {
  user_request: string;
  routing_mode: string;
  dashboard_mode?: string;
  planner_count?: number;
  code_agent_count?: number;
  qa_agent_count?: number;
  model?: string | null;
  reasoning_effort?: string | null;
  timeout_seconds?: number;
  max_fix_iterations?: number;
  planner_a_codex_home?: string | null;
  planner_b_codex_home?: string | null;
  planner_c_codex_home?: string | null;
  architect_codex_home?: string | null;
  scaffold_codex_home?: string | null;
  integrator_codex_home?: string | null;
  code_agent_codex_homes?: Array<string | null>;
  qa_agent_codex_homes?: Array<string | null>;
  agent_configs?: AgentProviderConfig[];
  workflow_graph?: WorkflowGraph | null;
};

declare global {
  interface Window {
    __ORCHESTRA_API_BASE__?: string;
    __TAURI_INTERNALS__?: unknown;
  }
}

let apiBasePromise: Promise<string> | null = null;

export function getApiBaseUrl(): Promise<string> {
  if (!apiBasePromise) {
    apiBasePromise = resolveApiBaseUrl();
  }
  return apiBasePromise;
}

async function resolveApiBaseUrl(): Promise<string> {
  if (window.__ORCHESTRA_API_BASE__) {
    return window.__ORCHESTRA_API_BASE__;
  }
  if (window.__TAURI_INTERNALS__) {
    try {
      const tauri = await import("@tauri-apps/api/core");
      const baseUrl = await tauri.invoke<string>("api_base_url");
      if (baseUrl) return baseUrl;
    } catch {
      // Fall through to browser dev defaults.
    }
  }
  return import.meta.env.VITE_ORCHESTRA_API_BASE || "http://127.0.0.1:8765";
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const baseUrl = await getApiBaseUrl();
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export function loadConfig(): Promise<AppConfig> {
  return apiFetch<AppConfig>("/config");
}

export function listProviders(): Promise<ProviderCliStatus[]> {
  return apiFetch<ProviderCliStatus[]>("/providers");
}

export function getCodexStatus(): Promise<ProviderCliStatus> {
  return apiFetch<ProviderCliStatus>("/providers/codex/status");
}

export function getCodexModels(bundled = false): Promise<ProviderModelCatalog> {
  return apiFetch<ProviderModelCatalog>(`/providers/codex/models?bundled=${bundled ? "true" : "false"}`);
}

export function getRuntimeHealth(): Promise<RuntimeHealthSnapshot> {
  return apiFetch<RuntimeHealthSnapshot>("/runtime/health");
}

export function getRuntimeUsage(): Promise<RuntimeUsageSnapshot> {
  return apiFetch<RuntimeUsageSnapshot>("/runtime/usage");
}

export function loadSettings(): Promise<LocalAppSettings> {
  return apiFetch<LocalAppSettings>("/settings");
}

export function saveSettings(settings: LocalAppSettings): Promise<LocalAppSettings> {
  return apiFetch<LocalAppSettings>("/settings", {
    method: "PUT",
    body: JSON.stringify(settings),
  });
}

export function listRuns(limit = 25): Promise<RunSummary[]> {
  return apiFetch<RunSummary[]>(`/runs?limit=${limit}`);
}

export function createRun(input: CreateRunInput): Promise<RunDetail> {
  return apiFetch<RunDetail>("/runs", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function getRun(runId: string): Promise<RunDetail> {
  return apiFetch<RunDetail>(`/runs/${encodeURIComponent(runId)}`);
}

export function getEvents(runId: string): Promise<TimelineEvent[]> {
  return apiFetch<TimelineEvent[]>(`/runs/${encodeURIComponent(runId)}/events`);
}

export function getActiveStep(runId: string): Promise<ActiveStepInfo> {
  return apiFetch<ActiveStepInfo>(`/runs/${encodeURIComponent(runId)}/active-step`);
}

export function listLogs(runId: string): Promise<LogFileInfo[]> {
  return apiFetch<LogFileInfo[]>(`/runs/${encodeURIComponent(runId)}/logs`);
}

export function readLogTail(runId: string, path: string, lines = 120): Promise<LogTail> {
  return apiFetch<LogTail>(
    `/runs/${encodeURIComponent(runId)}/logs/tail?path=${encodeURIComponent(path)}&lines=${lines}`,
  );
}

export function listArtifacts(runId: string): Promise<ArtifactInfo[]> {
  return apiFetch<ArtifactInfo[]>(`/runs/${encodeURIComponent(runId)}/artifacts`);
}

export function readArtifact(runId: string, path: string): Promise<ArtifactContent> {
  return apiFetch<ArtifactContent>(
    `/runs/${encodeURIComponent(runId)}/artifacts/content?path=${encodeURIComponent(path)}`,
  );
}

export function approveRun(runId: string): Promise<RunDetail> {
  return postAction(`/runs/${encodeURIComponent(runId)}/approve`);
}

export function requestChanges(runId: string, feedback: string): Promise<RunDetail> {
  return postAction(`/runs/${encodeURIComponent(runId)}/request-changes`, feedback);
}

export function cancelRun(runId: string): Promise<RunDetail> {
  return postAction(`/runs/${encodeURIComponent(runId)}/cancel`);
}

export function approveQa(runId: string): Promise<RunDetail> {
  return postAction(`/runs/${encodeURIComponent(runId)}/qa/approve`);
}

export function requestQaFix(runId: string, feedback: string): Promise<RunDetail> {
  return postAction(`/runs/${encodeURIComponent(runId)}/qa/request-fix`, feedback);
}

function postAction(path: string, feedback = ""): Promise<RunDetail> {
  return apiFetch<RunDetail>(path, {
    method: "POST",
    body: JSON.stringify({
      user_id: "local-operator",
      feedback,
    }),
  });
}
