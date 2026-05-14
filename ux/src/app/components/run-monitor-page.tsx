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
  ActiveStepInfo,
  ArtifactContent,
  ArtifactInfo,
  LogFileInfo,
  LogTail,
  RunDetail,
  TimelineEvent,
  approveQa,
  approveRun,
  cancelRun,
  getActiveStep,
  getEvents,
  getRun,
  listLogs,
  listArtifacts,
  readLogTail,
  readArtifact,
  requestChanges,
  requestQaFix,
} from "../api";

type Lang = "ko" | "en";
type Status = "idle" | "ready" | "running" | "waiting" | "error" | "done" | "paused" | "queued";
type TimelineFilter = "clean" | "agents" | "system" | "approvals" | "errors" | "all";
type TimelineArtifactRef = TimelineEvent["artifacts"][number];

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

function eventType(event: TimelineEvent) {
  return typeof event.raw.type === "string" ? event.raw.type : "";
}

function isCleanTimelineEvent(event: TimelineEvent) {
  const status = normalizeStatus(event.status);
  return event.kind === "agent" || event.kind === "approval" || event.kind === "user" || event.kind === "error" || status === "error";
}

function matchesTimelineFilter(event: TimelineEvent, filter: TimelineFilter) {
  if (filter === "all") return true;
  if (filter === "clean") return isCleanTimelineEvent(event);
  if (filter === "agents") return event.kind === "agent";
  if (filter === "system") return event.kind === "system";
  if (filter === "approvals") return event.kind === "approval" || eventType(event) === "approval";
  if (filter === "errors") return event.kind === "error" || normalizeStatus(event.status) === "error";
  return true;
}

function isPlanResultEvent(event: TimelineEvent) {
  const type = eventType(event);
  const path = typeof event.raw.data?.path === "string" ? event.raw.data.path : "";
  return (
    type === "agent_output" &&
    event.actor === "planner_a" &&
    (event.title.toLowerCase().includes("final plan") || path.includes("planning/03_final_plan"))
  );
}

function isQaResultEvent(event: TimelineEvent) {
  const type = eventType(event);
  const path = typeof event.raw.data?.path === "string" ? event.raw.data.path : "";
  return (
    (type === "agent_output" && event.actor.startsWith("qa_") && (event.title.toLowerCase().includes("review") || path.includes("qa_"))) ||
    (type === "qa_completed" && event.title.toLowerCase().includes("llm qa")) ||
    (type === "worker_checkpoint" && String(event.raw.data?.stage || "").includes("mechanical_qa"))
  );
}

function latestEventId(events: TimelineEvent[], predicate: (event: TimelineEvent) => boolean) {
  return [...events].reverse().find(predicate)?.id || "";
}

function isEvidenceArtifact(artifact: TimelineArtifactRef) {
  const path = artifact.path.toLowerCase();
  const name = artifact.name.toLowerCase();
  return (
    artifact.type === "image" ||
    path.includes("/qa/") ||
    path.includes("\\qa\\") ||
    name.includes("qa_") ||
    name.includes("scenario") ||
    name.includes("screenshot") ||
    name.includes("browser") ||
    name.includes("console") ||
    name.includes("syntax_report") ||
    name.includes("executable_report")
  );
}

function isTextEvidenceArtifact(artifact: TimelineArtifactRef) {
  if (artifact.type !== "file" && artifact.type !== "log") return false;
  return isEvidenceArtifact(artifact);
}

function timelinePreviewArtifacts(event: TimelineEvent) {
  return event.artifacts
    .filter((artifact) => artifact.type === "image" || isTextEvidenceArtifact(artifact))
    .slice(0, 12);
}

