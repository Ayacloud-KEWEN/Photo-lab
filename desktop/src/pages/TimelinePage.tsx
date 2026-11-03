import { ArrowUpToLine, CalendarDays } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { useTimeline } from "@/api/hooks";
import type { AssetQuery } from "@/api/query";
import type { AssetSummary } from "@/api/types";
import { FilterBar } from "@/components/library/FilterBar";
import { PhotoWall, type WallGroup } from "@/components/library/PhotoWall";
import { SelectionBar } from "@/components/library/SelectionBar";
import { Button } from "@/components/ui/button";
import { cleanQuery, useLibraryState } from "@/library/state";
import { useWall } from "@/library/useWall";
import { cn } from "@/lib/utils";
import { describeError } from "@/pages/LibraryPage";
import type { Selection } from "@/selection";

interface TimelinePageProps {
  onSelect: (selection: Selection) => void;
}

/** Photos grouped by day, newest first, with a month scrubber to jump through time. */
export function TimelinePage({ onSelect }: TimelinePageProps) {
  const { t, i18n } = useTranslation();
  const { query, setQuery } = useLibraryState();
  // Jumping to a month re-anchors the list there (date_to is exclusive).
  const [anchor, setAnchor] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const baseQuery = useMemo(() => cleanQuery({ ...query, sort: undefined }), [query]);
  const wallQuery = useMemo<AssetQuery>(
    () => (anchor ? { ...baseQuery, date_to: anchor } : baseQuery),
    [baseQuery, anchor],
  );
  const focusAsset = useCallback(
    (id: number | null) => {
      if (id !== null) onSelect({ kind: "asset", id });
    },
    [onSelect],
  );
  const wall = useWall(wallQuery, focusAsset);
  const months = useTimeline(baseQuery, "month");

  const groups = useMemo(
    () => groupByDay(wall.items, i18n.language),
    [wall.items, i18n.language],
  );

  const years = useMemo(() => {
    const byYear = new Map<string, { period: string; count: number }[]>();
    for (const bucket of months.data?.buckets ?? []) {
      const year = bucket.period.slice(0, 4);
      byYear.set(year, [...(byYear.get(year) ?? []), bucket]);
    }
    return [...byYear.entries()];
  }, [months.data]);

  const jumpTo = (period: string) => setAnchor(nextMonth(period));
  const anchorMonth = anchor ? previousMonth(anchor) : null;
  const monthName = (period: string) =>
    new Intl.DateTimeFormat(i18n.language, { month: "short" }).format(
      new Date(Number(period.slice(0, 4)), Number(period.slice(5, 7)) - 1, 1),
    );

  return (
    <div className="flex h-full">
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="shrink-0 space-y-3 px-6 pb-2 pt-5">
          <div className="flex items-center gap-3">
            <h1 className="text-lg font-medium">{t("timeline.title")}</h1>
            {anchor && (
              <Button variant="ghost" size="sm" onClick={() => setAnchor(null)}>
                <ArrowUpToLine className="size-3.5" />
                {t("timeline.latest")}
              </Button>
            )}
          </div>
          <FilterBar query={query} onChange={setQuery} sortable={false} />
          {wall.selection.selected.size > 1 && (
            <SelectionBar
              ids={wall.selectedIds}
              onClear={wall.clearSelection}
              onError={(cause) => setError(describeError(t, cause))}
            />
          )}
          {error && <p className="text-xs text-destructive">{error}</p>}
        </div>
        <div className="min-h-0 flex-1">
          {wall.items.length > 0 ? (
            <PhotoWall
              key={anchor ?? "latest"}
              groups={groups}
              mode="justified"
              selection={wall.selection}
              onSelect={wall.select}
              onOpen={wall.open}
              onReachEnd={wall.loadMore}
              onKeyDown={wall.onKeyDown}
            />
          ) : (
            <p className="flex items-center justify-center gap-2 pt-10 text-xs text-subtle-foreground">
              <CalendarDays className="size-3.5" />
              {wall.assets.isPending ? t("wall.loading") : t("timeline.empty")}
            </p>
          )}
        </div>
      </div>

      {years.length > 0 && (
        <nav
          aria-label={t("timeline.title")}
          className="w-24 shrink-0 overflow-y-auto border-l py-4 pr-2 text-right text-[11.5px]"
        >
          {years.map(([year, buckets]) => (
            <div key={year} className="mb-3">
              <button
                type="button"
                onClick={() => jumpTo(buckets[0]!.period)}
                className="mb-1 font-medium text-foreground hover:text-highlight"
              >
                {year}
              </button>
              <ul>
                {buckets.map((bucket) => (
                  <li key={bucket.period}>
                    <button
                      type="button"
                      title={`${bucket.period} · ${bucket.count}`}
                      onClick={() => jumpTo(bucket.period)}
                      className={cn(
                        "py-0.5 text-muted-foreground hover:text-foreground",
                        anchorMonth === bucket.period && "font-medium text-highlight",
                      )}
                    >
                      {monthName(bucket.period)}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
      )}
    </div>
  );
}

function groupByDay(items: AssetSummary[], locale: string): WallGroup[] {
  const dayFormat = new Intl.DateTimeFormat(locale, { weekday: "short", month: "long", day: "numeric" });
  const monthFormat = new Intl.DateTimeFormat(locale, { year: "numeric", month: "long" });
  const groups: WallGroup[] = [];
  let previousMonthKey = "";
  for (const item of items) {
    const day = item.capture_time?.slice(0, 10) ?? "";
    let group = groups.at(-1);
    if (!group || group.key !== day) {
      const date = new Date(`${day}T00:00:00`);
      const monthKey = day.slice(0, 7);
      const newMonth = monthKey !== previousMonthKey;
      previousMonthKey = monthKey;
      group = {
        key: day,
        titleHeight: newMonth ? 76 : 44,
        title: (
          <div>
            {newMonth && (
              <div className="mb-2 text-base font-semibold">{monthFormat.format(date)}</div>
            )}
            <div className="text-xs font-normal text-muted-foreground">{dayFormat.format(date)}</div>
          </div>
        ),
        items: [],
      };
      groups.push(group);
    }
    group.items.push(item);
  }
  return groups;
}

function nextMonth(period: string): string {
  const year = Number(period.slice(0, 4));
  const month = Number(period.slice(5, 7));
  return month === 12 ? `${year + 1}-01` : `${year}-${String(month + 1).padStart(2, "0")}`;
}

function previousMonth(period: string): string {
  const year = Number(period.slice(0, 4));
  const month = Number(period.slice(5, 7));
  return month === 1 ? `${year - 1}-12` : `${year}-${String(month - 1).padStart(2, "0")}`;
}
