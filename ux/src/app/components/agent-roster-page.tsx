import { useState } from "react";
import {
  Plus,
  Settings,
  Copy,
  Trash2,
  Power,
  Paperclip,
  FileText,
  Play,
  Save,
  ChevronRight,
  AlertTriangle,
  CircleDot,
  Boxes,
  Cpu,
  Layers,
  Pause,
  RotateCw,
  Sun,
  Moon,
  LogOut,
  UserPlus,
  ChevronUp,
  Check,
} from "lucide-react";

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
  reasoning: "low" | "medium" | "high";
  skill: string;
  status: AgentStatus;
  contextLeft: number | null;
  sessionId: string;
  lastAction: string;
  enabled: boolean;
  group: number;
};

const initialAgents: Agent[] = [
  {
    id: "a1",
    name: "Planner A",
    role: "Requirement Analysis",
    description: "Drafts the initial development plan from the user request.",
    capabilities: ["Planning", "Risk Check", "Spec Draft"],
    provider: "Codex",
    account: "codex-main",
    model: "gpt-5-codex",
    reasoning: "high",
    skill: "planner.md",
    status: "ready",
    contextLeft: 72,
    sessionId: "sess_8f21a",
    lastAction: "Awaiting run start",
    enabled: true,
    group: 1,
  },
  {
    id: "a2",
    name: "Planner B",
    role: "Plan Review",
    description: "Cross-checks Planner A and proposes risk mitigations.",
    capabilities: ["Review", "Risk", "Compare"],
    provider: "Claude",
    account: "claude-team",
    model: "Sonnet 4.6",
    reasoning: "medium",
    skill: "planner-review.md",
    status: "idle",
    contextLeft: null,
    sessionId: "—",
    lastAction: "No prior session",
    enabled: true,
    group: 2,
  },
  {
    id: "a3",
    name: "Architect",
    role: "Contract Bundle",
    description: "Produces interface contracts and module boundaries.",
    capabilities: ["Schema", "Types", "Boundaries"],
    provider: "Codex",
    account: "codex-main",
    model: "gpt-5-codex",
    reasoning: "high",
    skill: "architect.md",
    status: "idle",
    contextLeft: 91,
    sessionId: "sess_b1042",
    lastAction: "Resumed session",
    enabled: true,
    group: 3,
  },
  {
    id: "a4",
    name: "Designer Agent",
    role: "UI/UX Direction",
    description: "Defines layouts, components, and visual tokens.",
    capabilities: ["Layout", "Tokens", "States"],
    provider: "Claude",
    account: "claude-team",
    model: "Opus 4.7",
    reasoning: "high",
    skill: "designer.md",
    status: "ready",
    contextLeft: 88,
    sessionId: "sess_c7711",
    lastAction: "Loaded design tokens",
    enabled: true,
    group: 4,
  },
  {
    id: "a5",
    name: "Code Agent 1",
    role: "Frontend Implementation",
    description: "Implements UI components and client state.",
    capabilities: ["React", "UI", "State Logic"],
    provider: "Codex",
    account: "codex-main",
    model: "gpt-5-codex",
    reasoning: "medium",
    skill: "frontend.md",
    status: "idle",
    contextLeft: null,
    sessionId: "—",
    lastAction: "New session",
    enabled: true,
    group: 5,
  },
  {
    id: "a6",
    name: "Code Agent 2",
    role: "Backend Implementation",
    description: "Implements server logic, schemas, and integrations.",
    capabilities: ["Node", "DB", "API"],
    provider: "Codex",
    account: "codex-alt",
    model: "gpt-5-codex",
    reasoning: "medium",
    skill: "backend.md",
    status: "idle",
    contextLeft: null,
    sessionId: "—",
    lastAction: "New session",
    enabled: true,
    group: 5,
  },
  {
    id: "a7",
    name: "Integrator",
    role: "Merge & Wire",
    description: "Merges parallel outputs and wires modules together.",
    capabilities: ["Merge", "Lint", "Resolve"],
    provider: "Codex",
    account: "codex-main",
    model: "gpt-5-codex",
    reasoning: "medium",
    skill: "integrator.md",
    status: "idle",
    contextLeft: null,
    sessionId: "—",
    lastAction: "—",
    enabled: true,
    group: 6,
  },
  {
    id: "a8",
    name: "QA Agent",
    role: "Execution & Visual QA",
    description: "Runs tests, captures screenshots, files defects.",
    capabilities: ["Run Test", "Screenshot", "Report"],
    provider: "Claude",
    account: "claude-team",
    model: "Opus 4.7",
    reasoning: "high",
    skill: "qa-review.md",
    status: "waiting",
    contextLeft: 85,
    sessionId: "sess_qa991",
    lastAction: "Standby for build",
    enabled: true,
    group: 7,
  },
];

