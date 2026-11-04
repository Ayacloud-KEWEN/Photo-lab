import { useTranslation } from "react-i18next";

import { useSettings, useUpdateSettings } from "@/api/hooks";
import type { AppSettings } from "@/api/types";
import { cn } from "@/lib/utils";

export type MapStyle = AppSettings["map_style"];

/** Online: the OpenFreeMap styles of the same name. */
export const ONLINE_STYLES: readonly MapStyle[] = ["dark", "liberty", "bright", "positron"];
/** Offline there is a dark and a light country map; "positron" stands for the light one. */
export const OFFLINE_STYLES: readonly MapStyle[] = ["dark", "positron"];

/** The offline palette for a style: every online style but "dark" is light. */
export function offlinePalette(style: MapStyle): "dark" | "light" {
  return style === "dark" ? "dark" : "light";
}

/** Swatch colours (water / land) that hint at each style. */
const SWATCHES: Record<MapStyle, [string, string]> = {
  dark: ["#0e1114", "#2a2e33"],
  liberty: ["#9ecbe8", "#e9e4d4"],
  bright: ["#a8d4ef", "#f3efe4"],
  positron: ["#d4dde2", "#f7f6f3"],
};

/**
 * Basemap style choice, saved in the settings. Shows the four online styles when the online
 * map is on, otherwise the dark and light offline maps.
 */
export function BasemapPicker({ compact = false }: { compact?: boolean }) {
  const { t } = useTranslation();
  const settings = useSettings();
  const updateSettings = useUpdateSettings();
  const online = settings.data?.map_online_tiles ?? false;
  const style = settings.data?.map_style ?? "dark";
  const options = online ? ONLINE_STYLES : OFFLINE_STYLES;
  const selected = online ? style : offlinePalette(style) === "dark" ? "dark" : "positron";

  return (
    <div
      role="radiogroup"
      aria-label={t("map.basemap")}
      className={cn("flex", compact ? "gap-0.5" : "flex-wrap gap-2")}
    >
      {options.map((option) => {
        const active = option === selected;
        const [water, land] = SWATCHES[option];
        return (
          <button
            key={option}
            type="button"
            role="radio"
            aria-checked={active}
            disabled={!settings.data || updateSettings.isPending}
            onClick={() => {
              if (!active) updateSettings.mutate({ map_style: option });
            }}
            className={cn(
              "flex items-center gap-2 rounded-md text-[13px] transition-colors disabled:cursor-default",
              compact ? "h-7 px-2 text-xs" : "h-8 border px-3",
              active
                ? compact
                  ? "bg-accent text-foreground"
                  : "border-highlight/70 bg-accent text-foreground"
                : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
            )}
          >
            <span
              aria-hidden
              className="size-3.5 shrink-0 rounded-full border border-white/25"
              style={{ background: `linear-gradient(135deg, ${land} 50%, ${water} 50%)` }}
            />
            {online
              ? t(`map.styles.${option}`)
              : t(option === "dark" ? "map.styles.offlineDark" : "map.styles.offlineLight")}
          </button>
        );
      })}
    </div>
  );
}
