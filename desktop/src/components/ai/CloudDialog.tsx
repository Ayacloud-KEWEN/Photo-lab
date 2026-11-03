import { Cloud, Loader2, Sparkles, Trophy, X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import Markdown from "react-markdown";

import { ApiError, thumbnailUrl } from "@/api/client";
import { useCloudAnalyze, useCloudPreview, useConnection, useSettings } from "@/api/hooks";
import type { AnalysisResult, CloudPreview, CloudRequest } from "@/api/types";
import { Button } from "@/components/ui/button";
import { useLibraryState, type CloudDialogRequest } from "@/library/state";
import { cn } from "@/lib/utils";

/**
 * Consent-first cloud analysis: shows exactly what will be uploaded (images, fields,
 * destination), sends only after "Send", then shows the result.
 */
export function CloudDialog({ onOpenSettings }: { onOpenSettings: () => void }) {
  const { cloudRequest, closeCloud } = useLibraryState();
  if (!cloudRequest) return null;
  return (
    <CloudDialogBody
      key={cloudRequest.nonce}
      request={cloudRequest}
      onClose={closeCloud}
      onOpenSettings={() => {
        closeCloud();
        onOpenSettings();
      }}
    />
  );
}

function CloudDialogBody({
  request,
  onClose,
  onOpenSettings,
}: {
  request: CloudDialogRequest;
  onClose: () => void;
  onOpenSettings: () => void;
}) {
  const { t, i18n } = useTranslation();
  const conn = useConnection();
  const settings = useSettings();
  const preview = useCloudPreview();
  const analyze = useCloudAnalyze();
  const rootRef = useRef<HTMLDivElement>(null);
  const [includeLocation, setIncludeLocation] = useState<boolean | null>(null);
  const [textOnly, setTextOnly] = useState(false);
  const location = includeLocation ?? settings.data?.cloud_include_location ?? false;
  const language = (["zh-CN", "en", "fr"].includes(i18n.language) ? i18n.language : "zh-CN") as CloudRequest["language"];

  const body: CloudRequest = {
    kind: request.kind,
    asset_ids: request.assetIds,
    include_location: location,
    text_only: textOnly,
    language,
  };
  const { mutate: loadPreview } = preview;
  useEffect(() => {
    if (settings.data) loadPreview(body);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- body is derived from these
  }, [settings.data, location, textOnly, language, loadPreview]);
  useEffect(() => rootRef.current?.focus(), []);

  const error = analyze.error ?? preview.error;
  const code = error instanceof ApiError ? error.code : null;

  let content: ReactNode;
  if (code === "cloud_not_configured") {
    content = (
      <Notice>
        <p>{t("cloud.notConfigured")}</p>
        <Button size="sm" variant="secondary" onClick={onOpenSettings}>
          {t("cloud.openSettings")}
        </Button>
      </Notice>
    );
  } else if (analyze.data) {
    content = <Result result={analyze.data} preview={preview.data} />;
  } else if (analyze.isPending) {
    content = (
      <Notice>
        <Loader2 className="size-5 animate-spin text-highlight" />
        <p>{t("cloud.sending")}</p>
      </Notice>
    );
  } else if (preview.data) {
    content = (
      <PreviewView
        preview={preview.data}
        includeLocation={location}
        onIncludeLocation={setIncludeLocation}
      />
    );
  } else {
    content = (
      <Notice>
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      </Notice>
    );
  }

  const canSend = preview.data && !analyze.data && !analyze.isPending && code !== "cloud_not_configured";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6">
      <div
        ref={rootRef}
        role="dialog"
        aria-modal
        aria-label={t(`cloud.title_${request.kind}`)}
        tabIndex={-1}
        onKeyDown={(event) => {
          event.stopPropagation();
          if (event.key === "Escape" && !analyze.isPending) onClose();
        }}
        className="flex max-h-full w-full max-w-2xl flex-col overflow-hidden rounded-lg border bg-panel shadow-2xl outline-none"
      >
        <header className="flex h-11 shrink-0 items-center gap-2 border-b px-4">
          <Sparkles className="size-4 text-highlight" />
          <h2 className="text-sm font-medium">{t(`cloud.title_${request.kind}`)}</h2>
          <Button
            variant="ghost"
            size="icon-sm"
            className="ml-auto"
            aria-label={t("cloud.close")}
            onClick={onClose}
            disabled={analyze.isPending}
          >
            <X className="size-4" />
          </Button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {content}
          {code === "vision_unsupported" && !textOnly && (
            <div className="mt-4 space-y-2 rounded-md border border-warning/40 bg-warning/10 p-3 text-xs">
              <p>{t("cloud.visionUnsupported")}</p>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => {
                  analyze.reset();
                  setTextOnly(true);
                }}
              >
                {t("cloud.useTextOnly")}
              </Button>
            </div>
          )}
          {error && code !== "vision_unsupported" && code !== "cloud_not_configured" && (
            <p role="alert" className="mt-4 select-text text-xs text-destructive">
              {error.message}
            </p>
          )}
        </div>

        <footer className="flex shrink-0 justify-end gap-2 border-t px-4 py-3">
          {analyze.data ? (
            <Button onClick={onClose}>{t("cloud.close")}</Button>
          ) : (
            <>
              <Button variant="ghost" onClick={onClose} disabled={analyze.isPending}>
                {t("cloud.cancel")}
              </Button>
              <Button disabled={!canSend} onClick={() => conn && analyze.mutate(body)}>
                <Cloud className="size-4" />
                {preview.data?.cached ? t("cloud.showCached") : t("cloud.send")}
              </Button>
            </>
          )}
        </footer>
      </div>
    </div>
  );
}

