import { useQuery } from "@tanstack/react-query";

import { api, originalUrl, playbackUrl } from "@/api/client";
import { useConnection, useTask } from "@/api/hooks";
import type { AssetDetail } from "@/api/types";

export interface Playback {
  /** What the video element plays; null while the copy is being made. */
  src: string | null;
  /** 0..1 while the copy is being made. */
  progress: number | null;
  error: string | null;
}

/**
 * The source a video plays from: the original when the web view can play it, else its
 * converted copy, made on first play (AVI, MTS, WMV, MPEG...).
 */
export function usePlayback(detail: AssetDetail | undefined): Playback {
  const conn = useConnection();
  const needed = !!detail && detail.media_type === "video" && !!detail.needs_playback_copy;
  const state = useQuery({
    queryKey: ["playback", detail?.id ?? 0],
    queryFn: () => api.getPlaybackState(conn!, detail!.id, true),
    enabled: !!conn && needed,
    refetchInterval: (query) => (query.state.data?.ready ? false : 1500),
  });
  const task = useTask(state.data?.task_id ?? null);
  if (!conn || !detail) return { src: null, progress: null, error: null };
  const version = detail.rendition_version ?? "";
  if (!needed) return { src: originalUrl(conn, detail.id, version), progress: null, error: null };
  if (state.data?.ready) {
    return { src: playbackUrl(conn, detail.id, version), progress: null, error: null };
  }
  const failed = task.data?.status === "failed" ? (task.data.error ?? "") : null;
  const error = state.error ? state.error.message : failed;
  const total = task.data?.progress_total;
  return {
    src: null,
    progress: total ? (task.data?.progress_current ?? 0) / total : 0,
    error,
  };
}
