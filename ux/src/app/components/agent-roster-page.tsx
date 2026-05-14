import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  Boxes,
  Check,
  ChevronRight,
  ChevronUp,
  Cpu,
  FileText,
  Layers,
  LogOut,
  Moon,
  Paperclip,
  Play,
  Plus,
  Power,
  RotateCw,
  Save,
  Settings,
  Sun,
  Trash2,
  UserPlus,
} from "lucide-react";
import {
  AgentPromptConfig,
  PromptPresetInfo,
  SkillInfo,
  AgentProviderConfig,
  AppConfig,
  LocalAppSettings,
  ProviderCliStatus,
  ProviderModelCatalog,
  RunSummary,
  RuntimeHealthSnapshot,
  RuntimeUsageSnapshot,
  WorkflowGraph,
  getCodexModels,
  getRuntimeHealth,
  getRuntimeUsages,
  listProviders,
  loadAgentPrompt,
  loadPromptCatalog,
  loadSettings,
  resetAgentPrompt,
  saveAgentPrompt,
  saveSettings,
} from "../api";

type Lang = "ko" | "en";
type AgentStatus = "idle" | "ready" | "running" | "waiting" | "error" | "done" | "paused";

type Agent = {
  id: string;
  name: string;
  role: string;
  description: string;
  capabilities: string[];
  provider: "Codex" | "Claude" | "Manual" | "Local";
  account: string;
  model: string;
  reasoning: string;
  skill: string;
  status: AgentStatus;
  contextLeft: number | null;
  sessionId: string;
  lastAction: string;
  enabled: boolean;
  group: number;
  custom?: boolean;
};

type AccountOption = {
  label: string;
  value: string;
  detail: string;
};

type RunDefaults = {
  accountLabel?: string;
  model?: string;
  reasoning?: string;
};

type StartRunOptions = {
  plannerCount?: number;
  codeAgentCount?: number;
  qaAgentCount?: number;
  model?: string | null;
  reasoningEffort?: string | null;
  codexHome?: string | null;
  agentConfigs?: AgentProviderConfig[];
  workflowGraph?: WorkflowGraph | null;
};

type ManualStageId = "planning" | "approval_plan" | "contract" | "scaffold" | "code" | "integration" | "qa" | "approval_qa";

const DEFAULT_MANUAL_STAGE_ORDER: ManualStageId[] = [
  "planning",
  "approval_plan",
  "contract",
  "scaffold",
  "code",
  "integration",
  "qa",
  "approval_qa",
];

const MANUAL_STAGE_LABELS: Record<ManualStageId, string> = {
  planning: "Planning",
  approval_plan: "Approval",
  contract: "Contract",
  scaffold: "Scaffold",
  code: "Code",
  integration: "Integration",
  qa: "QA",
  approval_qa: "QA Approval",
};

const statusStyles: Record<AgentStatus, string> = {
  idle: "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-500 border-slate-200 dark:border-slate-700",
  ready: "bg-sky-50 text-sky-700 border-sky-200",
  running: "bg-indigo-50 text-indigo-700 border-indigo-200",
  waiting: "bg-amber-50 text-amber-800 border-amber-200",
  error: "bg-rose-50 text-rose-700 border-rose-200",
  done: "bg-emerald-50 text-emerald-700 border-emerald-200",
  paused: "bg-violet-50 text-violet-700 border-violet-200",
};

const statusLabels: Record<Lang, Record<AgentStatus, string>> = {
  ko: {
    idle: "대기",
    ready: "준비",
    running: "실행 중",
    waiting: "대기 중",
    error: "오류",
    done: "완료",
    paused: "일시정지",
  },
  en: {
    idle: "idle",
    ready: "ready",
    running: "running",
    waiting: "waiting",
    error: "error",
    done: "done",
    paused: "paused",
  },
};

const roleTint: Record<string, { bar: string; chip: string }> = {
  Planner: { bar: "bg-sky-400/70", chip: "bg-sky-50 text-sky-700 border-sky-100" },
  Architect: { bar: "bg-indigo-400/70", chip: "bg-indigo-50 text-indigo-700 border-indigo-100" },
  Designer: { bar: "bg-violet-400/70", chip: "bg-violet-50 text-violet-700 border-violet-100" },
  Code: { bar: "bg-emerald-400/70", chip: "bg-emerald-50 text-emerald-700 border-emerald-100" },
  Integrator: { bar: "bg-amber-400/70", chip: "bg-amber-50 text-amber-800 border-amber-100" },
  QA: { bar: "bg-rose-400/70", chip: "bg-rose-50 text-rose-700 border-rose-100" },
};

function resolvedModel(config: AppConfig | null, selectedModel?: string) {
  return selectedModel || config?.defaults.model || "Codex CLI default";
}

function resolvedReasoning(config: AppConfig | null, selectedReasoning?: string) {
  return selectedReasoning || config?.defaults.reasoning_effort || "Codex CLI default";
}

function buildAgents(config: AppConfig | null, runMode: string, defaults: RunDefaults = {}): Agent[] {
  const model = resolvedModel(config, defaults.model);
  const reasoning = resolvedReasoning(config, defaults.reasoning);
  const defaultAccount = defaults.accountLabel;
  const codeCount = Math.max(1, config?.defaults.code_agent_count || (runMode === "parallel" ? 2 : 1));
  const qaCount = Math.max(0, config?.defaults.qa_agent_count || 0);
  const codeAgents = Array.from({ length: runMode === "parallel" ? Math.max(2, codeCount) : 1 }, (_, index) => ({
    id: `code_${index + 1}`,
    name: `Code Agent ${index + 1}`,
    role: index === 0 ? "Implementation" : "Parallel Implementation",
    description: index === 0 ? "Implements the approved plan." : "Owns assigned paths in a parallel workspace.",
    capabilities: ["Code", "Tests", "Local Files"],
    provider: "Codex" as const,
    account: defaultAccount || codexAccount(config, index),
    model,
    reasoning,
    skill: "karpathy/code_agent",
    status: "idle" as AgentStatus,
    contextLeft: null,
    sessionId: "new",
    lastAction: "Ready for new session",
    enabled: true,
    group: runMode === "parallel" ? 5 : 3,
    custom: false,
  }));
  const base: Agent[] = [
    {
      id: "planner_a",
      name: "Planner A",
      role: "Requirement Analysis",
      description: "Drafts the first implementation plan from the request.",
      capabilities: ["Planning", "Spec Draft", "Risk Notes"],
      provider: "Codex",
      account: defaultAccount || codexAccount(config, 0),
      model,
      reasoning,
      skill: config?.reference_profiles.planner_a || "none",
      status: "ready",
      contextLeft: null,
      sessionId: "new",
      lastAction: "Awaiting run start",
      enabled: true,
      group: 1,
      custom: false,
    },
    {
      id: "planner_b",
      name: "Planner B",
      role: "Plan Review",
      description: "Reviews Planner A output and calls out missing constraints.",
      capabilities: ["Review", "Risk", "Compare"],
      provider: "Codex",
      account: defaultAccount || codexAccount(config, 0),
      model,
      reasoning,
      skill: config?.reference_profiles.planner_b || "none",
      status: runMode === "fast" ? "idle" : "ready",
      contextLeft: null,
      sessionId: "new",
      lastAction: runMode === "fast" ? "Skipped in fast route" : "Awaiting run start",
      enabled: runMode !== "fast",
      group: 2,
      custom: false,
    },
  ];
  const contractAgents: Agent[] =
    runMode === "parallel"
      ? [
          {
            id: "architect",
            name: "Architect",
            role: "Contract Bundle",
            description: "Creates requirements, API/data contracts, task manifest, and ownership notes.",
            capabilities: ["Schema", "Boundaries", "Manifest"],
            provider: "Codex",
            account: defaultAccount || codexAccount(config, 0),
            model,
            reasoning,
            skill: "architect.md",
            status: "ready",
            contextLeft: null,
            sessionId: "new",
            lastAction: "Enabled by parallel route",
            enabled: true,
            group: 3,
            custom: false,
          },
          {
            id: "designer",
            name: "Designer Agent",
            role: "UI/UX Direction",
            description: "Display-only placeholder until a design provider adapter is implemented.",
            capabilities: ["Layout", "Tokens", "States"],
            provider: "Claude",
            account: "display-only",
            model: "not wired",
            reasoning: "n/a",
            skill: "designer.md",
            status: "paused",
            contextLeft: null,
            sessionId: "disabled",
            lastAction: "Backend adapter not implemented",
            enabled: false,
            group: 4,
            custom: false,
          },
        ]
      : [];
  const tail: Agent[] = [
    ...codeAgents,
    {
      id: "integrator",
      name: "Integrator",
      role: "Merge & Wire",
      description: runMode === "parallel" ? "Merges parallel code outputs into generated_app." : "Skipped for single-code routes.",
      capabilities: ["Merge", "Resolve", "QA Prep"],
      provider: "Codex",
      account: defaultAccount || codexAccount(config, 0),
      model,
      reasoning,
      skill: config?.reference_profiles.integrator || "karpathy/integrator",
      status: runMode === "parallel" ? "ready" : "idle",
      contextLeft: null,
      sessionId: "new",
      lastAction: runMode === "parallel" ? "Enabled by parallel route" : "Not used by this route",
      enabled: runMode === "parallel",
      group: runMode === "parallel" ? 6 : 4,
      custom: false,
    },
    {
      id: "qa_1",
      name: "QA Agent",
      role: "Execution & Visual QA",
      description: qaCount > 0 ? "Reviews mechanical QA reports and screenshots." : "Mechanical QA only unless QA count is enabled.",
      capabilities: ["Syntax", "Executable Probe", "Report"],
      provider: "Codex",
      account: defaultAccount || codexAccount(config, 0),
      model,
      reasoning,
      skill: config?.reference_profiles.qa_agent || "none",
      status: qaCount > 0 ? "ready" : "idle",
      contextLeft: null,
      sessionId: "new",
      lastAction: qaCount > 0 ? "Awaiting generated app" : "LLM QA disabled",
      enabled: qaCount > 0,
      group: runMode === "parallel" ? 7 : 5,
      custom: false,
    },
  ];
  return [...base, ...contractAgents, ...tail];
}

function codexAccount(config: AppConfig | null, index: number) {
  const providers = config?.providers.filter((provider) => provider.name === "Codex" && provider.configured) || [];
  return providers[index % Math.max(1, providers.length)]?.account || "default";
}

function codexAccountOptions(config: AppConfig | null): AccountOption[] {
  const providers = config?.providers.filter((provider) => provider.name === "Codex" && provider.configured) || [];
  if (providers.length === 0) {
    return [{ label: "default", value: "", detail: "Codex CLI default" }];
  }
  return providers.map((provider) => {
    const status = provider.status || "";
    const isPath = /^[A-Za-z]:[\\/]/.test(status) || status.startsWith("/") || status.startsWith("\\\\");
    return {
      label: provider.account || "default",
      value: isPath ? status : "",
      detail: status,
    };
  });
}

function accountLabelForValue(options: AccountOption[], value: string) {
  return options.find((option) => option.value === value)?.label || options[0]?.label || "default";
}