function PreviewView({
  preview,
  includeLocation,
  onIncludeLocation,
}: {
  preview: CloudPreview;
  includeLocation: boolean;
  onIncludeLocation: (value: boolean) => void;
}) {
  const { t } = useTranslation();
  const conn = useConnection();
  return (
    <div className="space-y-4 text-[13px]">
      <p>{t("cloud.willSend", { host: preview.host, model: preview.model })}</p>
      <p className="text-xs text-muted-foreground">
        {preview.image_max_edge
          ? t("cloud.imagesNote", { count: preview.items.length, edge: preview.image_max_edge })
          : t("cloud.noImages")}
      </p>
      <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {preview.items.map((item) => (
          <li key={item.asset_id} className="flex gap-3 rounded-md border bg-card p-2">
            {conn && preview.image_max_edge ? (
              <img
                src={thumbnailUrl(conn, item.asset_id, item.rendition_version)}
                alt=""
                className="size-16 shrink-0 rounded object-cover"
              />
            ) : null}
            <dl className="min-w-0 text-[11.5px]">
              {Object.entries(item.fields).map(([key, value]) => (
                <div key={key} className="flex gap-1.5">
                  <dt className="shrink-0 text-subtle-foreground">{key}</dt>
                  <dd className="select-text truncate">{value}</dd>
                </div>
              ))}
            </dl>
          </li>
        ))}
      </ul>
      <label className="flex cursor-pointer items-center gap-2 text-xs">
        <input
          type="checkbox"
          checked={includeLocation}
          onChange={(event) => onIncludeLocation(event.target.checked)}
          className="size-3.5 accent-[var(--highlight)]"
        />
        {t("cloud.includeLocation")}
      </label>
      {preview.cached && <p className="text-xs text-success">{t("cloud.cachedNote")}</p>}
    </div>
  );
}

export function Result({ result, preview }: { result: AnalysisResult; preview?: CloudPreview | undefined }) {
  const { t } = useTranslation();
  const conn = useConnection();
  const ranking = (result.data?.ranking as number[] | undefined) ?? [];
  const best = result.data?.best as number | undefined;
  const ordered = ranking.length ? ranking : best ? [best] : [];

  return (
    <div className="space-y-4">
      {ordered.length > 0 && conn && (
        <ol className="flex flex-wrap gap-2">
          {ordered.map((position, index) => {
            const assetId = result.asset_ids[position - 1];
            if (assetId === undefined) return null;
            return (
              <li
                key={position}
                className={cn(
                  "relative overflow-hidden rounded-md border",
                  position === best && "ring-2 ring-warning",
                )}
              >
                <img
                  src={thumbnailUrl(
                    conn,
                    assetId,
                    preview?.items.find((item) => item.asset_id === assetId)?.rendition_version ??
                      String(result.id),
                  )}
                  alt=""
                  className="size-24 object-cover"
                />
                <span className="absolute left-1 top-1 flex items-center gap-1 rounded bg-black/70 px-1.5 py-0.5 text-[10.5px] text-white">
                  {position === best && <Trophy className="size-3 text-warning" />}
                  {position === best ? t("cloud.best") : t("cloud.rank", { n: index + 1 })}
                </span>
              </li>
            );
          })}
        </ol>
      )}
      {!result.vision && (
        <span className="inline-block rounded border border-warning/40 px-1.5 py-0.5 text-[11px] text-warning">
          {t("cloud.textOnlyBadge")}
        </span>
      )}
      <div className="prose-lumen select-text text-[13px] leading-relaxed">
        <Markdown>{result.result}</Markdown>
      </div>
      <p className="text-[11px] text-subtle-foreground">
        {result.provider} · {result.model}
        {result.cached ? ` · ${t("ai.cached")}` : ""}
        {result.input_tokens !== null && result.output_tokens !== null
          ? ` · ${t("cloud.tokens", { input: result.input_tokens, output: result.output_tokens })}`
          : ""}
      </p>
    </div>
  );
}

function Notice({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-10 text-center text-[13px] text-muted-foreground">
      {children}
    </div>
  );
}