const statusStyles: Record<AgentStatus, string> = {
  idle: "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-500 border-slate-200 dark:border-slate-700",
  ready: "bg-sky-50 text-sky-700 border-sky-200",
  running: "bg-indigo-50 text-indigo-700 border-indigo-200",
  waiting: "bg-amber-50 text-amber-800 border-amber-200",
  error: "bg-rose-50 text-rose-700 border-rose-200",
  done: "bg-emerald-50 text-emerald-700 border-emerald-200",
  paused: "bg-violet-50 text-violet-700 border-violet-200",
};

const roleTint: Record<string, { bar: string; chip: string }> = {
  Planner: { bar: "bg-sky-400/70", chip: "bg-sky-50 text-sky-700 border-sky-100" },
  Architect: { bar: "bg-indigo-400/70", chip: "bg-indigo-50 text-indigo-700 border-indigo-100" },
  Designer: { bar: "bg-violet-400/70", chip: "bg-violet-50 text-violet-700 border-violet-100" },
  Code: { bar: "bg-emerald-400/70", chip: "bg-emerald-50 text-emerald-700 border-emerald-100" },
  Integrator: { bar: "bg-amber-400/70", chip: "bg-amber-50 text-amber-800 border-amber-100" },
  QA: { bar: "bg-rose-400/70", chip: "bg-rose-50 text-rose-700 border-rose-100" },
};

function tintFor(name: string) {
  if (name.startsWith("Planner")) return roleTint.Planner;
  if (name.startsWith("Architect")) return roleTint.Architect;
  if (name.startsWith("Designer")) return roleTint.Designer;
  if (name.startsWith("Code")) return roleTint.Code;
  if (name.startsWith("Integrator")) return roleTint.Integrator;
  if (name.startsWith("QA")) return roleTint.QA;
  return { bar: "bg-slate-300", chip: "bg-slate-50 dark:bg-slate-900 text-slate-600 dark:text-slate-500 border-slate-200 dark:border-slate-700" };
}

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

