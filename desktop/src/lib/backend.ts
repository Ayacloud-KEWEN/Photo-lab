import { invoke, isTauri } from "@tauri-apps/api/core";

/** Mirrors `BackendStatus` in src-tauri/src/backend.rs. */
export type BackendStatus =
  | { state: "starting" }
  | { state: "ready"; baseUrl: string; token: string }
  | { state: "failed"; message: string };

/**
 * Ask the desktop shell how to reach the Python backend.
 *
 * Outside Tauri (plain `npm run dev` in a browser) the connection comes from
 * VITE_LUMEN_API_URL / VITE_LUMEN_API_TOKEN, for UI development only.
 */
export async function fetchBackendStatus(): Promise<BackendStatus> {
  if (isTauri()) {
    return invoke<BackendStatus>("backend_status");
  }
  const baseUrl = import.meta.env.VITE_LUMEN_API_URL as string | undefined;
  const token = import.meta.env.VITE_LUMEN_API_TOKEN as string | undefined;
  if (import.meta.env.DEV && baseUrl && token) {
    return { state: "ready", baseUrl: baseUrl.replace(/\/$/, ""), token };
  }
  return {
    state: "failed",
    message: "Not running in the desktop shell (VITE_LUMEN_API_URL / VITE_LUMEN_API_TOKEN unset)",
  };
}
