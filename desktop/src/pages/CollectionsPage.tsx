import {
  Album,
  ArrowLeft,
  BookOpen,
  Download,
  ImageIcon,
  Plane,
  Plus,
  Star,
  Trash2,
  X,
} from "lucide-react";
import { useEffect, useState, type DragEvent, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { thumbnailUrl } from "@/api/client";
import {
  useCollection,
  useCollectionActions,
  useCollections,
  useConnection,
  useTripSuggestions,
} from "@/api/hooks";
import type {
  AssetSummary,
  Collection,
  CollectionDetail,
  CollectionItem,
  CollectionUpdate,
  TripSuggestion,
} from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useLibraryState } from "@/library/state";
import { confirmAction } from "@/lib/dialogs";
import { formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Portfolios: albums and trips, each an ordered selection with captions. */
export function CollectionsPage() {
  const [openId, setOpenId] = useState<number | null>(null);
  return openId === null ? (
    <CollectionList onOpen={setOpenId} />
  ) : (
    <CollectionView id={openId} onBack={() => setOpenId(null)} />
  );
}

function dateRange(start: string | null | undefined, end: string | null | undefined, locale: string) {
  if (!start) return "";
  const format = (value: string) =>
    new Intl.DateTimeFormat(locale, { dateStyle: "medium" }).format(new Date(`${value.slice(0, 10)}T12:00:00`));
  const from = format(start);
  const to = end ? format(end) : from;
  return from === to ? from : `${from} – ${to}`;
}

function Thumb({ asset, className }: { asset: AssetSummary; className?: string }) {
  const conn = useConnection();
  if (!conn) return null;
  return (
    <img
      src={thumbnailUrl(conn, asset.id, asset.rendition_version)}
      alt={asset.file_name}
      loading="lazy"
      draggable={false}
      className={cn("size-full object-cover", className)}
    />
  );
}

// --- List ---------------------------------------------------------------------------------

function CollectionList({ onOpen }: { onOpen: (id: number) => void }) {
  const { t, i18n } = useTranslation();
  const collections = useCollections();
  const suggestions = useTripSuggestions();
  const actions = useCollectionActions();
  const [name, setName] = useState("");

  const create = (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    void actions.create({ name: name.trim(), kind: "album" }).then((created) => {
      setName("");
      onOpen(created.id);
    });
  };
  const createTrip = (suggestion: TripSuggestion) =>
    void actions
      .create({
        name: t("collections.tripName", {
          dates: dateRange(suggestion.start_date, suggestion.end_date, i18n.language),
        }),
        kind: "trip",
        start_date: suggestion.start_date,
        end_date: suggestion.end_date,
        asset_ids: suggestion.asset_ids,
      })
      .then((created) => onOpen(created.id));

  return (
    <div className="h-full overflow-y-auto px-6 py-5">
      <div className="mb-5 flex items-center gap-3">
        <h1 className="text-lg font-medium">{t("nav.collections")}</h1>
        <form onSubmit={create} className="ml-auto flex gap-2">
          <Input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder={t("collections.newName")}
            aria-label={t("collections.newName")}
            className="w-56"
          />
          <Button type="submit" disabled={!name.trim()}>
            <Plus /> {t("collections.create")}
          </Button>
        </form>
      </div>

      {collections.data?.length === 0 && (
        <p className="mb-6 text-[13px] text-muted-foreground">{t("collections.empty")}</p>
      )}
      <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-4">
        {collections.data?.map((collection) => (
          <CollectionCard key={collection.id} collection={collection} onOpen={onOpen} />
        ))}
      </div>

      {(suggestions.data?.length ?? 0) > 0 && (
        <section aria-label={t("collections.suggestions")} className="mt-10">
          <h2 className="mb-1 text-[14px] font-medium">{t("collections.suggestions")}</h2>
          <p className="mb-4 text-[12px] text-muted-foreground">{t("collections.suggestionsHint")}</p>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-4">
            {suggestions.data?.map((suggestion) => (
              <article
                key={suggestion.start_date}
                className="overflow-hidden rounded-md border border-white/10 bg-card"
              >
                <div className="grid aspect-[4/3] grid-cols-2 grid-rows-2 gap-px bg-black">
                  {suggestion.samples.map((asset) => (
                    <Thumb key={asset.id} asset={asset} />
                  ))}
                </div>
                <div className="space-y-1 p-3 text-[12px]">
                  <p className="font-medium">
                    {dateRange(suggestion.start_date, suggestion.end_date, i18n.language)}
                  </p>
                  <p className="text-muted-foreground">
                    {t("collections.suggestionInfo", {
                      count: suggestion.asset_count,
                      distance: formatNumber(Math.round(suggestion.distance_km), i18n.language),
                    })}
                  </p>
                  <Button size="sm" variant="secondary" onClick={() => createTrip(suggestion)}>
                    <Plane /> {t("collections.createTrip")}
                  </Button>
                </div>
              </article>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function CollectionCard({
  collection,
  onOpen,
}: {
  collection: Collection;
  onOpen: (id: number) => void;
}) {
  const { t, i18n } = useTranslation();
  const dates =
    collection.kind === "trip" && collection.start_date
      ? dateRange(collection.start_date, collection.end_date, i18n.language)
      : dateRange(collection.first_capture, collection.last_capture, i18n.language);
  return (
    <button
      type="button"
      onClick={() => onOpen(collection.id)}
      className="group overflow-hidden rounded-md border border-white/10 bg-card text-left hover:border-white/25"
    >
      <div className="flex aspect-[4/3] items-center justify-center bg-black/40">
        {collection.cover ? (
          <Thumb asset={collection.cover} />
        ) : (
          <ImageIcon className="size-8 text-subtle-foreground" strokeWidth={1.25} />
        )}
      </div>
      <div className="space-y-0.5 p-3">
        <p className="flex items-center gap-1.5 text-[13px] font-medium">
          {collection.kind === "trip" ? (
            <Plane className="size-3.5 shrink-0 text-muted-foreground" />
          ) : (
            <Album className="size-3.5 shrink-0 text-muted-foreground" />
          )}
          <span className="truncate">{collection.name}</span>
        </p>
        <p className="text-[11.5px] text-muted-foreground">
          {t("collections.count", { count: collection.item_count })}
          {dates && ` · ${dates}`}
        </p>
      </div>
    </button>
  );
}

// --- One collection -----------------------------------------------------------------------

function CollectionView({ id, onBack }: { id: number; onBack: () => void }) {
  const { t } = useTranslation();
  const collection = useCollection(id);
  const actions = useCollectionActions();
  const { openViewer, openExport, openCloud } = useLibraryState();
  const [order, setOrder] = useState<CollectionItem[]>([]);
  const [dragged, setDragged] = useState<number | null>(null);
  const data = collection.data;

  useEffect(() => {
    if (data) setOrder(data.items);
  }, [data]);

  if (!data) return null;
  const ids = order.map((item) => item.asset.id);
  const update = (body: CollectionUpdate) => void actions.update(id, body).then(() => collection.refetch());

  const moveTo = (target: number) => {
    if (dragged === null || dragged === target) return;
    const next = [...order];
    const from = next.findIndex((item) => item.asset.id === dragged);
    const to = next.findIndex((item) => item.asset.id === target);
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved!);
    setOrder(next);
  };
  const saveOrder = () => {
    setDragged(null);
    if (ids.join() !== data.items.map((item) => item.asset.id).join()) {
      void actions.reorder(id, ids).then(() => collection.refetch());
    }
  };
  const remove = async () => {
    const ok = await confirmAction(t("collections.deleteConfirm", { name: data.name }), {
      title: t("collections.delete"),
      okLabel: t("collections.delete"),
      cancelLabel: t("export.cancel"),
    });
    if (ok) void actions.remove(id).then(onBack);
  };

  return (
    <div className="flex h-full flex-col">
      <header className="shrink-0 space-y-3 border-b border-white/10 px-6 py-4">
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="icon-sm" aria-label={t("collections.back")} onClick={onBack}>
            <ArrowLeft />
          </Button>
          <CollectionFields key={data.updated_at} collection={data} onSave={update} />
          <div className="ml-auto flex shrink-0 items-center gap-1">
            <Button
              variant="ghost"
              size="sm"
              disabled={ids.length < 2}
              onClick={() => openCloud("story", ids.slice(0, 30))}
            >
              <BookOpen /> {t("collections.story")}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={ids.length === 0}
              onClick={() => openExport(ids, { numbered: true })}
            >
              <Download /> {t("export.action")}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => void remove()}>
              <Trash2 /> {t("collections.delete")}
            </Button>
          </div>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
        {order.length === 0 ? (
          <p className="text-[13px] text-muted-foreground">{t("collections.emptyOne")}</p>
        ) : (
          <ol className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-4">
            {order.map((item, index) => (
              <li
                key={item.asset.id}
                draggable
                onDragStart={(event: DragEvent) => {
                  if (event.dataTransfer) event.dataTransfer.effectAllowed = "move";
                  setDragged(item.asset.id);
                }}
                onDragOver={(event: DragEvent) => {
                  event.preventDefault();
                  moveTo(item.asset.id);
                }}
                onDragEnd={saveOrder}
                onDrop={(event) => {
                  event.preventDefault();
                  saveOrder();
                }}
                className={cn(
                  "group relative overflow-hidden rounded-md border border-white/10 bg-card",
                  dragged === item.asset.id && "opacity-40",
                )}
              >
                <button
                  type="button"
                  aria-label={item.asset.file_name}
                  onDoubleClick={() => openViewer(ids, item.asset.id)}
                  className="block aspect-[4/3] w-full cursor-grab bg-black/40"
                >
                  <Thumb asset={item.asset} />
                </button>
                <span className="absolute left-2 top-2 rounded bg-black/60 px-1.5 text-[10.5px] text-white">
                  {index + 1}
                </span>
                {data.cover?.id === item.asset.id && (
                  <span className="absolute right-2 top-2 rounded bg-black/60 px-1.5 text-[10.5px] text-white">
                    {t("collections.cover")}
                  </span>
                )}
                <div className="absolute right-1.5 top-8 flex flex-col gap-1 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
                  <Button
                    variant="secondary"
                    size="icon-sm"
                    aria-label={t("collections.setCover")}
                    title={t("collections.setCover")}
                    onClick={() => update({ cover_asset_id: item.asset.id })}
                  >
                    <Star />
                  </Button>
                  <Button
                    variant="secondary"
                    size="icon-sm"
                    aria-label={t("collections.removeItem")}
                    title={t("collections.removeItem")}
                    onClick={() =>
                      void actions.removeItems(id, [item.asset.id]).then(() => collection.refetch())
                    }
                  >
                    <X />
                  </Button>
                </div>
                <Caption
                  key={`${item.asset.id}:${item.caption ?? ""}`}
                  value={item.caption}
                  label={t("collections.caption", { name: item.asset.file_name })}
                  onSave={(caption) => void actions.caption(id, item.asset.id, caption)}
                />
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}

/** Name, kind, dates, place and description; each saved when it loses the focus. */
function CollectionFields({
  collection,
  onSave,
}: {
  collection: CollectionDetail;
  onSave: (body: CollectionUpdate) => void;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState(collection.name);
  const saveIfChanged = (body: CollectionUpdate, changed: boolean) => {
    if (changed) onSave(body);
  };
  return (
    <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2 text-[12.5px]">
      <Input
        aria-label={t("collections.name")}
        value={name}
        onChange={(event) => setName(event.target.value)}
        onBlur={() => saveIfChanged({ name: name.trim() }, !!name.trim() && name.trim() !== collection.name)}
        className="h-8 w-64 text-[14px] font-medium"
      />
      <select
        aria-label={t("collections.kind")}
        value={collection.kind}
        onChange={(event) => onSave({ kind: event.target.value as "album" | "trip" })}
        className="h-8 rounded-md border border-input bg-background/60 px-2"
      >
        <option value="album">{t("collections.album")}</option>
        <option value="trip">{t("collections.trip")}</option>
      </select>
      {collection.kind === "trip" && (
        <>
          <input
            type="date"
            aria-label={t("collections.startDate")}
            defaultValue={collection.start_date ?? ""}
            onBlur={(event) =>
              saveIfChanged(
                { start_date: event.target.value || null },
                event.target.value !== (collection.start_date ?? ""),
              )
            }
            className="h-8 rounded-md border border-input bg-background/60 px-2"
          />
          <span className="text-muted-foreground">–</span>
          <input
            type="date"
            aria-label={t("collections.endDate")}
            defaultValue={collection.end_date ?? ""}
            onBlur={(event) =>
              saveIfChanged(
                { end_date: event.target.value || null },
                event.target.value !== (collection.end_date ?? ""),
              )
            }
            className="h-8 rounded-md border border-input bg-background/60 px-2"
          />
          <Input
            aria-label={t("collections.place")}
            placeholder={t("collections.place")}
            defaultValue={collection.place ?? ""}
            onBlur={(event) =>
              saveIfChanged(
                { place: event.target.value.trim() || null },
                event.target.value.trim() !== (collection.place ?? ""),
              )
            }
            className="h-8 w-40"
          />
        </>
      )}
      <Input
        aria-label={t("collections.description")}
        placeholder={t("collections.description")}
        defaultValue={collection.description ?? ""}
        onBlur={(event) =>
          saveIfChanged(
            { description: event.target.value.trim() || null },
            event.target.value.trim() !== (collection.description ?? ""),
          )
        }
        className="h-8 min-w-48 flex-1"
      />
    </div>
  );
}

function Caption({
  value,
  label,
  onSave,
}: {
  value: string | null;
  label: string;
  onSave: (caption: string | null) => void;
}) {
  const { t } = useTranslation();
  const [text, setText] = useState(value ?? "");
  return (
    <input
      aria-label={label}
      value={text}
      placeholder={t("collections.captionPlaceholder")}
      onChange={(event) => setText(event.target.value)}
      onBlur={() => {
        if (text.trim() !== (value ?? "")) onSave(text.trim() || null);
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter") event.currentTarget.blur();
      }}
      className="w-full border-t border-white/10 bg-transparent px-2.5 py-2 text-[12px] outline-none placeholder:text-subtle-foreground focus:bg-white/5"
    />
  );
}
