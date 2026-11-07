import { Clock, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import { useLocationActions } from "@/api/hooks";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useLibraryState, type AssetsRequest } from "@/library/state";
import { formatDateTime } from "@/lib/format";

/** A capture time moved by ``seconds`` (both local wall-clock times, "YYYY-MM-DDTHH:MM:SS"). */
export function shifted(time: string, seconds: number): string {
  const moment = new Date(`${time.slice(0, 19)}Z`);
  return new Date(moment.getTime() + seconds * 1000).toISOString().slice(0, 19);
}

/** Correct capture times: a camera clock set wrong, or left on the time zone at home. */
export function TimeShiftDialog() {
  const { timeRequest, closeTimeShift } = useLibraryState();
  if (!timeRequest) return null;
  return <Body key={timeRequest.nonce} request={timeRequest} onClose={closeTimeShift} />;
}

function Body({ request, onClose }: { request: AssetsRequest; onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const rootRef = useRef<HTMLDivElement>(null);
  const actions = useLocationActions();
  const [sign, setSign] = useState<1 | -1>(1);
  const [days, setDays] = useState(0);
  const [hours, setHours] = useState(0);
  const [minutes, setMinutes] = useState(0);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => rootRef.current?.focus(), []);

  const seconds = sign * (days * 86400 + hours * 3600 + minutes * 60);
  const count = request.assetIds.length;
  const fail = (failure: unknown) =>
    setError(failure instanceof ApiError ? failure.message : String(failure));
  const number = (value: string, max: number) =>
    Math.max(0, Math.min(max, Math.floor(Number(value) || 0)));

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
        className="w-[440px] max-w-full rounded-lg border bg-popover p-5 shadow-xl outline-none"
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
        {request.sampleTime && seconds !== 0 && (
          <p role="status" className="mt-3 text-[12px] text-muted-foreground">
            {formatDateTime(request.sampleTime, i18n.language)} →{" "}
            <span className="text-foreground">
              {formatDateTime(shifted(request.sampleTime, seconds), i18n.language)}
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
          <Button
            size="sm"
            disabled={seconds === 0 || actions.shift.isPending}
            onClick={() =>
              actions.shift.mutate(
                { assetIds: request.assetIds, seconds },
                { onSuccess: onClose, onError: fail },
              )
            }
          >
            {t("timeShift.apply", { count })}
          </Button>
        </div>
      </div>
    </div>
  );
}
