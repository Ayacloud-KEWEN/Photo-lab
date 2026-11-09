import { EyeOff, FolderOpen, Loader2, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import { useLutActions, useLuts } from "@/api/hooks";
import type { Lut, LutKind, LutSpace } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { pickDirectory } from "@/lib/dialogs";

const KINDS: LutKind[] = ["look", "log", "transform"];

/**
 * The LUT library: import .cube files (a whole folder at once), say which colour space
 * each expects, hide or delete them. LUTs for log footage are kept apart.
 */
export function LutSettings() {
  const { t } = useTranslation();
  const luts = useLuts();
  const { importLuts, update, remove } = useLutActions();
  const [path, setPath] = useState("");
  const [space, setSpace] = useState<LutSpace>("rec709");

  const groups = useMemo(() => {
    const byKind = new Map<LutKind, Lut[]>(KINDS.map((kind) => [kind, []]));
    for (const lut of luts.data ?? []) byKind.get(lut.kind)?.push(lut);
    return byKind;
  }, [luts.data]);
  const browse = async () => {
    const folder = await pickDirectory(t("lut.pickFolder"));
    if (folder) setPath(folder);
  };
  const result = importLuts.data;
  const error = importLuts.error instanceof ApiError ? importLuts.error.message : null;

  return (
    <div className="space-y-4">
      <p className="max-w-lg text-xs leading-relaxed text-subtle-foreground">{t("lut.hint")}</p>
      <div className="flex max-w-xl flex-wrap items-center gap-2">
        <Input
          aria-label={t("lut.importPath")}
          placeholder="D:\LUT"
          value={path}
          onChange={(event) => setPath(event.target.value)}
          className="h-8 min-w-56 flex-1 font-mono text-[12px]"
        />
        <Button size="sm" variant="outline" onClick={() => void browse()}>
          <FolderOpen className="size-3.5" />
          {t("lut.browse")}
        </Button>
        <select
          aria-label={t("lut.space")}
          value={space}
          onChange={(event) => setSpace(event.target.value as LutSpace)}
          className="h-8 rounded-md border border-input bg-background/60 px-2 text-xs"
        >
          <option value="rec709">Rec.709 / sRGB</option>
          <option value="p3">Display P3</option>
        </select>
        <Button
          size="sm"
          disabled={!path.trim() || importLuts.isPending}
          onClick={() => importLuts.mutate({ paths: [path.trim()], colorSpace: space })}
        >
          {importLuts.isPending && <Loader2 className="size-3.5 animate-spin" />}
          {t("lut.import")}
        </Button>
      </div>
      {result && (
        <p role="status" className="text-xs text-muted-foreground">
          {t("lut.imported", { count: result.imported, already: result.already })}
          {result.failed.length > 0 && ` · ${t("lut.failed", { count: result.failed.length })}`}
        </p>
      )}
      {result && result.failed.length > 0 && (
        <details className="max-w-xl text-[11.5px] text-subtle-foreground">
          <summary className="cursor-pointer">{t("lut.failedList")}</summary>
          <ul className="mt-1 space-y-0.5">
            {result.failed.map((line) => (
              <li key={line} className="break-all">
                {line}
              </li>
            ))}
          </ul>
        </details>
      )}
      {error && <p role="alert" className="text-xs text-destructive">{error}</p>}

      {KINDS.map((kind) => {
        const items = groups.get(kind) ?? [];
        if (items.length === 0) return null;
        return (
          <details key={kind} open={kind === "look"} className="max-w-2xl">
            <summary className="cursor-pointer text-[13px]">
              {t(`lut.group_${kind}`, { count: items.length })}
            </summary>
            {kind !== "look" && (
              <p className="mt-1 text-xs text-subtle-foreground">{t(`lut.groupHint_${kind}`)}</p>
            )}
            <ul className="mt-2 max-h-96 divide-y overflow-y-auto rounded-lg border bg-card">
              {items.map((lut) => (
                <li
                  key={lut.id}
                  className="flex items-center gap-2 px-3 py-1.5 text-[12.5px]"
                  aria-label={lut.name}
                >
                  <span className="min-w-0 flex-1">
                    <span className={lut.hidden ? "text-subtle-foreground line-through" : ""}>
                      {lut.name}
                    </span>
                    <span className="block truncate text-[11px] text-subtle-foreground">
                      {[lut.pack, `${lut.size}³`, lut.used ? t("lut.used", { count: lut.used }) : null]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                  </span>
                  <select
                    aria-label={t("lut.space")}
                    value={lut.color_space}
                    onChange={(event) =>
                      update.mutate({
                        id: lut.id,
                        body: { color_space: event.target.value as LutSpace },
                      })
                    }
                    className="h-7 rounded border border-input bg-background/60 px-1 text-[11.5px]"
                  >
                    <option value="rec709">Rec.709</option>
                    <option value="p3">P3</option>
                  </select>
                  <select
                    aria-label={t("lut.kind")}
                    value={lut.kind}
                    onChange={(event) =>
                      update.mutate({ id: lut.id, body: { kind: event.target.value as LutKind } })
                    }
                    className="h-7 rounded border border-input bg-background/60 px-1 text-[11.5px]"
                  >
                    {KINDS.map((option) => (
                      <option key={option} value={option}>
                        {t(`lut.kind_${option}`)}
                      </option>
                    ))}
                  </select>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-pressed={lut.hidden}
                    title={lut.hidden ? t("lut.show") : t("lut.hide")}
                    aria-label={lut.hidden ? t("lut.show") : t("lut.hide")}
                    onClick={() => update.mutate({ id: lut.id, body: { hidden: !lut.hidden } })}
                  >
                    <EyeOff className="size-3.5" />
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    title={lut.used ? t("lut.deleteUsed") : t("lut.delete")}
                    aria-label={t("lut.delete")}
                    onClick={() => remove.mutate(lut.id)}
                  >
                    <Trash2 className="size-3.5" />
                  </Button>
                </li>
              ))}
            </ul>
          </details>
        );
      })}
    </div>
  );
}
