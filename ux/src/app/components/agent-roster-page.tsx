import { useMemo, useState, type ReactNode } from "react";
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
import { AppConfig, RunSummary } from "../api";

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

function resolvedModel(config: AppConfig | null) {
  return config?.defaults.model || "Codex CLI default";
}

function resolvedReasoning(config: AppConfig | null) {
  return config?.defaults.reasoning_effort || "Codex CLI default";
}

function buildAgents(config: AppConfig | null, runMode: string): Agent[] {
  const model = resolvedModel(config);
  const reasoning = resolvedReasoning(config);
  const codeCount = Math.max(1, config?.defaults.code_agent_count || (runMode === "parallel" ? 2 : 1));
  const qaCount = Math.max(0, config?.defaults.qa_agent_count || 0);
  const codeAgents = Array.from({ length: runMode === "parallel" ? Math.max(2, codeCount) : 1 }, (_, index) => ({
    id: `code_${index + 1}`,
    name: `Code Agent ${index + 1}`,
    role: index === 0 ? "Implementation" : "Parallel Implementation",
    description: index === 0 ? "Implements the approved plan." : "Owns assigned paths in a parallel workspace.",
    capabilities: ["Code", "Tests", "Local Files"],
    provider: "Codex" as const,
    account: codexAccount(config, index),
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
      account: codexAccount(config, 0),
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
      account: codexAccount(config, 0),
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
            account: codexAccount(config, 0),
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
      account: codexAccount(config, 0),
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
      account: codexAccount(config, 0),
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
  onToggle,
  onDelete,
}: {
  agent: Agent;
  lang: Lang;
  editable?: boolean;
  onToggle?: () => void;
  onDelete?: () => void;
}) {
  const tint = tintFor(agent.name);
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
          <button className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800" title="Settings">
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
        <Meta label={lang === "ko" ? "스킬" : "skill"} value={agent.skill} mono icon={<FileText className="size-3" />} />
        <Meta label={lang === "ko" ? "세션" : "session"} value={agent.sessionId} mono />
      </div>
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
    options?: { plannerCount?: number; codeAgentCount?: number; qaAgentCount?: number },
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
  const baseAgents = useMemo(() => buildAgents(config, runMode), [config, runMode]);
  const agents = useMemo(() => {
    const visibleAgents = runMode === "manual" ? [...baseAgents, ...customAgents] : baseAgents;
    return visibleAgents.map((agent) => ({
      ...agent,
      enabled: disabledAgentIds.has(agent.id) ? false : agent.enabled,
      status: disabledAgentIds.has(agent.id) ? "paused" : agent.status,
    }));
  }, [baseAgents, customAgents, disabledAgentIds, runMode]);
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

  function addManualAgent() {
    if (runMode !== "manual") {
      setRunMode("manual");
      return;
    }
    const rawType = window.prompt("Add agent type: planner, code, qa, architect, integrator", "code");
    const type = (rawType || "code").trim().toLowerCase();
    const id = `manual_${type}_${Date.now()}`;
    const model = resolvedModel(config);
    const reasoning = resolvedReasoning(config);
    const nextGroup = Math.max(1, ...agents.map((agent) => agent.group)) + 1;
    const templates: Record<string, Omit<Agent, "id" | "group">> = {
      planner: {
        name: `Planner ${manualCounts.plannerCount + 1}`,
        role: "Manual Planning",
        description: "Manual-mode planning agent.",
        capabilities: ["Planning", "Risk", "Spec"],
        provider: "Codex",
        account: codexAccount(config, 0),
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
        account: codexAccount(config, manualCounts.codeAgentCount),
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
        account: codexAccount(config, 0),
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
        account: codexAccount(config, 0),
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
        account: codexAccount(config, 0),
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
    setDisabledAgentIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function deleteAgent(id: string) {
    setCustomAgents((current) => current.filter((agent) => agent.id !== id));
    setDisabledAgentIds((current) => {
      const next = new Set(current);
      next.delete(id);
      return next;
    });
  }

  return (
    <div
      className="size-full flex text-slate-900 dark:text-slate-100"
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
          </SidebarSection>
          <SidebarSection title={t("기본값", "Defaults")}>
            <Field label={t("모델", "Model")} value={resolvedModel(config)} />
            <Field label={t("추론", "Reasoning")} value={resolvedReasoning(config)} />
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
            <button className="px-2 py-1 rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 inline-flex items-center gap-1 text-slate-600 dark:text-slate-500" style={{ fontSize: 12 }}>
              <Cpu className="size-3.5" /> {t("리소스", "Resources")}
            </button>
          </div>
        </header>
        <div className="px-5 py-2 border-b border-slate-200 dark:border-slate-700 bg-white/40 dark:bg-slate-900/40 backdrop-blur-sm flex items-center gap-1.5 overflow-x-auto shrink-0">
          {groupKeys.map((group, index) => (
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
                onToggle={() => toggleAgent(agent.id)}
                onDelete={() => deleteAgent(agent.id)}
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
                  {t("모드", "mode")}: {runMode} · model: {resolvedModel(config)} · reasoning: {resolvedReasoning(config)}
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                <button className="px-2.5 py-1.5 rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 inline-flex items-center gap-1.5 text-slate-700 dark:text-slate-300" style={{ fontSize: 12 }}>
                  <Save className="size-3.5" /> {t("프리셋 저장", "Save Preset")}
                </button>
                <button
                  onClick={() => onStartRun(prompt, runMode, runMode === "manual" ? manualCounts : undefined)}
                  disabled={loading || !prompt.trim()}
                  className="px-3 py-1.5 rounded-md bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-60 inline-flex items-center gap-1.5 shadow-[0_1px_0_rgba(79,70,229,0.4),0_2px_6px_rgba(79,70,229,0.25)]"
                  style={{ fontSize: 12 }}
                >
                  <Play className="size-3.5" /> {loading ? t("실행 생성 중", "Creating run") : t("실행 시작", "Start Run")}
                </button>
              </div>
            </div>
          </div>
          {error && <div className="mt-2 text-rose-700 bg-rose-50 border border-rose-200 rounded px-2 py-1" style={{ fontSize: 12 }}>{error}</div>}
        </div>
      </main>
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
