import {
  Album,
  ArrowDownUp,
  ArrowLeft,
  BookOpen,
  NotebookPen,
  CalendarDays,
  Check,
  ClockArrowDown,
  ClockArrowUp,
  Download,
  Grid3x3,
  ImageIcon,
  LayoutDashboard,
  MapPinned,
  Map as MapIcon,
  Plane,
  Plus,
  Search,
  Sparkles,
  Star,
  Trash2,
  X,
  type LucideIcon,
} from "lucide-react";
import {
  Fragment,
  useEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
  type FormEvent,
  type KeyboardEvent,
  type MouseEvent,
} from "react";
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
  RenditionVariant,
  TripSuggestion,
} from "@/api/types";
import { DraftBar, DraftLine, useCaptionDrafts } from "@/components/collections/CaptionDrafts";
import { CollectionMap } from "@/components/collections/CollectionMap";
import { DiaryView } from "@/components/collections/DiaryView";
import { StoryDialog } from "@/components/collections/StoryDialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useLibraryState } from "@/library/state";
import { confirmAction } from "@/lib/dialogs";
import { formatNumber } from "@/lib/format";
import { tripPlace } from "@/lib/places";
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

function dateRange(
  start: string | null | undefined,
  end: string | null | undefined,
  locale: string,
) {
  if (!start) return "";
  const format = (value: string) =>
    new Intl.DateTimeFormat(locale, { dateStyle: "medium" }).format(
      new Date(`${value.slice(0, 10)}T12:00:00`),
    );
  const from = format(start);
  const to = end ? format(end) : from;
  return from === to ? from : `${from} – ${to}`;
}

function Thumb({
  asset,
  className,
  variant,
  decorative = false,
}: {
  asset: AssetSummary;
  className?: string;
  variant?: RenditionVariant;
  /** Only illustrates a labelled control: no alternative text. */
  decorative?: boolean;
}) {
  const conn = useConnection();
  if (!conn) return null;
  return (
    <img
      src={thumbnailUrl(conn, asset.id, asset.rendition_version, variant)}
      alt={decorative ? "" : asset.file_name}
      loading="lazy"
      draggable={false}
      className={cn("size-full object-cover", className)}
    />
  );
}

function readPref<T extends string>(
  key: string,
  allowed: readonly T[],
  fallback: T,
): T {
  try {
    const value = localStorage.getItem(key);
    return allowed.includes(value as T) ? (value as T) : fallback;
  } catch {
    return fallback;
  }
}

/** A remembered choice (per viewer); kept only where the browser allows. */
function usePref<T extends string>(
  key: string,
  allowed: readonly T[],
  fallback: T,
) {
  const [value, setValue] = useState<T>(() => readPref(key, allowed, fallback));
  const set = (next: T) => {
    setValue(next);
    try {
      localStorage.setItem(key, next);
    } catch {
      // Not remembered: fine.
    }
  };
  return [value, set] as const;
}

/** A row of mutually exclusive toggle buttons. */
function Segmented<T extends string>({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: T;
  onChange: (value: T) => void;
  options: { id: T; label: string; icon?: LucideIcon }[];
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className="inline-flex rounded-md border border-white/10 bg-background/40 p-0.5"
    >
      {options.map((option) => (
        <button
          key={option.id}
          type="button"
          aria-pressed={value === option.id}
          onClick={() => onChange(option.id)}
          className={cn(
            "flex h-7 items-center gap-1.5 rounded px-2.5 text-[12px] text-muted-foreground hover:text-foreground",
            value === option.id && "bg-white/10 text-foreground",
          )}
        >
          {option.icon && <option.icon className="size-3.5" />}
          {option.label}
        </button>
      ))}
    </div>
  );
}

// --- List ---------------------------------------------------------------------------------

const LIST_SORTS = ["recent", "oldest", "updated", "name"] as const;
type ListSort = (typeof LIST_SORTS)[number];
type KindFilter = "all" | "album" | "trip";

/** When the collection's photos were taken: a trip's own dates, else its items'. */
function collectionStart(c: Collection) {
  return (c.kind === "trip" && c.start_date) || c.first_capture || null;
}
function collectionEnd(c: Collection) {
  return (
    (c.kind === "trip" && (c.end_date || c.start_date)) ||
    c.last_capture ||
    null
  );
}