function artifactImageSrc(content?: ArtifactContent) {
  if (!content || content.encoding !== "base64") return "";
  return `data:${content.media_type || "image/png"};base64,${content.content}`;
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
  onCancel,
  t,
}: {
  run: RunDetail | null;
  onBack: () => void;
  onCancel: () => void;
  t: (ko: string, en: string) => string;
}) {
  const status = normalizeStatus(run?.status);
  const route = run?.route_mode || run?.state.routing?.mode || "local";
  const waitingForUser = run?.status === "awaiting_plan_approval" || run?.status === "awaiting_qa_approval";
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
        {waitingForUser && (
          <span className="hidden lg:inline-flex items-center gap-1.5 px-2 py-1.5 rounded-md border border-amber-200 bg-amber-50 text-amber-800" style={{ fontSize: 12 }}>
            <AlertTriangle className="size-3.5" />
            {t("타임라인의 결과 카드에서 승인하세요", "Approve from the timeline result card")}
          </span>
        )}
        <ActionBtn icon={<Pause className="size-3.5" />} label={t("일시정지", "Pause")} disabled />
        <ActionBtn icon={<Square className="size-3.5" />} label={t("중지", "Stop")} onClick={onCancel} />
        <ActionBtn icon={<RotateCw className="size-3.5" />} label={t("새로고침", "Refresh")} />
        <ActionBtn icon={<FolderOpen className="size-3.5" />} label={t("출력 폴더", "Output")} disabled />
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
  actionCard,
  artifactContents,
  onOpenArtifact,
  t,
}: {
  event: TimelineEvent;
  selected: boolean;
  onSelect: () => void;
  expanded: boolean;
  onToggle: () => void;
  actionCard?: ReactNode;
  artifactContents: Record<string, ArtifactContent>;
  onOpenArtifact: (path: string) => void;
  t: (ko: string, en: string) => string;
}) {
  const status = normalizeStatus(event.status);
  const imageArtifacts = event.artifacts.filter((artifact) => artifact.type === "image");
  const textEvidenceArtifacts = event.artifacts.filter(isTextEvidenceArtifact).slice(0, 4);
  const canExpand = !!event.summary || event.details.length > 0 || event.artifacts.length > 0;
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
      <div
        onClick={onSelect}
        role="button"
        tabIndex={0}
        onKeyDown={(keyEvent) => {
          if (keyEvent.key === "Enter" || keyEvent.key === " ") onSelect();
        }}
        className={`w-full text-left rounded-lg border ${accent} ${selected ? "ring-1 ring-indigo-300 border-indigo-300" : ""} hover:border-slate-300 dark:hover:border-slate-600 transition-colors shadow-[0_1px_0_rgba(15,23,42,0.02)]`}
      >
        <div className="px-3 py-2 flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span style={{ fontSize: 12 }}>{event.who}</span>
              <span className="font-mono text-slate-400 dark:text-slate-500" style={{ fontSize: 10 }}>{event.time}</span>
              <StatusBadge status={status} />
              {status === "error" && <span className="inline-flex items-center gap-1 text-rose-700" style={{ fontSize: 11 }}><XCircle className="size-3" /> {t("실패", "failed")}</span>}
            </div>
            <div className="mt-0.5" style={{ fontSize: 13 }}>{event.title}</div>
            {event.summary && (
              <div className={`text-slate-600 dark:text-slate-500 mt-1 whitespace-pre-wrap ${expanded ? "" : "max-h-20 overflow-hidden"}`} style={{ fontSize: 12, lineHeight: "1.45" }}>
                {event.summary}
              </div>
            )}
          </div>
          {canExpand && (
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
                {event.artifacts.map((artifact) => (
                  <button
                    key={artifact.path}
                    type="button"
                    onClick={(clickEvent) => {
                      clickEvent.stopPropagation();
                      onOpenArtifact(artifact.path);
                    }}
                    className="text-left"
                  >
                    <ArtifactChip name={artifact.name} type={artifact.type} />
                  </button>
                ))}
              </div>
            )}
            {(imageArtifacts.length > 0 || textEvidenceArtifacts.length > 0) && (
              <div className="rounded-md border border-slate-200 dark:border-slate-700 bg-slate-50/80 dark:bg-slate-950/30 p-2 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="uppercase tracking-wider text-slate-500 dark:text-slate-500" style={{ fontSize: 10 }}>
                    {t("QA 증거", "QA Evidence")}
                  </span>
                  <span className="font-mono text-slate-400 dark:text-slate-500" style={{ fontSize: 10 }}>
                    {imageArtifacts.length} images · {textEvidenceArtifacts.length} files
                  </span>
                </div>
                {imageArtifacts.length > 0 && (
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                    {imageArtifacts.slice(0, 6).map((artifact) => {
                      const src = artifactImageSrc(artifactContents[artifact.path]);
                      return (
                        <button
                          key={artifact.path}
                          type="button"
                          onClick={(clickEvent) => {
                            clickEvent.stopPropagation();
                            onOpenArtifact(artifact.path);
                          }}
                          className="group rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 overflow-hidden text-left hover:border-indigo-300"
                        >
                          {src ? (
                            <img alt={artifact.name} src={src} className="h-32 w-full object-cover bg-slate-100 dark:bg-slate-800" />
                          ) : (
                            <div className="h-32 w-full bg-slate-100 dark:bg-slate-800 flex items-center justify-center text-slate-400">
                              <ImageIcon className="size-5" />
                            </div>
                          )}
                          <div className="px-1.5 py-1 font-mono truncate text-slate-600 dark:text-slate-400" style={{ fontSize: 10 }}>
                            {artifact.name}
                          </div>
                        </button>
                      );
                    })}
                  </div>
                )}
                {textEvidenceArtifacts.map((artifact) => {
                  const artifactContent = artifactContents[artifact.path];
                  return (
                    <button
                      key={artifact.path}
                      type="button"
                      onClick={(clickEvent) => {
                        clickEvent.stopPropagation();
                        onOpenArtifact(artifact.path);
                      }}
                      className="block w-full text-left rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 hover:border-indigo-300 overflow-hidden"
                    >
                      <div className="px-2 py-1 flex items-center justify-between gap-2 border-b border-slate-100 dark:border-slate-800">
                        <span className="font-mono truncate text-slate-700 dark:text-slate-300" style={{ fontSize: 11 }}>{artifact.path}</span>
                        {artifactContent?.truncated && <span className="text-amber-700" style={{ fontSize: 10 }}>truncated</span>}
                      </div>
                      <pre className="p-2 whitespace-pre-wrap text-slate-700 dark:text-slate-300 overflow-x-auto" style={{ fontSize: 11, lineHeight: "1.45" }}>
                        {artifactContent?.encoding === "utf-8" ? artifactContent.content : "Loading evidence preview..."}
                      </pre>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        )}
        {actionCard && (
          <div className="border-t border-amber-100 dark:border-amber-900/50 px-3 py-2 bg-amber-50/70 dark:bg-amber-950/20">
            {actionCard}
          </div>
        )}
      </div>
    </div>
  );
}

function TimelineActionCard({
  title,
  description,
  approveLabel,
  requestLabel,
  cancelLabel,
  onApprove,
  onRequest,
  onCancel,
}: {
  title: string;
  description: string;
  approveLabel: string;
  requestLabel: string;
  cancelLabel: string;
  onApprove: () => void;
  onRequest: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <div className="inline-flex items-center gap-1.5 text-amber-900 dark:text-amber-200 font-medium" style={{ fontSize: 12 }}>
          <AlertTriangle className="size-3.5" />
          {title}
        </div>
        <div className="mt-0.5 text-amber-800/80 dark:text-amber-200/70" style={{ fontSize: 12 }}>
          {description}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-1.5 shrink-0">
        <button
          type="button"
          onClick={(event) => { event.stopPropagation(); onRequest(); }}
          className="px-2.5 py-1.5 rounded-md border border-amber-300 bg-white text-amber-800 hover:bg-amber-100 inline-flex items-center gap-1.5"
          style={{ fontSize: 12 }}
        >
          <CircleSlash className="size-3.5" />
          {requestLabel}
        </button>
        <button
          type="button"
          onClick={(event) => { event.stopPropagation(); onCancel(); }}
          className="px-2.5 py-1.5 rounded-md border border-slate-300 bg-white text-slate-700 hover:bg-slate-50 inline-flex items-center gap-1.5"
          style={{ fontSize: 12 }}
        >
          <Square className="size-3.5" />
          {cancelLabel}
        </button>
        <button
          type="button"
          onClick={(event) => { event.stopPropagation(); onApprove(); }}
          className="px-2.5 py-1.5 rounded-md bg-emerald-600 text-white hover:bg-emerald-700 inline-flex items-center gap-1.5 shadow-[0_1px_0_rgba(5,150,105,0.4),0_2px_6px_rgba(5,150,105,0.2)]"
          style={{ fontSize: 12 }}
        >
          <CheckCircle2 className="size-3.5" />
          {approveLabel}
        </button>
      </div>
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

function EventDetailPanel({
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
  const [showAllArtifacts, setShowAllArtifacts] = useState(false);
  const relatedArtifacts = event?.artifacts || [];
  const detailLines = event?.details || [];
  return (
    <aside className="w-[360px] shrink-0 border-l border-slate-200/80 dark:border-slate-700/70 bg-gradient-to-b from-slate-50 to-indigo-50/40 dark:from-slate-900 dark:to-indigo-950/40 flex flex-col overflow-hidden">
      <div className="px-3 py-2 border-b border-slate-200/70 dark:border-slate-700/70 flex items-center justify-between">
        <span className="uppercase tracking-wider text-slate-500 dark:text-slate-500" style={{ fontSize: 10 }}>{t("상세", "Details")}</span>
        <FolderOpen className="size-3.5 text-slate-500 dark:text-slate-500" />
      </div>
      <div className="overflow-y-auto flex-1">
        <Section title={t("선택 이벤트", "Selected Event")}>
          <div className="rounded border border-slate-200 dark:border-slate-700 bg-slate-50/60 dark:bg-slate-900/60 p-2">
            <div className="flex items-center gap-2">
              <span style={{ fontSize: 12 }}>{event?.who || "System"}</span>
              <StatusBadge status={normalizeStatus(event?.status)} />
            </div>
            <div className="mt-0.5" style={{ fontSize: 13 }}>{event?.title || "No event selected"}</div>
            {event?.summary && (
              <div className="text-slate-600 dark:text-slate-500 mt-1 max-h-48 overflow-auto whitespace-pre-wrap" style={{ fontSize: 12, lineHeight: "1.45" }}>
                {event.summary}
              </div>
            )}
            {detailLines.length > 0 && (
              <div className="mt-2 space-y-0.5 border-t border-slate-200/70 dark:border-slate-700/70 pt-2">
                {detailLines.slice(0, 10).map((detail) => (
                  <div key={detail} className="font-mono text-slate-500 dark:text-slate-500 truncate" style={{ fontSize: 10 }}>
                    {detail}
                  </div>
                ))}
              </div>
            )}
          </div>
        </Section>
        <Section title={t("관련 파일", "Related Files")}>
          {relatedArtifacts.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {relatedArtifacts.map((artifact) => (
                <button
                  key={artifact.path}
                  type="button"
                  onClick={() => artifact.type !== "directory" && onOpenArtifact(artifact.path)}
                  className="text-left"
                >
                  <ArtifactChip name={artifact.name} type={artifact.type} />
                </button>
              ))}
            </div>
          ) : (
            <div className="text-slate-500 dark:text-slate-500" style={{ fontSize: 12 }}>
              {t("이 이벤트에 연결된 파일이 없습니다.", "No files are attached to this event.")}
            </div>
          )}
        </Section>
        <Section title={t("미리보기", "Preview")}>
          {content ? (
            <div className="space-y-1.5">
              <div className="rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 py-1">
                <div className="font-mono truncate text-slate-700 dark:text-slate-300" style={{ fontSize: 11 }}>{content.path}</div>
                <div className="flex items-center gap-2 text-slate-500 dark:text-slate-500" style={{ fontSize: 10 }}>
                  <span>{formatBytes(content.size_bytes)}</span>
                  <span>{content.encoding}</span>
                  {content.truncated && <span className="text-amber-700">truncated</span>}
                </div>
              </div>
              {content.encoding === "base64" && content.kind === "image" ? (
                <img alt={content.name} src={`data:${content.media_type || "image/png"};base64,${content.content}`} className="w-full rounded border border-slate-200 dark:border-slate-700" />
              ) : (
                <pre className="rounded border border-slate-200 dark:border-slate-700 bg-slate-950 text-slate-100 p-2 overflow-auto max-h-[560px] font-mono whitespace-pre-wrap" style={{ fontSize: 11, lineHeight: "1.5" }}>{content.content}</pre>
              )}
            </div>
          ) : (
            <div className="rounded-md border border-dashed border-slate-300 dark:border-slate-700 bg-white/60 dark:bg-slate-900/50 p-3 text-slate-500 dark:text-slate-500" style={{ fontSize: 12 }}>
              {t("타임라인 카드의 파일이나 스크린샷을 클릭하면 여기에서 크게 볼 수 있습니다.", "Click a timeline file or screenshot to inspect it here.")}
            </div>
          )}
        </Section>
        <Section title={t("전체 산출물", "All Artifacts")}>
          <button
            type="button"
            onClick={() => setShowAllArtifacts((value) => !value)}
            className="w-full rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 py-1.5 text-left hover:border-slate-300 dark:hover:border-slate-600 flex items-center justify-between"
          >
            <span className="text-slate-700 dark:text-slate-300" style={{ fontSize: 12 }}>
              {showAllArtifacts ? t("전체 산출물 숨기기", "Hide full artifact list") : t("전체 산출물 보기", "Show full artifact list")}
            </span>
            <span className="font-mono text-slate-500 dark:text-slate-500" style={{ fontSize: 11 }}>{artifacts.length}</span>
          </button>
          {showAllArtifacts && (
            <div className="mt-2 space-y-1 max-h-72 overflow-y-auto">
              {artifacts.slice(0, 120).map((artifact) => (
                <ArtifactRow key={artifact.path} artifact={artifact} onClick={() => artifact.kind !== "directory" && onOpenArtifact(artifact.path)} />
              ))}
              {artifacts.length === 0 && <div className="text-slate-500 dark:text-slate-500" style={{ fontSize: 12 }}>{t("산출물이 없습니다.", "No artifacts")}</div>}
            </div>
          )}
          {showAllArtifacts && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {["state.json", "events.jsonl", "transcript.md", "qa_report.md"].map((path) => (
                <button key={path} onClick={() => onOpenArtifact(path)} className="text-left">
                  <ArtifactChip name={path} type={path.endsWith(".jsonl") ? "log" : "file"} />
                </button>
              ))}
            </div>
          )}
        </Section>
      </div>
    </aside>
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
            {event?.summary && <div className="text-slate-600 dark:text-slate-500 mt-1 max-h-40 overflow-auto whitespace-pre-wrap" style={{ fontSize: 12, lineHeight: "1.45" }}>{event.summary}</div>}
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
      <div className="flex items-center gap-1.5 shrink-0">
        {artifact.stage && <span className="rounded border border-slate-200 dark:border-slate-700 px-1 text-slate-500 dark:text-slate-500" style={{ fontSize: 10 }}>{artifact.stage}</span>}
        {artifact.size_bytes != null && <span className="font-mono text-slate-500 dark:text-slate-500" style={{ fontSize: 11 }}>{formatBytes(artifact.size_bytes)}</span>}
      </div>
    </button>
  );
}

function ObservationPanel({
  activeStep,
  logs,
  logTail,
  onOpenLog,
}: {
  activeStep: ActiveStepInfo | null;
  logs: LogFileInfo[];
  logTail: LogTail | null;
  onOpenLog: (path: string) => void;
}) {
  return (
    <div className="grid grid-cols-[minmax(220px,280px)_1fr] gap-3 px-4 py-3 border-b border-slate-200 dark:border-slate-700 bg-white/65 dark:bg-slate-900/55 backdrop-blur-sm shrink-0">
      <div className="rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-2 min-w-0">
        <div className="flex items-center justify-between gap-2">
          <span className="uppercase tracking-wider text-slate-500 dark:text-slate-500" style={{ fontSize: 10 }}>Active step</span>
          <StatusBadge status={activeStep?.active ? "running" : normalizeStatus(activeStep?.status)} />
        </div>
        <div className="mt-1 font-mono text-slate-800 dark:text-slate-200 truncate" style={{ fontSize: 12 }}>
          {activeStep?.label || "idle"}
        </div>
        <div className="mt-1 grid grid-cols-2 gap-1 text-slate-500 dark:text-slate-500" style={{ fontSize: 11 }}>
          <span>stage: <span className="font-mono">{activeStep?.stage || "--"}</span></span>
          <span>pid: <span className="font-mono">{activeStep?.pid || "--"}</span></span>
          <span>agent: <span className="font-mono">{activeStep?.agent_id || "--"}</span></span>
          <span>started: <span className="font-mono">{timeOnly(activeStep?.started_at)}</span></span>
        </div>
      </div>
      <div className="rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 min-w-0 overflow-hidden grid grid-cols-[260px_1fr]">
        <div className="border-r border-slate-200 dark:border-slate-700 min-w-0">
          <div className="px-2 py-1.5 uppercase tracking-wider text-slate-500 dark:text-slate-500 border-b border-slate-100 dark:border-slate-800" style={{ fontSize: 10 }}>Recent logs</div>
          <div className="max-h-28 overflow-y-auto p-1 space-y-1">
            {logs.slice(0, 8).map((log) => (
              <button key={log.path} onClick={() => onOpenLog(log.path)} className="w-full min-w-0 flex items-center justify-between gap-2 rounded px-1.5 py-1 text-left hover:bg-slate-50 dark:hover:bg-slate-800">
                <span className="font-mono truncate text-slate-700 dark:text-slate-300" style={{ fontSize: 11 }}>{log.name}</span>
                <span className="font-mono text-slate-500 dark:text-slate-500 shrink-0" style={{ fontSize: 10 }}>{formatBytes(log.size_bytes)}</span>
              </button>
            ))}
            {logs.length === 0 && <div className="px-1.5 py-1 text-slate-500 dark:text-slate-500" style={{ fontSize: 12 }}>No logs yet</div>}
          </div>
        </div>
        <pre className="max-h-36 overflow-auto bg-slate-950 text-slate-100 p-2 font-mono whitespace-pre-wrap" style={{ fontSize: 11, lineHeight: "1.45" }}>
          {logTail?.content || "Select a log to inspect the latest lines."}
        </pre>
      </div>
    </div>
  );
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function timeOnly(value?: string | null) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
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
  const [activeStep, setActiveStep] = useState<ActiveStepInfo | null>(null);
  const [logs, setLogs] = useState<LogFileInfo[]>([]);
  const [logTail, setLogTail] = useState<LogTail | null>(null);
  const [content, setContent] = useState<ArtifactContent | null>(null);
  const [timelineContents, setTimelineContents] = useState<Record<string, ArtifactContent>>({});
  const [selectedAgent, setSelectedAgent] = useState("");
  const [selectedEventId, setSelectedEventId] = useState("");
  const [timelineFilter, setTimelineFilter] = useState<TimelineFilter>("clean");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [chatInput, setChatInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const t = (ko: string, en: string) => (lang === "ko" ? ko : en);

  const refresh = useCallback(async () => {
    if (!runId) return;
    const [nextRun, nextEvents, nextArtifacts, nextActiveStep, nextLogs] = await Promise.all([
      getRun(runId),
      getEvents(runId),
      listArtifacts(runId),
      getActiveStep(runId),
      listLogs(runId),
    ]);
    setRun(nextRun);
    setEvents(nextEvents);
    setArtifacts(nextArtifacts);
    setActiveStep(nextActiveStep);
    setLogs(nextLogs);
    const defaultEvent = [...nextEvents].reverse().find(isCleanTimelineEvent) || nextEvents[nextEvents.length - 1];
    setSelectedEventId((current) => current || defaultEvent?.id || "");
    setSelectedAgent((current) => current || Object.keys(nextRun.state.agent_sessions || {})[0] || "");
    setLogTail((current) => current || null);
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

  useEffect(() => {
    setTimelineContents({});
    setContent(null);
  }, [runId]);

  const rows = useMemo(() => buildAgentRows(run, events), [run, events]);
  const visibleEvents = useMemo(
    () => events.filter((event) => matchesTimelineFilter(event, timelineFilter)),
    [events, timelineFilter],
  );
  const selectedEvent = visibleEvents.find((event) => event.id === selectedEventId) || visibleEvents[visibleEvents.length - 1] || events[events.length - 1] || null;
  const planActionEventId = run?.status === "awaiting_plan_approval" ? latestEventId(visibleEvents, isPlanResultEvent) || latestEventId(events, isPlanResultEvent) : "";
  const qaActionEventId = run?.status === "awaiting_qa_approval" ? latestEventId(visibleEvents, isQaResultEvent) || latestEventId(events, isQaResultEvent) : "";

  useEffect(() => {
    if (!runId) return;
    const expandedOrSelected = visibleEvents.filter((event) => expanded[event.id] || event.id === selectedEventId);
    const paths = Array.from(
      new Set(expandedOrSelected.flatMap((event) => timelinePreviewArtifacts(event).map((artifact) => artifact.path))),
    ).filter((path) => !timelineContents[path]);
    if (paths.length === 0) return;

    let cancelled = false;
    Promise.all(
      paths.slice(0, 12).map(async (path) => {
        try {
          return [path, await readArtifact(runId, path)] as const;
        } catch {
          return null;
        }
      }),
    ).then((results) => {
      if (cancelled) return;
      const loaded = results.filter((item): item is readonly [string, ArtifactContent] => item !== null);
      if (loaded.length === 0) return;
      setTimelineContents((current) => {
        const next = { ...current };
        for (const [path, artifactContent] of loaded) {
          next[path] = artifactContent;
        }
        return next;
      });
    });

    return () => {
      cancelled = true;
    };
  }, [expanded, runId, selectedEventId, timelineContents, visibleEvents]);

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
      const artifactContent = await readArtifact(runId, path);
      setContent(artifactContent);
      setTimelineContents((current) => ({ ...current, [path]: artifactContent }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function openLog(path: string) {
    if (!runId) return;
    try {
      setLogTail(await readLogTail(runId, path));
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
        onCancel={() => runId && runAction(() => cancelRun(runId))}
        t={t}
      />
      <div className="flex-1 flex min-h-0">
        <AgentSidePanel rows={rows} selected={selectedAgent} onSelect={setSelectedAgent} lang={lang} setLang={setLang} theme={theme} setTheme={setTheme} />
        <main className="flex-1 flex flex-col min-w-0">
          <ObservationPanel activeStep={activeStep} logs={logs} logTail={logTail} onOpenLog={openLog} />
          <div className="px-4 py-2 border-b border-slate-200 dark:border-slate-700 bg-white/70 dark:bg-slate-900/60 backdrop-blur-sm flex items-center justify-between shrink-0">
            <div className="flex items-center gap-2">
              <Activity className="size-3.5 text-slate-500 dark:text-slate-500" />
              <span className="uppercase tracking-wider text-slate-500 dark:text-slate-500" style={{ fontSize: 10 }}>{t("실행 타임라인", "Execution Timeline")}</span>
              <span className="font-mono text-slate-400 dark:text-slate-500" style={{ fontSize: 11 }}>{visibleEvents.length}/{events.length} {t("이벤트", "events")}</span>
            </div>
            <div className="flex items-center gap-1">
              {[
                ["clean", "Clean"],
                ["agents", "Agents"],
                ["system", "System"],
                ["approvals", "Approvals"],
                ["errors", "Errors"],
                ["all", "All"],
              ].map(([id, label]) => (
                <FilterPill key={id} active={timelineFilter === id} onClick={() => setTimelineFilter(id as TimelineFilter)}>
                  {label}
                </FilterPill>
              ))}
            </div>
          </div>
          <div className="flex-1 overflow-y-auto px-4 py-3 relative">
            <div className="absolute left-[22px] top-3 bottom-3 w-px bg-slate-200 dark:bg-slate-700" />
            <div className="space-y-2">
              {run?.status === "awaiting_plan_approval" && runId && !visibleEvents.some((event) => event.id === planActionEventId) && (
                <div className="relative pl-6">
                  <span className="absolute left-1.5 top-3 size-2 rounded-full bg-amber-500 ring-2 ring-white" />
                  <div className="rounded-lg border border-amber-300 bg-amber-50/70 shadow-[0_1px_0_rgba(15,23,42,0.02)] px-3 py-2">
                    <TimelineActionCard
                      title={t("기획 승인 대기", "Plan approval required")}
                      description={t("이 기획안으로 개발을 진행할지 결정하세요.", "Decide whether to proceed with this plan.")}
                      approveLabel={t("기획 승인", "Approve Plan")}
                      requestLabel={t("수정 요청", "Request Changes")}
                      cancelLabel={t("중지", "Stop")}
                      onApprove={() => runAction(() => approveRun(runId))}
                      onRequest={() => {
                        const feedback = window.prompt(t("변경 요청 내용을 입력하세요.", "Enter change request feedback.")) || "";
                        if (feedback.trim()) runAction(() => requestChanges(runId, feedback));
                      }}
                      onCancel={() => runAction(() => cancelRun(runId))}
                    />
                  </div>
                </div>
              )}
              {run?.status === "awaiting_qa_approval" && runId && !visibleEvents.some((event) => event.id === qaActionEventId) && (
                <div className="relative pl-6">
                  <span className="absolute left-1.5 top-3 size-2 rounded-full bg-amber-500 ring-2 ring-white" />
                  <div className="rounded-lg border border-amber-300 bg-amber-50/70 shadow-[0_1px_0_rgba(15,23,42,0.02)] px-3 py-2">
                    <TimelineActionCard
                      title={t("QA 확인 대기", "QA approval required")}
                      description={t("QA 결과와 스크린샷을 확인하고 최종 승인 또는 수정 요청을 선택하세요.", "Review QA evidence and choose final approval or a fix request.")}
                      approveLabel={t("최종 승인", "Approve QA")}
                      requestLabel={t("QA 수정 요청", "Request Fix")}
                      cancelLabel={t("중지", "Stop")}
                      onApprove={() => runAction(() => approveQa(runId))}
                      onRequest={() => {
                        const feedback = window.prompt(t("QA 수정 요청 내용을 입력하세요.", "Enter QA fix feedback.")) || "";
                        if (feedback.trim()) runAction(() => requestQaFix(runId, feedback));
                      }}
                      onCancel={() => runAction(() => cancelRun(runId))}
                    />
                  </div>
                </div>
              )}
              {visibleEvents.map((event) => (
                <TimelineItem
                  key={event.id}
                  event={event}
                  selected={selectedEvent?.id === event.id}
                  onSelect={() => setSelectedEventId(event.id)}
                  expanded={!!expanded[event.id]}
                  onToggle={() => setExpanded((state) => ({ ...state, [event.id]: !state[event.id] }))}
                  artifactContents={timelineContents}
                  onOpenArtifact={openArtifact}
                  actionCard={
                    event.id === planActionEventId && runId ? (
                      <TimelineActionCard
                        title={t("기획 승인 대기", "Plan approval required")}
                        description={t("이 기획안으로 개발을 진행할지 결정하세요.", "Decide whether to proceed with this plan.")}
                        approveLabel={t("기획 승인", "Approve Plan")}
                        requestLabel={t("수정 요청", "Request Changes")}
                        cancelLabel={t("중지", "Stop")}
                        onApprove={() => runAction(() => approveRun(runId))}
                        onRequest={() => {
                          const feedback = window.prompt(t("변경 요청 내용을 입력하세요.", "Enter change request feedback.")) || "";
                          if (feedback.trim()) runAction(() => requestChanges(runId, feedback));
                        }}
                        onCancel={() => runAction(() => cancelRun(runId))}
                      />
                    ) : event.id === qaActionEventId && runId ? (
                      <TimelineActionCard
                        title={t("QA 확인 대기", "QA approval required")}
                        description={t("QA 결과와 스크린샷을 확인하고 최종 승인 또는 수정 요청을 선택하세요.", "Review QA evidence and choose final approval or a fix request.")}
                        approveLabel={t("최종 승인", "Approve QA")}
                        requestLabel={t("QA 수정 요청", "Request Fix")}
                        cancelLabel={t("중지", "Stop")}
                        onApprove={() => runAction(() => approveQa(runId))}
                        onRequest={() => {
                          const feedback = window.prompt(t("QA 수정 요청 내용을 입력하세요.", "Enter QA fix feedback.")) || "";
                          if (feedback.trim()) runAction(() => requestQaFix(runId, feedback));
                        }}
                        onCancel={() => runAction(() => cancelRun(runId))}
                      />
                    ) : null
                  }
                  t={t}
                />
              ))}
              {events.length === 0 && <div className="relative pl-6 text-slate-500 dark:text-slate-500" style={{ fontSize: 13 }}>{runId ? t("이벤트를 불러오는 중입니다.", "Loading events.") : t("선택된 실행이 없습니다.", "No run selected.")}</div>}
              {events.length > 0 && visibleEvents.length === 0 && (
                <div className="relative pl-6 text-slate-500 dark:text-slate-500" style={{ fontSize: 13 }}>
                  No visible events in this filter yet.
                </div>
              )}
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
        <EventDetailPanel event={selectedEvent} artifacts={artifacts} content={content} onOpenArtifact={openArtifact} t={t} />
      </div>
    </div>
  );
}

function FilterPill({ children, active, onClick }: { children: ReactNode; active?: boolean; onClick?: () => void }) {
  return (
    <button onClick={onClick} className={`px-2 py-0.5 rounded border ${active ? "bg-indigo-600 text-white border-indigo-600" : "bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-500 border-slate-200 dark:border-slate-700 hover:border-slate-300 dark:hover:border-slate-600"}`} style={{ fontSize: 11 }}>
      {children}
    </button>
  );
}