function tintFor(name: string) {
  if (name.startsWith("Planner")) return roleTint.Planner;
  if (name.startsWith("Architect")) return roleTint.Architect;
  if (name.startsWith("Designer")) return roleTint.Designer;
  if (name.startsWith("Code")) return roleTint.Code;
  if (name.startsWith("Integrator")) return roleTint.Integrator;
  if (name.startsWith("QA")) return roleTint.QA;
  return { bar: "bg-slate-300", chip: "bg-slate-50 dark:bg-slate-900 text-slate-600 dark:text-slate-500 border-slate-200 dark:border-slate-700" };
}

function StatusBadge({ status, lang }: { status: AgentStatus; lang: Lang }) {
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded border ${statusStyles[status]}`} style={{ fontSize: 11 }}>
      <span className="size-1.5 rounded-full bg-current opacity-80" />
      <span>{statusLabels[lang][status]}</span>
    </span>
  );
}

function ContextBar({ value, lang }: { value: number | null; lang: Lang }) {
  if (value === null) {
    return <span className="font-mono text-slate-400 dark:text-slate-500" style={{ fontSize: 11 }}>{lang === "ko" ? "새 세션" : "new session"}</span>;
  }
  const tone = value > 60 ? "bg-emerald-500" : value > 30 ? "bg-amber-500" : "bg-rose-500";
  return (
    <div className="flex items-center gap-2 min-w-0">
      <div className="h-1 w-16 rounded bg-slate-100 dark:bg-slate-800 overflow-hidden">
        <div className={`h-full ${tone}`} style={{ width: `${value}%` }} />
      </div>
      <span className="font-mono text-slate-500 dark:text-slate-500" style={{ fontSize: 11 }}>{value}%</span>
    </div>
  );
}

function AgentCard({
  agent,
  lang,
  editable,
  configurable,
  accountOptions = [],
  modelOptions = [],
  defaultCodexHome = "",
  override,
  reasoningOptionsForModel = () => [],
  onConfigChange,
  onToggle,
  onDelete,
  onEditPrompt,
}: {
  agent: Agent;
  lang: Lang;
  editable?: boolean;
  configurable?: boolean;
  accountOptions?: AccountOption[];
  modelOptions?: ProviderModelCatalog["models"];
  defaultCodexHome?: string;
  override?: AgentProviderConfig;
  reasoningOptionsForModel?: (model: string) => string[];
  onConfigChange?: (patch: Partial<AgentProviderConfig>) => void;
  onToggle?: () => void;
  onDelete?: () => void;
  onEditPrompt?: () => void;
}) {
  const tint = tintFor(agent.name);
  const updateConfig = onConfigChange || ((_patch: Partial<AgentProviderConfig>) => undefined);
  const codexConfigurable = configurable && agent.provider === "Codex" && onConfigChange;
  const modelSelectOptions = modelOptions.length
    ? modelOptions.map((model) => ({ label: model.id, value: model.id }))
    : [{ label: agent.model, value: agent.model }];
  const selectedModel = override?.model || agent.model;
  const selectedReasoning = override?.reasoning_effort || agent.reasoning;
  const reasoningSelectOptions = reasoningOptionsForModel(selectedModel).map((effort) => ({ label: effort, value: effort }));
  const selectedCodexHome = override?.codex_home ?? defaultCodexHome;
  return (
    <div className={`group relative rounded-lg border border-slate-200/80 dark:border-slate-700/70 bg-white dark:bg-slate-900 shadow-[0_1px_0_rgba(15,23,42,0.02),0_1px_2px_rgba(15,23,42,0.04)] hover:border-slate-300 dark:hover:border-slate-600 transition-all overflow-hidden ${agent.enabled ? "" : "opacity-65"}`}>
      <span className={`absolute inset-y-0 left-0 w-0.5 ${tint.bar}`} />
      <div className="flex items-start justify-between gap-3 px-4 pt-3 pb-2 border-b border-slate-100 dark:border-slate-800">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-mono text-slate-400 dark:text-slate-500" style={{ fontSize: 10 }}>#{agent.group}</span>
            <span className="truncate text-slate-900 dark:text-slate-100">{agent.name}</span>
            <StatusBadge status={agent.status} lang={lang} />
          </div>
          <div className={`mt-0.5 inline-flex items-center px-1.5 py-0.5 rounded border ${tint.chip}`} style={{ fontSize: 11 }}>
            {agent.role}
          </div>
        </div>
        <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100">
          <button onClick={onEditPrompt} className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800" title="Skill / Prompt">
            <Settings className="size-3.5 text-slate-500 dark:text-slate-500" />
          </button>
          {editable && (
            <button onClick={onToggle} className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800" title={agent.enabled ? "Disable" : "Enable"}>
              <Power className="size-3.5 text-slate-500 dark:text-slate-500" />
            </button>
          )}
          {editable && agent.custom && (
            <button onClick={onDelete} className="p-1 rounded hover:bg-rose-50" title="Delete">
              <Trash2 className="size-3.5 text-slate-500 dark:text-slate-500" />
            </button>
          )}
        </div>
      </div>
      <div className="px-4 py-2.5 text-slate-600 dark:text-slate-500" style={{ fontSize: 12 }}>{agent.description}</div>
      <div className="px-4 pb-2 flex flex-wrap gap-1">
        {agent.capabilities.map((capability) => (
          <span key={capability} className="px-1.5 py-0.5 rounded bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-500" style={{ fontSize: 10 }}>
            {capability}
          </span>
        ))}
      </div>
      <div className="px-4 py-2 grid grid-cols-2 gap-x-3 gap-y-1.5 border-t border-slate-100 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-900/60">
        <Meta label={lang === "ko" ? "프로바이더" : "provider"} value={agent.provider} />
        <Meta label={lang === "ko" ? "계정" : "account"} value={agent.account} mono />
        <Meta label={lang === "ko" ? "모델" : "model"} value={agent.model} mono />
        <Meta label={lang === "ko" ? "추론" : "reasoning"} value={agent.reasoning} />
        <SkillMeta label={lang === "ko" ? "스킬" : "skill"} value={agent.skill} onClick={onEditPrompt} />
        <Meta label={lang === "ko" ? "세션" : "session"} value={agent.sessionId} mono />
      </div>
      {codexConfigurable && (
        <div className="px-4 py-2 grid grid-cols-3 gap-1.5 border-t border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900">
          <InlineSelect
            label={lang === "ko" ? "계정" : "account"}
            value={selectedCodexHome}
            options={accountOptions.map((option) => ({ label: option.label, value: option.value }))}
            onChange={(value) =>
              updateConfig({
                provider: "codex",
                codex_home: value || null,
                account: accountLabelForValue(accountOptions, value),
              })
            }
          />
          <InlineSelect
            label={lang === "ko" ? "모델" : "model"}
            value={selectedModel}
            options={modelSelectOptions}
            onChange={(value) => {
              const nextReasoningOptions = reasoningOptionsForModel(value);
              updateConfig({
                provider: "codex",
                model: value || null,
                reasoning_effort: nextReasoningOptions.includes(selectedReasoning)
                  ? selectedReasoning
                  : nextReasoningOptions[0] || null,
              });
            }}
          />
          <InlineSelect
            label={lang === "ko" ? "추론" : "reasoning"}
            value={selectedReasoning}
            options={reasoningSelectOptions.length ? reasoningSelectOptions : [{ label: selectedReasoning, value: selectedReasoning }]}
            onChange={(value) => updateConfig({ provider: "codex", reasoning_effort: value || null })}
          />
        </div>
      )}
      <div className="px-4 py-2 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-slate-400 dark:text-slate-500 uppercase tracking-wide" style={{ fontSize: 10 }}>{lang === "ko" ? "컨텍스트" : "ctx"}</span>
          <ContextBar value={agent.contextLeft} lang={lang} />
        </div>
        <div className="text-slate-500 dark:text-slate-500 truncate" style={{ fontSize: 11 }}>{agent.lastAction}</div>
      </div>
    </div>
  );
}

function Meta({ label, value, mono, icon }: { label: string; value: string; mono?: boolean; icon?: ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-slate-400 dark:text-slate-500 uppercase tracking-wide" style={{ fontSize: 10 }}>{label}</div>
      <div className={`flex items-center gap-1 truncate text-slate-700 dark:text-slate-300 ${mono ? "font-mono" : ""}`} style={{ fontSize: 12 }}>
        {icon}
        <span className="truncate">{value}</span>
      </div>
    </div>
  );
}

function SkillMeta({ label, value, onClick }: { label: string; value: string; onClick?: () => void }) {
  return (
    <div className="min-w-0">
      <div className="text-slate-400 dark:text-slate-500 uppercase tracking-wide" style={{ fontSize: 10 }}>{label}</div>
      <button
        type="button"
        onClick={onClick}
        className="flex items-center gap-1 max-w-full truncate text-slate-700 dark:text-slate-300 font-mono hover:text-indigo-700"
        style={{ fontSize: 12 }}
        title="Open skill and system prompt editor"
      >
        <FileText className="size-3 shrink-0" />
        <span className="truncate">{value}</span>
      </button>
    </div>
  );
}

function InlineSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: Array<{ label: string; value: string }>;
  onChange: (value: string) => void;
}) {
  const normalizedOptions = options.length > 0 ? options : [{ label: "--", value: "" }];
  const normalizedValue = normalizedOptions.some((option) => option.value === value) ? value : normalizedOptions[0].value;
  return (
    <label className="min-w-0">
      <span className="block text-slate-400 dark:text-slate-500 uppercase tracking-wide" style={{ fontSize: 9 }}>{label}</span>
      <select
        value={normalizedValue}
        onChange={(event) => onChange(event.target.value)}
        className="mt-0.5 w-full rounded border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-950 px-1 py-0.5 font-mono text-slate-700 dark:text-slate-300 outline-none"
        style={{ fontSize: 10 }}
      >
        {normalizedOptions.map((option) => (
          <option key={`${option.label}-${option.value}`} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function SidebarSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="px-3 py-2.5 border-b border-slate-200/70 dark:border-slate-700/70">
      <div className="text-slate-500 dark:text-slate-500 uppercase tracking-wider mb-2" style={{ fontSize: 10 }}>{title}</div>
      <div className="space-y-1.5">{children}</div>
    </div>
  );
}

function ProviderRow({ name, account, ok, status, warn }: { name: string; account: string; ok: boolean; status: string; warn?: boolean }) {
  return (
    <div className="flex items-center justify-between rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 py-1.5 shadow-[0_1px_0_rgba(15,23,42,0.02)]">
      <div className="min-w-0">
        <div className="flex items-center gap-1.5">
          <span className={`size-1.5 rounded-full ${ok ? "bg-emerald-500" : "bg-slate-400"}`} />
          <span className="text-slate-800 dark:text-slate-200" style={{ fontSize: 12 }}>{name}</span>
          {warn && <AlertTriangle className="size-3 text-amber-500" />}
        </div>
        <div className="font-mono text-slate-500 dark:text-slate-500 truncate" style={{ fontSize: 11 }}>{account}</div>
      </div>
      <div className="font-mono text-slate-600 dark:text-slate-500 text-right truncate max-w-24" style={{ fontSize: 11 }}>{status}</div>
    </div>
  );
}

function ResourcePanel({
  providers,
  models,
  health,
  usages,
  loading,
  error,
  onRefresh,
  onClose,
}: {
  providers: ProviderCliStatus[];
  models: ProviderModelCatalog | null;
  health: RuntimeHealthSnapshot | null;
  usages: RuntimeUsageSnapshot[];
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
  onClose: () => void;
}) {
  const codexModels = models?.models || [];
  const selectedModel = codexModels[0];
  const usageItems = usages || [];
  return (
    <div className="absolute inset-0 z-20 bg-slate-950/20 backdrop-blur-[1px] flex justify-end">
      <section className="w-[440px] h-full border-l border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 shadow-[-12px_0_32px_rgba(15,23,42,0.12)] flex flex-col">
        <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-700 flex items-center justify-between">
          <div>
            <div className="text-slate-900 dark:text-slate-100" style={{ fontSize: 14 }}>Resources</div>
            <div className="text-slate-500 dark:text-slate-500" style={{ fontSize: 11 }}>Provider health, models, usage, and runtime settings</div>
          </div>
          <div className="flex items-center gap-1">
            <button onClick={onRefresh} className="p-1.5 rounded hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-400" title="Refresh">
              <RotateCw className={`size-4 ${loading ? "animate-spin" : ""}`} />
            </button>
            <button onClick={onClose} className="px-2 py-1 rounded border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-400" style={{ fontSize: 12 }}>
              Close
            </button>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {error && <div className="rounded-md border border-rose-200 bg-rose-50 text-rose-700 px-3 py-2" style={{ fontSize: 12 }}>{error}</div>}
          <ResourceSection title="Providers">
            {providers.map((provider) => (
              <div key={provider.provider} className="rounded-md border border-slate-200 dark:border-slate-700 p-3 bg-slate-50/70 dark:bg-slate-950/30">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className={`size-2 rounded-full ${provider.installed ? "bg-emerald-500" : "bg-slate-400"}`} />
                    <span className="capitalize text-slate-900 dark:text-slate-100" style={{ fontSize: 13 }}>{provider.provider}</span>
                  </div>
                  <StatusToken status={provider.status} />
                </div>
                <div className="mt-2 grid grid-cols-2 gap-2">
                  <MiniField label="version" value={provider.version || "--"} />
                  <MiniField label="login" value={provider.logged_in == null ? "--" : provider.logged_in ? "logged in" : "required"} />
                  <MiniField label="account" value={provider.account || "--"} />
                  <MiniField label="plan" value={provider.plan || "--"} />
                </div>
                <div className="mt-2 font-mono text-slate-500 dark:text-slate-500 truncate" style={{ fontSize: 10 }}>{provider.executable || provider.detail || "not detected"}</div>
              </div>
            ))}
          </ResourceSection>
          <ResourceSection title="Codex Models">
            <div className="flex items-center justify-between">
              <span className="text-slate-600 dark:text-slate-400" style={{ fontSize: 12 }}>{models?.source || "not loaded"}</span>
              <StatusToken status={models?.ok ? "ready" : "unavailable"} />
            </div>
            {models?.error && <div className="text-rose-700 bg-rose-50 border border-rose-200 rounded px-2 py-1" style={{ fontSize: 12 }}>{models.error}</div>}
            <div className="space-y-1 max-h-56 overflow-y-auto">
              {codexModels.slice(0, 20).map((model) => (
                <div key={model.id} className="rounded border border-slate-200 dark:border-slate-700 px-2 py-1.5 bg-white dark:bg-slate-900">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-slate-800 dark:text-slate-200" style={{ fontSize: 12 }}>{model.id}</span>
                    <span className="text-slate-500 dark:text-slate-500" style={{ fontSize: 11 }}>{model.default_reasoning_level || "--"}</span>
                  </div>
                  <div className="text-slate-500 dark:text-slate-500 truncate" style={{ fontSize: 11 }}>{model.supported_reasoning_levels.map((level) => level.effort).join(", ") || "reasoning defaults"}</div>
                </div>
              ))}
              {codexModels.length === 0 && <div className="text-slate-500 dark:text-slate-500" style={{ fontSize: 12 }}>No model catalog loaded.</div>}
            </div>
            {selectedModel && (
              <div className="rounded-md border border-indigo-100 bg-indigo-50/60 px-2 py-1.5 text-indigo-800" style={{ fontSize: 11 }}>
                Dropdown-ready: {selectedModel.id} supports {selectedModel.supported_reasoning_levels.map((level) => level.effort).join(", ")}.
              </div>
            )}
          </ResourceSection>
          <ResourceSection title="Usage">
            <div className="flex items-center justify-between">
              <span className="text-slate-600 dark:text-slate-400" style={{ fontSize: 12 }}>
                {usageItems.length > 0 ? `${usageItems.length} Codex account${usageItems.length === 1 ? "" : "s"}` : "not loaded"}
              </span>
              <StatusToken status={usageItems.some((usage) => usage.ok) ? "ready" : "unavailable"} />
            </div>
            {usageItems.map((usage, index) => (
              <div key={`${usage.account || "default"}-${usage.codex_home || index}`} className="rounded border border-slate-200 dark:border-slate-700 px-2 py-1.5 space-y-1.5 bg-white dark:bg-slate-900">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="font-mono text-slate-800 dark:text-slate-200 truncate" style={{ fontSize: 12 }}>
                      {usage.account || "default"}
                    </div>
                    <div className="font-mono text-slate-500 dark:text-slate-500 truncate" style={{ fontSize: 10 }}>
                      {usage.codex_home || "default CODEX_HOME"}
                    </div>
                  </div>
                  <StatusToken status={usage.ok ? "ready" : "unavailable"} />
                </div>
                {usage.limits.map((limit) => (
                  <div key={limit.name} className="space-y-1">
                    <div className="flex items-center justify-between">
                      <span style={{ fontSize: 12 }}>{limit.name}</span>
                      <span className="font-mono text-slate-500 dark:text-slate-500" style={{ fontSize: 11 }}>
                        {limit.available ? `${limit.remaining_percent ?? "--"}% left` : "unavailable"}
                      </span>
                    </div>
                    <div className="h-1.5 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
                      <div
                        className="h-full rounded-full bg-indigo-500"
                        style={{ width: `${limit.available ? Math.max(0, Math.min(100, limit.remaining_percent ?? 0)) : 0}%` }}
                      />
                    </div>
                    <div className="flex items-center justify-between text-slate-500 dark:text-slate-500" style={{ fontSize: 10 }}>
                      <span>{limit.used_percent == null ? "-- used" : `${limit.used_percent}% used`}</span>
                      <span>{formatResetAt(limit.reset_at)}</span>
                    </div>
                  </div>
                ))}
                {usage.message && <div className="text-slate-500 dark:text-slate-500" style={{ fontSize: 11 }}>{usage.message}</div>}
              </div>
            ))}
            {usageItems.length === 0 && <div className="text-slate-500 dark:text-slate-500" style={{ fontSize: 12 }}>Usage has not been loaded.</div>}
          </ResourceSection>
          <ResourceSection title="Runtime">
            <MiniField label="overall" value={health?.status || "--"} />
            <MiniField label="discord token" value={health?.discord_token_configured ? "configured" : "missing"} />
            <MiniField label="executable QA" value={health?.executable_qa_enabled ? "enabled" : "disabled"} />
            <MiniField label="windows sandbox" value={health?.codex_child_windows_sandbox || "--"} />
          </ResourceSection>
        </div>
      </section>
    </div>
  );
}

function PromptEditorPanel({
  agent,
  promptConfig,
  presets,
  skills,
  loading,
  saving,
  error,
  width,
  activeTab,
  onTabChange,
  onWidthChange,
  onChange,
  onApplyPreset,
  onApplySkill,
  onSave,
  onReset,
  onClose,
}: {
  agent: Agent;
  promptConfig: AgentPromptConfig | null;
  presets: PromptPresetInfo[];
  skills: SkillInfo[];
  loading: boolean;
  saving: boolean;
  error: string | null;
  width: number;
  activeTab: "skill" | "system" | "preview";
  onTabChange: (tab: "skill" | "system" | "preview") => void;
  onWidthChange: (value: number) => void;
  onChange: (patch: Partial<AgentPromptConfig>) => void;
  onApplyPreset: (preset: PromptPresetInfo) => void;
  onApplySkill: (skill: SkillInfo) => void;
  onSave: () => void;
  onReset: () => void;
  onClose: () => void;
}) {
  const qaPresets = promptConfig?.role === "qa_agent" ? presets.filter((preset) => preset.id.includes("qa")) : [];
  const availableSkills = skills;
  const showGuidelinePresets = activeTab === "skill" && qaPresets.length > 0;
  const showSkillSelector = activeTab === "skill" && availableSkills.length > 0;
  const textValue =
    activeTab === "system"
      ? promptConfig?.system_prompt || ""
      : activeTab === "preview"
        ? promptConfig?.effective_prompt_preview || ""
        : promptConfig?.skill_markdown || "";
  return (
    <div className="absolute inset-0 z-30 bg-slate-950/20 backdrop-blur-[1px] flex justify-end">
      <section
        className="h-full border-l border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 shadow-[-12px_0_32px_rgba(15,23,42,0.14)] flex flex-col"
        style={{ width: `${width}vw`, minWidth: 520, maxWidth: "72vw" }}
      >
        <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-700 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-slate-900 dark:text-slate-100" style={{ fontSize: 14 }}>{agent.name} Prompt</div>
            <div className="text-slate-500 dark:text-slate-500 truncate" style={{ fontSize: 11 }}>
              Skill, guideline, and system prompt used by this agent. Saved prompts are snapshotted into each run.
            </div>
          </div>
          <div className="flex items-center gap-1 shrink-0">
            <button onClick={onReset} disabled={saving || loading} className="px-2 py-1 rounded border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-400 disabled:opacity-50" style={{ fontSize: 12 }}>Reset</button>
            <button onClick={onSave} disabled={saving || loading || !promptConfig} className="px-2 py-1 rounded border border-indigo-200 bg-indigo-600 text-white disabled:opacity-50" style={{ fontSize: 12 }}>
              {saving ? "Saving" : "Save"}
            </button>
            <button onClick={onClose} className="px-2 py-1 rounded border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-400" style={{ fontSize: 12 }}>Close</button>
          </div>
        </div>
        <div className="px-4 py-2 border-b border-slate-200 dark:border-slate-700 flex items-center justify-between gap-3">
          <div className="flex items-center gap-1">
            {(["skill", "system", "preview"] as const).map((tab) => (
              <button
                key={tab}
                onClick={() => onTabChange(tab)}
                className={`px-2 py-1 rounded border ${activeTab === tab ? "bg-indigo-600 text-white border-indigo-600" : "bg-white dark:bg-slate-900 text-slate-700 dark:text-slate-300 border-slate-200 dark:border-slate-700"}`}
                style={{ fontSize: 12 }}
              >
                {tab === "skill" ? "Skill / Guideline" : tab === "system" ? "System Prompt" : "Effective Preview"}
              </button>
            ))}
          </div>
          <label className="flex items-center gap-2 text-slate-500 dark:text-slate-500" style={{ fontSize: 11 }}>
            width
            <input type="range" min={42} max={68} value={width} onChange={(event) => onWidthChange(Number(event.target.value))} />
          </label>
        </div>
        {(showGuidelinePresets || showSkillSelector) && (
          <div className="px-4 py-2 border-b border-slate-200 dark:border-slate-700 flex flex-wrap items-center gap-2">
            {showSkillSelector && (
              <>
                <span className="text-slate-500 dark:text-slate-500" style={{ fontSize: 11 }}>Skill Source</span>
                <select
                  value={promptConfig?.skill_id || ""}
                  onChange={(event) => {
                    const value = event.target.value;
                    if (!value) {
                      onChange({ skill_id: null });
                      return;
                    }
                    const skill = availableSkills.find((item) => item.id === value);
                    if (skill) onApplySkill(skill);
                  }}
                  className="max-w-64 rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-950 px-2 py-1 text-slate-700 dark:text-slate-300"
                  style={{ fontSize: 12 }}
                >
                  <option value="">Custom / manual</option>
                  {availableSkills.map((skill) => (
                    <option key={skill.id} value={skill.id}>{skill.label}</option>
                  ))}
                </select>
              </>
            )}
            {showGuidelinePresets && (
              <>
                <span className="text-slate-500 dark:text-slate-500" style={{ fontSize: 11 }}>QA Preset</span>
                <select
                  value={promptConfig?.preset || ""}
                  onChange={(event) => {
                    const preset = qaPresets.find((item) => item.id === event.target.value);
                    if (preset) onApplyPreset(preset);
                  }}
                  className="rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-950 px-2 py-1 text-slate-700 dark:text-slate-300"
                  style={{ fontSize: 12 }}
                >
                  {qaPresets.map((preset) => (
                    <option key={preset.id} value={preset.id}>{preset.label}</option>
                  ))}
                </select>
              </>
            )}
            <span className="text-slate-400 dark:text-slate-500 truncate" style={{ fontSize: 11 }}>
              {availableSkills.find((skill) => skill.id === promptConfig?.skill_id)?.description
                || qaPresets.find((preset) => preset.id === promptConfig?.preset)?.description
                || "Custom guideline"}
            </span>
          </div>
        )}
        <div className="flex-1 min-h-0 p-4">
          {error && <div className="mb-2 rounded border border-rose-200 bg-rose-50 text-rose-700 px-3 py-2" style={{ fontSize: 12 }}>{error}</div>}
          {loading ? (
            <div className="h-full rounded border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-950 flex items-center justify-center text-slate-500" style={{ fontSize: 13 }}>Loading prompt...</div>
          ) : (
            <textarea
              value={textValue}
              readOnly={activeTab === "preview"}
              onChange={(event) =>
                activeTab === "system"
                  ? onChange({ system_prompt: event.target.value })
                  : onChange({ skill_markdown: event.target.value })
              }
              className="h-full w-full resize-none rounded border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-950 px-3 py-2 font-mono text-slate-800 dark:text-slate-200 outline-none focus:border-indigo-300"
              style={{ fontSize: 12, lineHeight: 1.55 }}
            />
          )}
        </div>
      </section>
    </div>
  );
}

function formatResetAt(value?: string | null) {
  if (!value) {
    return "reset --";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return `reset ${date.toLocaleString([], { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })}`;
}

function ResourceSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <div className="uppercase tracking-wider text-slate-500 dark:text-slate-500" style={{ fontSize: 10 }}>{title}</div>
      {children}
    </section>
  );
}

function MiniField({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 py-1">
      <div className="uppercase tracking-wide text-slate-400 dark:text-slate-500" style={{ fontSize: 9 }}>{label}</div>
      <div className="font-mono text-slate-700 dark:text-slate-300 truncate" style={{ fontSize: 11 }}>{value}</div>
    </div>
  );
}

function StatusToken({ status }: { status: string }) {
  const ready = ["ready", "detected", "ok"].includes(status);
  const warn = ["login_required", "setup_required", "unavailable"].includes(status);
  const color = ready ? "border-emerald-200 bg-emerald-50 text-emerald-700" : warn ? "border-amber-200 bg-amber-50 text-amber-800" : "border-slate-200 bg-slate-50 text-slate-600";
  return <span className={`px-1.5 py-0.5 rounded border ${color}`} style={{ fontSize: 10 }}>{status}</span>;
}

function ManualGraphEditor({
  agents,
  graph,
  warnings,
  stageOrder,
  draggedStageId,
  forcedEnabledAgentIds,
  setDraggedStageId,
  dropManualStage,
  moveManualStage,
  toggleIntegratorStage,
  resetManualGraph,
}: {
  agents: Agent[];
  graph: WorkflowGraph;
  warnings: string[];
  stageOrder: ManualStageId[];
  draggedStageId: ManualStageId | null;
  forcedEnabledAgentIds: Set<string>;
  setDraggedStageId: (stageId: ManualStageId | null) => void;
  dropManualStage: (stageId: ManualStageId) => void;
  moveManualStage: (stageId: ManualStageId, offset: -1 | 1) => void;
  toggleIntegratorStage: () => void;
  resetManualGraph: () => void;
}) {
  const activeStages = graph.stages
    .map((stage) => ({ stage, orderIndex: stageOrder.indexOf(stage.id as ManualStageId) }))
    .sort((a, b) => a.orderIndex - b.orderIndex)
    .map((item) => item.stage);
  const integrationEnabled = forcedEnabledAgentIds.has("integrator") || graph.stages.some((stage) => stage.id === "integration");
  return (
    <div className={`w-full rounded-lg border px-3 py-2 ${warnings.length ? "border-amber-200 bg-amber-50/80" : "border-emerald-200 bg-emerald-50/70"}`}>
      <div className="flex items-center justify-between gap-2 mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-mono text-slate-500" style={{ fontSize: 10 }}>manual graph</span>
          <span className="text-slate-700 truncate" style={{ fontSize: 12 }}>
            {activeStages.map((stage) => manualStageSummary(stage, agents)).join(" -> ")}
          </span>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button onClick={toggleIntegratorStage} className="px-2 py-1 rounded border border-amber-300 bg-white text-amber-800" style={{ fontSize: 11 }}>
            {integrationEnabled ? "Remove Integrator" : "Add Integrator"}
          </button>
          <button onClick={resetManualGraph} className="px-2 py-1 rounded border border-slate-300 bg-white text-slate-700" style={{ fontSize: 11 }}>Reset</button>
          {warnings.length > 0 && <span className="px-2 py-1 rounded border border-amber-300 bg-white text-amber-800 font-mono" style={{ fontSize: 10 }}>{warnings.length} warning</span>}
        </div>
      </div>
      <div className="flex items-stretch gap-2 overflow-x-auto pb-1">
        {activeStages.map((stage, index) => {
          const stageId = stage.id as ManualStageId;
          const orderIndex = stageOrder.indexOf(stageId);
          const canMoveLeft = orderIndex > 0;
          const canMoveRight = orderIndex < stageOrder.length - 1;
          const stageAgents = manualStageAgents(stage, agents);
          return (
            <div key={stage.id} className="flex items-center gap-2 shrink-0">
              <div
                draggable
                onDragStart={() => setDraggedStageId(stageId)}
                onDragEnd={() => setDraggedStageId(null)}
                onDragOver={(event) => event.preventDefault()}
                onDrop={() => dropManualStage(stageId)}
                className={`w-56 min-h-20 rounded-lg border bg-white shadow-[0_1px_0_rgba(15,23,42,0.04)] px-3 py-2 cursor-move ${draggedStageId === stageId ? "border-indigo-400 ring-2 ring-indigo-100" : "border-slate-200"}`}
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <div className="font-mono text-slate-400" style={{ fontSize: 10 }}>#{index + 1}</div>
                    <div className="text-slate-900 truncate" style={{ fontSize: 13 }}>{MANUAL_STAGE_LABELS[stageId]}</div>
                  </div>
                  <div className="flex items-center gap-0.5">
                    <button type="button" disabled={!canMoveLeft} onClick={() => moveManualStage(stageId, -1)} className="size-6 rounded border border-slate-200 disabled:opacity-30 text-slate-600">‹</button>
                    <button type="button" disabled={!canMoveRight} onClick={() => moveManualStage(stageId, 1)} className="size-6 rounded border border-slate-200 disabled:opacity-30 text-slate-600">›</button>
                  </div>
                </div>
                <div className="mt-2 flex flex-wrap gap-1">
                  {stageAgents.map((agentName) => (
                    <span key={agentName} className="px-1.5 py-0.5 rounded border border-slate-200 bg-slate-50 text-slate-700 max-w-44 truncate" style={{ fontSize: 10 }}>
                      {agentName}
                    </span>
                  ))}
                  {stage.parallel && <span className="px-1.5 py-0.5 rounded border border-indigo-200 bg-indigo-50 text-indigo-700 font-mono" style={{ fontSize: 10 }}>parallel</span>}
                </div>
              </div>
              {index < activeStages.length - 1 && <ChevronRight className="size-4 text-slate-400 shrink-0" />}
            </div>
          );
        })}
      </div>
      {warnings.length > 0 && <div className="mt-1 text-amber-800 truncate" style={{ fontSize: 11 }}>{warnings.join(" ")}</div>}
    </div>
  );
}

function manualStageSummary(stage: WorkflowGraph["stages"][number], agents: Agent[]) {
  if (stage.type === "approval") return MANUAL_STAGE_LABELS[stage.id as ManualStageId] || "Approval";
  const names = manualStageAgents(stage, agents);
  return names.length ? names.join(stage.parallel ? " + " : ", ") : MANUAL_STAGE_LABELS[stage.id as ManualStageId] || stage.type;
}

function manualStageAgents(stage: WorkflowGraph["stages"][number], agents: Agent[]) {
  return (stage.agents || []).map((agentId) => {
    if (agentId === "mechanical_qa") return "Mechanical QA";
    return agents.find((agent) => agent.id === agentId)?.name || agentId;
  });
}

function Pill({ active, children, onClick }: { active?: boolean; children: ReactNode; onClick?: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`px-2 py-1 rounded-md border transition-colors ${active ? "bg-indigo-600 text-white border-indigo-600 shadow-[0_1px_0_rgba(79,70,229,0.4)]" : "bg-white dark:bg-slate-900 text-slate-700 dark:text-slate-300 border-slate-200 dark:border-slate-700 hover:border-slate-300 dark:hover:border-slate-600 hover:bg-slate-50 dark:hover:bg-slate-800"}`}
      style={{ fontSize: 11 }}
    >
      {children}
    </button>
  );
}

function deriveManualWorkflowGraph(agents: Agent[], stageOrder: ManualStageId[]): { graph: WorkflowGraph; warnings: string[] } {
  const enabled = agents.filter((agent) => agent.enabled);
  const planners = enabled.filter((agent) => agent.name.startsWith("Planner"));
  const contractAgents = enabled.filter((agent) => agent.name.startsWith("Architect"));
  const scaffoldAgents = enabled.filter((agent) => agent.name.startsWith("Scaffold"));
  const codeAgents = enabled.filter((agent) => agent.name.startsWith("Code Agent"));
  const integrators = enabled.filter((agent) => agent.name.startsWith("Integrator"));
  const qaAgents = enabled.filter((agent) => agent.name.startsWith("QA"));
  const stages: WorkflowGraph["stages"] = [];
  const warnings: string[] = [];

  if (planners.length === 0) warnings.push("Manual graph needs at least one planner.");
  if (codeAgents.length === 0) warnings.push("Manual graph needs at least one code agent.");

  let previous: string | undefined;
  for (const stageId of stageOrder) {
    const stage = buildManualStage(stageId, {
      planners,
      contractAgents,
      scaffoldAgents,
      codeAgents,
      integrators,
      qaAgents,
      previous,
    });
    if (!stage) continue;
    stages.push(stage);
    previous = stage.id;
  }

  const stageIds = stages.map((stage) => stage.id);
  const codeIndex = stageIds.indexOf("code");
  const integrationIndex = stageIds.indexOf("integration");
  const qaIndex = stageIds.indexOf("qa");
  if (codeAgents.length > 1 && integrationIndex === -1) {
    warnings.push("Parallel code agents need an integration stage.");
  }
  if (integrationIndex !== -1 && codeIndex === -1) {
    warnings.push("Integration needs a code stage before it.");
  }
  if (integrationIndex !== -1 && codeIndex !== -1 && integrationIndex !== codeIndex + 1) {
    warnings.push("Integration must be placed directly after the code stage.");
  }
  if (qaIndex !== -1 && codeIndex !== -1 && qaIndex < codeIndex) {
    warnings.push("QA must run after code.");
  }
  if (stageIds.includes("approval_plan") && !stageIds.includes("planning")) {
    warnings.push("Plan approval needs a planning stage.");
  }
  if (stageIds.includes("approval_qa") && !stageIds.includes("qa")) {
    warnings.push("QA approval needs a QA stage.");
  }

  return { graph: { mode: "manual", stages }, warnings };
}

function buildManualStage(
  stageId: ManualStageId,
  context: {
    planners: Agent[];
    contractAgents: Agent[];
    scaffoldAgents: Agent[];
    codeAgents: Agent[];
    integrators: Agent[];
    qaAgents: Agent[];
    previous?: string;
  },
): WorkflowGraph["stages"][number] | null {
  const after = context.previous ? [context.previous] : [];
  if (stageId === "planning" && context.planners.length > 0) {
    return { id: "planning", type: "planning", agents: context.planners.map((agent) => agent.id), parallel: false };
  }
  if (stageId === "approval_plan" && context.planners.length > 0) {
    return { id: "approval_plan", type: "approval", after };
  }
  if (stageId === "contract" && context.contractAgents.length > 0) {
    return { id: "contract", type: "contract", agents: context.contractAgents.map((agent) => agent.id), after, parallel: context.contractAgents.length > 1 };
  }
  if (stageId === "scaffold" && context.scaffoldAgents.length > 0) {
    return { id: "scaffold", type: "scaffold", agents: context.scaffoldAgents.map((agent) => agent.id), after, parallel: context.scaffoldAgents.length > 1 };
  }
  if (stageId === "code" && context.codeAgents.length > 0) {
    return { id: "code", type: "code", agents: context.codeAgents.map((agent) => agent.id), after, parallel: context.codeAgents.length > 1 };
  }
  if (stageId === "integration" && context.integrators.length > 0) {
    return { id: "integration", type: "integration", agents: context.integrators.map((agent) => agent.id), after, parallel: false };
  }
  if (stageId === "qa") {
    return { id: "qa", type: "qa", agents: ["mechanical_qa", ...context.qaAgents.map((agent) => agent.id)], after, parallel: context.qaAgents.length > 1 };
  }
  if (stageId === "approval_qa") {
    return { id: "approval_qa", type: "approval", after };
  }
  return null;
}

function nextManualAgentId(type: string, agents: Agent[]) {
  const used = new Set(agents.map((agent) => agent.id));
  if (type === "code") return nextIndexedAgentId("code_", used);
  if (type === "qa") return nextIndexedAgentId("qa_", used);
  if (type === "planner") {
    for (const id of ["planner_a", "planner_b", "planner_c"]) {
      if (!used.has(id)) return id;
    }
    return nextIndexedAgentId("planner_", used);
  }
  if (type === "architect" && !used.has("architect")) return "architect";
  if (type === "integrator" && !used.has("integrator")) return "integrator";
  if (type === "scaffold" && !used.has("scaffold")) return "scaffold";
  return `manual_${type}_${Date.now()}`;
}

function nextIndexedAgentId(prefix: string, used: Set<string>) {
  let index = 1;
  while (used.has(`${prefix}${index}`)) index += 1;
  return `${prefix}${index}`;
}

function insertBeforeStage(order: ManualStageId[], stageId: ManualStageId, beforeStageId: ManualStageId) {
  if (order.includes(stageId)) return order;
  const next = [...order];
  const index = next.indexOf(beforeStageId);
  next.splice(index >= 0 ? index : next.length, 0, stageId);
  return next;
}

export function AgentRosterPage({
  onStartRun,
  onOpenRun,
  config,
  runs,
  loading,
  error,
  lang,
  setLang,
  theme,
  setTheme,
}: {
  onStartRun: (
    prompt: string,
    runMode: string,
    options?: StartRunOptions,
  ) => void;
  onOpenRun: (runId: string) => void;
  config: AppConfig | null;
  runs: RunSummary[];
  loading: boolean;
  error: string | null;
  lang: Lang;
  setLang: (l: Lang) => void;
  theme: "light" | "dark";
  setTheme: (t: "light" | "dark") => void;
}) {
  const [runMode, setRunMode] = useState(config?.defaults.routing_mode || "balanced");
  const [prompt, setPrompt] = useState("");
  const [customAgents, setCustomAgents] = useState<Agent[]>([]);
  const [disabledAgentIds, setDisabledAgentIds] = useState<Set<string>>(() => new Set());
  const [resourcesOpen, setResourcesOpen] = useState(false);
  const [resourceLoading, setResourceLoading] = useState(false);
  const [resourceError, setResourceError] = useState<string | null>(null);
  const [providerStatuses, setProviderStatuses] = useState<ProviderCliStatus[]>([]);
  const [codexModels, setCodexModels] = useState<ProviderModelCatalog | null>(null);
  const [runtimeHealth, setRuntimeHealth] = useState<RuntimeHealthSnapshot | null>(null);
  const [runtimeUsages, setRuntimeUsages] = useState<RuntimeUsageSnapshot[]>([]);
  const [selectedAccountHome, setSelectedAccountHome] = useState("");
  const [selectedModel, setSelectedModel] = useState("");
  const [selectedReasoning, setSelectedReasoning] = useState("");
  const [agentOverrides, setAgentOverrides] = useState<Record<string, AgentProviderConfig>>({});
  const [settingsMessage, setSettingsMessage] = useState("");
  const [manualStageOrder, setManualStageOrder] = useState<ManualStageId[]>(DEFAULT_MANUAL_STAGE_ORDER);
  const [draggedStageId, setDraggedStageId] = useState<ManualStageId | null>(null);
  const [forcedEnabledAgentIds, setForcedEnabledAgentIds] = useState<Set<string>>(() => new Set());
  const [promptPanelAgentId, setPromptPanelAgentId] = useState<string | null>(null);
  const [promptConfig, setPromptConfig] = useState<AgentPromptConfig | null>(null);
  const [promptPresets, setPromptPresets] = useState<PromptPresetInfo[]>([]);
  const [promptSkills, setPromptSkills] = useState<SkillInfo[]>([]);
  const [promptLoading, setPromptLoading] = useState(false);
  const [promptSaving, setPromptSaving] = useState(false);
  const [promptError, setPromptError] = useState<string | null>(null);
  const [promptTab, setPromptTab] = useState<"skill" | "system" | "preview">("skill");
  const [promptPanelWidth, setPromptPanelWidth] = useState(52);
  const accountOptions = useMemo(() => codexAccountOptions(config), [config]);
  const selectedAccountLabel = accountLabelForValue(accountOptions, selectedAccountHome);
  const modelOptions = codexModels?.models || [];
  const selectedModelInfo = modelOptions.find((model) => model.id === selectedModel);
  const reasoningOptions = selectedModelInfo?.supported_reasoning_levels.length
    ? selectedModelInfo.supported_reasoning_levels.map((level) => level.effort)
    : config?.reasoning_efforts || ["low", "medium", "high", "xhigh"];
  const activeModel = resolvedModel(config, selectedModel);
  const activeReasoning = resolvedReasoning(config, selectedReasoning);
  const reasoningOptionsForModel = useCallback(
    (modelId: string) => {
      const model = modelOptions.find((entry) => entry.id === modelId);
      return model?.supported_reasoning_levels.length
        ? model.supported_reasoning_levels.map((level) => level.effort)
        : config?.reasoning_efforts || ["low", "medium", "high", "xhigh"];
    },
    [config, modelOptions],
  );

  useEffect(() => {
    let cancelled = false;
    async function loadSavedSettings() {
      try {
        const settings = await loadSettings();
        if (cancelled) return;
        setSelectedAccountHome(settings.default_codex_home || "");
        setSelectedModel(settings.default_model || "");
        setSelectedReasoning(settings.default_reasoning_effort || "");
        setAgentOverrides(
          Object.fromEntries(
            (settings.agent_configs || []).map((agentConfig) => [agentConfig.agent_id, agentConfig]),
          ),
        );
      } catch (err) {
        if (!cancelled) {
          setSettingsMessage(err instanceof Error ? err.message : String(err));
        }
      }
    }
    loadSavedSettings();
    return () => {
      cancelled = true;
    };
  }, []);
  const baseAgents = useMemo(
    () =>
      buildAgents(config, runMode, {
        accountLabel: selectedAccountLabel,
        model: selectedModel,
        reasoning: selectedReasoning,
      }),
    [config, runMode, selectedAccountLabel, selectedModel, selectedReasoning],
  );
  const agents = useMemo(() => {
    const visibleAgents = runMode === "manual" ? [...baseAgents, ...customAgents] : baseAgents;
    return visibleAgents.map((agent) => {
      const override = agentOverrides[agent.id];
      const overrideHome = override?.codex_home || "";
      const overrideAccount = override?.account || (overrideHome ? accountLabelForValue(accountOptions, overrideHome) : agent.account);
      const disabled = disabledAgentIds.has(agent.id);
      const forcedEnabled = runMode === "manual" && forcedEnabledAgentIds.has(agent.id);
      return {
        ...agent,
        account: overrideAccount,
        model: override?.model || agent.model,
        reasoning: override?.reasoning_effort || agent.reasoning,
        enabled: disabled ? false : forcedEnabled ? true : agent.enabled,
        status: disabled ? "paused" : agent.status,
      };
    });
  }, [accountOptions, agentOverrides, baseAgents, customAgents, disabledAgentIds, forcedEnabledAgentIds, runMode]);
  const groups = agents.reduce<Record<number, Agent[]>>((acc, agent) => {
    (acc[agent.group] ||= []).push(agent);
    return acc;
  }, {});
  const groupKeys = Object.keys(groups).map(Number).sort((a, b) => a - b);
  const t = (ko: string, en: string) => (lang === "ko" ? ko : en);
  const manualCounts = useMemo(() => {
    const enabled = agents.filter((agent) => agent.enabled);
    return {
      plannerCount: Math.max(1, Math.min(3, enabled.filter((agent) => agent.name.startsWith("Planner")).length)),
      codeAgentCount: Math.max(1, Math.min(6, enabled.filter((agent) => agent.name.startsWith("Code Agent")).length)),
      qaAgentCount: Math.max(0, Math.min(2, enabled.filter((agent) => agent.name.startsWith("QA")).length)),
    };
  }, [agents]);
  const agentConfigs = useMemo(
    () =>
      agents
        .filter((agent) => agent.provider === "Codex")
        .map((agent) => ({
          agent_id: agent.id,
          provider: "codex",
          account: agent.account,
          codex_home: (agentOverrides[agent.id]?.codex_home ?? selectedAccountHome) || null,
          model: agent.model === "Codex CLI default" ? null : agent.model,
          reasoning_effort: agent.reasoning === "Codex CLI default" ? null : agent.reasoning,
          enabled: agent.enabled,
        })),
    [agentOverrides, agents, selectedAccountHome],
  );
  const manualGraph = useMemo(() => deriveManualWorkflowGraph(agents, manualStageOrder), [agents, manualStageOrder]);
  const graphWarnings = manualGraph.warnings;
  const selectedPromptAgent = promptPanelAgentId ? agents.find((agent) => agent.id === promptPanelAgentId) || null : null;
  const llmQaEnabled = runMode === "manual" ? manualCounts.qaAgentCount > 0 : runMode !== "fast" && (config?.defaults.qa_agent_count || 0) > 0;

  useEffect(() => {
    if (!selectedModel && config?.defaults.model) {
      setSelectedModel(config.defaults.model);
    }
    if (!selectedReasoning && config?.defaults.reasoning_effort) {
      setSelectedReasoning(config.defaults.reasoning_effort);
    }
  }, [config, selectedModel, selectedReasoning]);

  useEffect(() => {
    if (!selectedModel && modelOptions.length > 0) {
      setSelectedModel(modelOptions[0].id);
    }
  }, [modelOptions, selectedModel]);

  useEffect(() => {
    if (codexModels || resourceLoading) {
      return;
    }
    let cancelled = false;
    getCodexModels()
      .then((models) => {
        if (!cancelled) {
          setCodexModels(models);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setCodexModels({ provider: "codex", ok: false, source: "not loaded", models: [], error: "Model catalog unavailable." });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [codexModels, resourceLoading]);

  useEffect(() => {
    if (!selectedModelInfo) {
      return;
    }
    const supported = selectedModelInfo.supported_reasoning_levels.map((level) => level.effort);
    if (supported.length > 0 && (!selectedReasoning || !supported.includes(selectedReasoning))) {
      setSelectedReasoning(selectedModelInfo.default_reasoning_level || supported[0]);
    }
  }, [selectedModelInfo, selectedReasoning]);

  async function loadResources() {
    setResourceLoading(true);
    setResourceError(null);
    try {
      const [nextProviders, nextModels, nextHealth, nextUsage] = await Promise.all([
        listProviders(),
        getCodexModels(),
        getRuntimeHealth(),
        getRuntimeUsages(),
      ]);
      setProviderStatuses(nextProviders);
      setCodexModels(nextModels);
      setRuntimeHealth(nextHealth);
      setRuntimeUsages(nextUsage);
    } catch (err) {
      setResourceError(err instanceof Error ? err.message : String(err));
    } finally {
      setResourceLoading(false);
    }
  }

  useEffect(() => {
    if (resourcesOpen && providerStatuses.length === 0 && !resourceLoading) {
      loadResources();
    }
  }, [resourcesOpen]);

  useEffect(() => {
    if (!promptPanelAgentId) {
      return;
    }
    let cancelled = false;
    setPromptLoading(true);
    setPromptError(null);
    Promise.all([loadAgentPrompt(promptPanelAgentId), loadPromptCatalog()])
      .then(([agentPrompt, catalog]) => {
        if (cancelled) return;
        setPromptConfig(agentPrompt);
        setPromptPresets(catalog.presets);
        setPromptSkills(catalog.skills || []);
      })
      .catch((err) => {
        if (!cancelled) {
          setPromptError(err instanceof Error ? err.message : String(err));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setPromptLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [promptPanelAgentId]);

  function updateAgentConfig(agent: Agent, patch: Partial<AgentProviderConfig>) {
    setAgentOverrides((current) => ({
      ...current,
      [agent.id]: {
        agent_id: agent.id,
        provider: "codex",
        account: agent.account,
        codex_home: selectedAccountHome || null,
        model: agent.model === "Codex CLI default" ? null : agent.model,
        reasoning_effort: agent.reasoning === "Codex CLI default" ? null : agent.reasoning,
        enabled: agent.enabled,
        ...current[agent.id],
        ...patch,
      },
    }));
  }

  async function handleSavePreset() {
    const settings: LocalAppSettings = {
      default_provider: "codex",
      default_account: selectedAccountLabel,
      default_codex_home: selectedAccountHome || null,
      default_model: selectedModel || config?.defaults.model || null,
      default_reasoning_effort: selectedReasoning || config?.defaults.reasoning_effort || null,
      agent_configs: agentConfigs,
    };
    try {
      await saveSettings(settings);
      setSettingsMessage(t("프리셋 저장 완료", "Preset saved"));
    } catch (err) {
      setSettingsMessage(err instanceof Error ? err.message : String(err));
    }
  }

  function openPromptEditor(agentId: string) {
    setPromptPanelAgentId(agentId);
    setPromptTab("skill");
  }

  function updatePromptConfig(patch: Partial<AgentPromptConfig>) {
    setPromptConfig((current) => {
      if (!current) return current;
      const next = { ...current, ...patch };
      next.effective_prompt_preview = [
        next.system_prompt?.trim() ? `System Prompt:\n${next.system_prompt.trim()}` : "",
        next.skill_markdown?.trim() ? `Skill / Guideline:\n${next.skill_markdown.trim()}` : "",
      ].filter(Boolean).join("\n\n");
      return next;
    });
  }

  function applyPromptPreset(preset: PromptPresetInfo) {
    updatePromptConfig({
      preset: preset.id,
      skill_id: null,
      skill_markdown: preset.skill_markdown,
    });
  }

  function applySkillSource(skill: SkillInfo) {
    updatePromptConfig({
      skill_id: skill.id,
      preset: null,
      skill_markdown: skill.markdown,
    });
  }

  async function handleSaveAgentPrompt() {
    if (!promptConfig) return;
    setPromptSaving(true);
    setPromptError(null);
    try {
      const saved = await saveAgentPrompt(promptConfig.agent_id, {
        agent_id: promptConfig.agent_id,
        preset: promptConfig.preset || null,
        skill_id: promptConfig.skill_id || null,
        skill_markdown: promptConfig.skill_markdown,
        system_prompt: promptConfig.system_prompt,
      });
      setPromptConfig(saved);
      setSettingsMessage(t("프롬프트 저장 완료", "Prompt saved"));
    } catch (err) {
      setPromptError(err instanceof Error ? err.message : String(err));
    } finally {
      setPromptSaving(false);
    }
  }

  async function handleResetAgentPrompt() {
    if (!promptConfig) return;
    setPromptSaving(true);
    setPromptError(null);
    try {
      const reset = await resetAgentPrompt(promptConfig.agent_id);
      setPromptConfig(reset);
      setSettingsMessage(t("프롬프트 초기화 완료", "Prompt reset"));
    } catch (err) {
      setPromptError(err instanceof Error ? err.message : String(err));
    } finally {
      setPromptSaving(false);
    }
  }

  function moveManualStage(stageId: ManualStageId, offset: -1 | 1) {
    setManualStageOrder((current) => {
      const index = current.indexOf(stageId);
      const target = index + offset;
      if (index < 0 || target < 0 || target >= current.length) return current;
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }

  function dropManualStage(targetStageId: ManualStageId) {
    if (!draggedStageId || draggedStageId === targetStageId) return;
    setManualStageOrder((current) => {
      const draggedIndex = current.indexOf(draggedStageId);
      const targetIndex = current.indexOf(targetStageId);
      if (draggedIndex < 0 || targetIndex < 0) return current;
      const next = [...current];
      const [item] = next.splice(draggedIndex, 1);
      next.splice(targetIndex, 0, item);
      return next;
    });
    setDraggedStageId(null);
  }

  function resetManualGraph() {
    setManualStageOrder(DEFAULT_MANUAL_STAGE_ORDER);
    setForcedEnabledAgentIds((current) => {
      const next = new Set(current);
      next.delete("integrator");
      return next;
    });
  }

  function toggleIntegratorStage() {
    setManualStageOrder((current) =>
      current.includes("integration") ? current.filter((stage) => stage !== "integration") : insertBeforeStage(current, "integration", "qa"),
    );
    setForcedEnabledAgentIds((current) => {
      const next = new Set(current);
      if (next.has("integrator")) next.delete("integrator");
      else next.add("integrator");
      return next;
    });
    setDisabledAgentIds((current) => {
      const next = new Set(current);
      next.delete("integrator");
      return next;
    });
  }

  function addManualAgent() {
    if (runMode !== "manual") {
      setRunMode("manual");
      return;
    }
    const rawType = window.prompt("Add agent type: planner, code, qa, architect, integrator", "code");
    const type = (rawType || "code").trim().toLowerCase();
    if (type === "integrator") {
      setForcedEnabledAgentIds((current) => new Set(current).add("integrator"));
      setDisabledAgentIds((current) => {
        const next = new Set(current);
        next.delete("integrator");
        return next;
      });
      setManualStageOrder((current) => insertBeforeStage(current, "integration", "qa"));
      return;
    }
    const id = nextManualAgentId(type, agents);
    const model = activeModel;
    const reasoning = activeReasoning;
    const account = selectedAccountLabel;
    const nextGroup = Math.max(1, ...agents.map((agent) => agent.group)) + 1;
    const templates: Record<string, Omit<Agent, "id" | "group">> = {
      planner: {
        name: `Planner ${manualCounts.plannerCount + 1}`,
        role: "Manual Planning",
        description: "Manual-mode planning agent.",
        capabilities: ["Planning", "Risk", "Spec"],
        provider: "Codex",
        account,
        model,
        reasoning,
        skill: "none",
        status: "ready",
        contextLeft: null,
        sessionId: "new",
        lastAction: "Added in manual mode",
        enabled: true,
        custom: true,
      },
      code: {
        name: `Code Agent ${manualCounts.codeAgentCount + 1}`,
        role: "Manual Implementation",
        description: "Manual-mode code agent.",
        capabilities: ["Code", "Tests", "Local Files"],
        provider: "Codex",
        account,
        model,
        reasoning,
        skill: "karpathy/code_agent",
        status: "ready",
        contextLeft: null,
        sessionId: "new",
        lastAction: "Added in manual mode",
        enabled: true,
        custom: true,
      },
      qa: {
        name: `QA Agent ${manualCounts.qaAgentCount + 1}`,
        role: "Manual QA",
        description: "Manual-mode QA review agent.",
        capabilities: ["QA", "Report", "Screenshots"],
        provider: "Codex",
        account,
        model,
        reasoning,
        skill: "none",
        status: "ready",
        contextLeft: null,
        sessionId: "new",
        lastAction: "Added in manual mode",
        enabled: true,
        custom: true,
      },
      architect: {
        name: "Architect",
        role: "Manual Contract",
        description: "Manual-mode contract agent.",
        capabilities: ["Schema", "Boundaries", "Manifest"],
        provider: "Codex",
        account,
        model,
        reasoning,
        skill: "architect.md",
        status: "ready",
        contextLeft: null,
        sessionId: "new",
        lastAction: "Added in manual mode",
        enabled: true,
        custom: true,
      },
      integrator: {
        name: "Integrator",
        role: "Manual Merge",
        description: "Manual-mode integration agent.",
        capabilities: ["Merge", "Resolve", "QA Prep"],
        provider: "Codex",
        account,
        model,
        reasoning,
        skill: "karpathy/integrator",
        status: "ready",
        contextLeft: null,
        sessionId: "new",
        lastAction: "Added in manual mode",
        enabled: true,
        custom: true,
      },
    };
    const template = templates[type] || templates.code;
    setCustomAgents((current) => [...current, { ...template, id, group: nextGroup }]);
  }

  function toggleAgent(id: string) {
    const selectedAgent = agents.find((agent) => agent.id === id);
    if (selectedAgent && !selectedAgent.enabled) {
      setForcedEnabledAgentIds((current) => new Set(current).add(id));
      setDisabledAgentIds((current) => {
        const next = new Set(current);
        next.delete(id);
        return next;
      });
      return;
    }
    setForcedEnabledAgentIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      return next;
    });
    setDisabledAgentIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function deleteAgent(id: string) {
    setCustomAgents((current) => current.filter((agent) => agent.id !== id));
    setForcedEnabledAgentIds((current) => {
      const next = new Set(current);
      next.delete(id);
      return next;
    });
    setDisabledAgentIds((current) => {
      const next = new Set(current);
      next.delete(id);
      return next;
    });
  }

  return (
    <div
      className="size-full flex text-slate-900 dark:text-slate-100 relative"
      style={{
        background:
          theme === "dark"
            ? "radial-gradient(1200px 600px at 0% 0%, rgba(99,102,241,0.18), transparent 60%), linear-gradient(180deg, #0a0f1c 0%, #0b1224 100%)"
            : "radial-gradient(1200px 600px at 0% 0%, rgba(99,102,241,0.08), transparent 60%), linear-gradient(180deg, #eef2f7 0%, #e8edf5 100%)",
      }}
    >
      <aside className="w-64 shrink-0 border-r border-slate-200/80 dark:border-slate-700/70 flex flex-col overflow-hidden bg-gradient-to-b from-slate-50 to-indigo-50/40 dark:from-slate-900 dark:to-indigo-950/40">
        <div className="px-3 py-3 border-b border-slate-200/70 dark:border-slate-700/70 flex items-center gap-2">
          <div className="size-6 rounded bg-indigo-600 text-white flex items-center justify-center shadow-[0_1px_0_rgba(79,70,229,0.4)]">
            <Boxes className="size-3.5" />
          </div>
          <div className="min-w-0">
            <div className="text-slate-900 dark:text-slate-100" style={{ fontSize: 13 }}>Orchestra</div>
            <div className="font-mono text-slate-500 dark:text-slate-500 truncate" style={{ fontSize: 10 }}>local desktop API</div>
          </div>
        </div>
        <div className="overflow-y-auto flex-1">
          <SidebarSection title={t("프로바이더", "Providers")}>
            {(config?.providers || []).slice(0, 5).map((provider) => (
              <ProviderRow
                key={`${provider.name}-${provider.account}`}
                name={provider.name}
                account={provider.account}
                ok={provider.configured}
                status={provider.status}
                warn={provider.display_only}
              />
            ))}
            {!config && <ProviderRow name="Local API" account="127.0.0.1" ok={false} status="loading" />}
          </SidebarSection>
          <SidebarSection title={t("실행 모드", "Run Mode")}>
            <div className="flex flex-wrap gap-1">
              {(config?.routing_modes || ["fast", "balanced", "parallel", "manual"]).map((mode) => (
                <Pill key={mode} active={runMode === mode} onClick={() => setRunMode(mode)}>
                  {mode}
                </Pill>
              ))}
            </div>
            <div className={`rounded-md border px-2 py-1.5 ${llmQaEnabled ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-slate-200 bg-white text-slate-600"}`} style={{ fontSize: 11 }}>
              QA route: {llmQaEnabled ? "LLM QA Agent enabled" : "mechanical QA only"}
            </div>
          </SidebarSection>
          <SidebarSection title={t("기본값", "Defaults")}>
            <SelectField
              label={t("계정", "Account")}
              value={selectedAccountHome}
              onChange={setSelectedAccountHome}
              options={accountOptions.map((option) => ({ label: option.label, value: option.value }))}
            />
            <SelectField
              label={t("모델", "Model")}
              value={selectedModel}
              onChange={setSelectedModel}
              options={[
                ...(config?.defaults.model ? [{ label: config.defaults.model, value: config.defaults.model }] : []),
                ...modelOptions
                  .filter((model) => model.id !== config?.defaults.model)
                  .map((model) => ({ label: model.id, value: model.id })),
              ]}
            />
            <SelectField
              label={t("추론", "Reasoning")}
              value={selectedReasoning}
              onChange={setSelectedReasoning}
              options={reasoningOptions.map((effort) => ({ label: effort, value: effort }))}
            />
            <Field label={t("타임아웃", "Timeout")} value={`${config?.defaults.timeout_seconds || 900}s`} />
            <Field label={t("재시도", "Retries")} value={`${config?.defaults.max_fix_iterations ?? 1}`} />
          </SidebarSection>
          <SidebarSection title={t("히스토리", "History")}>
            {runs.slice(0, 5).map((run) => (
              <button key={run.run_id} onClick={() => onOpenRun(run.run_id)} className="w-full text-left px-2 py-1.5 rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 hover:border-indigo-300" style={{ fontSize: 12 }}>
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono truncate">{run.run_id}</span>
                  <span className="text-slate-500 dark:text-slate-500">{run.status}</span>
                </div>
                <div className="text-slate-500 dark:text-slate-500 truncate" style={{ fontSize: 10 }}>{run.user_request}</div>
              </button>
            ))}
            {runs.length === 0 && <div className="text-slate-500 dark:text-slate-500" style={{ fontSize: 12 }}>{t("실행 기록 없음", "No runs yet")}</div>}
          </SidebarSection>
        </div>
        <AccountFooter lang={lang} setLang={setLang} theme={theme} setTheme={setTheme} />
      </aside>

      <main className="flex-1 flex flex-col min-w-0">
        <header className="h-12 px-5 border-b border-slate-200 dark:border-slate-700 bg-white/70 dark:bg-slate-900/60 backdrop-blur-sm flex items-center justify-between shrink-0">
          <div className="flex items-center gap-3">
            <span className="text-slate-900 dark:text-slate-100" style={{ fontSize: 13 }}>{t("에이전트 로스터", "Agent Roster")}</span>
            <span className="text-slate-300 dark:text-slate-700" style={{ fontSize: 12 }}>/</span>
            <span className="font-mono text-slate-500 dark:text-slate-500" style={{ fontSize: 12 }}>local-api</span>
            <span className="ml-2 px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 font-mono text-slate-600 dark:text-slate-500" style={{ fontSize: 10 }}>
              {agents.length} {t("에이전트", "agents")}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button className="px-2 py-1 rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 inline-flex items-center gap-1 text-slate-600 dark:text-slate-500" style={{ fontSize: 12 }}>
              <Layers className="size-3.5" /> {t("워크플로", "Workflow")}
            </button>
            <button onClick={() => setResourcesOpen(true)} className="px-2 py-1 rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 inline-flex items-center gap-1 text-slate-600 dark:text-slate-500" style={{ fontSize: 12 }}>
              <Cpu className="size-3.5" /> {t("리소스", "Resources")}
            </button>
          </div>
        </header>
        <div className={`px-5 py-2 border-b border-slate-200 dark:border-slate-700 bg-white/40 dark:bg-slate-900/40 backdrop-blur-sm shrink-0 ${runMode === "manual" ? "" : "flex items-center gap-1.5 overflow-x-auto"}`}>
          {runMode === "manual" ? (
            <ManualGraphEditor
              agents={agents}
              graph={manualGraph.graph}
              warnings={graphWarnings}
              stageOrder={manualStageOrder}
              draggedStageId={draggedStageId}
              forcedEnabledAgentIds={forcedEnabledAgentIds}
              setDraggedStageId={setDraggedStageId}
              dropManualStage={dropManualStage}
              moveManualStage={moveManualStage}
              toggleIntegratorStage={toggleIntegratorStage}
              resetManualGraph={resetManualGraph}
            />
          ) : groupKeys.map((group, index) => (
            <div key={group} className="flex items-center gap-1.5">
              <div className="px-2 py-1 rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 flex items-center gap-1.5 shadow-[0_1px_0_rgba(15,23,42,0.02)]">
                <span className="font-mono text-slate-400 dark:text-slate-500" style={{ fontSize: 10 }}>{group}</span>
                <span className="text-slate-700 dark:text-slate-300" style={{ fontSize: 12 }}>{groups[group].map((agent) => agent.name).join(" + ")}</span>
                {groups[group].length > 1 && <span className="px-1 rounded bg-indigo-50 text-indigo-700 border border-indigo-100 font-mono" style={{ fontSize: 10 }}>{t("병렬", "parallel")}</span>}
              </div>
              {index < groupKeys.length - 1 && <ChevronRight className="size-3.5 text-slate-300 dark:text-slate-700" />}
            </div>
          ))}
        </div>
        <div className="flex-1 overflow-y-auto p-5">
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {agents.map((agent) => (
              <AgentCard
                key={agent.id}
                agent={agent}
                lang={lang}
                editable={runMode === "manual"}
                configurable
                accountOptions={accountOptions}
                modelOptions={modelOptions}
                defaultCodexHome={selectedAccountHome}
                override={agentOverrides[agent.id]}
                reasoningOptionsForModel={reasoningOptionsForModel}
                onConfigChange={(patch) => updateAgentConfig(agent, patch)}
                onToggle={() => toggleAgent(agent.id)}
                onDelete={() => deleteAgent(agent.id)}
                onEditPrompt={() => openPromptEditor(agent.id)}
              />
            ))}
            <button
              onClick={addManualAgent}
              className="rounded-lg border border-dashed border-slate-300 dark:border-slate-600 bg-white/50 dark:bg-slate-900/50 hover:border-indigo-300 hover:bg-indigo-50/40 hover:text-indigo-700 transition-colors flex flex-col items-center justify-center text-slate-500 dark:text-slate-500 min-h-64"
            >
              <Plus className="size-5 mb-1" />
              <span style={{ fontSize: 13 }}>{t("에이전트 추가", "Add Agent")}</span>
              <span className="text-slate-400 dark:text-slate-500 mt-0.5" style={{ fontSize: 11 }}>
                {runMode === "manual" ? "Planner / Architect / Code / QA" : t("manual 모드로 전환", "switches to manual")}
              </span>
            </button>
          </div>
        </div>
        <div className="border-t border-slate-200 dark:border-slate-700 bg-white/60 dark:bg-slate-900/60 backdrop-blur-sm px-5 py-3 shrink-0">
          <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 shadow-[0_1px_0_rgba(15,23,42,0.02),0_4px_16px_rgba(15,23,42,0.05)] focus-within:border-indigo-300 focus-within:ring-1 focus-within:ring-indigo-200 transition-colors">
            <textarea
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              rows={3}
              placeholder={t("에이전트가 만들 앱이나 기능을 설명해주세요...", "Describe the app or feature you want the agents to build...")}
              className="w-full resize-none px-3 py-2.5 bg-transparent outline-none text-slate-800 dark:text-slate-200 placeholder:text-slate-400 dark:placeholder:text-slate-500"
              style={{ fontSize: 13 }}
            />
            <div className="flex items-center justify-between px-2 py-1.5 border-t border-slate-100 dark:border-slate-800 bg-slate-50/60 dark:bg-slate-900/60 rounded-b-lg">
              <div className="flex items-center gap-1 min-w-0">
                <ToolButton icon={<Paperclip className="size-3.5" />} label={t("첨부", "Attach")} />
                <ToolButton icon={<FileText className="size-3.5" />} label={t("스킬 파일", "Skill file")} />
                <ToolButton icon={<RotateCw className="size-3.5" />} label={t("세션 이어가기", "Continue session")} />
                <span className="ml-2 font-mono text-slate-400 dark:text-slate-500 truncate" style={{ fontSize: 10 }}>
                  {t("모드", "mode")}: {runMode} · account: {selectedAccountLabel} · model: {activeModel} · reasoning: {activeReasoning}
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                <button
                  onClick={handleSavePreset}
                  className="px-2.5 py-1.5 rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 inline-flex items-center gap-1.5 text-slate-700 dark:text-slate-300"
                  style={{ fontSize: 12 }}
                >
                  <Save className="size-3.5" /> {t("프리셋 저장", "Save Preset")}
                </button>
                <button
                  onClick={() =>
                    onStartRun(prompt, runMode, {
                      ...(runMode === "manual" ? manualCounts : {}),
                      model: selectedModel || config?.defaults.model || null,
                      reasoningEffort: selectedReasoning || config?.defaults.reasoning_effort || null,
                      codexHome: selectedAccountHome || null,
                      agentConfigs,
                      workflowGraph: runMode === "manual" ? manualGraph.graph : null,
                    })
                  }
                  disabled={loading || !prompt.trim() || (runMode === "manual" && graphWarnings.length > 0)}
                  className="px-3 py-1.5 rounded-md bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-60 inline-flex items-center gap-1.5 shadow-[0_1px_0_rgba(79,70,229,0.4),0_2px_6px_rgba(79,70,229,0.25)]"
                  style={{ fontSize: 12 }}
                >
                  <Play className="size-3.5" /> {loading ? t("실행 생성 중", "Creating run") : t("실행 시작", "Start Run")}
                </button>
              </div>
            </div>
          </div>
          {error && <div className="mt-2 text-rose-700 bg-rose-50 border border-rose-200 rounded px-2 py-1" style={{ fontSize: 12 }}>{error}</div>}
          {runMode === "manual" && graphWarnings.length > 0 && (
            <div className="mt-2 text-amber-800 bg-amber-50 border border-amber-200 rounded px-2 py-1" style={{ fontSize: 12 }}>
              {graphWarnings.join(" ")}
            </div>
          )}
          {settingsMessage && !error && (
            <div className="mt-2 text-slate-600 bg-slate-50 border border-slate-200 rounded px-2 py-1" style={{ fontSize: 12 }}>
              {settingsMessage}
            </div>
          )}
        </div>
      </main>
      {resourcesOpen && (
        <ResourcePanel
          providers={providerStatuses}
          models={codexModels}
          health={runtimeHealth}
          usages={runtimeUsages}
          loading={resourceLoading}
          error={resourceError}
          onRefresh={loadResources}
          onClose={() => setResourcesOpen(false)}
        />
      )}
      {selectedPromptAgent && (
        <PromptEditorPanel
          agent={selectedPromptAgent}
          promptConfig={promptConfig}
          presets={promptPresets}
          skills={promptSkills}
          loading={promptLoading}
          saving={promptSaving}
          error={promptError}
          width={promptPanelWidth}
          activeTab={promptTab}
          onTabChange={setPromptTab}
          onWidthChange={setPromptPanelWidth}
          onChange={updatePromptConfig}
          onApplyPreset={applyPromptPreset}
          onApplySkill={applySkillSource}
          onSave={handleSaveAgentPrompt}
          onReset={handleResetAgentPrompt}
          onClose={() => {
            setPromptPanelAgentId(null);
            setPromptConfig(null);
            setPromptError(null);
          }}
        />
      )}
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 py-1.5 shadow-[0_1px_0_rgba(15,23,42,0.02)]">
      <span className="text-slate-500 dark:text-slate-500" style={{ fontSize: 11 }}>{label}</span>
      <span className="font-mono text-slate-700 dark:text-slate-300 truncate" style={{ fontSize: 11 }}>{value}</span>
    </div>
  );
}

