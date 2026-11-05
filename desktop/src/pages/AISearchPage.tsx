import { ArrowLeft, Loader2, Search, Sparkles } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, ApiError, thumbnailUrl } from "@/api/client";
import {
  useActiveTasks,
  useAiSearch,
  useAiStatus,
  useAsset,
  useConnection,
  useSimilar,
  useUpdateSettings,
} from "@/api/hooks";
import { FilterBar } from "@/components/library/FilterBar";
import { PhotoWall } from "@/components/library/PhotoWall";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { emptySelection, selectItem, type Modifiers, type SelectionState } from "@/library/selection";
import { cleanQuery, useLibraryState } from "@/library/state";
import type { Selection } from "@/selection";

interface AISearchPageProps {
  onSelect: (selection: Selection) => void;
}

export function AISearchPage({ onSelect }: AISearchPageProps) {
  const { t } = useTranslation();
  const status = useAiStatus();
  const local = status.data?.local;
  const ready = !!local && local.installed && local.enabled && local.model_downloaded;
  const conn = useConnection();
  const warmedUp = useRef(false);
  // Load the model while the user types (the first search would wait ~20 s for it).
  useEffect(() => {
    if (!ready || !conn || warmedUp.current) return;
    warmedUp.current = true;
    api.warmUpAi(conn).catch(() => {});
  }, [ready, conn]);

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 px-6 pt-5">
        <h1 className="flex items-center gap-2 text-lg font-medium">
          <Sparkles className="size-4 text-highlight" />
          {t("aiSearch.title")}
        </h1>
      </div>
      {!status.data ? null : ready ? (
        <SearchView onSelect={onSelect} />
      ) : (
        <Setup />
      )}
    </div>
  );
}

function Setup() {
  const { t } = useTranslation();
  const status = useAiStatus();
  const tasks = useActiveTasks();
  const updateSettings = useUpdateSettings();
  const local = status.data!.local;
  const spec = local.models.find((model) => model.id === local.model_id);
  const downloading = tasks.data?.find((task) => task.kind === "ai_download_model");

  return (
    <div className="flex flex-1 flex-col items-center justify-center px-8 text-center">
      <div className="mb-5 flex size-14 items-center justify-center rounded-full border bg-card">
        <Sparkles className="size-6 text-highlight" strokeWidth={1.5} />
      </div>
      <h2 className="text-base font-medium">{t("aiSearch.setupTitle")}</h2>
      <p className="mt-2 max-w-md leading-relaxed text-muted-foreground">
        {t("aiSearch.setupText")}
      </p>
      {!local.installed ? (
        <p className="mt-5 max-w-lg select-text rounded-md border bg-card px-3 py-2 text-left font-mono text-[11.5px] text-muted-foreground">
          {t("aiSearch.notInstalled")}
        </p>
      ) : downloading || (local.enabled && !local.model_downloaded) ? (
        <p className="mt-6 flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="size-3.5 animate-spin text-highlight" />
          {t("aiSearch.downloading")}
          {downloading?.progress_total
            ? ` ${gb(downloading.progress_current)} / ${gb(downloading.progress_total)} GB`
            : ""}
        </p>
      ) : (
        <Button
          size="lg"
          className="mt-6"
          disabled={updateSettings.isPending}
          onClick={() => updateSettings.mutate({ ai_enabled: true })}
        >
          <Sparkles className="size-4" />
          {t("aiSearch.enable", { size: spec?.approx_download_gb ?? "?" })}
        </Button>
      )}
      {local.installed && (
        <p className="mt-4 text-xs text-subtle-foreground">
          {local.device === "cuda" ? `GPU · ${local.device_name ?? ""}` : "CPU"}
        </p>
      )}
    </div>
  );
}

function gb(bytes: number): string {
  return (bytes / 1024 ** 3).toFixed(1);
}

