import { useQueryClient } from "@tanstack/react-query";
import { ClipboardCopy, Import, Loader2, Plus, Printer } from "lucide-react";
import { Fragment, useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, thumbnailUrl } from "@/api/client";
import { useCollectionDiary, useCollectionStories, useConnection } from "@/api/hooks";
import type { CollectionItem, DiaryDay } from "@/api/types";
import { Button } from "@/components/ui/button";
import { placeName } from "@/lib/places";
import { cn } from "@/lib/utils";

/** Only the diary is printed (print it, or save it as PDF from the print dialog). */
const PRINT_CSS = `
@media print {
  body * { visibility: hidden !important; }
  .diary-print, .diary-print * { visibility: visible !important; }
  .diary-print { position: absolute; inset: 0 auto auto 0; width: 100%; color: #111; background: #fff; }
  .diary-print .no-print { display: none !important; }
  .diary-print section { break-inside: auto; }
  .diary-print figure { break-inside: avoid; }
}`;

/**
 * A portfolio as a travel diary: day after day its photos with their captions, and the
 * user's text opening each day and between photos. Saved as it is written.
 */
export function DiaryView({
  collectionId,
  name,
  items,
  onOpen,
}: {
  collectionId: number;
  name: string;
  items: CollectionItem[];
  onOpen: (assetId: number) => void;
}) {
  const { t, i18n } = useTranslation();
  const conn = useConnection();
  const queryClient = useQueryClient();
  const diary = useCollectionDiary(collectionId);
  const stories = useCollectionStories(collectionId);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const byId = new Map(items.map((item) => [item.asset.id, item]));
  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: ["library", "collections", collectionId, "diary"] });

  const save = (day: string, after: number | null, text: string) => {
    if (!conn) return;
    void api
      .writeCollectionDiary(conn, collectionId, { day, after_asset_id: after, text })
      .then(refresh)
      .catch((reason: unknown) =>
        setError(reason instanceof Error ? reason.message : String(reason)),
      );
  };
  const withNotes = stories.data?.find(
    (story) => ((story.data as { days?: unknown[] } | null)?.days?.length ?? 0) > 0,
  );
  const importNotes = () => {
    if (!conn || !withNotes) return;
    void api.importDiaryNotes(conn, collectionId, withNotes.id).then(refresh);
  };

  const dateLabel = (day: DiaryDay) =>
    day.date
      ? new Intl.DateTimeFormat(i18n.language, { dateStyle: "full" }).format(
          new Date(`${day.date}T12:00:00`),
        )
      : t("collections.noDate");
  const places = (day: DiaryDay) => day.places.map((p) => placeName(p, i18n.language)).join(" → ");
  const heading = (day: DiaryDay) =>
    [t("collections.routeDay", { day: day.number }), dateLabel(day), places(day)]
      .filter(Boolean)
      .join(" · ");

  const markdown = () =>
    [
      `# ${name}`,
      ...(diary.data?.days ?? []).map((day) => {
        const notes = new Map(day.notes.map((note) => [note.after_asset_id, note.text]));
        const parts = [`## ${heading(day)}`];
        if (day.intro) parts.push(day.intro);
        for (const assetId of day.asset_ids) {
          const caption = byId.get(assetId)?.caption;
          if (caption) parts.push(`- ${caption}`);
          const note = notes.get(assetId);
          if (note) parts.push(note);
        }
        return parts.join("\n\n");
      }),
    ].join("\n\n");
  const copy = () =>
    void navigator.clipboard?.writeText(markdown()).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });

  if (!diary.data) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center">
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      </div>
    );
  }
  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <style>{PRINT_CSS}</style>
      <div className="flex flex-wrap items-center gap-2 border-b border-white/5 px-6 py-2 text-[12px]">
        <span className="text-muted-foreground">{t("collections.diaryHint")}</span>
        <div className="ml-auto flex flex-wrap gap-1">
          {withNotes && (
            <Button variant="ghost" size="sm" onClick={importNotes}>
              <Import /> {t("collections.diaryImport")}
            </Button>
          )}
          <Button variant="ghost" size="sm" onClick={copy}>
            <ClipboardCopy /> {copied ? t("collections.storyCopied") : t("collections.diaryCopy")}
          </Button>
          <Button variant="ghost" size="sm" onClick={() => window.print()}>
            <Printer /> {t("collections.diaryPrint")}
          </Button>
        </div>
        {error && (
          <p role="alert" className="basis-full text-destructive">
            {error}
          </p>
        )}
      </div>

      <div className="diary-print mx-auto max-w-4xl space-y-10 px-6 py-6">
        <h1 className="hidden text-2xl font-semibold print:block">{name}</h1>
        {diary.data.days.length === 0 && (
          <p className="text-[13px] text-muted-foreground">{t("collections.emptyOne")}</p>
        )}
        {diary.data.days.map((day) => {
          const notes = new Map(day.notes.map((note) => [note.after_asset_id, note.text]));
          // Photos in runs, cut where a text follows a photo.
          const runs: number[][] = [[]];
          for (const assetId of day.asset_ids) {
            runs[runs.length - 1]!.push(assetId);
            if (notes.has(assetId)) runs.push([]);
          }
          return (
            <section key={day.date} aria-label={heading(day)} className="space-y-4">
              <header className="flex items-baseline gap-3 border-b border-white/10 pb-2">
                <span className="text-[22px] font-semibold text-highlight">
                  {t("collections.routeDay", { day: day.number })}
                </span>
                <span className="text-[13px] text-muted-foreground">
                  {dateLabel(day)}
                  {places(day) && ` · ${places(day)}`}
                </span>
              </header>
              <DiaryText
                key={`intro:${day.intro ?? ""}`}
                label={t("collections.diaryIntro", { day: day.number })}
                value={day.intro ?? ""}
                placeholder={t("collections.diaryIntroPlaceholder")}
                onSave={(text) => save(day.date, null, text)}
                large
              />
              {runs.map((run, index) => (
                <Fragment key={run[0] ?? index}>
                  {run.length > 0 && (
                    <div className="flex flex-wrap gap-2 after:grow-[10] after:content-['']">
                      {run.map((assetId) => {
                        const item = byId.get(assetId);
                        if (!item || !conn) return null;
                        const ratio =
                          item.asset.width && item.asset.height
                            ? Math.min(Math.max(item.asset.width / item.asset.height, 0.5), 2.5)
                            : 4 / 3;
                        const last = assetId === run[run.length - 1];
                        return (
                          <figure
                            key={assetId}
                            style={{ flexGrow: ratio, flexBasis: `${Math.round(ratio * 160)}px` }}
                            className="group relative"
                          >
                            <button
                              type="button"
                              aria-label={item.asset.file_name}
                              onClick={() => onOpen(assetId)}
                              style={{ aspectRatio: ratio }}
                              className="block w-full overflow-hidden rounded-md bg-black/40"
                            >
                              <img
                                src={thumbnailUrl(conn, assetId, item.asset.rendition_version)}
                                alt=""
                                loading="lazy"
                                className="size-full object-cover"
                              />
                            </button>
                            {item.caption && (
                              <figcaption className="mt-1 text-[11.5px] leading-snug text-muted-foreground">
                                {item.caption}
                              </figcaption>
                            )}
                            {!notes.has(assetId) && (
                              <AddText
                                label={t("collections.diaryAdd", { name: item.asset.file_name })}
                                onAdd={(text) => save(day.date, assetId, text)}
                                visible={last}
                              />
                            )}
                          </figure>
                        );
                      })}
                    </div>
                  )}
                  {index < runs.length - 1 && run.length > 0 && (
                    <DiaryText
                      key={`${run[run.length - 1]}:${notes.get(run[run.length - 1]!) ?? ""}`}
                      label={t("collections.diaryAfter", {
                        name: byId.get(run[run.length - 1]!)?.asset.file_name ?? "",
                      })}
                      value={notes.get(run[run.length - 1]!) ?? ""}
                      placeholder={t("collections.diaryNotePlaceholder")}
                      onSave={(text) => save(day.date, run[run.length - 1]!, text)}
                    />
                  )}
                </Fragment>
              ))}
            </section>
          );
        })}
      </div>
    </div>
  );
}