function StatusBadge({ status, lang }: { status: AgentStatus; lang: Lang }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded border ${statusStyles[status]}`}
      style={{ fontSize: 11 }}
    >
      <span className="size-1.5 rounded-full bg-current opacity-80" />
      <span>{statusLabels[lang][status]}</span>
    </span>
  );
}

function ContextBar({ value, lang }: { value: number | null; lang: Lang }) {
  if (value === null)
    return (
      <span className="font-mono text-slate-400 dark:text-slate-500" style={{ fontSize: 11 }}>
        {lang === "ko" ? "새 세션" : "new session"}
      </span>
    );
  const tone = value > 60 ? "bg-emerald-500" : value > 30 ? "bg-amber-500" : "bg-rose-500";
  return (
    <div className="flex items-center gap-2 min-w-0">
      <div className="h-1 w-16 rounded bg-slate-100 dark:bg-slate-800 overflow-hidden">
        <div className={`h-full ${tone}`} style={{ width: `${value}%` }} />
      </div>
      <span className="font-mono text-slate-500 dark:text-slate-500" style={{ fontSize: 11 }}>
        {value}%
      </span>
    </div>
  );
}

function AgentCard({ agent, lang }: { agent: Agent; lang: Lang }) {
  const tint = tintFor(agent.name);
  return (
    <div className="group relative rounded-lg border border-slate-200/80 dark:border-slate-700/70 bg-white dark:bg-slate-900 shadow-[0_1px_0_rgba(15,23,42,0.02),0_1px_2px_rgba(15,23,42,0.04)] hover:border-slate-300 dark:hover:border-slate-600 dark:border-slate-600 hover:shadow-[0_1px_0_rgba(15,23,42,0.03),0_4px_12px_rgba(15,23,42,0.06)] transition-all overflow-hidden">
      <span className={`absolute inset-y-0 left-0 w-0.5 ${tint.bar}`} />
      <div className="flex items-start justify-between gap-3 px-4 pt-3 pb-2 border-b border-slate-100 dark:border-slate-800">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-mono text-slate-400 dark:text-slate-500" style={{ fontSize: 10 }}>
              #{agent.group}
            </span>
            <span className="truncate text-slate-900 dark:text-slate-100">{agent.name}</span>
            <StatusBadge status={agent.status} lang={lang} />
          </div>
          <div className={`mt-0.5 inline-flex items-center px-1.5 py-0.5 rounded border ${tint.chip}`} style={{ fontSize: 11 }}>
            {agent.role}
          </div>
        </div>
        <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
          <button className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800" title="Settings">
            <Settings className="size-3.5 text-slate-500 dark:text-slate-500" />
          </button>
          <button className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800" title="Duplicate">
            <Copy className="size-3.5 text-slate-500 dark:text-slate-500" />
          </button>
          <button className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800" title="Toggle">
            <Power className="size-3.5 text-slate-500 dark:text-slate-500" />
          </button>
          <button className="p-1 rounded hover:bg-rose-50" title="Delete">
            <Trash2 className="size-3.5 text-slate-500 dark:text-slate-500" />
          </button>
        </div>
      </div>

      <div className="px-4 py-2.5 text-slate-600 dark:text-slate-500" style={{ fontSize: 12 }}>
        {agent.description}
      </div>

      <div className="px-4 pb-2 flex flex-wrap gap-1">
        {agent.capabilities.map((c) => (
          <span
            key={c}
            className="px-1.5 py-0.5 rounded bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-500"
            style={{ fontSize: 10 }}
          >
            {c}
          </span>
        ))}
      </div>

      <div className="px-4 py-2 grid grid-cols-2 gap-x-3 gap-y-1.5 border-t border-slate-100 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-900/60">
        <Meta label={lang === "ko" ? "프로바이더" : "provider"} value={agent.provider} />
        <Meta label={lang === "ko" ? "계정" : "account"} value={agent.account} mono />
        <Meta label={lang === "ko" ? "모델" : "model"} value={agent.model} mono />
        <Meta label={lang === "ko" ? "추론 수준" : "reasoning"} value={agent.reasoning} />
        <Meta label={lang === "ko" ? "스킬" : "skill"} value={agent.skill} mono icon={<FileText className="size-3" />} />
        <Meta label={lang === "ko" ? "세션" : "session"} value={agent.sessionId} mono />
      </div>

      <div className="px-4 py-2 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-slate-400 dark:text-slate-500 uppercase tracking-wide" style={{ fontSize: 10 }}>
            {lang === "ko" ? "컨텍스트" : "ctx"}
          </span>
          <ContextBar value={agent.contextLeft} lang={lang} />
        </div>
        <div className="text-slate-500 dark:text-slate-500 truncate" style={{ fontSize: 11 }}>
          {agent.lastAction}
        </div>
      </div>
    </div>
  );
}

function Meta({
  label,
  value,
  mono,
  icon,
}: {
  label: string;
  value: string;
  mono?: boolean;
  icon?: React.ReactNode;
}) {
  return (
    <div className="min-w-0">
      <div className="text-slate-400 dark:text-slate-500 uppercase tracking-wide" style={{ fontSize: 10 }}>
        {label}
      </div>
      <div
        className={`flex items-center gap-1 truncate text-slate-700 dark:text-slate-300 ${mono ? "font-mono" : ""}`}
        style={{ fontSize: 12 }}
      >
        {icon}
        <span className="truncate">{value}</span>
      </div>
    </div>
  );
}

function AddAgentCard({ onClick, lang }: { onClick: () => void; lang: Lang }) {
  return (
    <button
      onClick={onClick}
      className="rounded-lg border border-dashed border-slate-300 dark:border-slate-600 bg-white/50 dark:bg-slate-900/50 hover:border-indigo-300 hover:bg-indigo-50/40 hover:text-indigo-700 transition-colors flex flex-col items-center justify-center text-slate-500 dark:text-slate-500 min-h-64"
    >
      <Plus className="size-5 mb-1" />
      <span style={{ fontSize: 13 }}>{lang === "ko" ? "에이전트 추가" : "Add Agent"}</span>
      <span className="text-slate-400 dark:text-slate-500 mt-0.5" style={{ fontSize: 11 }}>
        Planner / Architect / Code / QA …
      </span>
    </button>
  );
}

function SidebarSection({
  title,
  children,
  action,
}: {
  title: string;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="px-3 py-2.5 border-b border-slate-200/70 dark:border-slate-700/70">
      <div className="flex items-center justify-between mb-2">
        <div
          className="text-slate-500 dark:text-slate-500 uppercase tracking-wider"
          style={{ fontSize: 10 }}
        >
          {title}
        </div>
        {action}
      </div>
      <div className="space-y-1.5">{children}</div>
    </div>
  );
}

function ProviderRow({
  name,
  account,
  ok,
  quota,
  warn,
}: {
  name: string;
  account: string;
  ok: boolean;
  quota: string;
  warn?: boolean;
}) {
  return (
    <div className="flex items-center justify-between rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 py-1.5 shadow-[0_1px_0_rgba(15,23,42,0.02)]">
      <div className="min-w-0">
        <div className="flex items-center gap-1.5">
          <span
            className={`size-1.5 rounded-full ${ok ? "bg-emerald-500" : "bg-slate-400"}`}
          />
          <span className="text-slate-800 dark:text-slate-200" style={{ fontSize: 12 }}>{name}</span>
          {warn && <AlertTriangle className="size-3 text-amber-500" />}
        </div>
        <div className="font-mono text-slate-500 dark:text-slate-500 truncate" style={{ fontSize: 11 }}>
          {account}
        </div>
      </div>
      <div className="text-right">
        <div className="font-mono text-slate-600 dark:text-slate-500" style={{ fontSize: 11 }}>
          {quota}
        </div>
      </div>
    </div>
  );
}

function Pill({
  active,
  children,
  onClick,
}: {
  active?: boolean;
  children: React.ReactNode;
  onClick?: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`px-2 py-1 rounded-md border transition-colors ${
        active
          ? "bg-indigo-600 text-white border-indigo-600 shadow-[0_1px_0_rgba(79,70,229,0.4)]"
          : "bg-white dark:bg-slate-900 text-slate-700 dark:text-slate-300 border-slate-200 dark:border-slate-700 hover:border-slate-300 dark:hover:border-slate-600 dark:border-slate-600 hover:bg-slate-50 dark:hover:bg-slate-800 dark:bg-slate-900"
      }`}
      style={{ fontSize: 11 }}
    >
      {children}
    </button>
  );
}

export function AgentRosterPage({
  onStartRun,
  lang,
  setLang,
  theme,
  setTheme,
}: {
  onStartRun: () => void;
  lang: Lang;
  setLang: (l: Lang) => void;
  theme: "light" | "dark";
  setTheme: (t: "light" | "dark") => void;
}) {
  const [agents] = useState<Agent[]>(initialAgents);
  const [runMode, setRunMode] = useState("balanced");
  const [prompt, setPrompt] = useState(
    lang === "ko"
      ? "에이전트 오케스트레이션 도구의 운영자 대시보드(2페이지)와 승인 플로를 구현해줘."
      : "Build a two-page operator dashboard for the agent orchestration tool, with run monitor and approval flow."
  );

  const groups = agents.reduce<Record<number, Agent[]>>((acc, a) => {
    (acc[a.group] ||= []).push(a);
    return acc;
  }, {});
  const groupKeys = Object.keys(groups)
    .map(Number)
    .sort((a, b) => a - b);

  const t = (ko: string, en: string) => (lang === "ko" ? ko : en);

  return (
    <div
      className="size-full flex text-slate-900 dark:text-slate-100"
      style={{
        background:
          theme === "dark"
            ? "radial-gradient(1200px 600px at 0% 0%, rgba(99,102,241,0.18), transparent 60%), radial-gradient(900px 500px at 100% 100%, rgba(56,189,248,0.08), transparent 60%), linear-gradient(180deg, #0a0f1c 0%, #0b1224 100%)"
            : "radial-gradient(1200px 600px at 0% 0%, rgba(99,102,241,0.08), transparent 60%), radial-gradient(900px 500px at 100% 100%, rgba(56,189,248,0.06), transparent 60%), linear-gradient(180deg, #eef2f7 0%, #e8edf5 100%)",
      }}
    >
      {/* Sidebar */}
      <aside className="w-64 shrink-0 border-r border-slate-200/80 dark:border-slate-700/70 flex flex-col overflow-hidden bg-gradient-to-b from-slate-50 to-indigo-50/40 dark:from-slate-900 dark:to-indigo-950/40">
        <div className="px-3 py-3 border-b border-slate-200/70 dark:border-slate-700/70 flex items-center gap-2">
          <div className="size-6 rounded bg-indigo-600 text-white flex items-center justify-center shadow-[0_1px_0_rgba(79,70,229,0.4)]">
            <Boxes className="size-3.5" />
          </div>
          <div className="min-w-0">
            <div className="text-slate-900 dark:text-slate-100" style={{ fontSize: 13 }}>Orchestra</div>
            <div className="font-mono text-slate-500 dark:text-slate-500 truncate" style={{ fontSize: 10 }}>
              ws/dashboard-app
            </div>
          </div>
        </div>

        <div className="overflow-y-auto flex-1">
          <SidebarSection title={t("프로바이더", "Providers")}>
            <ProviderRow name="Codex" account="codex-main" ok quota="5h 84%" />
            <ProviderRow name="Codex" account="codex-alt" ok quota="5h 41%" warn />
            <ProviderRow name="Claude" account="claude-team" ok quota="wk 62%" />
            <ProviderRow name="Local" account="cli-profile" ok={false} quota="—" />
          </SidebarSection>

          <SidebarSection title={t("실행 모드", "Run Mode")}>
            <div className="flex flex-wrap gap-1">
              {[
                { id: "fast", ko: "빠름", en: "fast" },
                { id: "balanced", ko: "균형", en: "balanced" },
                { id: "parallel", ko: "병렬", en: "parallel" },
                { id: "manual", ko: "수동", en: "manual" },
              ].map((m) => (
                <Pill key={m.id} active={runMode === m.id} onClick={() => setRunMode(m.id)}>
                  {lang === "ko" ? m.ko : m.en}
                </Pill>
              ))}
            </div>
          </SidebarSection>

          <SidebarSection title={t("기본값", "Defaults")}>
            <Field label={t("모델", "Model")} value="gpt-5-codex" />
            <Field label={t("추론", "Reasoning")} value={t("높음", "high")} />
            <Field label={t("타임아웃", "Timeout")} value="180s" />
            <Field label={t("재시도", "Retries")} value="2" />
          </SidebarSection>

          <SidebarSection title={t("프리셋", "Presets")}>
            <button className="w-full text-left px-2 py-1.5 rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 hover:border-indigo-300 hover:bg-indigo-50/40" style={{ fontSize: 12 }}>
              <div className="flex items-center justify-between text-slate-800 dark:text-slate-200">
                <span>full-stack/parallel</span>
                <ChevronRight className="size-3.5 text-slate-400 dark:text-slate-500" />
              </div>
              <div className="font-mono text-slate-500 dark:text-slate-500" style={{ fontSize: 10 }}>
                {t("에이전트 8 · 병렬 2", "8 agents · 2 parallel")}
              </div>
            </button>
            <button className="w-full text-left px-2 py-1.5 rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 hover:border-indigo-300 hover:bg-indigo-50/40" style={{ fontSize: 12 }}>
              <div className="flex items-center justify-between text-slate-800 dark:text-slate-200">
                <span>frontend-only</span>
                <ChevronRight className="size-3.5 text-slate-400 dark:text-slate-500" />
              </div>
              <div className="font-mono text-slate-500 dark:text-slate-500" style={{ fontSize: 10 }}>
                {t("에이전트 4 · 순차", "4 agents · sequential")}
              </div>
            </button>
          </SidebarSection>

          <SidebarSection title={t("히스토리", "History")}>
            <button className="w-full text-left text-slate-600 dark:text-slate-500 hover:text-indigo-700" style={{ fontSize: 12 }}>
              ↺ {t("이전 실행 불러오기", "Load previous run")}
            </button>
          </SidebarSection>
        </div>

        <AccountFooter lang={lang} setLang={setLang} theme={theme} setTheme={setTheme} />
      </aside>

      {/* Main */}
      <main className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <header className="h-12 px-5 border-b border-slate-200 dark:border-slate-700 bg-white/70 dark:bg-slate-900/60 backdrop-blur-sm flex items-center justify-between shrink-0">
          <div className="flex items-center gap-3">
            <span className="text-slate-900 dark:text-slate-100" style={{ fontSize: 13 }}>{t("에이전트 로스터", "Agent Roster")}</span>
            <span className="text-slate-300 dark:text-slate-700" style={{ fontSize: 12 }}>/</span>
            <span className="font-mono text-slate-500 dark:text-slate-500" style={{ fontSize: 12 }}>
              dashboard-app
            </span>
            <span className="ml-2 px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 font-mono text-slate-600 dark:text-slate-500" style={{ fontSize: 10 }}>
              {agents.length} {t("에이전트", "agents")}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button className="px-2 py-1 rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 hover:border-slate-300 dark:hover:border-slate-600 dark:border-slate-600 hover:bg-slate-50 dark:hover:bg-slate-800 dark:bg-slate-900 inline-flex items-center gap-1 text-slate-600 dark:text-slate-500" style={{ fontSize: 12 }}>
              <Layers className="size-3.5" /> {t("워크플로", "Workflow")}
            </button>
            <button className="px-2 py-1 rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 hover:border-slate-300 dark:hover:border-slate-600 dark:border-slate-600 hover:bg-slate-50 dark:hover:bg-slate-800 dark:bg-slate-900 inline-flex items-center gap-1 text-slate-600 dark:text-slate-500" style={{ fontSize: 12 }}>
              <Cpu className="size-3.5" /> {t("리소스", "Resources")}
            </button>
          </div>
        </header>

        {/* Workflow strip */}
        <div className="px-5 py-2 border-b border-slate-200 dark:border-slate-700 bg-white/40 dark:bg-slate-900/40 backdrop-blur-sm flex items-center gap-1.5 overflow-x-auto shrink-0">
          {groupKeys.map((g, idx) => (
            <div key={g} className="flex items-center gap-1.5">
              <div className="px-2 py-1 rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 flex items-center gap-1.5 shadow-[0_1px_0_rgba(15,23,42,0.02)]">
                <span className="font-mono text-slate-400 dark:text-slate-500" style={{ fontSize: 10 }}>
                  {g}
                </span>
                <span className="text-slate-700 dark:text-slate-300" style={{ fontSize: 12 }}>
                  {groups[g].map((a) => a.name).join(" + ")}
                </span>
                {groups[g].length > 1 && (
                  <span className="px-1 rounded bg-indigo-50 text-indigo-700 border border-indigo-100 font-mono" style={{ fontSize: 10 }}>
                    {t("병렬", "parallel")}
                  </span>
                )}
              </div>
              {idx < groupKeys.length - 1 && (
                <ChevronRight className="size-3.5 text-slate-300 dark:text-slate-700" />
              )}
            </div>
          ))}
        </div>

        {/* Cards grid */}
        <div className="flex-1 overflow-y-auto p-5">
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {agents.map((a) => (
              <AgentCard key={a.id} agent={a} lang={lang} />
            ))}
            <AddAgentCard onClick={() => {}} lang={lang} />
          </div>
        </div>

        {/* Composer */}
        <div className="border-t border-slate-200 dark:border-slate-700 bg-white/60 dark:bg-slate-900/60 backdrop-blur-sm px-5 py-3 shrink-0">
          <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 shadow-[0_1px_0_rgba(15,23,42,0.02),0_4px_16px_rgba(15,23,42,0.05)] focus-within:border-indigo-300 focus-within:ring-1 focus-within:ring-indigo-200 transition-colors">
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={3}
              placeholder={t("에이전트가 만들 앱이나 기능을 설명해주세요…", "Describe the app or feature you want the agents to build…")}
              className="w-full resize-none px-3 py-2.5 bg-transparent outline-none text-slate-800 dark:text-slate-200 placeholder:text-slate-400 dark:placeholder:text-slate-500 dark:text-slate-500"
              style={{ fontSize: 13 }}
            />
            <div className="flex items-center justify-between px-2 py-1.5 border-t border-slate-100 dark:border-slate-800 bg-slate-50/60 dark:bg-slate-900/60 rounded-b-lg">
              <div className="flex items-center gap-1">
                <ToolButton icon={<Paperclip className="size-3.5" />} label={t("첨부", "Attach")} />
                <ToolButton icon={<FileText className="size-3.5" />} label={t("스킬 파일", "Skill file")} />
                <ToolButton icon={<RotateCw className="size-3.5" />} label={t("세션 이어가기", "Continue session")} />
                <span className="ml-2 font-mono text-slate-400 dark:text-slate-500" style={{ fontSize: 10 }}>
                  {t("모드", "mode")}: {runMode} · {t("모델", "model")}: gpt-5-codex
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                <button className="px-2.5 py-1.5 rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 hover:border-slate-300 dark:hover:border-slate-600 dark:border-slate-600 inline-flex items-center gap-1.5 text-slate-700 dark:text-slate-300" style={{ fontSize: 12 }}>
                  <Save className="size-3.5" /> {t("프리셋 저장", "Save Preset")}
                </button>
                <button
                  onClick={onStartRun}
                  className="px-3 py-1.5 rounded-md bg-indigo-600 text-white hover:bg-indigo-700 inline-flex items-center gap-1.5 shadow-[0_1px_0_rgba(79,70,229,0.4),0_2px_6px_rgba(79,70,229,0.25)]"
                  style={{ fontSize: 12 }}
                >
                  <Play className="size-3.5" /> {t("실행 시작", "Start Run")}
                </button>
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}

function ToolButton({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <button
      className="px-2 py-1 rounded-md hover:bg-slate-100 dark:hover:bg-slate-800 inline-flex items-center gap-1.5 text-slate-600 dark:text-slate-500"
      style={{ fontSize: 12 }}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 py-1.5 shadow-[0_1px_0_rgba(15,23,42,0.02)]">
      <span className="text-slate-500 dark:text-slate-500" style={{ fontSize: 11 }}>
        {label}
      </span>
      <span className="font-mono text-slate-700 dark:text-slate-300" style={{ fontSize: 11 }}>
        {value}
      </span>
    </div>
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
            <div className="text-slate-400 dark:text-slate-500 uppercase tracking-wider mb-1" style={{ fontSize: 10 }}>
              {t("계정", "Accounts")}
            </div>
            <AccountRow name="codex-main" provider="Codex" active />
            <AccountRow name="claude-team" provider="Claude" />
            <AccountRow name="codex-alt" provider="Codex" />
            <button className="w-full mt-1 text-left flex items-center gap-1.5 text-indigo-700 hover:bg-indigo-50/60 rounded px-1.5 py-1" style={{ fontSize: 12 }}>
              <UserPlus className="size-3.5" /> {t("계정 추가", "Add account")}
            </button>
          </div>
          <div className="px-3 py-2 border-b border-slate-100 dark:border-slate-800">
            <div className="text-slate-400 dark:text-slate-500 uppercase tracking-wider mb-1.5" style={{ fontSize: 10 }}>
              {t("언어", "Language")}
            </div>
            <Segmented
              options={[
                { id: "ko", label: "한국어" },
                { id: "en", label: "English" },
              ]}
              value={lang}
              onChange={(v) => setLang(v as Lang)}
            />
          </div>
          <div className="px-3 py-2 border-b border-slate-100 dark:border-slate-800">
            <div className="text-slate-400 dark:text-slate-500 uppercase tracking-wider mb-1.5" style={{ fontSize: 10 }}>
              {t("테마", "Theme")}
            </div>
            <Segmented
              options={[
                { id: "light", label: t("라이트", "Light"), icon: <Sun className="size-3" /> },
                { id: "dark", label: t("다크", "Dark"), icon: <Moon className="size-3" /> },
              ]}
              value={theme}
              onChange={(v) => setTheme(v as "light" | "dark")}
            />
          </div>
          <button className="w-full text-left px-3 py-2 hover:bg-rose-50/60 text-rose-700 inline-flex items-center gap-1.5" style={{ fontSize: 12 }}>
            <LogOut className="size-3.5" /> {t("로그아웃", "Sign out")}
          </button>
        </div>
      )}

      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2.5 hover:bg-white/80 dark:bg-slate-900/70 transition-colors"
      >
        <div className="size-7 rounded-full bg-gradient-to-br from-indigo-500 to-sky-500 text-white flex items-center justify-center font-mono" style={{ fontSize: 11 }}>
          OP
        </div>
        <div className="min-w-0 flex-1 text-left">
          <div className="text-slate-800 dark:text-slate-200 truncate" style={{ fontSize: 12 }}>
            operator@local
          </div>
          <div className="font-mono text-slate-500 dark:text-slate-500 truncate" style={{ fontSize: 10 }}>
            codex-main · claude-team
          </div>
        </div>
        <div className="flex items-center gap-0.5">
          <span
            className="px-1.5 py-0.5 rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 font-mono text-slate-600 dark:text-slate-500"
            style={{ fontSize: 10 }}
            title={t("언어", "Language")}
          >
            {lang === "ko" ? "한" : "EN"}
          </span>
          <span
            className="size-5 rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 inline-flex items-center justify-center text-slate-600 dark:text-slate-500"
            title={t("테마", "Theme")}
          >
            {theme === "light" ? <Sun className="size-3" /> : <Moon className="size-3" />}
          </span>
          <Settings className="size-3.5 text-slate-400 dark:text-slate-500 ml-0.5" />
          <ChevronUp className={`size-3.5 text-slate-400 dark:text-slate-500 transition-transform ${open ? "" : "rotate-180"}`} />
        </div>
      </button>
    </div>
  );
}

function AccountRow({
  name,
  provider,
  active,
}: {
  name: string;
  provider: string;
  active?: boolean;
}) {
  return (
    <button className="w-full flex items-center justify-between px-1.5 py-1 rounded hover:bg-slate-50 dark:hover:bg-slate-800 dark:bg-slate-900" style={{ fontSize: 12 }}>
      <div className="flex items-center gap-1.5 min-w-0">
        <span className="size-1.5 rounded-full bg-emerald-500" />
        <span className="font-mono text-slate-700 dark:text-slate-300 truncate">{name}</span>
        <span className="text-slate-400 dark:text-slate-500" style={{ fontSize: 10 }}>
          · {provider}
        </span>
      </div>
      {active && <Check className="size-3.5 text-indigo-600" />}
    </button>
  );
}

function Segmented({
  options,
  value,
  onChange,
}: {
  options: { id: string; label: string; icon?: React.ReactNode }[];
  value: string;
  onChange: (id: string) => void;
}) {
  return (
    <div className="inline-flex p-0.5 rounded-md border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 w-full">
      {options.map((o) => {
        const active = value === o.id;
        return (
          <button
            key={o.id}
            onClick={() => onChange(o.id)}
            className={`flex-1 inline-flex items-center justify-center gap-1 px-2 py-1 rounded transition-colors ${
              active
                ? "bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 shadow-[0_1px_0_rgba(15,23,42,0.05)] border border-slate-200 dark:border-slate-700"
                : "text-slate-600 dark:text-slate-500 hover:text-slate-900 dark:text-slate-100"
            }`}
            style={{ fontSize: 11 }}
          >
            {o.icon}
            <span>{o.label}</span>
          </button>
        );
      })}
    </div>
  );
}

export { CircleDot, Pause };
