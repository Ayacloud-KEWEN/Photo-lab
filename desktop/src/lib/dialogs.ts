import { isTauri } from "@tauri-apps/api/core";
import { confirm as tauriConfirm, open } from "@tauri-apps/plugin-dialog";

/** Show the native Windows folder picker. Resolves to `null` when cancelled. */
export async function pickDirectory(title: string): Promise<string | null> {
  if (isTauri()) {
    const selected = await open({ directory: true, multiple: false, recursive: false, title });
    return typeof selected === "string" ? selected : null;
  }
  // Browser-only development fallback.
  const typed = window.prompt(title);
  return typed?.trim() || null;
}

export async function confirmAction(
  message: string,
  options: { title: string; okLabel: string; cancelLabel: string },
): Promise<boolean> {
  if (isTauri()) {
    return tauriConfirm(message, { ...options, kind: "warning" });
  }
  return window.confirm(message);
}