function SearchView({ onSelect }: { onSelect: (selection: Selection) => void }) {
  const { t } = useTranslation();
  const conn = useConnection();
  const status = useAiStatus();
  const tasks = useActiveTasks();
  const { query, setQuery, openViewer, similarTo, findSimilar } = useLibraryState();
  const [draft, setDraft] = useState("");
  const [text, setText] = useState("");
  const [selection, setSelection] = useState<SelectionState>(emptySelection);
  const [showAll, setShowAll] = useState(false);

  const filters = useMemo(() => cleanQuery({ ...query, q: undefined, sort: undefined }), [query]);
  const similarId = similarTo?.id ?? null;
  const textResults = useAiSearch(text, filters, similarId === null);
  const similarResults = useSimilar(similarId, filters);
  const results = similarId !== null ? similarResults : textResults;
  const source = useAsset(similarId);
  const relevant = results.data?.relevant_count ?? 0;
  const allItems = results.data?.items;
  const items = useMemo(
    () => (allItems ? (showAll ? allItems : allItems.slice(0, relevant)) : []),
    [allItems, showAll, relevant],
  );
  const weaker = (allItems?.length ?? 0) - relevant;
  const order = useMemo(() => items.map((item) => item.id), [items]);
  const groups = useMemo(() => [{ key: "results", items }], [items]);

  useEffect(() => {
    setSelection(emptySelection);
    setShowAll(false);
  }, [text, similarId]);
  useEffect(() => {
    if (selection.focused !== null) onSelect({ kind: "asset", id: selection.focused });
  }, [selection.focused, onSelect]);

  const select = useCallback(
    (id: number, modifiers: Modifiers) => setSelection((state) => selectItem(state, id, order, modifiers)),
    [order],
  );
  const submit = (value: string) => {
    findSimilar(null);
    setDraft(value);
    setText(value.trim());
  };

  const local = status.data?.local;
  const indexTask = tasks.data?.find((task) => task.kind === "ai_index_assets");
  const indexKey =
    indexTask?.status === "running"
      ? "aiSearch.indexing"
      : indexTask
        ? "aiSearch.indexQueued"
        : "aiSearch.indexPartial";
  const examples = t("aiSearch.examples").split("|");
  const error = results.error instanceof ApiError ? results.error.message : results.error?.message;

  return (
    <>
      <div className="shrink-0 space-y-3 px-6 pb-3 pt-4">
        {similarId !== null ? (
          <div className="flex items-center gap-3">
            <Button variant="ghost" size="sm" onClick={() => findSimilar(null)}>
              <ArrowLeft className="size-3.5" />
              {t("aiSearch.backToText")}
            </Button>
            {conn && source.data?.rendition_version && (
              <img
                src={thumbnailUrl(conn, source.data.id, source.data.rendition_version)}
                alt=""
                className="size-10 rounded object-cover"
              />
            )}
            <span className="text-[13px]">{t("aiSearch.similarTo")}</span>
          </div>
        ) : (
          <>
            <form
              className="flex max-w-3xl gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                submit(draft);
              }}
            >
              <div className="relative flex-1">
                <Sparkles className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-highlight" />
                <Input
                  value={draft}
                  autoFocus
                  aria-label={t("aiSearch.placeholder")}
                  placeholder={t("aiSearch.placeholder")}
                  onChange={(event) => setDraft(event.target.value)}
                  onKeyDown={(event) => event.stopPropagation()}
                  className="h-10 pl-9 text-sm"
                />
              </div>
              <Button type="submit" className="h-10" disabled={!draft.trim()}>
                <Search className="size-4" />
                {t("aiSearch.search")}
              </Button>
            </form>
            <div className="flex flex-wrap items-center gap-1.5">
              {examples.map((example) => (
                <button
                  key={example}
                  type="button"
                  onClick={() => submit(example)}
                  className="rounded-full border px-2.5 py-0.5 text-xs text-muted-foreground hover:border-highlight/50 hover:text-foreground"
                >
                  {example}
                </button>
              ))}
            </div>
          </>
        )}
        <FilterBar query={query} onChange={setQuery} sortable={false} />
        <p className="text-xs text-subtle-foreground">
          {local && local.indexed < local.total
            ? t(indexKey, { current: local.indexed, total: local.total })
            : results.data
              ? t("aiSearch.results", { count: relevant })
              : t("aiSearch.hint")}
          {weaker > 0 && (
            <button
              type="button"
              onClick={() => setShowAll((value) => !value)}
              className="ml-3 text-highlight hover:underline"
            >
              {showAll ? t("aiSearch.showLess") : t("aiSearch.showMore", { count: weaker })}
            </button>
          )}
        </p>
        {error && <p className="text-xs text-destructive">{error}</p>}
      </div>
      <div className="min-h-0 flex-1">
        {results.isFetching && items.length === 0 ? (
          <p className="flex items-center justify-center gap-2 pt-10 text-xs text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
            {/* The first search loads the model (~20 s); say what is being waited for. */}
            {status.data && !status.data.local.model_loaded && t("aiSearch.loadingModel")}
          </p>
        ) : items.length > 0 ? (
          <PhotoWall
            groups={groups}
            mode="justified"
            selection={selection}
            onSelect={select}
            onOpen={(id) => openViewer(order, id)}
            onReachEnd={() => undefined}
          />
        ) : results.data ? (
          <p className="pt-10 text-center text-xs text-subtle-foreground">{t("aiSearch.noResults")}</p>
        ) : null}
      </div>
    </>
  );
}
