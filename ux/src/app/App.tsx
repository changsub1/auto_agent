import { useState } from "react";
import { AgentRosterPage } from "./components/agent-roster-page";
import { RunMonitorPage } from "./components/run-monitor-page";

export default function App() {
  const [page, setPage] = useState<"roster" | "monitor">("roster");
  const [lang, setLang] = useState<"ko" | "en">("ko");
  const [theme, setTheme] = useState<"light" | "dark">("light");

  return (
    <div className={`size-full ${theme === "dark" ? "dark" : ""}`}>
      {page === "roster" ? (
        <AgentRosterPage
          onStartRun={() => setPage("monitor")}
          lang={lang}
          setLang={setLang}
          theme={theme}
          setTheme={setTheme}
        />
      ) : (
        <RunMonitorPage
          onBack={() => setPage("roster")}
          lang={lang}
          setLang={setLang}
          theme={theme}
          setTheme={setTheme}
        />
      )}
    </div>
  );
}
