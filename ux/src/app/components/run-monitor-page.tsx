import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleSlash,
  FileText,
  FolderOpen,
  Image as ImageIcon,
  Pause,
  RotateCw,
  Send,
  ShieldAlert,
  Square,
  Terminal,
  XCircle,
} from "lucide-react";
import { AccountFooter } from "./agent-roster-page";
import {
  ArtifactContent,
  ArtifactInfo,
  RunDetail,
  TimelineEvent,
  approveQa,
  approveRun,
  cancelRun,
  getEvents,
  getRun,
  listArtifacts,
  readArtifact,
  requestChanges,
  requestQaFix,
} from "../api";

type Lang = "ko" | "en";
type Status = "idle" | "ready" | "running" | "waiting" | "error" | "done" | "paused" | "queued";

const statusStyles: Record<Status, string> = {
  idle: "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-500 border-slate-200 dark:border-slate-700",
  ready: "bg-sky-50 text-sky-700 border-sky-200",
  running: "bg-indigo-50 text-indigo-700 border-indigo-200",
  waiting: "bg-amber-50 text-amber-800 border-amber-200",
  error: "bg-rose-50 text-rose-700 border-rose-200",
  done: "bg-emerald-50 text-emerald-700 border-emerald-200",
  paused: "bg-violet-50 text-violet-700 border-violet-200",
  queued: "bg-slate-50 dark:bg-slate-900 text-slate-500 dark:text-slate-500 border-slate-200 dark:border-slate-700",
};

type AgentRow = {
  id: string;
  name: string;
  role: string;
  status: Status;
  elapsed: string;
  context: number | null;
  session: string;
  lastEvent: string;
};

function normalizeStatus(status?: string | null): Status {
  if (!status) return "idle";
  if (["ready", "running", "waiting", "error", "done", "paused", "queued", "idle"].includes(status)) {
    return status as Status;
  }
  if (status.includes("running")) return "running";
  if (status.includes("awaiting") || status.includes("requested")) return "waiting";
  if (status.includes("failed")) return "error";
  if (status.includes("completed") || status.includes("approved")) return "done";
  if (status.includes("cancelled")) return "paused";
  return "idle";
}

function agentLabel(id: string) {
  if (id === "planner_a") return "Planner A";
  if (id === "planner_b") return "Planner B";
  if (id === "planner_c") return "Planner C";
  if (id === "architect") return "Architect";
  if (id === "scaffold") return "Scaffold";
  if (id === "integrator") return "Integrator";
  if (id === "developer") return "Developer";
  if (id === "qa") return "QA";
  if (id.startsWith("code_")) return `Code Agent ${id.split("_")[1]}`;
  if (id.startsWith("qa_")) return `QA Agent ${id.split("_")[1]}`;
  return id.replace("_", " ");
}

function agentRole(id: string) {
  if (id.startsWith("planner")) return "Plan";
  if (id === "architect") return "Contract";
  if (id === "scaffold") return "Scaffold";
  if (id.startsWith("code_") || id === "developer") return "Code";
  if (id === "integrator") return "Merge";
  if (id.startsWith("qa")) return "QA";
  return "Agent";
}

function buildAgentRows(run: RunDetail | null, events: TimelineEvent[]): AgentRow[] {
  const sessions = run?.state.agent_sessions || {};
  return Object.entries(sessions)
    .filter(([id]) => id !== "qa" && id !== "developer")
    .map(([id, session]) => {
      const lastEvent = [...events].reverse().find((event) => event.actor === id);
      return {
        id,
        name: agentLabel(id),
        role: agentRole(id),
        status: lastEvent ? normalizeStatus(lastEvent.status) : session.session_id ? "done" : "queued",
        elapsed: "--",
        context: null,
        session: session.session_id ? `${session.session_id.slice(0, 8)}...` : "new",
        lastEvent: lastEvent?.title || session.last_step || "No event yet",
      };
    });
}

