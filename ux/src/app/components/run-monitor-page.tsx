import { useState } from "react";
import {
  ArrowLeft,
  Pause,
  Square,
  RotateCw,
  CheckCircle2,
  XCircle,
  FolderOpen,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  FileText,
  Image as ImageIcon,
  Terminal,
  ShieldAlert,
  Send,
  CircleSlash,
  Activity,
} from "lucide-react";
import { AccountFooter } from "./agent-roster-page";

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

function StatusBadge({ status }: { status: Status }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded border ${statusStyles[status]}`}
      style={{ fontSize: 11 }}
    >
      <span
        className={`size-1.5 rounded-full ${
          status === "running" ? "bg-current animate-pulse" : "bg-current opacity-80"
        }`}
      />
      <span className="capitalize">{status}</span>
    </span>
  );
}
// Note: status text kept in English here to match technical labels in the ChatOps stream.

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

const agentRows: AgentRow[] = [
  { id: "a1", name: "Planner A", role: "Plan", status: "done", elapsed: "01:12", context: 68, session: "sess_8f21a", lastEvent: "Plan v1 published" },
  { id: "a2", name: "Planner B", role: "Review", status: "running", elapsed: "00:43", context: 81, session: "sess_2b5cc", lastEvent: "Reviewing plan v1" },
  { id: "a3", name: "Architect", role: "Contract", status: "waiting", elapsed: "—", context: null, session: "—", lastEvent: "Waiting for plan approval" },
  { id: "a4", name: "Designer", role: "UI", status: "queued", elapsed: "—", context: null, session: "—", lastEvent: "Queued" },
  { id: "a5", name: "Code Agent 1", role: "Frontend", status: "queued", elapsed: "—", context: null, session: "—", lastEvent: "Queued" },
  { id: "a6", name: "Code Agent 2", role: "Backend", status: "queued", elapsed: "—", context: null, session: "—", lastEvent: "Queued" },
  { id: "a7", name: "Integrator", role: "Merge", status: "queued", elapsed: "—", context: null, session: "—", lastEvent: "Queued" },
  { id: "a8", name: "QA Agent", role: "QA", status: "queued", elapsed: "—", context: null, session: "—", lastEvent: "Queued" },
];

type TimelineKind = "system" | "agent" | "user" | "approval" | "error";

type TimelineEvent = {
  id: string;
  kind: TimelineKind;
  who: string;
  time: string;
  status: Status;
  title: string;
  summary?: string;
  details?: string[];
  artifacts?: { name: string; type: "file" | "image" | "log" }[];
  approvalOpen?: boolean;
  failed?: boolean;
};

const timelineEvents: TimelineEvent[] = [
  {
    id: "e1",
    kind: "system",
    who: "System",
    time: "14:32:00",
    status: "done",
    title: "Run created",
    summary: "20260428_143200 · mode: balanced",
    details: ["workspace: dashboard-app", "agents: 8", "preset: full-stack/parallel"],
  },
  {
    id: "e2",
    kind: "agent",
    who: "Planner A",
    time: "14:32:11",
    status: "done",
    title: "Initial development plan created",
    summary: "5 milestones, 12 tasks. Risk: Low.",
    details: [
      "Build a two-page dashboard",
      "Implement agent roster configuration",
      "Add ChatOps run monitor",
      "Store run settings as JSON",
      "Use mock runner before connecting real CLI",
    ],
    artifacts: [
      { name: "plan.v1.md", type: "file" },
      { name: "risk.json", type: "file" },
    ],
  },
  {
    id: "e3",
    kind: "agent",
    who: "Planner B",
    time: "14:33:24",
    status: "done",
    title: "Plan review completed",
    summary: "3 findings. Suggests approval gate before code.",
    details: [
      "Add approval checkpoint before code generation",
      "Separate visual agent order from execution pipeline order",
      "Add context-risk state to each session",
    ],
  },
  {
    id: "e4",
    kind: "approval",
    who: "System",
    time: "14:33:42",
    status: "waiting",
    title: "Approval required before implementation",
    summary: "Review plan and findings, then approve, request changes, or cancel.",
    approvalOpen: true,
  },
  {
    id: "e5",
    kind: "user",
    who: "operator@local",
    time: "—",
    status: "queued",
    title: "Awaiting operator decision",
    summary: "No response yet.",
  },
  {
    id: "e6",
    kind: "agent",
    who: "QA Agent",
    time: "—",
    status: "queued",
    title: "Standby for build artifacts",
    summary: "Will run syntax check + visual capture once Integrator finishes.",
  },
];

function ContextBar({ value }: { value: number | null }) {
  if (value === null)
    return (
      <span className="font-mono text-slate-400 dark:text-slate-500" style={{ fontSize: 11 }}>
        —
      </span>
    );
  const tone = value > 60 ? "bg-emerald-500" : value > 30 ? "bg-amber-500" : "bg-rose-500";
  return (
    <div className="flex items-center gap-1.5 min-w-0">
      <div className="h-1 w-12 rounded bg-slate-100 dark:bg-slate-800 overflow-hidden">
        <div className={`h-full ${tone}`} style={{ width: `${value}%` }} />
      </div>
      <span className="font-mono text-slate-500 dark:text-slate-500" style={{ fontSize: 11 }}>
        {value}%
      </span>
    </div>
  );
}

function TopBar({ onBack, t }: { onBack: () => void; t: (ko: string, en: string) => string }) {
  return (
    <header className="h-14 px-4 border-b border-slate-200 dark:border-slate-700 bg-white/70 dark:bg-slate-900/60 backdrop-blur-sm flex items-center justify-between shrink-0">
      <div className="flex items-center gap-3 min-w-0">
        <button
          onClick={onBack}
          className="p-1.5 rounded-md hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-500"
          title={t("로스터로 돌아가기", "Back to roster")}
        >
          <ArrowLeft className="size-4" />
        </button>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-slate-900 dark:text-slate-100" style={{ fontSize: 13 }}>{t("실행 모니터", "Run Monitor")}</span>
            <span className="font-mono text-slate-500 dark:text-slate-500" style={{ fontSize: 11 }}>
              run_20260428_143200
            </span>
            <StatusBadge status="waiting" />
          </div>
          <div className="flex items-center gap-3 mt-0.5 text-slate-500 dark:text-slate-500" style={{ fontSize: 11 }}>
            <span>
              {t("프로젝트", "project")}: <span className="font-mono text-slate-700 dark:text-slate-300">dashboard-app</span>
            </span>
            <span>
              {t("단계", "phase")}: <span className="text-slate-700 dark:text-slate-300">{t("플랜 리뷰", "Planner Review")}</span>
            </span>
            <span>
              {t("경과", "elapsed")}: <span className="font-mono text-slate-700 dark:text-slate-300">04:32</span>
            </span>
            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded border border-emerald-100 bg-emerald-50 text-emerald-700">
              <ShieldAlert className="size-3" /> {t("컨텍스트 위험: 낮음", "ctx risk: low")}
            </span>
            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded border border-amber-100 bg-amber-50 text-amber-800">
              <AlertTriangle className="size-3" /> codex-alt 5h 41%
            </span>
          </div>
        </div>
      </div>
      <div className="flex items-center gap-1.5">
        <ActionBtn icon={<Pause className="size-3.5" />} label={t("일시정지", "Pause")} />
        <ActionBtn icon={<Square className="size-3.5" />} label={t("중지", "Stop")} />
        <ActionBtn icon={<RotateCw className="size-3.5" />} label={t("재시도", "Retry")} />
        <ActionBtn icon={<FolderOpen className="size-3.5" />} label={t("출력 폴더", "Output")} />
        <div className="w-px h-6 bg-slate-200 dark:bg-slate-700 mx-1" />
        <button
          className="px-2.5 py-1.5 rounded-md border border-amber-300 bg-amber-50 text-amber-800 hover:bg-amber-100 inline-flex items-center gap-1.5"
          style={{ fontSize: 12 }}
        >
          <CircleSlash className="size-3.5" /> {t("변경 요청", "Request Changes")}
        </button>
        <button
          className="px-2.5 py-1.5 rounded-md bg-emerald-600 text-white hover:bg-emerald-700 inline-flex items-center gap-1.5 shadow-[0_1px_0_rgba(5,150,105,0.4),0_2px_6px_rgba(5,150,105,0.2)]"
          style={{ fontSize: 12 }}
        >
          <CheckCircle2 className="size-3.5" /> {t("승인", "Approve")}
        </button>
      </div>
    </header>
  );
}

function ActionBtn({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <button
      className="px-2 py-1.5 rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 hover:border-slate-300 dark:hover:border-slate-600 dark:border-slate-600 hover:bg-slate-50 dark:hover:bg-slate-800 dark:bg-slate-900 inline-flex items-center gap-1 text-slate-700 dark:text-slate-300"
      style={{ fontSize: 12 }}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}

function AgentSidePanel({
  selected,
  onSelect,
  lang,
  setLang,
  theme,
  setTheme,
}: {
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
        <span className="uppercase tracking-wider text-slate-500 dark:text-slate-500" style={{ fontSize: 10 }}>
          {lang === "ko" ? "에이전트" : "Agents"}
        </span>
        <span className="font-mono text-slate-500 dark:text-slate-500" style={{ fontSize: 10 }}>
          {agentRows.length}
        </span>
      </div>
      <div className="overflow-y-auto flex-1 p-1.5 space-y-1">
        {agentRows.map((a) => {
          const active = selected === a.id;
          return (
            <button
              key={a.id}
              onClick={() => onSelect(a.id)}
              className={`relative w-full text-left rounded-md border px-2 py-1.5 transition-colors ${
                active
                  ? "border-indigo-200 bg-white dark:bg-slate-900 shadow-[inset_2px_0_0_rgb(79,70,229)]"
                  : "border-transparent bg-white/60 dark:bg-slate-900/60 hover:border-slate-200 dark:border-slate-700 hover:bg-white dark:bg-slate-900"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="text-slate-800 dark:text-slate-200" style={{ fontSize: 12 }}>{a.name}</span>
                <StatusBadge status={a.status} />
              </div>
              <div className="flex items-center justify-between mt-0.5">
                <span className="text-slate-500 dark:text-slate-500" style={{ fontSize: 11 }}>
                  {a.role}
                </span>
                <span className="font-mono text-slate-500 dark:text-slate-500" style={{ fontSize: 10 }}>
                  {a.elapsed}
                </span>
              </div>
              <div className="flex items-center justify-between mt-1">
                <ContextBar value={a.context} />
                <span className="font-mono text-slate-400 dark:text-slate-500 truncate ml-2" style={{ fontSize: 10 }}>
                  {a.session}
                </span>
              </div>
              <div className="text-slate-500 dark:text-slate-500 truncate mt-1" style={{ fontSize: 11 }}>
                {a.lastEvent}
              </div>
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
  const accent =
    event.kind === "approval"
      ? "border-amber-300 bg-amber-50/70"
      : event.kind === "user"
      ? "border-slate-200 dark:border-slate-700 bg-slate-50/80 dark:bg-slate-900/70"
      : event.failed
      ? "border-rose-300 bg-rose-50/60"
      : "border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900";

  const dot =
    event.kind === "approval"
      ? "bg-amber-500"
      : event.failed
      ? "bg-rose-500"
      : event.status === "running"
      ? "bg-indigo-500"
      : event.status === "done"
      ? "bg-emerald-500"
      : "bg-slate-400";

  return (
    <div className="relative pl-6">
      <span
        className={`absolute left-1.5 top-3 size-2 rounded-full ${dot} ring-2 ring-white`}
      />
      <button
        onClick={onSelect}
        className={`w-full text-left rounded-lg border ${accent} ${
          selected ? "ring-1 ring-indigo-300 border-indigo-300" : ""
        } hover:border-slate-300 dark:hover:border-slate-600 dark:border-slate-600 transition-colors shadow-[0_1px_0_rgba(15,23,42,0.02)]`}
      >
        <div className="px-3 py-2 flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span style={{ fontSize: 12 }}>{event.who}</span>
              <span className="font-mono text-slate-400 dark:text-slate-500" style={{ fontSize: 10 }}>
                {event.time}
              </span>
              <StatusBadge status={event.status} />
              {event.failed && (
                <span className="inline-flex items-center gap-1 text-rose-700" style={{ fontSize: 11 }}>
                  <XCircle className="size-3" /> {t("실패", "failed")}
                </span>
              )}
            </div>
            <div className="mt-0.5" style={{ fontSize: 13 }}>
              {event.title}
            </div>
            {event.summary && (
              <div className="text-slate-600 dark:text-slate-500 mt-0.5" style={{ fontSize: 12 }}>
                {event.summary}
              </div>
            )}
          </div>
          {(event.details?.length || event.artifacts?.length) && (
            <span
              role="button"
              onClick={(e) => {
                e.stopPropagation();
                onToggle();
              }}
              className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 dark:text-slate-500"
            >
              {expanded ? (
                <ChevronDown className="size-3.5" />
              ) : (
                <ChevronRight className="size-3.5" />
              )}
            </span>
          )}
        </div>

        {expanded && (
          <div className="border-t border-slate-100 dark:border-slate-800 px-3 py-2 space-y-2">
            {event.details && (
              <ul className="space-y-0.5">
                {event.details.map((d) => (
                  <li
                    key={d}
                    className="text-slate-700 dark:text-slate-300 flex gap-2"
                    style={{ fontSize: 12 }}
                  >
                    <span className="text-slate-400 dark:text-slate-500">›</span>
                    <span>{d}</span>
                  </li>
                ))}
              </ul>
            )}
            {event.artifacts && (
              <div className="flex flex-wrap gap-1.5">
                {event.artifacts.map((a) => (
                  <span
                    key={a.name}
                    className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 font-mono text-slate-700 dark:text-slate-300"
                    style={{ fontSize: 11 }}
                  >
                    {a.type === "file" ? (
                      <FileText className="size-3" />
                    ) : a.type === "image" ? (
                      <ImageIcon className="size-3" />
                    ) : (
                      <Terminal className="size-3" />
                    )}
                    {a.name}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}

        {event.approvalOpen && (
          <div className="border-t border-amber-200 px-3 py-2 bg-amber-50/60 flex items-center justify-between">
            <span className="text-amber-800" style={{ fontSize: 12 }}>
              {t(
                "구현 단계 진입 전 운영자 결정이 필요합니다.",
                "Operator decision required to proceed to implementation phase."
              )}
            </span>
            <div className="flex items-center gap-1.5">
              <button
                className="px-2 py-1 rounded border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-900 hover:bg-slate-50 dark:hover:bg-slate-800 dark:bg-slate-900"
                style={{ fontSize: 11 }}
              >
                {t("취소", "Cancel")}
              </button>
              <button
                className="px-2 py-1 rounded border border-amber-300 bg-white dark:bg-slate-900 text-amber-800 hover:bg-amber-100"
                style={{ fontSize: 11 }}
              >
                {t("변경 요청", "Request Changes")}
              </button>
              <button
                className="px-2 py-1 rounded bg-emerald-600 text-white hover:bg-emerald-700"
                style={{ fontSize: 11 }}
              >
                {t("승인", "Approve")}
              </button>
            </div>
          </div>
        )}
      </button>
    </div>
  );
}

function ArtifactPanel({
  event,
  t,
}: {
  event: TimelineEvent;
  t: (ko: string, en: string) => string;
}) {
  return (
    <aside className="w-[360px] shrink-0 border-l border-slate-200/80 dark:border-slate-700/70 bg-gradient-to-b from-slate-50 to-indigo-50/40 dark:from-slate-900 dark:to-indigo-950/40 flex flex-col overflow-hidden">
      <div className="px-3 py-2 border-b border-slate-200/70 dark:border-slate-700/70 flex items-center justify-between">
        <span className="uppercase tracking-wider text-slate-500 dark:text-slate-500" style={{ fontSize: 10 }}>
          {t("상세", "Details")}
        </span>
        <button className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 dark:text-slate-500" title={t("폴더 열기", "Open folder")}>
          <FolderOpen className="size-3.5" />
        </button>
      </div>

      <div className="overflow-y-auto flex-1">
        <Section title={t("선택", "Selection")}>
          <div className="rounded border border-slate-200 dark:border-slate-700 bg-slate-50/60 dark:bg-slate-900/60 p-2">
            <div className="flex items-center gap-2">
              <span style={{ fontSize: 12 }}>{event.who}</span>
              <StatusBadge status={event.status} />
            </div>
            <div className="mt-0.5" style={{ fontSize: 13 }}>
              {event.title}
            </div>
            {event.summary && (
              <div className="text-slate-600 dark:text-slate-500 mt-1" style={{ fontSize: 12 }}>
                {event.summary}
              </div>
            )}
            <div className="font-mono text-slate-400 dark:text-slate-500 mt-1" style={{ fontSize: 10 }}>
              {event.time}
            </div>
          </div>
        </Section>

        <Section title={t("산출물", "Artifacts")}>
          <ArtifactRow icon={<FileText className="size-3.5" />} name="plan.v1.md" size="2.4 KB" />
          <ArtifactRow icon={<FileText className="size-3.5" />} name="risk.json" size="612 B" />
          <ArtifactRow icon={<FileText className="size-3.5" />} name="contract-bundle.ts" size="—" muted />
        </Section>

        <Section title={t("QA 리포트", "QA Report")}>
          <div className="rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-2 space-y-1.5">
            <div className="flex items-center justify-between" style={{ fontSize: 12 }}>
              <span>{t("문법 검사", "syntax check")}</span>
              <span className="inline-flex items-center gap-1 text-emerald-700">
                <CheckCircle2 className="size-3" /> {t("통과", "pass")}
              </span>
            </div>
            <div className="flex items-center justify-between" style={{ fontSize: 12 }}>
              <span>{t("타입 검사", "type check")}</span>
              <span className="text-slate-500 dark:text-slate-500">{t("대기", "pending")}</span>
            </div>
            <div className="flex items-center justify-between" style={{ fontSize: 12 }}>
              <span>{t("비주얼 캡처", "visual capture")}</span>
              <span className="text-slate-500 dark:text-slate-500">{t("대기", "pending")}</span>
            </div>
          </div>
        </Section>

        <Section title={t("로그", "Logs")}>
          <pre
            className="rounded border border-slate-200 dark:border-slate-700 bg-slate-950 text-slate-100 p-2 overflow-x-auto font-mono"
            style={{ fontSize: 11, lineHeight: "1.5" }}
          >
{`14:32:00  system   run created (mode=balanced)
14:32:01  planner  spawning session sess_8f21a
14:32:11  planner  plan v1 emitted (12 tasks)
14:33:02  reviewer spawning session sess_2b5cc
14:33:24  reviewer 3 findings recorded
14:33:42  system   approval gate -> waiting`}
          </pre>
        </Section>

        <Section title={t("실행 파일", "Run files")}>
          <ArtifactRow name="run_config.json" mono />
          <ArtifactRow name="events.jsonl" mono />
          <ArtifactRow name="transcript.md" mono />
        </Section>
      </div>
    </aside>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="px-3 py-2.5 border-b border-slate-100 dark:border-slate-800">
      <div
        className="uppercase tracking-wider text-slate-500 dark:text-slate-500 mb-1.5"
        style={{ fontSize: 10 }}
      >
        {title}
      </div>
      <div className="space-y-1">{children}</div>
    </div>
  );
}

function ArtifactRow({
  icon,
  name,
  size,
  muted,
  mono,
}: {
  icon?: React.ReactNode;
  name: string;
  size?: string;
  muted?: boolean;
  mono?: boolean;
}) {
  return (
    <div
      className={`flex items-center justify-between rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 py-1 hover:border-slate-300 dark:hover:border-slate-600 dark:border-slate-600 ${
        muted ? "opacity-60" : ""
      }`}
    >
      <div className="flex items-center gap-1.5 min-w-0">
        {icon}
        <span
          className={`truncate ${mono ? "font-mono" : ""}`}
          style={{ fontSize: 12 }}
        >
          {name}
        </span>
      </div>
      {size && (
        <span className="font-mono text-slate-500 dark:text-slate-500" style={{ fontSize: 11 }}>
          {size}
        </span>
      )}
    </div>
  );
}

export function RunMonitorPage({
  onBack,
  lang,
  setLang,
  theme,
  setTheme,
}: {
  onBack: () => void;
  lang: Lang;
  setLang: (l: Lang) => void;
  theme: "light" | "dark";
  setTheme: (t: "light" | "dark") => void;
}) {
  const [selectedAgent, setSelectedAgent] = useState("a2");
  const [selectedEventId, setSelectedEventId] = useState("e4");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({ e2: true, e4: true });
  const [chatInput, setChatInput] = useState("");

  const selectedEvent =
    timelineEvents.find((e) => e.id === selectedEventId) ?? timelineEvents[0];

  const t = (ko: string, en: string) => (lang === "ko" ? ko : en);

  return (
    <div
      className="size-full flex flex-col text-slate-900 dark:text-slate-100"
      style={{
        background:
          theme === "dark"
            ? "radial-gradient(1200px 600px at 0% 0%, rgba(99,102,241,0.18), transparent 60%), radial-gradient(900px 500px at 100% 100%, rgba(56,189,248,0.08), transparent 60%), linear-gradient(180deg, #0a0f1c 0%, #0b1224 100%)"
            : "radial-gradient(1200px 600px at 0% 0%, rgba(99,102,241,0.08), transparent 60%), radial-gradient(900px 500px at 100% 100%, rgba(56,189,248,0.06), transparent 60%), linear-gradient(180deg, #eef2f7 0%, #e8edf5 100%)",
      }}
    >
      <TopBar onBack={onBack} t={t} />

      <div className="flex-1 flex min-h-0">
        <AgentSidePanel
          selected={selectedAgent}
          onSelect={setSelectedAgent}
          lang={lang}
          setLang={setLang}
          theme={theme}
          setTheme={setTheme}
        />

        {/* Center timeline */}
        <main className="flex-1 flex flex-col min-w-0">
          <div className="px-4 py-2 border-b border-slate-200 dark:border-slate-700 bg-white/70 dark:bg-slate-900/60 backdrop-blur-sm flex items-center justify-between shrink-0">
            <div className="flex items-center gap-2">
              <Activity className="size-3.5 text-slate-500 dark:text-slate-500" />
              <span className="uppercase tracking-wider text-slate-500 dark:text-slate-500" style={{ fontSize: 10 }}>
                {t("실행 타임라인", "Execution Timeline")}
              </span>
              <span className="font-mono text-slate-400 dark:text-slate-500" style={{ fontSize: 11 }}>
                {timelineEvents.length} {t("이벤트", "events")}
              </span>
            </div>
            <div className="flex items-center gap-1">
              <FilterPill active>{t("전체", "All")}</FilterPill>
              <FilterPill>{t("에이전트", "Agents")}</FilterPill>
              <FilterPill>{t("시스템", "System")}</FilterPill>
              <FilterPill>{t("승인", "Approvals")}</FilterPill>
              <FilterPill>{t("오류", "Errors")}</FilterPill>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto px-4 py-3 relative">
            <div className="absolute left-[22px] top-3 bottom-3 w-px bg-slate-200 dark:bg-slate-700" />
            <div className="space-y-2">
              {timelineEvents.map((e) => (
                <TimelineItem
                  key={e.id}
                  event={e}
                  selected={selectedEventId === e.id}
                  onSelect={() => setSelectedEventId(e.id)}
                  expanded={!!expanded[e.id]}
                  onToggle={() =>
                    setExpanded((s) => ({ ...s, [e.id]: !s[e.id] }))
                  }
                  t={t}
                />
              ))}
            </div>
          </div>

          {/* Operator input */}
          <div className="border-t border-slate-200 dark:border-slate-700 bg-white/60 dark:bg-slate-900/60 backdrop-blur-sm px-4 py-2.5 shrink-0">
            <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 shadow-[0_1px_0_rgba(15,23,42,0.02),0_4px_16px_rgba(15,23,42,0.05)] focus-within:border-indigo-300 focus-within:ring-1 focus-within:ring-indigo-200 flex items-center gap-2 px-2 py-1">
              <span className="font-mono text-slate-400 dark:text-slate-500 px-1" style={{ fontSize: 11 }}>
                operator ›
              </span>
              <input
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                placeholder={t("메모, 변경 요청, 또는 주석을 입력하세요…", "Send a note, request a change, or annotate the run…")}
                className="flex-1 bg-transparent outline-none py-1.5"
                style={{ fontSize: 13 }}
              />
              <button
                className="p-1.5 rounded hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-500"
                title={t("보내기", "Send")}
              >
                <Send className="size-3.5" />
              </button>
            </div>
          </div>
        </main>

        <ArtifactPanel event={selectedEvent} t={t} />
      </div>
    </div>
  );
}

function FilterPill({
  children,
  active,
}: {
  children: React.ReactNode;
  active?: boolean;
}) {
  return (
    <button
      className={`px-2 py-0.5 rounded border ${
        active
          ? "bg-indigo-600 text-white border-indigo-600"
          : "bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-500 border-slate-200 dark:border-slate-700 hover:border-slate-300 dark:hover:border-slate-600 dark:border-slate-600"
      }`}
      style={{ fontSize: 11 }}
    >
      {children}
    </button>
  );
}