/** Undated collections always come last; ties by name. */
export function sortCollections(
  items: Collection[],
  sort: ListSort,
  locale: string,
) {
  const byName = (a: Collection, b: Collection) =>
    a.name.localeCompare(b.name, locale);
  const byDate = (a: string | null, b: string | null, newest: boolean) =>
    a === b
      ? 0
      : a === null
        ? 1
        : b === null
          ? -1
          : (a < b ? -1 : 1) * (newest ? -1 : 1);
  return [...items].sort((a, b) => {
    if (sort === "name") return byName(a, b);
    if (sort === "updated")
      return byDate(a.updated_at, b.updated_at, true) || byName(a, b);
    if (sort === "oldest")
      return (
        byDate(collectionStart(a), collectionStart(b), false) || byName(a, b)
      );
    return byDate(collectionEnd(a), collectionEnd(b), true) || byName(a, b);
  });
}

function CollectionList({ onOpen }: { onOpen: (id: number) => void }) {
  const { t, i18n } = useTranslation();
  const collections = useCollections();
  const suggestions = useTripSuggestions();
  const actions = useCollectionActions();
  const [name, setName] = useState("");
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<KindFilter>("all");
  const [sort, setSort] = usePref<ListSort>(
    "lumen.collections.sort",
    LIST_SORTS,
    "recent",
  );

  const shown = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase(i18n.language);
    const matching = (collections.data ?? []).filter(
      (c) =>
        (kind === "all" || c.kind === kind) &&
        (!needle ||
          [c.name, c.place, c.description].some((text) =>
            text?.toLocaleLowerCase(i18n.language).includes(needle),
          )),
    );
    return sortCollections(matching, sort, i18n.language);
  }, [collections.data, query, kind, sort, i18n.language]);

  const create = (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    void actions
      .create({ name: name.trim(), kind: "album" })
      .then((created) => {
        setName("");
        onOpen(created.id);
      });
  };
  const createTrip = (suggestion: TripSuggestion) =>
    void actions
      .create({
        name: tripPlace(suggestion, i18n.language)
          ? t("collections.tripNamePlace", {
              place: tripPlace(suggestion, i18n.language),
              dates: dateRange(
                suggestion.start_date,
                suggestion.end_date,
                i18n.language,
              ),
            })
          : t("collections.tripName", {
              dates: dateRange(
                suggestion.start_date,
                suggestion.end_date,
                i18n.language,
              ),
            }),
        kind: "trip",
        place: tripPlace(suggestion, i18n.language) || null,
        start_date: suggestion.start_date,
        end_date: suggestion.end_date,
        asset_ids: suggestion.asset_ids,
      })
      .then((created) => onOpen(created.id));

  const total = collections.data?.length ?? 0;
  return (
    <div className="h-full overflow-y-auto px-6 py-5">
      <div className="mb-4 flex flex-wrap items-center gap-3">
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

      {total > 0 && (
        <div className="mb-5 flex flex-wrap items-center gap-2 text-[12.5px]">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t("collections.search")}
              aria-label={t("collections.search")}
              className="h-8 w-60 pl-8"
            />
          </div>
          <Segmented
            label={t("collections.filterKind")}
            value={kind}
            onChange={setKind}
            options={[
              { id: "all", label: t("collections.filterAll") },
              { id: "album", label: t("collections.album"), icon: Album },
              { id: "trip", label: t("collections.trip"), icon: Plane },
            ]}
          />
          <label className="ml-auto flex items-center gap-2 text-muted-foreground">
            <ArrowDownUp className="size-3.5" />
            <select
              aria-label={t("collections.sortBy")}
              value={sort}
              onChange={(event) => setSort(event.target.value as ListSort)}
              className="h-8 rounded-md border border-input bg-background/60 px-2 text-foreground"
            >
              <option value="recent">{t("collections.sortRecent")}</option>
              <option value="oldest">{t("collections.sortOldest")}</option>
              <option value="updated">{t("collections.sortUpdated")}</option>
              <option value="name">{t("collections.sortName")}</option>
            </select>
          </label>
        </div>
      )}

      {collections.data && total === 0 && (
        <p className="mb-6 text-[13px] text-muted-foreground">
          {t("collections.empty")}
        </p>
      )}
      {total > 0 && shown.length === 0 && (
        <p className="mb-6 text-[13px] text-muted-foreground">
          {t("collections.noMatch")}
        </p>
      )}
      <div className="grid grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-5">
        {shown.map((collection) => (
          <CollectionCard
            key={collection.id}
            collection={collection}
            onOpen={onOpen}
          />
        ))}
      </div>

      {(suggestions.data?.length ?? 0) > 0 && (
        <section aria-label={t("collections.suggestions")} className="mt-10">
          <h2 className="mb-1 text-[14px] font-medium">
            {t("collections.suggestions")}
          </h2>
          <p className="mb-4 text-[12px] text-muted-foreground">
            {t("collections.suggestionsHint")}
          </p>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-4">
            {suggestions.data?.map((suggestion) => (
              <article
                key={suggestion.start_date}
                className="overflow-hidden rounded-lg border border-dashed border-white/15 bg-card/60"
              >
                <div className="grid aspect-[4/3] grid-cols-2 grid-rows-2 gap-px bg-black">
                  {suggestion.samples.map((asset) => (
                    <Thumb key={asset.id} asset={asset} />
                  ))}
                </div>
                <div className="space-y-1 p-3 text-[12px]">
                  {tripPlace(suggestion, i18n.language) && (
                    <p className="truncate font-medium">
                      {tripPlace(suggestion, i18n.language)}
                    </p>
                  )}
                  <p
                    className={
                      tripPlace(suggestion, i18n.language)
                        ? "text-muted-foreground"
                        : "font-medium"
                    }
                  >
                    {dateRange(
                      suggestion.start_date,
                      suggestion.end_date,
                      i18n.language,
                    )}
                  </p>
                  <p className="text-muted-foreground">
                    {t("collections.suggestionInfo", {
                      count: suggestion.asset_count,
                      distance: formatNumber(
                        Math.round(suggestion.distance_km),
                        i18n.language,
                      ),
                    })}
                  </p>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => createTrip(suggestion)}
                  >
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
      : dateRange(
          collection.first_capture,
          collection.last_capture,
          i18n.language,
        );
  const samples = collection.samples ?? [];
  const zoom = "transition-transform duration-500 group-hover:scale-[1.04]";
  return (
    <button
      type="button"
      onClick={() => onOpen(collection.id)}
      className="group overflow-hidden rounded-lg border border-white/10 bg-card text-left shadow-sm transition hover:-translate-y-0.5 hover:border-white/25 hover:shadow-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <div
        className={cn(
          "relative grid aspect-[4/3] gap-0.5 overflow-hidden bg-black/40",
          samples.length > 0 ? "grid-cols-3 grid-rows-2" : "grid-cols-1",
        )}
      >
        {collection.cover ? (
          <div
            className={cn(
              "overflow-hidden",
              samples.length > 0 && "col-span-2 row-span-2",
            )}
          >
            <Thumb
              asset={collection.cover}
              variant="preview"
              className={zoom}
              decorative
            />
          </div>
        ) : (
          <div className="flex items-center justify-center">
            <ImageIcon
              className="size-8 text-subtle-foreground"
              strokeWidth={1.25}
            />
          </div>
        )}
        {samples.map((asset) => (
          <div
            key={asset.id}
            className={cn(
              "overflow-hidden",
              samples.length === 1 && "row-span-2",
            )}
          >
            <Thumb asset={asset} className={zoom} decorative />
          </div>
        ))}
        <span className="absolute left-2 top-2 flex items-center gap-1 rounded-full bg-black/55 px-2 py-0.5 text-[10.5px] text-white backdrop-blur-sm">
          {collection.kind === "trip" ? (
            <Plane className="size-3" />
          ) : (
            <Album className="size-3" />
          )}
          {t(
            collection.kind === "trip"
              ? "collections.trip"
              : "collections.album",
          )}
        </span>
      </div>
      <div className="space-y-0.5 p-3">
        <p className="truncate text-[13.5px] font-medium">{collection.name}</p>
        <p className="truncate text-[11.5px] text-muted-foreground">
          {t("collections.count", { count: collection.item_count })}
          {dates && ` · ${dates}`}
          {collection.place && ` · ${collection.place}`}
        </p>
      </div>
    </button>
  );
}

type CollectionView = "photos" | "map" | "diary";

// --- One collection -----------------------------------------------------------------------

const LAYOUTS = ["grid", "justified"] as const;
type Layout = (typeof LAYOUTS)[number];

/** Items by capture time (undated ones last, in their current order). */
export function byCaptureTime(items: CollectionItem[], newest: boolean) {
  return items
    .map((item, index) => ({ item, index }))
    .sort((a, b) => {
      const x = a.item.asset.capture_time;
      const y = b.item.asset.capture_time;
      if (x === y || (!x && !y)) return a.index - b.index;
      if (!x) return 1;
      if (!y) return -1;
      return (x < y ? -1 : 1) * (newest ? -1 : 1);
    })
    .map(({ item }) => item);
}

function CollectionView({ id, onBack }: { id: number; onBack: () => void }) {
  const { t, i18n } = useTranslation();
  const collection = useCollection(id);
  const actions = useCollectionActions();
  const { openViewer, openExport, openMapSend } = useLibraryState();
  const [order, setOrder] = useState<CollectionItem[]>([]);
  const [dragged, setDragged] = useState<number | null>(null);
  const [view, setView] = useState<CollectionView>("photos");
  const [choosingCover, setChoosingCover] = useState(false);
  const [writingStory, setWritingStory] = useState(false);
  const drafts = useCaptionDrafts(id, () => collection.refetch());
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [layout, setLayout] = usePref<Layout>(
    "lumen.collections.layout",
    LAYOUTS,
    "grid",
  );
  const [grouped, setGrouped] = usePref(
    "lumen.collections.byDay",
    ["on", "off"] as const,
    "off",
  );
  const data = collection.data;

  useEffect(() => {
    if (data) {
      setOrder(data.items);
      setSelected((current) => {
        const present = new Set(data.items.map((item) => item.asset.id));
        const kept = [...current].filter((asset) => present.has(asset));
        return kept.length === current.size ? current : new Set(kept);
      });
    }
  }, [data]);

  if (!data) return null;
  const ids = order.map((item) => item.asset.id);
  const update = (body: CollectionUpdate) =>
    void actions.update(id, body).then(() => collection.refetch());
  const save = (next: CollectionItem[]) => {
    const nextIds = next.map((item) => item.asset.id);
    if (nextIds.join() !== data.items.map((item) => item.asset.id).join()) {
      void actions.reorder(id, nextIds).then(() => collection.refetch());
    }
  };

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
    save(order);
  };
  const moveBy = (index: number, step: number) => {
    const to = index + step;
    if (to < 0 || to >= order.length) return;
    const next = [...order];
    const [moved] = next.splice(index, 1);
    next.splice(to, 0, moved!);
    setOrder(next);
    save(next);
  };
  const sortByTime = (newest: boolean) => {
    const next = byCaptureTime(order, newest);
    setOrder(next);
    save(next);
  };
  const toggle = (asset: number) =>
    setSelected((current) => {
      const next = new Set(current);
      if (!next.delete(asset)) next.add(asset);
      return next;
    });
  const removeSelected = () => {
    const chosen = ids.filter((asset) => selected.has(asset));
    setSelected(new Set());
    void actions.removeItems(id, chosen).then(() => collection.refetch());
  };
  const remove = async () => {
    const ok = await confirmAction(
      t("collections.deleteConfirm", { name: data.name }),
      {
        title: t("collections.delete"),
        okLabel: t("collections.delete"),
        cancelLabel: t("export.cancel"),
      },
    );
    if (ok) void actions.remove(id).then(onBack);
  };

  const dates =
    data.kind === "trip" && data.start_date
      ? dateRange(data.start_date, data.end_date, i18n.language)
      : dateRange(data.first_capture, data.last_capture, i18n.language);
  const dayFormat = new Intl.DateTimeFormat(i18n.language, {
    dateStyle: "full",
  });
  const dayOf = (item: CollectionItem) =>
    item.asset.capture_time?.slice(0, 10) ?? "";
  const justified = layout === "justified";

  return (
    <div className="flex h-full flex-col">
      <header className="relative shrink-0 overflow-hidden border-b border-white/10">
        {data.cover && (
          <div aria-hidden className="absolute inset-0">
            <Thumb
              asset={data.cover}
              variant="preview"
              decorative
              className="scale-110 opacity-50 blur-2xl"
            />
            <div className="absolute inset-0 bg-gradient-to-b from-background/40 via-background/70 to-background" />
          </div>
        )}
        <div className="relative space-y-3 px-6 pb-3 pt-4">
          <div className="flex items-start gap-4">
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={t("collections.back")}
              onClick={onBack}
              className="mt-1"
            >
              <ArrowLeft />
            </Button>
            {data.cover && (
              <button
                type="button"
                title={t("collections.chooseCover")}
                aria-hidden
                tabIndex={-1}
                onClick={() => setChoosingCover(true)}
                className="hidden h-24 w-32 shrink-0 overflow-hidden rounded-md border border-white/15 shadow-lg md:block"
              >
                <Thumb asset={data.cover} variant="preview" decorative />
              </button>
            )}
            <div className="min-w-0 flex-1 space-y-1.5">
              <CollectionFields
                key={data.updated_at}
                collection={data}
                onSave={update}
              />
              <p className="flex items-center gap-1.5 px-1 text-[12px] text-muted-foreground">
                {data.kind === "trip" ? (
                  <Plane className="size-3.5" />
                ) : (
                  <Album className="size-3.5" />
                )}
                {t("collections.count", { count: order.length })}
                {dates && ` · ${dates}`}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-1">
            <ViewSwitch value={view} onChange={setView} />
            <div className="ml-auto flex flex-wrap items-center gap-1">
              <Button
                variant="ghost"
                size="sm"
                disabled={ids.length === 0}
                title={t("collections.chooseCover")}
                onClick={() => setChoosingCover(true)}
              >
                {data.cover ? (
                  <span className="block size-5 overflow-hidden rounded-sm">
                    <Thumb asset={data.cover} decorative />
                  </span>
                ) : (
                  <ImageIcon />
                )}
                {t("collections.cover")}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                disabled={ids.length === 0}
                onClick={() => setWritingStory(true)}
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
              <Button
                variant="ghost"
                size="sm"
                disabled={ids.length === 0}
                onClick={() => openMapSend(ids, { description: data.name })}
              >
                <MapPinned /> {t("mapweb.send")}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => void remove()}>
                <Trash2 /> {t("collections.delete")}
              </Button>
            </div>
          </div>
        </div>
      </header>
      {writingStory && (
        <StoryDialog
          collectionId={id}
          assetIds={ids}
          onClose={() => setWritingStory(false)}
        />
      )}
      {choosingCover && (
        <CoverPicker
          collection={data}
          items={order}
          onPick={(slot, assetId) => {
            if (slot === "cover") {
              if (assetId !== data.cover_asset_id)
                update({ cover_asset_id: assetId });
              return;
            }
            const collage = [...(data.collage_asset_ids ?? [null, null])];
            collage[slot] = assetId;
            update({ collage_asset_ids: collage });
          }}
          onClose={() => setChoosingCover(false)}
        />
      )}

      {view === "map" ? (
        <CollectionMap id={id} />
      ) : view === "diary" ? (
        <DiaryView
          collectionId={id}
          name={data.name}
          items={order}
          onOpen={(assetId) => openViewer(ids, assetId)}
        />
      ) : (
        <>
          {order.length > 0 && (
            <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-white/5 px-6 py-2 text-[12px]">
              {selected.size > 0 ? (
                <>
                  <span className="font-medium">
                    {t("collections.selected", { count: selected.size })}
                  </span>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={removeSelected}
                  >
                    <X /> {t("collections.removeSelected")}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={drafts.running}
                    onClick={() => drafts.start(ids.filter((asset) => selected.has(asset)))}
                  >
                    <Sparkles /> {t("collections.draftSelected")}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setSelected(new Set())}
                  >
                    {t("collections.clearSelection")}
                  </Button>
                </>
              ) : (
                <>
                  <span className="text-muted-foreground">
                    {t("collections.sortTime")}
                  </span>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => sortByTime(false)}
                  >
                    <ClockArrowUp /> {t("collections.sortTimeAsc")}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => sortByTime(true)}
                  >
                    <ClockArrowDown /> {t("collections.sortTimeDesc")}
                  </Button>
                  <DraftBar items={order} drafts={drafts} />
                </>
              )}
              <div className="ml-auto flex items-center gap-2">
                <button
                  type="button"
                  aria-pressed={grouped === "on"}
                  onClick={() => setGrouped(grouped === "on" ? "off" : "on")}
                  className={cn(
                    "flex h-7 items-center gap-1.5 rounded-md border border-white/10 px-2.5 text-muted-foreground hover:text-foreground",
                    grouped === "on" && "bg-white/10 text-foreground",
                  )}
                >
                  <CalendarDays className="size-3.5" />
                  {t("collections.groupByDay")}
                </button>
                <Segmented
                  label={t("collections.layout")}
                  value={layout}
                  onChange={setLayout}
                  options={[
                    {
                      id: "grid",
                      label: t("collections.layoutGrid"),
                      icon: Grid3x3,
                    },
                    {
                      id: "justified",
                      label: t("collections.layoutJustified"),
                      icon: LayoutDashboard,
                    },
                  ]}
                />
              </div>
            </div>
          )}
          <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
            {order.length === 0 ? (
              <p className="text-[13px] text-muted-foreground">
                {t("collections.emptyOne")}
              </p>
            ) : (
              <>
                <ol
                  className={cn(
                    justified
                      ? "flex flex-wrap gap-3 after:grow-[10] after:content-['']"
                      : "grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-4",
                  )}
                >
                  {order.map((item, index) => {
                    const assetId = item.asset.id;
                    const ratio =
                      item.asset.width && item.asset.height
                        ? Math.min(
                            Math.max(item.asset.width / item.asset.height, 0.5),
                            2.5,
                          )
                        : 4 / 3;
                    const isSelected = selected.has(assetId);
                    const isCover = data.cover?.id === assetId;
                    const day = dayOf(item);
                    const newDay =
                      grouped === "on" &&
                      (index === 0 || dayOf(order[index - 1]!) !== day);
                    return (
                      <Fragment key={assetId}>
                        {newDay && (
                          <li
                            role="presentation"
                            className={cn(
                              "flex items-center gap-2 pt-2 text-[12.5px] font-medium text-muted-foreground first:pt-0",
                              justified ? "basis-full" : "col-span-full",
                            )}
                          >
                            <CalendarDays className="size-3.5" />
                            {day
                              ? dayFormat.format(new Date(`${day}T12:00:00`))
                              : t("collections.noDate")}
                          </li>
                        )}
                        <li
                          draggable
                          onDragStart={(event: DragEvent) => {
                            if (event.dataTransfer)
                              event.dataTransfer.effectAllowed = "move";
                            setDragged(assetId);
                          }}
                          onDragOver={(event: DragEvent) => {
                            event.preventDefault();
                            moveTo(assetId);
                          }}
                          onDragEnd={saveOrder}
                          onDrop={(event) => {
                            event.preventDefault();
                            saveOrder();
                          }}
                          onKeyDown={(event: KeyboardEvent) => {
                            if (!event.altKey) return;
                            const step =
                              event.key === "ArrowLeft" ||
                              event.key === "ArrowUp"
                                ? -1
                                : event.key === "ArrowRight" ||
                                    event.key === "ArrowDown"
                                  ? 1
                                  : 0;
                            if (step) {
                              event.preventDefault();
                              moveBy(index, step);
                            }
                          }}
                          style={
                            justified
                              ? {
                                  flexGrow: ratio,
                                  flexBasis: `${Math.round(ratio * 190)}px`,
                                }
                              : undefined
                          }
                          className={cn(
                            "group relative overflow-hidden rounded-lg border border-white/10 bg-card shadow-sm transition-shadow hover:shadow-md",
                            dragged === assetId &&
                              "opacity-40 ring-2 ring-highlight",
                            isSelected &&
                              "border-highlight ring-2 ring-highlight/70",
                          )}
                        >
                          <button
                            type="button"
                            aria-label={item.asset.file_name}
                            onClick={(event: MouseEvent) => {
                              if (
                                event.ctrlKey ||
                                event.metaKey ||
                                selected.size > 0
                              ) {
                                toggle(assetId);
                              } else {
                                openViewer(ids, assetId);
                              }
                            }}
                            style={
                              justified ? { aspectRatio: ratio } : undefined
                            }
                            className={cn(
                              "block w-full cursor-pointer overflow-hidden bg-black/40 active:cursor-grabbing",
                              !justified && "aspect-[4/3]",
                            )}
                          >
                            <Thumb
                              asset={item.asset}
                              className="transition-transform duration-300 group-hover:scale-[1.03]"
                            />
                          </button>
                          <span className="pointer-events-none absolute left-9 top-2 rounded bg-black/60 px-1.5 text-[10.5px] text-white">
                            {index + 1}
                          </span>
                          <button
                            type="button"
                            role="checkbox"
                            aria-checked={isSelected}
                            aria-label={t("collections.selectItem", {
                              name: item.asset.file_name,
                            })}
                            onClick={() => toggle(assetId)}
                            className={cn(
                              "absolute left-2 top-2 flex size-5 items-center justify-center rounded-full border border-white/70 bg-black/40 text-white transition-opacity",
                              isSelected
                                ? "border-highlight bg-highlight text-black opacity-100"
                                : "opacity-0 group-hover:opacity-100 focus-visible:opacity-100",
                              selected.size > 0 && "opacity-100",
                            )}
                          >
                            {isSelected && (
                              <Check className="size-3.5" strokeWidth={3} />
                            )}
                          </button>
                          {isCover && (
                            <span className="absolute right-2 top-2 flex items-center gap-1 rounded bg-black/60 px-1.5 text-[10.5px] text-white group-hover:opacity-0">
                              <Star className="size-3 fill-highlight text-highlight" />
                              {t("collections.cover")}
                            </span>
                          )}
                          <div className="absolute right-1.5 top-1.5 flex gap-1 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
                            <Button
                              variant="secondary"
                              size="icon-sm"
                              aria-label={t("collections.setCover")}
                              aria-pressed={isCover}
                              title={t("collections.setCover")}
                              onClick={() => {
                                if (!isCover)
                                  update({ cover_asset_id: assetId });
                              }}
                            >
                              <Star
                                className={cn(
                                  isCover && "fill-highlight text-highlight",
                                )}
                              />
                            </Button>
                            <Button
                              variant="secondary"
                              size="icon-sm"
                              aria-label={t("collections.removeItem")}
                              title={t("collections.removeItem")}
                              onClick={() =>
                                void actions
                                  .removeItems(id, [assetId])
                                  .then(() => collection.refetch())
                              }
                            >
                              <X />
                            </Button>
                          </div>
                          <Caption
                            key={`${assetId}:${item.caption ?? ""}`}
                            value={item.caption}
                            label={t("collections.caption", {
                              name: item.asset.file_name,
                            })}
                            onSave={(caption) =>
                              void actions
                                .caption(id, assetId, caption)
                                .then(() => {
                                  if (item.caption_draft) void collection.refetch();
                                })
                            }
                          />
                          {item.caption_draft && (
                            <DraftLine
                              draft={item.caption_draft}
                              name={item.asset.file_name}
                              onAccept={() => drafts.settle([assetId], true)}
                              onDiscard={() => drafts.settle([assetId], false)}
                            />
                          )}
                        </li>
                      </Fragment>
                    );
                  })}
                </ol>
                <p className="mt-6 text-center text-[11.5px] text-subtle-foreground">
                  {t("collections.orderHint")}
                </p>
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}

/** Photos, map or route of one collection. */
function ViewSwitch({
  value,
  onChange,
}: {
  value: CollectionView;
  onChange: (view: CollectionView) => void;
}) {
  const { t } = useTranslation();
  const views = [
    { id: "photos", icon: Grid3x3, label: t("collections.viewPhotos") },
    { id: "map", icon: MapIcon, label: t("collections.viewMap") },
    { id: "diary", icon: NotebookPen, label: t("collections.viewDiary") },
  ] as const;
  return (
    <div
      role="tablist"
      aria-label={t("collections.views")}
      className="inline-flex rounded-md border border-white/10 bg-background/40 p-0.5"
    >
      {views.map((item) => (
        <button
          key={item.id}
          type="button"
          role="tab"
          aria-selected={value === item.id}
          onClick={() => onChange(item.id)}
          className={cn(
            "flex h-7 items-center gap-1.5 rounded px-3 text-[12px] text-muted-foreground hover:text-foreground",
            value === item.id && "bg-white/10 text-foreground",
          )}
        >
          <item.icon className="size-3.5" />
          {item.label}
        </button>
      ))}
    </div>
  );
}

type CoverSlot = "cover" | 0 | 1;

/**
 * Pick the collection's cover and the two small photos of its collage among its items;
 * each slot can go back to automatic (the first items).
 */
function CoverPicker({
  collection,
  items,
  onPick,
  onClose,
}: {
  collection: CollectionDetail;
  items: CollectionItem[];
  onPick: (slot: CoverSlot, assetId: number | null) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const rootRef = useRef<HTMLDivElement>(null);
  useEffect(() => rootRef.current?.focus(), []);
  const [slot, setSlot] = useState<CoverSlot>("cover");
  const chosen = collection.collage_asset_ids ?? [null, null];
  const samples = collection.samples ?? [];
  // What each slot shows now (chosen, else automatic).
  const shown: Record<string, AssetSummary | undefined> = {
    cover: collection.cover ?? undefined,
    0: samples[0],
    1: samples[1],
  };
  const slots: { id: CoverSlot; label: string }[] = [
    { id: "cover", label: t("collections.slotCover") },
    { id: 0, label: t("collections.slotSmall", { n: 1 }) },
    { id: 1, label: t("collections.slotSmall", { n: 2 }) },
  ];
  const isChosen =
    slot === "cover"
      ? collection.cover_asset_id !== null
      : chosen[slot] !== null;
  const badge = (assetId: number) =>
    slots
      .filter((s) => shown[String(s.id)]?.id === assetId)
      .map((s) => s.label);
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6"
      onClick={onClose}
    >
      <div
        ref={rootRef}
        role="dialog"
        aria-modal
        aria-label={t("collections.chooseCover")}
        tabIndex={-1}
        onClick={(event) => event.stopPropagation()}
        onKeyDown={(event) => {
          if (event.key === "Escape") onClose();
          event.stopPropagation();
        }}
        className="flex max-h-full w-[760px] max-w-full flex-col rounded-lg border bg-popover shadow-xl outline-none"
      >
        <div className="flex shrink-0 items-center gap-2 border-b px-5 py-3">
          <h2 className="text-[14px] font-medium">
            {t("collections.chooseCover")}
          </h2>
          <span className="text-[12px] text-muted-foreground">
            {t("collections.coverHint")}
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
        <div
          role="group"
          aria-label={t("collections.coverSlots")}
          className="flex shrink-0 items-end gap-3 border-b px-5 py-3"
        >
          {slots.map((option) => {
            const asset = shown[String(option.id)];
            const active = slot === option.id;
            return (
              <button
                key={option.id}
                type="button"
                aria-pressed={active}
                onClick={() => setSlot(option.id)}
                className={cn(
                  "flex flex-col items-center gap-1 rounded-md p-1 text-[11.5px] text-muted-foreground hover:text-foreground",
                  active && "bg-white/10 text-foreground",
                )}
              >
                <span
                  className={cn(
                    "block overflow-hidden rounded border-2 border-transparent bg-black/40",
                    option.id === "cover" ? "h-16 w-24" : "h-12 w-16",
                    active && "border-highlight",
                  )}
                >
                  {asset && <Thumb asset={asset} decorative />}
                </span>
                {option.label}
              </button>
            );
          })}
        </div>
        {/* The grid scrolls inside its own box: as the scroll box itself its rows would shrink. */}
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          <div className="grid grid-cols-[repeat(auto-fill,minmax(130px,1fr))] gap-2">
            {items.map((item) => {
              const current = shown[String(slot)]?.id === item.asset.id;
              const labels = badge(item.asset.id);
              return (
                <button
                  key={item.asset.id}
                  type="button"
                  aria-label={item.asset.file_name}
                  aria-pressed={current}
                  onClick={() => onPick(slot, item.asset.id)}
                  className={cn(
                    "relative aspect-[4/3] overflow-hidden rounded-md border-2 border-transparent bg-black/40 hover:border-white/40",
                    current && "border-highlight hover:border-highlight",
                  )}
                >
                  <Thumb asset={item.asset} />
                  {labels.length > 0 && (
                    <span className="absolute left-1.5 top-1.5 flex items-center gap-1 rounded bg-black/65 px-1.5 text-[10.5px] text-white">
                      {current && (
                        <Star className="size-3 fill-highlight text-highlight" />
                      )}
                      {labels.join(" · ")}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2 border-t px-5 py-3">
          <Button
            variant="ghost"
            size="sm"
            disabled={!isChosen}
            onClick={() => onPick(slot, null)}
          >
            {slot === "cover"
              ? t("collections.coverDefault")
              : t("collections.collageDefault")}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            className="ml-auto"
            onClick={onClose}
          >
            {t("export.close")}
          </Button>
        </div>
      </div>
    </div>
  );
}

/** Name, kind, dates, place and description, edited in place; each saved on blur. */
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
  // Look like text until hovered or focused.
  const quiet =
    "border-transparent bg-transparent shadow-none hover:border-white/15 focus-visible:border-input focus-visible:bg-background/60";
  return (
    <div className="space-y-1">
      <Input
        aria-label={t("collections.name")}
        value={name}
        onChange={(event) => setName(event.target.value)}
        onBlur={() =>
          saveIfChanged(
            { name: name.trim() },
            !!name.trim() && name.trim() !== collection.name,
          )
        }
        onKeyDown={(event) => {
          if (event.key === "Enter") event.currentTarget.blur();
        }}
        className={cn(
          "h-10 w-full max-w-2xl px-1 text-[22px] font-semibold",
          quiet,
        )}
      />
      <div className="flex flex-wrap items-center gap-1.5 text-[12.5px]">
        <select
          aria-label={t("collections.kind")}
          value={collection.kind}
          onChange={(event) =>
            onSave({ kind: event.target.value as "album" | "trip" })
          }
          className={cn("h-7 rounded-md border px-1", quiet)}
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
              className={cn("h-7 rounded-md border px-1", quiet)}
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
              className={cn("h-7 rounded-md border px-1", quiet)}
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
              className={cn("h-7 w-40 px-1", quiet)}
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
          className={cn("h-7 min-w-48 flex-1 px-1", quiet)}
        />
      </div>
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