function StatusBadge({ status }: { status: Status }) {
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded border ${statusStyles[status]}`} style={{ fontSize: 11 }}>
      <span className={`size-1.5 rounded-full ${status === "running" ? "bg-current animate-pulse" : "bg-current opacity-80"}`} />
      <span className="capitalize">{status}</span>
    </span>
  );
}

function TopBar({
  run,
  onBack,
  onApprove,
  onRequestChanges,
  onCancel,
  onApproveQa,
  t,
}: {
  run: RunDetail | null;
  onBack: () => void;
  onApprove: () => void;
  onRequestChanges: () => void;
  onCancel: () => void;
  onApproveQa: () => void;
  t: (ko: string, en: string) => string;
}) {
  const status = normalizeStatus(run?.status);
  const route = run?.route_mode || run?.state.routing?.mode || "local";
  return (
    <header className="h-14 px-4 border-b border-slate-200 dark:border-slate-700 bg-white/70 dark:bg-slate-900/60 backdrop-blur-sm flex items-center justify-between shrink-0">
      <div className="flex items-center gap-3 min-w-0">
        <button onClick={onBack} className="p-1.5 rounded-md hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-500" title={t("로스터로 돌아가기", "Back to roster")}>
          <ArrowLeft className="size-4" />
        </button>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-slate-900 dark:text-slate-100" style={{ fontSize: 13 }}>{t("실행 모니터", "Run Monitor")}</span>
            <span className="font-mono text-slate-500 dark:text-slate-500" style={{ fontSize: 11 }}>{run?.run_id || "no run selected"}</span>
            <StatusBadge status={status} />
          </div>
          <div className="flex items-center gap-3 mt-0.5 text-slate-500 dark:text-slate-500" style={{ fontSize: 11 }}>
            <span>{t("경로", "route")}: <span className="font-mono text-slate-700 dark:text-slate-300">{route}</span></span>
            <span>{t("산출물", "artifacts")}: <span className="font-mono text-slate-700 dark:text-slate-300">{run?.artifact_count ?? 0}</span></span>
            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded border border-emerald-100 bg-emerald-50 text-emerald-700">
              <ShieldAlert className="size-3" /> {t("로컬 전용", "local only")}
            </span>
            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded border border-amber-100 bg-amber-50 text-amber-800">
              <AlertTriangle className="size-3" /> 127.0.0.1 API
            </span>
          </div>
        </div>
      </div>
      <div className="flex items-center gap-1.5">
        <ActionBtn icon={<Pause className="size-3.5" />} label={t("일시정지", "Pause")} disabled />
        <ActionBtn icon={<Square className="size-3.5" />} label={t("중지", "Stop")} onClick={onCancel} />
        <ActionBtn icon={<RotateCw className="size-3.5" />} label={t("새로고침", "Refresh")} />
        <ActionBtn icon={<FolderOpen className="size-3.5" />} label={t("출력 폴더", "Output")} disabled />
        <div className="w-px h-6 bg-slate-200 dark:bg-slate-700 mx-1" />
        <button onClick={onRequestChanges} className="px-2.5 py-1.5 rounded-md border border-amber-300 bg-amber-50 text-amber-800 hover:bg-amber-100 inline-flex items-center gap-1.5" style={{ fontSize: 12 }}>
          <CircleSlash className="size-3.5" /> {t("변경 요청", "Request Changes")}
        </button>
        <button onClick={status === "waiting" && run?.status.includes("qa") ? onApproveQa : onApprove} className="px-2.5 py-1.5 rounded-md bg-emerald-600 text-white hover:bg-emerald-700 inline-flex items-center gap-1.5 shadow-[0_1px_0_rgba(5,150,105,0.4),0_2px_6px_rgba(5,150,105,0.2)]" style={{ fontSize: 12 }}>
          <CheckCircle2 className="size-3.5" /> {t("승인", "Approve")}
        </button>
      </div>
    </header>
  );
}

function ActionBtn({ icon, label, disabled, onClick }: { icon: ReactNode; label: string; disabled?: boolean; onClick?: () => void }) {
  return (
    <button
      disabled={disabled}
      onClick={onClick}
      className="px-2 py-1.5 rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 hover:border-slate-300 dark:hover:border-slate-600 hover:bg-slate-50 dark:hover:bg-slate-800 disabled:opacity-50 inline-flex items-center gap-1 text-slate-700 dark:text-slate-300"
      style={{ fontSize: 12 }}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}

function ContextBar({ value }: { value: number | null }) {
  if (value === null) return <span className="font-mono text-slate-400 dark:text-slate-500" style={{ fontSize: 11 }}>--</span>;
  return (
    <div className="flex items-center gap-1.5 min-w-0">
      <div className="h-1 w-12 rounded bg-slate-100 dark:bg-slate-800 overflow-hidden">
        <div className="h-full bg-emerald-500" style={{ width: `${value}%` }} />
      </div>
      <span className="font-mono text-slate-500 dark:text-slate-500" style={{ fontSize: 11 }}>{value}%</span>
    </div>
  );
}

function AgentSidePanel({
  rows,
  selected,
  onSelect,
  lang,
  setLang,
  theme,
  setTheme,
}: {
  rows: AgentRow[];
  selected: string;
  onSelect: (id: string) => void;
  lang: Lang;
  setLang: (l: Lang) => void;
  theme: "light" | "dark";
  setTheme: (t: "light" | "dark") => void;
}) {
  return (
    <aside className="w-64 shrink-0 border-r border-slate-200/80 dark:border-slate-700/70 bg-gradient-to-b from-slate-50 to-indigo-50/40 dark:from-slate-900 dark:to-indigo-950/40 flex flex-col overflow-hidden">
      <div className="px-3 py-2 border-b border-slate-200/70 dark:border-slate-700/70 flex items-center justify-between">
        <span className="uppercase tracking-wider text-slate-500 dark:text-slate-500" style={{ fontSize: 10 }}>{lang === "ko" ? "에이전트" : "Agents"}</span>
        <span className="font-mono text-slate-500 dark:text-slate-500" style={{ fontSize: 10 }}>{rows.length}</span>
      </div>
      <div className="overflow-y-auto flex-1 p-1.5 space-y-1">
        {rows.map((agent) => {
          const active = selected === agent.id;
          return (
            <button key={agent.id} onClick={() => onSelect(agent.id)} className={`relative w-full text-left rounded-md border px-2 py-1.5 transition-colors ${active ? "border-indigo-200 bg-white dark:bg-slate-900 shadow-[inset_2px_0_0_rgb(79,70,229)]" : "border-transparent bg-white/60 dark:bg-slate-900/60 hover:border-slate-200 dark:hover:border-slate-700 hover:bg-white dark:hover:bg-slate-900"}`}>
              <div className="flex items-center justify-between">
                <span className="text-slate-800 dark:text-slate-200" style={{ fontSize: 12 }}>{agent.name}</span>
                <StatusBadge status={agent.status} />
              </div>
              <div className="flex items-center justify-between mt-0.5">
                <span className="text-slate-500 dark:text-slate-500" style={{ fontSize: 11 }}>{agent.role}</span>
                <span className="font-mono text-slate-500 dark:text-slate-500" style={{ fontSize: 10 }}>{agent.elapsed}</span>
              </div>
              <div className="flex items-center justify-between mt-1">
                <ContextBar value={agent.context} />
                <span className="font-mono text-slate-400 dark:text-slate-500 truncate ml-2" style={{ fontSize: 10 }}>{agent.session}</span>
              </div>
              <div className="text-slate-500 dark:text-slate-500 truncate mt-1" style={{ fontSize: 11 }}>{agent.lastEvent}</div>
            </button>
          );
        })}
      </div>
      <AccountFooter lang={lang} setLang={setLang} theme={theme} setTheme={setTheme} />
    </aside>
  );
}

function TimelineItem({
  event,
  selected,
  onSelect,
  expanded,
  onToggle,
  t,
}: {
  event: TimelineEvent;
  selected: boolean;
  onSelect: () => void;
  expanded: boolean;
  onToggle: () => void;
  t: (ko: string, en: string) => string;
}) {
  const status = normalizeStatus(event.status);
  const accent =
    event.kind === "approval"
      ? "border-amber-300 bg-amber-50/70"
      : event.kind === "error" || status === "error"
        ? "border-rose-300 bg-rose-50/60"
        : "border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900";
  const dot = event.kind === "approval" ? "bg-amber-500" : status === "error" ? "bg-rose-500" : status === "running" ? "bg-indigo-500" : status === "done" ? "bg-emerald-500" : "bg-slate-400";
  return (
    <div className="relative pl-6">
      <span className={`absolute left-1.5 top-3 size-2 rounded-full ${dot} ring-2 ring-white`} />
      <button onClick={onSelect} className={`w-full text-left rounded-lg border ${accent} ${selected ? "ring-1 ring-indigo-300 border-indigo-300" : ""} hover:border-slate-300 dark:hover:border-slate-600 transition-colors shadow-[0_1px_0_rgba(15,23,42,0.02)]`}>
        <div className="px-3 py-2 flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span style={{ fontSize: 12 }}>{event.who}</span>
              <span className="font-mono text-slate-400 dark:text-slate-500" style={{ fontSize: 10 }}>{event.time}</span>
              <StatusBadge status={status} />
              {status === "error" && <span className="inline-flex items-center gap-1 text-rose-700" style={{ fontSize: 11 }}><XCircle className="size-3" /> {t("실패", "failed")}</span>}
            </div>
            <div className="mt-0.5" style={{ fontSize: 13 }}>{event.title}</div>
            {event.summary && <div className="text-slate-600 dark:text-slate-500 mt-0.5" style={{ fontSize: 12 }}>{event.summary}</div>}
          </div>
          {(event.details.length > 0 || event.artifacts.length > 0) && (
            <span role="button" onClick={(clickEvent) => { clickEvent.stopPropagation(); onToggle(); }} className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 dark:text-slate-500">
              {expanded ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
            </span>
          )}
        </div>
        {expanded && (
          <div className="border-t border-slate-100 dark:border-slate-800 px-3 py-2 space-y-2">
            {event.details.length > 0 && (
              <ul className="space-y-0.5">
                {event.details.map((detail) => <li key={detail} className="text-slate-700 dark:text-slate-300 flex gap-2" style={{ fontSize: 12 }}><span className="text-slate-400 dark:text-slate-500">›</span><span>{detail}</span></li>)}
              </ul>
            )}
            {event.artifacts.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {event.artifacts.map((artifact) => <ArtifactChip key={artifact.path} name={artifact.name} type={artifact.type} />)}
              </div>
            )}
          </div>
        )}
      </button>
    </div>
  );
}

function ArtifactChip({ name, type }: { name: string; type: string }) {
  const icon = type === "image" ? <ImageIcon className="size-3" /> : type === "log" ? <Terminal className="size-3" /> : <FileText className="size-3" />;
  return (
    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 font-mono text-slate-700 dark:text-slate-300" style={{ fontSize: 11 }}>
      {icon}
      {name}
    </span>
  );
}

function ArtifactPanel({
  event,
  artifacts,
  content,
  onOpenArtifact,
  t,
}: {
  event: TimelineEvent | null;
  artifacts: ArtifactInfo[];
  content: ArtifactContent | null;
  onOpenArtifact: (path: string) => void;
  t: (ko: string, en: string) => string;
}) {
  return (
    <aside className="w-[360px] shrink-0 border-l border-slate-200/80 dark:border-slate-700/70 bg-gradient-to-b from-slate-50 to-indigo-50/40 dark:from-slate-900 dark:to-indigo-950/40 flex flex-col overflow-hidden">
      <div className="px-3 py-2 border-b border-slate-200/70 dark:border-slate-700/70 flex items-center justify-between">
        <span className="uppercase tracking-wider text-slate-500 dark:text-slate-500" style={{ fontSize: 10 }}>{t("상세", "Details")}</span>
        <FolderOpen className="size-3.5 text-slate-500 dark:text-slate-500" />
      </div>
      <div className="overflow-y-auto flex-1">
        <Section title={t("선택", "Selection")}>
          <div className="rounded border border-slate-200 dark:border-slate-700 bg-slate-50/60 dark:bg-slate-900/60 p-2">
            <div className="flex items-center gap-2">
              <span style={{ fontSize: 12 }}>{event?.who || "System"}</span>
              <StatusBadge status={normalizeStatus(event?.status)} />
            </div>
            <div className="mt-0.5" style={{ fontSize: 13 }}>{event?.title || "No event selected"}</div>
            {event?.summary && <div className="text-slate-600 dark:text-slate-500 mt-1" style={{ fontSize: 12 }}>{event.summary}</div>}
          </div>
        </Section>
        <Section title={t("산출물", "Artifacts")}>
          <div className="space-y-1 max-h-72 overflow-y-auto">
            {artifacts.slice(0, 80).map((artifact) => (
              <ArtifactRow key={artifact.path} artifact={artifact} onClick={() => artifact.kind !== "directory" && onOpenArtifact(artifact.path)} />
            ))}
            {artifacts.length === 0 && <div className="text-slate-500 dark:text-slate-500" style={{ fontSize: 12 }}>{t("산출물 없음", "No artifacts")}</div>}
          </div>
        </Section>
        <Section title={t("미리보기", "Preview")}>
          {content ? (
            content.encoding === "base64" && content.kind === "image" ? (
              <img alt={content.name} src={`data:${content.media_type || "image/png"};base64,${content.content}`} className="w-full rounded border border-slate-200 dark:border-slate-700" />
            ) : (
              <pre className="rounded border border-slate-200 dark:border-slate-700 bg-slate-950 text-slate-100 p-2 overflow-auto max-h-72 font-mono" style={{ fontSize: 11, lineHeight: "1.5" }}>{content.content}</pre>
            )
          ) : (
            <div className="text-slate-500 dark:text-slate-500" style={{ fontSize: 12 }}>{t("산출물을 선택하세요.", "Select an artifact.")}</div>
          )}
        </Section>
        <Section title={t("실행 파일", "Run files")}>
          {["state.json", "events.jsonl", "transcript.md", "qa_report.md"].map((path) => (
            <button key={path} onClick={() => onOpenArtifact(path)} className="w-full text-left">
              <ArtifactChip name={path} type={path.endsWith(".jsonl") ? "log" : "file"} />
            </button>
          ))}
        </Section>
      </div>
    </aside>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="px-3 py-2.5 border-b border-slate-100 dark:border-slate-800">
      <div className="uppercase tracking-wider text-slate-500 dark:text-slate-500 mb-1.5" style={{ fontSize: 10 }}>{title}</div>
      <div className="space-y-1">{children}</div>
    </div>
  );
}

function ArtifactRow({ artifact, onClick }: { artifact: ArtifactInfo; onClick: () => void }) {
  return (
    <button onClick={onClick} className="w-full flex items-center justify-between rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 py-1 hover:border-slate-300 dark:hover:border-slate-600">
      <div className="flex items-center gap-1.5 min-w-0">
        {artifact.kind === "image" ? <ImageIcon className="size-3.5" /> : artifact.kind === "log" ? <Terminal className="size-3.5" /> : <FileText className="size-3.5" />}
        <span className="truncate font-mono" style={{ fontSize: 12 }}>{artifact.path}</span>
      </div>
      {artifact.size_bytes != null && <span className="font-mono text-slate-500 dark:text-slate-500" style={{ fontSize: 11 }}>{formatBytes(artifact.size_bytes)}</span>}
    </button>
  );
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function RunMonitorPage({
  onBack,
  runId,
  onRefreshRuns,
  lang,
  setLang,
  theme,
  setTheme,
}: {
  onBack: () => void;
  runId: string | null;
  onRefreshRuns: () => Promise<void>;
  lang: Lang;
  setLang: (l: Lang) => void;
  theme: "light" | "dark";
  setTheme: (t: "light" | "dark") => void;
}) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [artifacts, setArtifacts] = useState<ArtifactInfo[]>([]);
  const [content, setContent] = useState<ArtifactContent | null>(null);
  const [selectedAgent, setSelectedAgent] = useState("");
  const [selectedEventId, setSelectedEventId] = useState("");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [chatInput, setChatInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const t = (ko: string, en: string) => (lang === "ko" ? ko : en);

  const refresh = useCallback(async () => {
    if (!runId) return;
    const [nextRun, nextEvents, nextArtifacts] = await Promise.all([getRun(runId), getEvents(runId), listArtifacts(runId)]);
    setRun(nextRun);
    setEvents(nextEvents);
    setArtifacts(nextArtifacts);
    setSelectedEventId((current) => current || nextEvents[nextEvents.length - 1]?.id || "");
    setSelectedAgent((current) => current || Object.keys(nextRun.state.agent_sessions || {})[0] || "");
  }, [runId]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        await refresh();
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      }
    }
    load();
    const timer = window.setInterval(load, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [refresh]);

  const rows = useMemo(() => buildAgentRows(run, events), [run, events]);
  const selectedEvent = events.find((event) => event.id === selectedEventId) || events[events.length - 1] || null;

  async function runAction(action: () => Promise<RunDetail>) {
    if (!runId) return;
    setError(null);
    try {
      const nextRun = await action();
      setRun(nextRun);
      await Promise.all([refresh(), onRefreshRuns()]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function openArtifact(path: string) {
    if (!runId) return;
    try {
      setContent(await readArtifact(runId, path));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div
      className="size-full flex flex-col text-slate-900 dark:text-slate-100"
      style={{
        background:
          theme === "dark"
            ? "radial-gradient(1200px 600px at 0% 0%, rgba(99,102,241,0.18), transparent 60%), linear-gradient(180deg, #0a0f1c 0%, #0b1224 100%)"
            : "radial-gradient(1200px 600px at 0% 0%, rgba(99,102,241,0.08), transparent 60%), linear-gradient(180deg, #eef2f7 0%, #e8edf5 100%)",
      }}
    >
      <TopBar
        run={run}
        onBack={onBack}
        onApprove={() => runId && runAction(() => approveRun(runId))}
        onRequestChanges={() => {
          const feedback = window.prompt(t("변경 요청 내용을 입력하세요.", "Enter change request feedback.")) || "";
          if (feedback.trim() && runId) runAction(() => requestChanges(runId, feedback));
        }}
        onCancel={() => runId && runAction(() => cancelRun(runId))}
        onApproveQa={() => runId && runAction(() => approveQa(runId))}
        t={t}
      />
      <div className="flex-1 flex min-h-0">
        <AgentSidePanel rows={rows} selected={selectedAgent} onSelect={setSelectedAgent} lang={lang} setLang={setLang} theme={theme} setTheme={setTheme} />
        <main className="flex-1 flex flex-col min-w-0">
          <div className="px-4 py-2 border-b border-slate-200 dark:border-slate-700 bg-white/70 dark:bg-slate-900/60 backdrop-blur-sm flex items-center justify-between shrink-0">
            <div className="flex items-center gap-2">
              <Activity className="size-3.5 text-slate-500 dark:text-slate-500" />
              <span className="uppercase tracking-wider text-slate-500 dark:text-slate-500" style={{ fontSize: 10 }}>{t("실행 타임라인", "Execution Timeline")}</span>
              <span className="font-mono text-slate-400 dark:text-slate-500" style={{ fontSize: 11 }}>{events.length} {t("이벤트", "events")}</span>
            </div>
            <div className="flex items-center gap-1">
              {["All", "Agents", "System", "Approvals", "Errors"].map((label, index) => <FilterPill key={label} active={index === 0}>{label}</FilterPill>)}
            </div>
          </div>
          <div className="flex-1 overflow-y-auto px-4 py-3 relative">
            <div className="absolute left-[22px] top-3 bottom-3 w-px bg-slate-200 dark:bg-slate-700" />
            <div className="space-y-2">
              {events.map((event) => (
                <TimelineItem
                  key={event.id}
                  event={event}
                  selected={selectedEventId === event.id}
                  onSelect={() => setSelectedEventId(event.id)}
                  expanded={!!expanded[event.id]}
                  onToggle={() => setExpanded((state) => ({ ...state, [event.id]: !state[event.id] }))}
                  t={t}
                />
              ))}
              {events.length === 0 && <div className="relative pl-6 text-slate-500 dark:text-slate-500" style={{ fontSize: 13 }}>{runId ? t("이벤트를 불러오는 중입니다.", "Loading events.") : t("선택된 실행이 없습니다.", "No run selected.")}</div>}
            </div>
          </div>
          <div className="border-t border-slate-200 dark:border-slate-700 bg-white/60 dark:bg-slate-900/60 backdrop-blur-sm px-4 py-2.5 shrink-0">
            <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 shadow-[0_1px_0_rgba(15,23,42,0.02),0_4px_16px_rgba(15,23,42,0.05)] focus-within:border-indigo-300 focus-within:ring-1 focus-within:ring-indigo-200 flex items-center gap-2 px-2 py-1">
              <span className="font-mono text-slate-400 dark:text-slate-500 px-1" style={{ fontSize: 11 }}>operator ›</span>
              <input value={chatInput} onChange={(event) => setChatInput(event.target.value)} placeholder={t("메모, 변경 요청, 또는 QA 수정 요청을 입력하세요...", "Send a note, request a change, or request a QA fix...")} className="flex-1 bg-transparent outline-none py-1.5" style={{ fontSize: 13 }} />
              <button
                onClick={() => {
                  const feedback = chatInput.trim();
                  if (!feedback || !runId) return;
                  runAction(() => (run?.status.includes("qa") ? requestQaFix(runId, feedback) : requestChanges(runId, feedback)));
                  setChatInput("");
                }}
                className="p-1.5 rounded hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-500"
                title={t("보내기", "Send")}
              >
                <Send className="size-3.5" />
              </button>
            </div>
            {error && <div className="mt-2 text-rose-700 bg-rose-50 border border-rose-200 rounded px-2 py-1" style={{ fontSize: 12 }}>{error}</div>}
          </div>
        </main>
        <ArtifactPanel event={selectedEvent} artifacts={artifacts} content={content} onOpenArtifact={openArtifact} t={t} />
      </div>
    </div>
  );
}

function FilterPill({ children, active }: { children: ReactNode; active?: boolean }) {
  return (
    <button className={`px-2 py-0.5 rounded border ${active ? "bg-indigo-600 text-white border-indigo-600" : "bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-500 border-slate-200 dark:border-slate-700 hover:border-slate-300 dark:hover:border-slate-600"}`} style={{ fontSize: 11 }}>
      {children}
    </button>
  );
}
