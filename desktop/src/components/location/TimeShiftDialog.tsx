import { useQuery } from "@tanstack/react-query";
import { Clock, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, api } from "@/api/client";
import { useConnection, useLocationActions } from "@/api/hooks";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useLibraryState, type AssetsRequest } from "@/library/state";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

/** A capture time moved by ``seconds`` (both local wall-clock times, "YYYY-MM-DDTHH:MM:SS"). */
export function shifted(time: string, seconds: number): string {
  const moment = new Date(`${time.slice(0, 19)}Z`);
  return new Date(moment.getTime() + seconds * 1000).toISOString().slice(0, 19);
}

/** Seconds from one wall-clock time to another ("YYYY-MM-DDTHH:MM:SS"). */
export function secondsBetween(from: string, to: string): number {
  return (Date.parse(`${to.slice(0, 19)}Z`) - Date.parse(`${from.slice(0, 19)}Z`)) / 1000;
}

/** Correct capture times: set a date and time, or shift them (a camera clock set wrong). */
export function TimeShiftDialog() {
  const { timeRequest, closeTimeShift } = useLibraryState();
  if (!timeRequest) return null;
  return <Body key={timeRequest.nonce} request={timeRequest} onClose={closeTimeShift} />;
}

type Mode = "set" | "shift";

