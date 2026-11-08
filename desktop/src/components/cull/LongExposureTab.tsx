import { ImageOff, Loader2, Waves } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, api, thumbnailUrl } from "@/api/client";
import {
  useConnection,
  useEditActions,
  useLongExposureCandidates,
  useRefreshLibraryLists,
} from "@/api/hooks";
import type { AssetSummary } from "@/api/types";
import { Button } from "@/components/ui/button";
import { normalizeRecipe } from "@/components/develop/recipe";
import { useLibraryState } from "@/library/state";

const PAGE = 40;

/**
 * Live Photos whose scene suits a long exposure (water, traffic at night, fireworks...),
 * found by the local AI. One click turns a photo into its long exposure (an edit: the
 * original stays, and it can be undone in Develop).
 */
export function LongExposureTab() {
  const { t } = useTranslation();
  const candidates = useLongExposureCandidates();
  const [shown, setShown] = useState(PAGE);
  const { openViewer } = useLibraryState();
  const items = candidates.data?.items ?? [];
  const visible = items.slice(0, shown);
  const notReady =
    candidates.error instanceof ApiError && candidates.error.code === "ai_not_ready";

  return (
    <section>
      <p className="mb-4 max-w-3xl text-[12px] leading-relaxed text-muted-foreground">
        {t("cull.longExposureHint")}
      </p>
      {candidates.isPending && (
        <p className="flex items-center gap-2 text-[13px] text-muted-foreground">
          <Loader2 className="size-4 animate-spin" /> {t("cull.longExposureFinding")}
        </p>
      )}
      {notReady && (
        <p className="text-[13px] text-muted-foreground">{t("cull.longExposureNoAi")}</p>
      )}
      {candidates.isError && !notReady && (
        <p className="text-[13px] text-destructive">{String(candidates.error)}</p>
      )}
      {candidates.data && items.length === 0 && (
        <p className="text-[13px] text-muted-foreground">{t("cull.longExposureNone")}</p>
      )}
      <div className="flex flex-wrap gap-2">
        {visible.map((asset) => (
          <Candidate
            key={asset.id}
            asset={asset}
            onOpen={() =>
              openViewer(
                visible.map((item) => item.id),
                asset.id,
              )
            }
          />
        ))}
      </div>
      {items.length > shown && (
        <Button className="mt-4" size="sm" variant="secondary" onClick={() => setShown(shown + PAGE)}>
          {t("cull.more", { count: items.length - shown })}
        </Button>
      )}
    </section>
  );
}

function Candidate({ asset, onOpen }: { asset: AssetSummary; onOpen: () => void }) {
  const { t } = useTranslation();
  const conn = useConnection();
  const actions = useEditActions();
  const refresh = useRefreshLibraryLists();
  const [failed, setFailed] = useState(false);
  const [state, setState] = useState<"idle" | "busy" | "error">("idle");
  const ratio = asset.width && asset.height ? asset.width / asset.height : 1.33;

  const makeLongExposure = async () => {
    if (!conn) return;
    setState("busy");
    try {
      const current = await api.getEdit(conn, asset.id);
      await actions.save(asset.id, {
        ...normalizeRecipe(current.recipe),
        live_effect: "long_exposure",
      });
      void refresh();
    } catch (error) {
      console.warn("long exposure failed", error);
      setState("error");
    }
  };

  return (
    <figure
      className="group relative h-40 overflow-hidden rounded-md bg-black"
      style={{ width: `${Math.round(160 * Math.min(Math.max(ratio, 0.6), 1.8))}px` }}
    >
      <button type="button" aria-label={asset.file_name} onClick={onOpen} className="size-full">
        {conn && !failed ? (
          <img
            src={thumbnailUrl(conn, asset.id, asset.rendition_version)}
            alt=""
            loading="lazy"
            draggable={false}
            onError={() => setFailed(true)}
            className="size-full object-cover"
          />
        ) : (
          <span className="flex size-full items-center justify-center bg-card text-subtle-foreground">
            <ImageOff className="size-6" />
          </span>
        )}
      </button>
      <span className="absolute inset-x-1 bottom-1 flex justify-end">
        <Button
          size="sm"
          variant="secondary"
          disabled={state === "busy"}
          onClick={() => void makeLongExposure()}
          className="h-6 px-2 text-[11px] opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100 data-[busy=true]:opacity-100"
          data-busy={state !== "idle"}
        >
          {state === "busy" ? <Loader2 className="size-3 animate-spin" /> : <Waves className="size-3" />}
          {state === "error" ? t("cull.longExposureFailed") : t("cull.longExposureMake")}
        </Button>
      </span>
    </figure>
  );
}
