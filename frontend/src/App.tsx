import { useEffect, useState } from "react";

import { getBackendHealth } from "./api";

type BackendState = "checking" | "online" | "offline";

export default function App() {
  const [backendState, setBackendState] = useState<BackendState>("checking");

  useEffect(() => {
    getBackendHealth()
      .then(() => setBackendState("online"))
      .catch(() => setBackendState("offline"));
  }, []);

  return (
    <main className="app-shell">
      <section className="hero">
        <p className="eyebrow">Local-first · AI-assisted</p>
        <h1>Shadowing Video Studio</h1>
        <p className="description">
          Paste an English dialogue, prepare the sentence list, generate speech, and build a
          shadowing video.
        </p>

        <div className="status-card">
          <span>Application shell</span>
          <strong data-state={backendState}>
            {backendState === "checking" && "Checking backend…"}
            {backendState === "online" && "Backend connected"}
            {backendState === "offline" && "Backend unavailable"}
          </strong>
        </div>

        <p className="next-step">
          Bootstrap complete. The next implementation task is the manual sentence editor.
        </p>
      </section>
    </main>
  );
}
