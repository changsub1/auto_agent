import { useCallback, useEffect, useState } from "react";
import { AppConfig, RunSummary, createRun, listRuns, loadConfig } from "./api";
import { AgentRosterPage } from "./components/agent-roster-page";
import { RunMonitorPage } from "./components/run-monitor-page";

export default function App() {
  const [page, setPage] = useState<"roster" | "monitor">("roster");
  const [lang, setLang] = useState<"ko" | "en">("ko");
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshRuns = useCallback(async () => {
    const nextRuns = await listRuns();
    setRuns(nextRuns);
    if (!activeRunId && nextRuns.length > 0) {
      setActiveRunId(nextRuns[0].run_id);
    }
  }, [activeRunId]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [nextConfig, nextRuns] = await Promise.all([loadConfig(), listRuns()]);
        if (cancelled) return;
        setConfig(nextConfig);
        setRuns(nextRuns);
        if (nextRuns.length > 0) {
          setActiveRunId(nextRuns[0].run_id);
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleStartRun(
    prompt: string,
    routingMode: string,
    options?: { plannerCount?: number; codeAgentCount?: number; qaAgentCount?: number },
  ) {
    setLoading(true);
    setError(null);
    try {
      const detail = await createRun({
        user_request: prompt,
        routing_mode: routingMode,
        dashboard_mode: "planning_only",
        planner_count: options?.plannerCount ?? config?.defaults.planner_count,
        code_agent_count: options?.codeAgentCount ?? config?.defaults.code_agent_count,
        qa_agent_count: options?.qaAgentCount ?? config?.defaults.qa_agent_count,
        model: config?.defaults.model,
        reasoning_effort: config?.defaults.reasoning_effort,
        timeout_seconds: config?.defaults.timeout_seconds,
        max_fix_iterations: config?.defaults.max_fix_iterations,
      });
      setActiveRunId(detail.run_id);
      await refreshRuns();
      setPage("monitor");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className={`size-full ${theme === "dark" ? "dark" : ""}`}>
      {page === "roster" ? (
        <AgentRosterPage
          onStartRun={handleStartRun}
          onOpenRun={(runId) => {
            setActiveRunId(runId);
            setPage("monitor");
          }}
          config={config}
          runs={runs}
          loading={loading}
          error={error}
          lang={lang}
          setLang={setLang}
          theme={theme}
          setTheme={setTheme}
        />
      ) : (
        <RunMonitorPage
          onBack={() => setPage("roster")}
          runId={activeRunId}
          onRefreshRuns={refreshRuns}
          lang={lang}
          setLang={setLang}
          theme={theme}
          setTheme={setTheme}
        />
      )}
    </div>
  );
}
