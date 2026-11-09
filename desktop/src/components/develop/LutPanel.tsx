import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { lutPreviewUrl, type BackendConnection } from "@/api/client";
import { useLuts } from "@/api/hooks";
import type { EditRecipe, Lut } from "@/api/types";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import { LUT_STRENGTH } from "./recipe";
import { Slider } from "./Slider";

/** LUTs worth offering for this photo: looks, plus log ones only when asked for. */
export function offeredLuts(luts: Lut[], showLog: boolean, current: string | null): Lut[] {
  return luts.filter(
    (lut) =>
      lut.ref === current ||
      (!lut.hidden && (lut.kind === "look" || showLog)),
  );
}

/**
 * The develop panel's LUT group: a grid of small previews of this photo through each
 * imported LUT (rendered on the backend, cached by the browser), and the strength.
 */
export function LutPanel({
  conn,
  assetId,
  version,
  recipe,
  onChange,
  onCommit,
}: {
  conn: BackendConnection;
  assetId: number;
  /** Rendition version of the saved edit (previews show the photo as saved). */
  version: string;
  recipe: EditRecipe;
  onChange: (patch: Partial<EditRecipe>, delay?: number) => void;
  onCommit: () => void;
}) {
  const { t } = useTranslation();
  const luts = useLuts();
  const [query, setQuery] = useState("");
  const [pack, setPack] = useState("");
  const [showLog, setShowLog] = useState(false);
  const current = recipe.lut ?? null;

  const all = luts.data ?? [];
  const packs = useMemo(
    () => [...new Set(all.filter((lut) => !lut.hidden).map((lut) => lut.pack ?? ""))].sort(),
    [all],
  );
  const shown = offeredLuts(all, showLog, current).filter(
    (lut) =>
      (!pack || (lut.pack ?? "") === pack) &&
      (!query.trim() || lut.name.toLowerCase().includes(query.trim().toLowerCase())),
  );
  const selected = all.find((lut) => lut.ref === current);

  return (
    <section aria-label={t("lut.title")}>
      <h3 className="mb-1 text-[11px] font-medium uppercase tracking-wider text-subtle-foreground">
        {t("lut.title")}
      </h3>
      {luts.data && all.length === 0 ? (
        <p className="text-[11.5px] leading-relaxed text-subtle-foreground">{t("lut.empty")}</p>
      ) : (
        <>
          <div className="mb-2 flex gap-1">
            <Input
              aria-label={t("lut.search")}
              placeholder={t("lut.search")}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="h-7 min-w-0 flex-1 text-[12px]"
            />
            {packs.length > 1 && (
              <select
                aria-label={t("lut.pack")}
                value={pack}
                onChange={(event) => setPack(event.target.value)}
                className="h-7 max-w-28 rounded-md border border-input bg-background/60 px-1 text-[11.5px]"
              >
                <option value="">{t("lut.allPacks")}</option>
                {packs.map((name) => (
                  <option key={name} value={name}>
                    {name || t("lut.noPack")}
                  </option>
                ))}
              </select>
            )}
          </div>
          <div role="radiogroup" aria-label={t("lut.title")} className="grid max-h-72 grid-cols-3 gap-1 overflow-y-auto pr-1">
            <Tile
              label={t("lut.none")}
              checked={current === null}
              onSelect={() => onChange({ lut: null }, 0)}
            />
            {shown.map((lut) => (
              <Tile
                key={lut.id}
                label={lut.name}
                hint={lut.kind === "look" ? undefined : t(`lut.kind_${lut.kind}`)}
                checked={lut.ref === current}
                src={lutPreviewUrl(conn, assetId, version, lut.ref)}
                onSelect={() => onChange({ lut: lut.ref }, 0)}
              />
            ))}
          </div>
          <label className="mt-1.5 flex cursor-pointer items-center gap-1.5 text-[11px] text-subtle-foreground">
            <input
              type="checkbox"
              checked={showLog}
              onChange={(event) => setShowLog(event.target.checked)}
              className="size-3 accent-[var(--highlight)]"
            />
            {t("lut.showLog")}
          </label>
          {selected && selected.kind !== "look" && (
            <p className="mt-1 text-[11px] text-amber-300">{t("lut.logWarning")}</p>
          )}
          {current && (
            <Slider
              spec={LUT_STRENGTH}
              value={recipe.lut_strength ?? 100}
              onChange={(value) => onChange({ lut_strength: value })}
              onCommit={onCommit}
            />
          )}
        </>
      )}
    </section>
  );
}

function Tile({
  label,
  hint,
  checked,
  src,
  onSelect,
}: {
  label: string;
  hint?: string | undefined;
  checked: boolean;
  src?: string;
  onSelect: () => void;
}) {
  const [failed, setFailed] = useState(false);
  return (
    <button
      type="button"
      role="radio"
      aria-checked={checked}
      title={hint ? `${label} · ${hint}` : label}
      onClick={onSelect}
      className={cn(
        "overflow-hidden rounded border-2 bg-black text-left",
        checked ? "border-highlight" : "border-transparent hover:border-white/30",
      )}
    >
      <span className="block aspect-[4/3] w-full bg-white/5">
        {src && !failed && (
          <img
            src={src}
            alt=""
            loading="lazy"
            draggable={false}
            onError={() => setFailed(true)}
            className="size-full object-cover"
          />
        )}
      </span>
      <span className="block truncate px-1 py-0.5 text-[10.5px] text-muted-foreground">
        {label}
      </span>
    </button>
  );
}
