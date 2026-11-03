import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { fetchBackendStatus, type BackendStatus } from "@/lib/backend";

const POLL_INTERVAL_MS = 250;
const STARTUP_TIMEOUT_MS = 30_000;

const BackendContext = createContext<BackendStatus>({ state: "starting" });

/** Waits for the desktop shell to report the backend as ready (or failed). */
export function BackendProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<BackendStatus>({ state: "starting" });

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const deadline = Date.now() + STARTUP_TIMEOUT_MS;

    const poll = async () => {
      let next: BackendStatus;
      try {
        next = await fetchBackendStatus();
      } catch (error) {
        next = { state: "failed", message: String(error) };
      }
      if (cancelled) return;
      if (next.state === "starting" && Date.now() > deadline) {
        next = { state: "failed", message: "Timed out waiting for the backend to start" };
      }
      setStatus(next);
      if (next.state === "starting") timer = setTimeout(poll, POLL_INTERVAL_MS);
    };

    void poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, []);

  return <BackendContext.Provider value={status}>{children}</BackendContext.Provider>;
}

/** For tests and stories: provide a fixed backend status. */
export const StaticBackendProvider = BackendContext.Provider;

export function useBackendStatus(): BackendStatus {
  return useContext(BackendContext);
}