function Body({ request, onClose }: { request: AssetsRequest; onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const conn = useConnection();
  const rootRef = useRef<HTMLDivElement>(null);
  const actions = useLocationActions();
  const count = request.assetIds.length;
  const [mode, setMode] = useState<Mode>("set");
  // The time shown first: the photo's, or the earliest of the selection's.
  const range = useQuery({
    queryKey: ["timeRange", request.nonce],
    queryFn: () => api.timeRange(conn!, request.assetIds),
    enabled: !!conn && !request.sampleTime,
  });
  const start = request.sampleTime ?? range.data?.first ?? null;
  const [date, setDate] = useState<string | null>(null);
  const [clock, setClock] = useState<string | null>(null);
  const [together, setTogether] = useState(false);
  const [sign, setSign] = useState<1 | -1>(1);
  const [days, setDays] = useState(0);
  const [hours, setHours] = useState(0);
  const [minutes, setMinutes] = useState(0);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => rootRef.current?.focus(), []);

  const shownDate = date ?? start?.slice(0, 10) ?? "";
  const shownClock = clock ?? start?.slice(11, 19) ?? "12:00:00";
  const target = shownDate
    ? `${shownDate}T${shownClock.length === 5 ? `${shownClock}:00` : shownClock}`
    : null;
  const valid = !!target && !Number.isNaN(Date.parse(`${target}Z`));
  const seconds =
    mode === "shift"
      ? sign * (days * 86400 + hours * 3600 + minutes * 60)
      : valid && start
        ? secondsBetween(start, target!)
        : 0;
  const allSame = mode === "set" && count > 1 && together;
  const changes = mode === "shift" ? seconds !== 0 : valid && (allSame || seconds !== 0);
  const fail = (failure: unknown) =>
    setError(failure instanceof ApiError ? failure.message : String(failure));
  const number = (value: string, max: number) =>
    Math.max(0, Math.min(max, Math.floor(Number(value) || 0)));
  const apply = () => {
    if (mode === "shift") {
      actions.shift.mutate(
        { assetIds: request.assetIds, seconds },
        { onSuccess: onClose, onError: fail },
      );
    } else if (target) {
      actions.setTime.mutate(
        { assetIds: request.assetIds, time: target, keepSpacing: !allSame },
        { onSuccess: onClose, onError: fail },
      );
    }
  };
  const busy = actions.shift.isPending || actions.setTime.isPending;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6">
      <div
        ref={rootRef}
        role="dialog"
        aria-modal
        aria-label={t("timeShift.title")}
        tabIndex={-1}
        onKeyDown={(event) => {
          if (event.key === "Escape") onClose();
          event.stopPropagation();
        }}
        className="w-[460px] max-w-full rounded-lg border bg-popover p-5 shadow-xl outline-none"
      >
        <div className="mb-3 flex items-center gap-2">
          <Clock className="size-4 text-muted-foreground" />
          <h2 className="text-[14px] font-medium">{t("timeShift.title")}</h2>
          <span className="text-[12px] text-muted-foreground">{t("export.count", { count })}</span>
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
          role="tablist"
          aria-label={t("timeShift.modes")}
          className="mb-3 inline-flex rounded-md border border-white/10 bg-background/40 p-0.5"
        >
          {(["set", "shift"] as const).map((id) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={mode === id}
              onClick={() => setMode(id)}
              className={cn(
                "h-7 rounded px-3 text-[12px] text-muted-foreground hover:text-foreground",
                mode === id && "bg-white/10 text-foreground",
              )}
            >
              {t(id === "set" ? "timeShift.modeSet" : "timeShift.modeShift")}
            </button>
          ))}
        </div>

        {mode === "set" ? (
          <div className="space-y-3 text-[12.5px]">
            <div className="flex flex-wrap items-center gap-2">
              <input
                type="date"
                aria-label={t("timeShift.date")}
                value={shownDate}
                onChange={(event) => setDate(event.target.value)}
                className="h-8 rounded-md border border-input bg-background/60 px-2"
              />
              <input
                type="time"
                step={1}
                aria-label={t("timeShift.time")}
                value={shownClock}
                onChange={(event) => setClock(event.target.value)}
                className="h-8 rounded-md border border-input bg-background/60 px-2"
              />
            </div>
            {count > 1 && (
              <fieldset className="space-y-1.5">
                <legend className="sr-only">{t("timeShift.howMany")}</legend>
                {([false, true] as const).map((value) => (
                  <label key={String(value)} className="flex items-start gap-2">
                    <input
                      type="radio"
                      name="together"
                      checked={together === value}
                      onChange={() => setTogether(value)}
                      className="mt-0.5"
                    />
                    <span>
                      <span className="block">
                        {t(value ? "timeShift.allSame" : "timeShift.keepSpacing")}
                      </span>
                      <span className="block text-[11.5px] text-muted-foreground">
                        {t(value ? "timeShift.allSameHint" : "timeShift.keepSpacingHint")}
                      </span>
                    </span>
                  </label>
                ))}
              </fieldset>
            )}
          </div>
        ) : (
          <>
            <p className="mb-3 text-[12px] leading-relaxed text-muted-foreground">
              {t("timeShift.hint")}
            </p>
            <div className="flex flex-wrap items-center gap-2 text-[12.5px]">
              <select
                aria-label={t("timeShift.direction")}
                value={sign}
                onChange={(event) => setSign(Number(event.target.value) as 1 | -1)}
                className="h-8 rounded-md border border-input bg-background/60 px-2"
              >
                <option value={1}>{t("timeShift.later")}</option>
                <option value={-1}>{t("timeShift.earlier")}</option>
              </select>
              {(
                [
                  ["days", days, setDays, 400],
                  ["hours", hours, setHours, 23],
                  ["minutes", minutes, setMinutes, 59],
                ] as const
              ).map(([unit, value, set, max]) => (
                <label key={unit} className="flex items-center gap-1">
                  <Input
                    aria-label={t(`timeShift.${unit}`)}
                    type="number"
                    min={0}
                    max={max}
                    value={value}
                    onChange={(event) => set(number(event.target.value, max))}
                    className="h-8 w-16 text-right"
                  />
                  <span className="text-muted-foreground">{t(`timeShift.${unit}`)}</span>
                </label>
              ))}
            </div>
          </>
        )}

        {start && changes && (
          <p role="status" className="mt-3 text-[12px] text-muted-foreground">
            {count > 1 && !allSame && `${t("timeShift.earliest")} `}
            {formatDateTime(start, i18n.language)} →{" "}
            <span className="text-foreground">
              {formatDateTime(allSame && target ? target : shifted(start, seconds), i18n.language)}
            </span>
          </p>
        )}
        {error && (
          <p role="alert" className="mt-3 select-text text-[12px] text-destructive">
            {error}
          </p>
        )}
        <p className="mt-3 text-[11.5px] leading-relaxed text-subtle-foreground">
          {t("timeShift.note")}
        </p>
        <div className="mt-4 flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            disabled={actions.restoreTime.isPending}
            onClick={() =>
              actions.restoreTime.mutate(request.assetIds, { onSuccess: onClose, onError: fail })
            }
          >
            {t("timeShift.restore")}
          </Button>
          <Button variant="ghost" size="sm" className="ml-auto" onClick={onClose}>
            {t("export.cancel")}
          </Button>
          <Button size="sm" disabled={!changes || busy} onClick={apply}>
            {t("timeShift.apply", { count })}
          </Button>
        </div>
      </div>
    </div>
  );
}