function SelectField({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: Array<{ label: string; value: string }>;
  onChange: (value: string) => void;
}) {
  const normalizedOptions = options.length > 0 ? options : [{ label: "--", value: "" }];
  const normalizedValue = normalizedOptions.some((option) => option.value === value) ? value : normalizedOptions[0].value;
  return (
    <label className="flex flex-col gap-1 rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 py-1.5 shadow-[0_1px_0_rgba(15,23,42,0.02)]">
      <span className="text-slate-500 dark:text-slate-500" style={{ fontSize: 11 }}>{label}</span>
      <select
        value={normalizedValue}
        onChange={(event) => onChange(event.target.value)}
        className="w-full bg-transparent font-mono text-slate-800 dark:text-slate-200 outline-none"
        style={{ fontSize: 11 }}
      >
        {normalizedOptions.map((option) => (
          <option key={`${option.label}-${option.value}`} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function ToolButton({ icon, label }: { icon: ReactNode; label: string }) {
  return (
    <button className="px-2 py-1 rounded-md hover:bg-slate-100 dark:hover:bg-slate-800 inline-flex items-center gap-1.5 text-slate-600 dark:text-slate-500" style={{ fontSize: 12 }}>
      {icon}
      <span>{label}</span>
    </button>
  );
}

export function AccountFooter({
  lang,
  setLang,
  theme,
  setTheme,
}: {
  lang: Lang;
  setLang: (l: Lang) => void;
  theme: "light" | "dark";
  setTheme: (t: "light" | "dark") => void;
}) {
  const [open, setOpen] = useState(false);
  const t = (ko: string, en: string) => (lang === "ko" ? ko : en);
  return (
    <div className="border-t border-slate-200/70 dark:border-slate-700/70 bg-white/50 dark:bg-slate-900/50 backdrop-blur-sm relative">
      {open && (
        <div className="absolute bottom-full left-2 right-2 mb-1 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 shadow-[0_8px_24px_rgba(15,23,42,0.08)] overflow-hidden">
          <div className="px-3 py-2 border-b border-slate-100 dark:border-slate-800">
            <div className="text-slate-400 dark:text-slate-500 uppercase tracking-wider mb-1.5" style={{ fontSize: 10 }}>{t("언어", "Language")}</div>
            <Segmented options={[{ id: "ko", label: "한국어" }, { id: "en", label: "English" }]} value={lang} onChange={(value) => setLang(value as Lang)} />
          </div>
          <div className="px-3 py-2 border-b border-slate-100 dark:border-slate-800">
            <div className="text-slate-400 dark:text-slate-500 uppercase tracking-wider mb-1.5" style={{ fontSize: 10 }}>{t("테마", "Theme")}</div>
            <Segmented
              options={[{ id: "light", label: t("라이트", "Light"), icon: <Sun className="size-3" /> }, { id: "dark", label: t("다크", "Dark"), icon: <Moon className="size-3" /> }]}
              value={theme}
              onChange={(value) => setTheme(value as "light" | "dark")}
            />
          </div>
          <button className="w-full text-left px-3 py-2 hover:bg-rose-50/60 text-rose-700 inline-flex items-center gap-1.5" style={{ fontSize: 12 }}>
            <LogOut className="size-3.5" /> {t("닫기", "Close")}
          </button>
        </div>
      )}
      <button onClick={() => setOpen((value) => !value)} className="w-full flex items-center gap-2 px-3 py-2.5 hover:bg-white/80 dark:hover:bg-slate-900/70 transition-colors">
        <div className="size-7 rounded-full bg-gradient-to-br from-indigo-500 to-sky-500 text-white flex items-center justify-center font-mono" style={{ fontSize: 11 }}>OP</div>
        <div className="min-w-0 flex-1 text-left">
          <div className="text-slate-800 dark:text-slate-200 truncate" style={{ fontSize: 12 }}>operator@local</div>
          <div className="font-mono text-slate-500 dark:text-slate-500 truncate" style={{ fontSize: 10 }}>127.0.0.1 API</div>
        </div>
        <div className="flex items-center gap-0.5">
          <span className="px-1.5 py-0.5 rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 font-mono text-slate-600 dark:text-slate-500" style={{ fontSize: 10 }}>
            {lang === "ko" ? "한" : "EN"}
          </span>
          <span className="size-5 rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 inline-flex items-center justify-center text-slate-600 dark:text-slate-500">
            {theme === "light" ? <Sun className="size-3" /> : <Moon className="size-3" />}
          </span>
          <Settings className="size-3.5 text-slate-400 dark:text-slate-500 ml-0.5" />
          <ChevronUp className={`size-3.5 text-slate-400 dark:text-slate-500 transition-transform ${open ? "" : "rotate-180"}`} />
        </div>
      </button>
    </div>
  );
}

function Segmented({ options, value, onChange }: { options: { id: string; label: string; icon?: ReactNode }[]; value: string; onChange: (id: string) => void }) {
  return (
    <div className="inline-flex p-0.5 rounded-md border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 w-full">
      {options.map((option) => {
        const active = value === option.id;
        return (
          <button
            key={option.id}
            onClick={() => onChange(option.id)}
            className={`flex-1 inline-flex items-center justify-center gap-1 px-2 py-1 rounded transition-colors ${active ? "bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 shadow-[0_1px_0_rgba(15,23,42,0.05)] border border-slate-200 dark:border-slate-700" : "text-slate-600 dark:text-slate-500 hover:text-slate-900 dark:hover:text-slate-100"}`}
            style={{ fontSize: 11 }}
          >
            {option.icon}
            <span>{option.label}</span>
          </button>
        );
      })}
    </div>
  );
}
