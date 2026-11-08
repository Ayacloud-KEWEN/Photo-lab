import {
  ChevronRight,
  Clock,
  Cloud,
  FolderOpen,
  Heart,
  MapPinned,
  MapPinPlus,
  Pencil,
  ScanSearch,
  Sparkles,
  X,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";

import { thumbnailUrl } from "@/api/client";
import {
  useAiStatus,
  useAnalyses,
  useAsset,
  useBatchUpdate,
  useConnection,
  useShellActions,
  useStorageRoots,
  useUpdateAsset,
} from "@/api/hooks";
import { Result } from "@/components/ai/CloudDialog";
import type { AssetDetail, StorageRoot } from "@/api/types";
import { CullFlagToggle } from "@/components/library/CullFlagToggle";
import { PhotoDescription } from "@/components/library/PhotoDescription";
import { StarRating } from "@/components/library/StarRating";
import { Button } from "@/components/ui/button";
import { useLibraryState } from "@/library/state";
import { TagInput } from "@/components/library/TagInput";
import { formatBytes, formatDateTime, formatDuration, formatExposure } from "@/lib/format";
import { placeLine } from "@/lib/places";
import { cn } from "@/lib/utils";
import type { Selection } from "@/selection";

export function Inspector({ selection }: { selection: Selection }) {
  const { t } = useTranslation();
  const roots = useStorageRoots();
  const asset = useAsset(selection?.kind === "asset" ? selection.id : null);
  const root =
    selection?.kind === "root" ? roots.data?.find((item) => item.id === selection.id) : undefined;

  let content: ReactNode;
  if (root) content = <RootDetails root={root} />;
  else if (selection?.kind === "asset" && asset.data)
    content = <AssetDetails asset={asset.data} editable />;
  else
    content = (
      <p className="pt-8 text-center text-xs text-subtle-foreground">{t("inspector.empty")}</p>
    );

  return (
    <aside
      aria-label={t("inspector.title")}
      className="flex w-72 shrink-0 flex-col border-l bg-panel"
    >
      <div className="flex h-9 items-center border-b px-4 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
        {t("inspector.title")}
      </div>
      <div className="flex-1 overflow-y-auto p-4">{content}</div>
    </aside>
  );
}

function RootDetails({ root }: { root: StorageRoot }) {
  const { t, i18n } = useTranslation();
  return (
    <div className="space-y-4">
      <h2 className="break-words text-sm font-medium">{root.display_name}</h2>
      <dl className="space-y-3">
        <Field label={t("inspector.path")}>
          <span className="select-text break-all font-mono text-[11.5px]">{root.path}</span>
        </Field>
        <Field label={t("inspector.status")}>{t(`library.rootStatus.${root.status}`)}</Field>
        <Field label={t("inspector.availability")}>
          {root.is_available ? t("inspector.available") : t("inspector.unavailable")}
        </Field>
        <Field label={t("inspector.files")}>
          {t("library.stats.files", { count: root.stats.file_count })}
          {root.stats.error_count > 0 && (
            <span className="block text-destructive">
              {t("library.stats.errors", { count: root.stats.error_count })}
            </span>
          )}
          {root.stats.missing_count > 0 && (
            <span className="block text-warning">
              {t("library.stats.missing", { count: root.stats.missing_count })}
            </span>
          )}
        </Field>
        <Field label={t("inspector.volumeLabel")}>{root.volume_label ?? "—"}</Field>
        <Field label={t("inspector.volumeSerial")}>
          <span className="select-text font-mono text-[11.5px]">{root.volume_serial ?? "—"}</span>
        </Field>
        <Field label={t("inspector.addedAt")}>{formatDateTime(root.created_at, i18n.language)}</Field>
        <Field label={t("inspector.lastScanned")}>
          {root.last_scanned_at
            ? formatDateTime(root.last_scanned_at, i18n.language)
            : t("inspector.never")}
        </Field>
      </dl>
    </div>
  );
}

/** Asset metadata; with `editable`, also rating, favorite, tags and notes. */
export function AssetDetails({ asset, editable = false }: { asset: AssetDetail; editable?: boolean }) {
  const { t, i18n } = useTranslation();
  const conn = useConnection();
  const shell = useShellActions();
  const { openMapSend, openLocation, openTimeShift } = useLibraryState();
  const roots = useStorageRoots();
  const offline = new Set(roots.data?.filter((root) => !root.is_available).map((root) => root.id));
  const meta = asset.metadata;
  const cover = asset.files.find((file) => file.id === asset.cover_file_id) ?? asset.files[0];
  const name = cover?.relative_path.split(/[\\/]/).pop() ?? "";
  const camera = [meta.camera_make, meta.camera_model].filter(Boolean).join(" ");
  const exposure = [
    meta.aperture ? `f/${meta.aperture}` : null,
    meta.exposure_time_s ? formatExposure(meta.exposure_time_s) : null,
    meta.iso ? `ISO ${meta.iso}` : null,
    meta.focal_length_mm ? `${Math.round(meta.focal_length_mm)} mm` : null,
  ].filter(Boolean);
  const video = [
    meta.video_codec?.toUpperCase(),
    meta.frame_rate ? `${meta.frame_rate} fps` : null,
  ].filter(Boolean);

  return (
    <div className="space-y-4">
      {editable && conn && asset.rendition_version && (
        <img
          src={thumbnailUrl(conn, asset.id, asset.rendition_version)}
          alt={name}
          className="max-h-48 w-full rounded object-contain"
        />
      )}
      <h2 className="select-text break-all text-sm font-medium">{name}</h2>
      {editable && <Edits asset={asset} />}
      {editable && <AiActions asset={asset} />}
      <PhotoDescription asset={asset} />
      <dl className="space-y-3">
        {asset.capture_time && (
          <Field label={t("inspector.captureTime")}>
            <span className="flex items-center gap-1.5">
              <span>
                {formatDateTime(asset.capture_time, i18n.language)}
                {asset.time_shift_s !== 0 && (
                  <span className="text-subtle-foreground">
                    {" "}
                    · {t("inspector.shifted", { shift: describeShift(asset.time_shift_s, t) })}
                  </span>
                )}
              </span>
              <LinkButton
                label={t("timeShift.title")}
                hint={t("timeShift.title")}
                onClick={() => openTimeShift([asset.id], asset.capture_time)}
              >
                <Clock />
              </LinkButton>
            </span>
          </Field>
        )}
        {meta.width && meta.height && (
          <Field label={t("inspector.dimensions")}>
            {meta.width} × {meta.height}
          </Field>
        )}
        {meta.duration_ms ? (
          <Field label={t("inspector.duration")}>{formatDuration(meta.duration_ms)}</Field>
        ) : null}
        {video.length > 0 && <Field label={t("inspector.video")}>{video.join(" · ")}</Field>}
        {camera && <Field label={t("inspector.camera")}>{camera}</Field>}
        {meta.lens_model && <Field label={t("inspector.lens")}>{meta.lens_model}</Field>}
        {exposure.length > 0 && (
          <Field label={t("inspector.exposure")}>{exposure.join(" · ")}</Field>
        )}
        {asset.quality && (
          <Field label={t("inspector.quality")}>
            {[
              t("cull.sharpness", { value: Math.round(asset.quality.sharpness * 100) }),
              t("cull.exposure", { value: Math.round(asset.quality.exposure * 100) }),
              ...asset.quality.flags.map((flag) => t(`cull.quality_${flag}`)),
            ].join(" · ")}
          </Field>
        )}
        {asset.place && (
          <Field label={t("inspector.place")}>
            <span className="select-text">
              {placeLine([asset.place.city, asset.place.region, asset.place.country], i18n.language)}
            </span>
          </Field>
        )}
        {asset.location && (
          <Field label={t("inspector.location")}>
            <span className="flex items-center gap-1.5">
              <span className="select-text font-mono text-[11.5px]">
                {asset.location.latitude.toFixed(5)}, {asset.location.longitude.toFixed(5)}
              </span>
              {asset.location.source === "manual" && (
                <span className="text-[11px] text-subtle-foreground">{t("inspector.manual")}</span>
              )}
              <LinkButton
                label={t("location.edit")}
                hint={t("location.edit")}
                onClick={() =>
                  openLocation([asset.id], {
                    lat: asset.location!.latitude,
                    lon: asset.location!.longitude,
                  })
                }
              >
                <Pencil />
              </LinkButton>
              <LinkButton
                label={t("inspector.openMap")}
                hint={t("inspector.openMapHint")}
                onClick={() => shell.openMap.mutate(asset.id)}
              >
                <MapPinned />
              </LinkButton>
              {asset.media_type === "photo" && (
                <LinkButton
                  label={t("mapweb.send")}
                  hint={t("mapweb.sendHint")}
                  onClick={() => openMapSend([asset.id])}
                >
                  <MapPinPlus />
                </LinkButton>
              )}
            </span>
          </Field>
        )}
        {!asset.location && (
          <Field label={t("inspector.location")}>
            <button
              type="button"
              onClick={() => openLocation([asset.id])}
              className="flex items-center gap-1 text-[12px] text-highlight hover:underline"
            >
              <MapPinPlus className="size-3.5" />
              {t("location.add")}
            </button>
          </Field>
        )}
        {!editable && asset.tags.length > 0 && (
          <Field label={t("inspector.tags")}>{asset.tags.map((tag) => tag.name).join(", ")}</Field>
        )}
        <Field label={t("inspector.files")}>
          <ul className="space-y-2">
            {asset.files.map((file) => (
              <li key={file.id}>
                <span className="flex items-center gap-1.5 text-[11px] text-subtle-foreground">
                  {t(`inspector.fileRole.${file.role}`)} ·{" "}
                  {formatBytes(file.size_bytes, i18n.language)}
                  {file.status === "missing" && (
                    <span className="text-warning">· {t("inspector.fileMissing")}</span>
                  )}
                  {file.ingest_state === "error" && (
                    <span className="text-destructive" title={file.ingest_error ?? undefined}>
                      · {t("inspector.fileError")}
                    </span>
                  )}
                </span>
                <span className="flex items-start gap-1">
                  <span
                    className={cn(
                      "min-w-0 flex-1 select-text break-all font-mono text-[11px]",
                      file.status === "missing" && "line-through opacity-60",
                    )}
                  >
                    {file.path}
                  </span>
                  <LinkButton
                    label={t("inspector.reveal")}
                    hint={
                      offline.has(file.storage_root_id)
                        ? t("inspector.revealOffline")
                        : file.status === "missing"
                          ? t("inspector.fileMissing")
                          : t("inspector.reveal")
                    }
                    disabled={offline.has(file.storage_root_id) || file.status === "missing"}
                    onClick={() => shell.reveal.mutate(file.id)}
                  >
                    <FolderOpen />
                  </LinkButton>
                </span>
              </li>
            ))}
          </ul>
        </Field>
      </dl>
    </div>
  );
}

function Edits({ asset }: { asset: AssetDetail }) {
  const { t } = useTranslation();
  const update = useUpdateAsset();
  const batch = useBatchUpdate();
  const [notes, setNotes] = useState(asset.notes ?? "");
  useEffect(() => setNotes(asset.notes ?? ""), [asset.id, asset.notes]);

  const saveNotes = () => {
    if (notes.trim() !== (asset.notes ?? "")) {
      update.mutate({ id: asset.id, changes: { notes } });
    }
  };

  return (
    <div className="space-y-3 border-y py-3">
      <div className="flex items-center justify-between">
        <StarRating
          value={asset.rating}
          onChange={(rating) => update.mutate({ id: asset.id, changes: { rating } })}
        />
        <button
          type="button"
          aria-pressed={asset.is_favorite}
          aria-label={t("inspector.favorite")}
          title={`${t("inspector.favorite")} (F)`}
          onClick={() =>
            update.mutate({ id: asset.id, changes: { is_favorite: !asset.is_favorite } })
          }
          className="rounded p-1 hover:bg-accent"
        >
          <Heart
            className={cn(
              "size-4",
              asset.is_favorite ? "fill-destructive text-destructive" : "text-subtle-foreground",
            )}
          />
        </button>
        <CullFlagToggle
          value={asset.cull_flag}
          onChange={(flag) => update.mutate({ id: asset.id, changes: { cull_flag: flag } })}
        />
      </div>

      <div>
        <div className="mb-1.5 text-[11px] text-subtle-foreground">{t("inspector.tags")}</div>
        {asset.tags.length > 0 && (
          <ul className="mb-2 flex flex-wrap gap-1">
            {asset.tags.map((tag) => (
              <li
                key={tag.id}
                className="flex items-center gap-1 rounded bg-accent py-0.5 pl-2 pr-1 text-[11.5px]"
                title={
                  tag.source === "import"
                    ? t("inspector.importedTag")
                    : tag.source === "ai"
                      ? t("ai.label", { value: Math.round((tag.confidence ?? 0) * 100) })
                      : undefined
                }
              >
                {tag.source === "ai" && <Sparkles className="size-3 text-highlight" />}
                {tag.name}
                <button
                  type="button"
                  aria-label={t("inspector.removeTag", { name: tag.name })}
                  onClick={() => batch.mutate({ asset_ids: [asset.id], remove_tag_ids: [tag.id] })}
                  className="rounded p-0.5 text-subtle-foreground hover:bg-background/50 hover:text-foreground"
                >
                  <X className="size-3" />
                </button>
              </li>
            ))}
          </ul>
        )}
        <TagInput
          placeholder={t("inspector.addTag")}
          onAdd={(name) => batch.mutate({ asset_ids: [asset.id], add_tags: [name] })}
        />
      </div>

      <div>
        <label htmlFor="asset-notes" className="mb-1.5 block text-[11px] text-subtle-foreground">
          {t("inspector.notes")}
        </label>
        <textarea
          id="asset-notes"
          value={notes}
          placeholder={t("inspector.notesPlaceholder")}
          onChange={(event) => setNotes(event.target.value)}
          onBlur={saveNotes}
          onKeyDown={(event) => event.stopPropagation()}
          rows={3}
          maxLength={10_000}
          className="w-full resize-y rounded-md border border-input bg-background/60 px-2.5 py-1.5 text-[12.5px] outline-none placeholder:text-subtle-foreground focus-visible:border-ring/70"
        />
      </div>
    </div>
  );
}

/** "+7 小时", "-1 天 2 小时 30 分钟": a capture time correction in words. */
function describeShift(seconds: number, t: TFunction): string {
  const total = Math.abs(seconds);
  const parts = [
    [Math.floor(total / 86400), "timeShift.days"],
    [Math.floor((total % 86400) / 3600), "timeShift.hours"],
    [Math.floor((total % 3600) / 60), "timeShift.minutes"],
  ] as const;
  const text = parts
    .filter(([value]) => value > 0)
    .map(([value, key]) => `${value} ${t(key)}`)
    .join(" ");
  return `${seconds < 0 ? "-" : "+"}${text}`;
}

/** A small icon button next to a value (opens something outside the app). */
function LinkButton({
  label,
  hint,
  disabled = false,
  onClick,
  children,
}: {
  label: string;
  hint: string;
  disabled?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={hint}
      disabled={disabled}
      onClick={onClick}
      className="-my-0.5 shrink-0 rounded p-0.5 text-subtle-foreground hover:bg-accent hover:text-foreground disabled:pointer-events-none disabled:opacity-40 [&_svg]:size-3.5"
    >
      {children}
    </button>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="mb-0.5 text-[11px] text-subtle-foreground">{label}</dt>
      <dd className="text-[12.5px] text-foreground">{children}</dd>
    </div>
  );
}

function AiActions({ asset }: { asset: AssetDetail }) {
  const { t, i18n } = useTranslation();
  const status = useAiStatus();
  const analyses = useAnalyses(asset.id);
  const { findSimilar, openCloud } = useLibraryState();
  const [open, setOpen] = useState<number | null>(null);
  const local = status.data?.local;
  const aiReady = !!local && local.enabled && local.model_downloaded;

  return (
    <div className="space-y-2 border-b pb-3">
      {aiReady && (
        <Button variant="secondary" size="sm" className="w-full" onClick={() => findSimilar(asset.id)}>
          <ScanSearch className="size-3.5" />
          {t("ai.findSimilar")}
        </Button>
      )}
      <div className="flex items-center gap-1.5">
        <span className="flex items-center gap-1 text-[11px] text-subtle-foreground">
          <Cloud className="size-3" />
          {t("ai.cloud")}
        </span>
        <Button variant="ghost" size="sm" className="ml-auto" onClick={() => openCloud("describe", [asset.id])}>
          {t("ai.describe")}
        </Button>
        <Button variant="ghost" size="sm" onClick={() => openCloud("critique", [asset.id])}>
          {t("ai.critique")}
        </Button>
      </div>
      {(analyses.data?.length ?? 0) > 0 && (
        <div>
          <div className="mb-1 text-[11px] text-subtle-foreground">{t("ai.history")}</div>
          <ul className="space-y-1">
            {analyses.data!.map((analysis) => (
              <li key={analysis.id} className="rounded border bg-card">
                <button
                  type="button"
                  aria-expanded={open === analysis.id}
                  onClick={() => setOpen(open === analysis.id ? null : analysis.id)}
                  className="flex w-full items-center gap-1.5 px-2 py-1 text-left text-[11.5px]"
                >
                  <ChevronRight
                    className={cn("size-3 transition-transform", open === analysis.id && "rotate-90")}
                  />
                  {t(`ai.${kindKey(analysis.kind)}`)}
                  <span className="ml-auto text-subtle-foreground">
                    {formatDateTime(analysis.created_at, i18n.language)}
                  </span>
                </button>
                {open === analysis.id && (
                  <div className="border-t px-2 py-2">
                    <Result result={analysis} />
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function kindKey(kind: string): "describe" | "critique" | "selectBest" | "story" {
  if (kind === "select_best") return "selectBest";
  return kind as "describe" | "critique" | "story";
}
