import { Loader2, MapPin, MapPinned, Plus, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import { useMapWebActions, useMapWebPlan } from "@/api/hooks";
import { mapWebError } from "@/components/settings/MapWebSettings";
import { Button } from "@/components/ui/button";
import { useLibraryState, type MapSendRequest } from "@/library/state";
import { formatDateTime } from "@/lib/format";

const SHOWN = 6;
/** More photos than this: suggest picking the best ones first. */
const MANY = 300;

/** Send photos to MapWeb: what goes where on the map, then a background task. */
export function MapSendDialog({ onOpenSettings }: { onOpenSettings: () => void }) {
  const { mapSendRequest, closeMapSend } = useLibraryState();
  if (!mapSendRequest) return null;
  return (
    <Body
      key={mapSendRequest.nonce}
      request={mapSendRequest}
      onClose={closeMapSend}
      onOpenSettings={() => {
        closeMapSend();
        onOpenSettings();
      }}
    />
  );
}

function Body({
  request,
  onClose,
  onOpenSettings,
}: {
  request: MapSendRequest;
  onClose: () => void;
  onOpenSettings: () => void;
}) {
  const { t, i18n } = useTranslation();
  const rootRef = useRef<HTMLDivElement>(null);
  const plan = useMapWebPlan(request.assetIds, i18n.language);
  const { send } = useMapWebActions();
  const [started, setStarted] = useState(false);
  useEffect(() => rootRef.current?.focus(), []);

  const data = plan.data;
  const attached = data?.attach.reduce((sum, item) => sum + item.count, 0) ?? 0;
  const grouped = data?.groups.reduce((sum, item) => sum + item.count, 0) ?? 0;
  const total = attached + grouped;
  const notConfigured =
    plan.error instanceof ApiError && plan.error.code === "mapweb_not_configured";

  const start = () =>
    send.mutate(
      {
        asset_ids: request.assetIds,
        language: i18n.language,
        description: request.description,
      },
      { onSuccess: () => setStarted(true) },
    );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6">
      <div
        ref={rootRef}
        role="dialog"
        aria-modal
        aria-label={t("mapweb.send")}
        tabIndex={-1}
        onKeyDown={(event) => {
          if (event.key === "Escape") onClose();
          event.stopPropagation();
        }}
        className="flex max-h-full w-[520px] max-w-full flex-col rounded-lg border bg-popover shadow-xl outline-none"
      >
        <div className="flex shrink-0 items-center gap-2 border-b px-5 py-3">
          <MapPinned className="size-4 text-muted-foreground" />
          <h2 className="text-[14px] font-medium">{t("mapweb.send")}</h2>
          <span className="text-[12px] text-muted-foreground">
            {t("export.count", { count: request.assetIds.length })}
          </span>
          <Button
            variant="ghost"
            size="icon-sm"
            className="ml-auto"
            aria-label={t("export.close")}
            onClick={onClose}
          >
            <X />
          </Button>
        </div>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4 text-[12.5px]">
          {plan.isPending && (
            <p role="status" className="flex items-center gap-2 text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
              {t("mapweb.planning")}
            </p>
          )}
          {notConfigured && (
            <div className="space-y-2">
              <p className="text-muted-foreground">{t("mapweb.notConfigured")}</p>
              <Button size="sm" variant="secondary" onClick={onOpenSettings}>
                {t("mapweb.openSettings")}
              </Button>
            </div>
          )}
          {plan.error && !notConfigured && (
            <p role="alert" className="select-text text-destructive">
              {mapWebError(plan.error, t)}
            </p>
          )}

          {data && !started && (
            <>
              <p className="text-muted-foreground">
                {t("mapweb.to", { url: data.url })}
              </p>
              {data.attach.length > 0 && (
                <section>
                  <h3 className="mb-1.5 flex items-center gap-1.5 font-medium">
                    <MapPin className="size-3.5 text-muted-foreground" />
                    {t("mapweb.attach", { count: attached, points: data.attach.length })}
                  </h3>
                  <ul className="space-y-1 pl-5 text-muted-foreground">
                    {data.attach.slice(0, SHOWN).map((item) => (
                      <li key={item.point_id} className="flex gap-2">
                        <span className="min-w-0 flex-1 truncate text-foreground">{item.title}</span>
                        {item.visited_at && (
                          <span>{formatDateTime(item.visited_at, i18n.language)}</span>
                        )}
                        <span>+{item.count}</span>
                      </li>
                    ))}
                    {data.attach.length > SHOWN && (
                      <li>{t("mapweb.more", { count: data.attach.length - SHOWN })}</li>
                    )}
                  </ul>
                </section>
              )}
              {data.groups.length > 0 && (
                <section>
                  <h3 className="mb-1.5 flex items-center gap-1.5 font-medium">
                    <Plus className="size-3.5 text-muted-foreground" />
                    {t("mapweb.groups", { count: grouped, points: data.groups.length })}
                  </h3>
                  <ul className="space-y-1 pl-5 text-muted-foreground">
                    {data.groups.slice(0, SHOWN).map((group, index) => (
                      <li key={index} className="flex gap-2">
                        <span className="min-w-0 flex-1 truncate text-foreground">{group.title}</span>
                        <span>{t("collections.count", { count: group.count })}</span>
                      </li>
                    ))}
                    {data.groups.length > SHOWN && (
                      <li>{t("mapweb.more", { count: data.groups.length - SHOWN })}</li>
                    )}
                  </ul>
                </section>
              )}
              <ul className="space-y-0.5 text-[12px] text-muted-foreground">
                {data.duplicate_count > 0 && (
                  <li>{t("mapweb.duplicates", { count: data.duplicate_count })}</li>
                )}
                {data.unplaced_count > 0 && (
                  <li>{t("mapweb.unplaced", { count: data.unplaced_count })}</li>
                )}
                {data.video_count > 0 && (
                  <li>{t("mapweb.videos", { count: data.video_count })}</li>
                )}
              </ul>
              {total === 0 && <p className="text-muted-foreground">{t("mapweb.nothing")}</p>}
              {total > MANY && <p className="text-warning">{t("mapweb.many", { count: total })}</p>}
              <p className="text-[11.5px] leading-relaxed text-subtle-foreground">
                {t("mapweb.note")}
              </p>
            </>
          )}

          {started && (
            <p role="status" className="text-muted-foreground">
              {t("mapweb.started", { count: total })}
            </p>
          )}
          {send.error && (
            <p role="alert" className="select-text text-destructive">
              {mapWebError(send.error, t)}
            </p>
          )}
        </div>

        <div className="flex shrink-0 justify-end gap-2 border-t px-5 py-3">
          <Button variant="ghost" size="sm" onClick={onClose}>
            {started ? t("export.close") : t("export.cancel")}
          </Button>
          {!started && (
            <Button size="sm" disabled={total === 0 || send.isPending} onClick={start}>
              <MapPinned className="size-3.5" />
              {t("mapweb.start", { count: total })}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
