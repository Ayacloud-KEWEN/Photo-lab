import { useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Loader2, ScanText } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { useVlmActions } from "@/api/hooks";
import type { AssetDetail } from "@/api/types";
import { Button } from "@/components/ui/button";

const POLL_MS = 4000;
const POLL_LIMIT_MS = 15 * 60 * 1000;

/**
 * What the local vision model saw in a photo and the text it read there, marked as
 * machine-written. The photo can be read (again), or read with the careful model.
 */
export function PhotoDescription({ asset }: { asset: AssetDetail }) {
  const { t } = useTranslation();
  const { describe } = useVlmActions();
  const queryClient = useQueryClient();
  const [waitingSince, setWaitingSince] = useState<string | null | undefined>(undefined);
  const [copied, setCopied] = useState(false);
  const description = asset.description ?? null;

  // After asking, refresh the photo until its description changes.
  const waiting = waitingSince !== undefined && (description?.created_at ?? null) === waitingSince;
  useEffect(() => {
    if (!waiting) return;
    const started = Date.now();
    const timer = window.setInterval(() => {
      if (Date.now() - started > POLL_LIMIT_MS) window.clearInterval(timer);
      void queryClient.invalidateQueries({ queryKey: ["library", "asset", asset.id] });
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [waiting, asset.id, queryClient]);
  useEffect(() => setWaitingSince(undefined), [asset.id]);

  if (asset.media_type !== "photo") return null;
  const ask = (fine: boolean) =>
    describe.mutate(
      { ids: [asset.id], fine },
      { onSuccess: () => setWaitingSince(description?.created_at ?? null) },
    );
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(description?.text ?? "");
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard refused: nothing to do.
    }
  };

  return (
    <section aria-label={t("vlm.title")} className="space-y-2 border-b pb-3 text-[12.5px]">
      <div className="flex items-center gap-1.5 text-[11px] text-subtle-foreground">
        <ScanText className="size-3" />
        {t("vlm.title")}
      </div>
      {description ? (
        description.description || description.text ? (
          <>
            {description.description && (
              <p className="select-text leading-relaxed">{description.description}</p>
            )}
            {description.text && (
              <div className="relative rounded border bg-card px-2 py-1.5">
                <span className="mb-1 block text-[10.5px] text-subtle-foreground">
                  {t("vlm.textInPhoto")}
                </span>
                <p className="select-text whitespace-pre-wrap break-words font-mono text-[11.5px] leading-relaxed">
                  {description.text}
                </p>
                <button
                  type="button"
                  aria-label={t("vlm.copyText")}
                  title={t("vlm.copyText")}
                  onClick={() => void copy()}
                  className="absolute right-1 top-1 rounded p-1 text-muted-foreground hover:bg-white/10"
                >
                  {copied ? <Check className="size-3" /> : <Copy className="size-3" />}
                </button>
              </div>
            )}
            {description.keywords.length > 0 && (
              <p className="text-[11.5px] text-muted-foreground">{description.keywords.join(" · ")}</p>
            )}
          </>
        ) : (
          <p className="text-muted-foreground">{t("vlm.unreadable")}</p>
        )
      ) : (
        <p className="text-muted-foreground">{t("vlm.notRead")}</p>
      )}
      {description && (
        <p className="text-[10.5px] text-subtle-foreground">
          {t("vlm.byModel", { model: description.model_label })}
          {description.truncated && ` · ${t("vlm.truncated")}`}
        </p>
      )}
      <div className="flex items-center gap-1">
        {waiting ? (
          <span role="status" className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 className="size-3.5 animate-spin" />
            {t("vlm.queued")}
          </span>
        ) : (
          <>
            <Button size="sm" variant="ghost" disabled={describe.isPending} onClick={() => ask(false)}>
              {description ? t("vlm.readAgain") : t("vlm.read")}
            </Button>
            <Button size="sm" variant="ghost" disabled={describe.isPending} onClick={() => ask(true)}>
              {t("vlm.readFine")}
            </Button>
          </>
        )}
      </div>
    </section>
  );
}