/** A text of the diary, saved when it loses the focus; grows with its content. */
function DiaryText({
  label,
  value,
  placeholder,
  onSave,
  large = false,
  autoFocus = false,
}: {
  label: string;
  value: string;
  placeholder: string;
  onSave: (text: string) => void;
  large?: boolean;
  autoFocus?: boolean;
}) {
  const [text, setText] = useState(value);
  const ref = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    const area = ref.current;
    if (!area) return;
    area.style.height = "auto";
    area.style.height = `${area.scrollHeight}px`;
  }, [text]);
  return (
    <textarea
      ref={ref}
      aria-label={label}
      value={text}
      rows={large ? 2 : 1}
      autoFocus={autoFocus}
      placeholder={placeholder}
      onChange={(event) => setText(event.target.value)}
      onBlur={() => {
        if (text.trim() !== value.trim()) onSave(text);
      }}
      className={cn(
        "w-full resize-none rounded-md border border-transparent bg-transparent px-2 py-1.5 leading-relaxed outline-none placeholder:text-subtle-foreground hover:border-white/10 focus:border-input focus:bg-background/40 print:border-none print:placeholder:text-transparent",
        large ? "text-[14.5px]" : "text-[13.5px]",
      )}
    />
  );
}

/** "+" after a photo: opens a text there. */
function AddText({
  label,
  onAdd,
  visible,
}: {
  label: string;
  onAdd: (text: string) => void;
  visible: boolean;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  if (open) {
    return (
      <div className="no-print absolute inset-x-0 top-full z-10 mt-1 min-w-56 rounded-md border bg-popover p-1 shadow-lg">
        <DiaryText
          label={label}
          value=""
          placeholder={t("collections.diaryNotePlaceholder")}
          autoFocus
          onSave={(text) => {
            setOpen(false);
            if (text.trim()) onAdd(text);
          }}
        />
      </div>
    );
  }
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={() => setOpen(true)}
      className={cn(
        "no-print absolute -right-1.5 top-1/2 flex size-6 -translate-y-1/2 items-center justify-center rounded-full border border-white/20 bg-background text-muted-foreground shadow transition-opacity hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100",
        visible ? "opacity-60" : "opacity-0",
      )}
    >
      <Plus className="size-3.5" />
    </button>
  );
}
