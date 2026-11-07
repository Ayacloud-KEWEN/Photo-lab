import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { useTimeline } from "@/api/hooks";
import type { AssetQuery } from "@/api/query";
import type { AssetSummary } from "@/api/types";
import type { WallGroup } from "@/components/library/PhotoWall";
import { cn } from "@/lib/utils";

/**
 * Years and months of the photos matching ``query``, to jump through time. The order
 * follows the wall's (newest or oldest first); ``current`` is the month jumped to.
 */
export function DateRail({
  query,
  oldestFirst,
  current,
  onJump,
}: {
  query: AssetQuery;
  oldestFirst: boolean;
  current: string | null;
  onJump: (period: string) => void;
}) {
  const { t, i18n } = useTranslation();
  const months = useTimeline(query, "month");

  const years = useMemo(() => {
    const byYear = new Map<string, { period: string; count: number }[]>();
    const buckets = [...(months.data?.buckets ?? [])].sort((a, b) =>
      oldestFirst ? a.period.localeCompare(b.period) : b.period.localeCompare(a.period),
    );
    for (const bucket of buckets) {
      const year = bucket.period.slice(0, 4);
      byYear.set(year, [...(byYear.get(year) ?? []), bucket]);
    }
    return [...byYear.entries()];
  }, [months.data, oldestFirst]);

  if (years.length === 0) return null;
  const monthName = (period: string) =>
    new Intl.DateTimeFormat(i18n.language, { month: "short" }).format(
      new Date(Number(period.slice(0, 4)), Number(period.slice(5, 7)) - 1, 1),
    );

  return (
    <nav
      aria-label={t("library.dateRail")}
      className="w-24 shrink-0 overflow-y-auto border-l py-4 pr-2 text-right text-[11.5px]"
    >
      {years.map(([year, buckets]) => (
        <div key={year} className="mb-3">
          <button
            type="button"
            onClick={() => onJump(buckets[0]!.period)}
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
                  onClick={() => onJump(bucket.period)}
                  className={cn(
                    "py-0.5 text-muted-foreground hover:text-foreground",
                    current === bucket.period && "font-medium text-highlight",
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
  );
}

/** The wall from a month on: newest first, the photos before its end; oldest first, from
 * its start ("YYYY-MM" compares as a prefix of the capture times). */
export function fromMonth(query: AssetQuery, period: string, oldestFirst: boolean): AssetQuery {
  return oldestFirst ? { ...query, date_from: period } : { ...query, date_to: nextMonth(period) };
}

/** Photos grouped by day, with the month's name above its first day. */
export function groupByDay(items: AssetSummary[], locale: string): WallGroup[] {
  const dayFormat = new Intl.DateTimeFormat(locale, {
    weekday: "short",
    month: "long",
    day: "numeric",
  });
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
            <div className="text-xs font-normal text-muted-foreground">
              {dayFormat.format(date)}
            </div>
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

export function nextMonth(period: string): string {
  const year = Number(period.slice(0, 4));
  const month = Number(period.slice(5, 7));
  return month === 12 ? `${year + 1}-01` : `${year}-${String(month + 1).padStart(2, "0")}`;
}
