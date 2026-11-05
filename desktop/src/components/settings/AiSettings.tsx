import { CheckCircle2, Cpu, KeyRound, Loader2, XCircle } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import {
  useActiveTasks,
  useAiActions,
  useAiStatus,
  useSettings,
  useUpdateSettings,
} from "@/api/hooks";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function LocalAiSettings() {
  const { t } = useTranslation();
  const status = useAiStatus();
  const settings = useSettings();
  const update = useUpdateSettings();
  const actions = useAiActions();
  const tasks = useActiveTasks();
  const local = status.data?.local;
  if (!local || !settings.data) return null;

  const download = tasks.data?.find((task) => task.kind === "ai_download_model");
  const indexing = tasks.data?.find((task) => task.kind === "ai_index_assets");
  const model = local.models.find((item) => item.id === local.model_id);

  return (
    <div className="space-y-3">
      <Toggle
        checked={local.enabled}
        disabled={!local.installed || update.isPending}
        onChange={(checked) => update.mutate({ ai_enabled: checked })}
        label={t("settings.aiEnable")}
        hint={local.installed ? t("settings.aiHint") : t("aiSearch.notInstalled")}
      />
      {local.installed && (
        <dl className="divide-y rounded-lg border bg-card text-[13px]">
          <Row label={t("settings.device")}>
            <span className="flex items-center gap-1.5">
              <Cpu className="size-3.5 text-muted-foreground" />
              {local.device === "cuda"
                ? `${local.device_name ?? "GPU"} · ${local.memory_gb ?? "?"} GB`
                : t("settings.deviceCpu")}
            </span>
          </Row>
          <Row label={t("settings.aiModel")}>
            <select
              aria-label={t("settings.aiModel")}
              value={settings.data.ai_model}
              disabled={update.isPending}
              onChange={(event) => update.mutate({ ai_model: event.target.value })}
              className="h-7 max-w-64 rounded-md border bg-background/60 px-2 text-xs"
            >
              {local.models.map((item) => (
                <option key={item.id} value={item.id} className="bg-popover">
                  {item.display_name}
                </option>
              ))}
            </select>
          </Row>
          <Row label="">
            {download ? (
              <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <Loader2 className="size-3.5 animate-spin text-highlight" />
                {t("status.taskAiDownload", {
                  done: gb(download.progress_current),
                  total: gb(download.progress_total ?? 0),
                })}
              </span>
            ) : local.model_downloaded ? (
              <span className="text-xs text-success">{t("settings.modelReady")}</span>
            ) : (
              <span className="flex items-center gap-2 text-xs text-muted-foreground">
                {t("settings.modelMissing", { size: model?.approx_download_gb ?? "?" })}
                <Button size="sm" variant="secondary" onClick={() => actions.download.mutate()}>
                  {t("settings.download")}
                </Button>
              </span>
            )}
          </Row>
          {local.enabled && local.model_downloaded && (
            <Row label="">
              <span className="flex items-center gap-2 text-xs text-muted-foreground">
                {indexing?.status === "running" && (
                  <Loader2 className="size-3.5 animate-spin text-highlight" />
                )}
                {t("settings.analysed", { indexed: local.indexed, total: local.total })}
                {indexing?.status === "pending" && (
                  <span className="text-subtle-foreground">· {t("settings.analyseQueued")}</span>
                )}
                {!indexing && local.indexed < local.total && (
                  <Button size="sm" variant="secondary" onClick={() => actions.index.mutate()}>
                    {t("settings.reindex")}
                  </Button>
                )}
              </span>
            </Row>
          )}
        </dl>
      )}
    </div>
  );
}

function gb(bytes: number): string {
  return (bytes / 1024 ** 3).toFixed(1);
}

export function CloudSettings() {
  const { t } = useTranslation();
  const status = useAiStatus();
  const settings = useSettings();
  const update = useUpdateSettings();
  const actions = useAiActions();
  const [key, setKey] = useState("");
  const [model, setModel] = useState<string | null>(null);
  const [baseUrl, setBaseUrl] = useState<string | null>(null);
  const cloud = status.data?.cloud;
  if (!cloud || !settings.data) return null;
  const test = actions.test.data;

  return (
    <div className="space-y-3">
      <Toggle
        checked={cloud.enabled}
        disabled={update.isPending}
        onChange={(checked) => update.mutate({ cloud_enabled: checked })}
        label={t("settings.cloudEnable")}
        hint={t("settings.cloudHint")}
      />
      <dl className="divide-y rounded-lg border bg-card text-[13px]">
        <Row label={t("settings.apiKey")}>
          {cloud.has_key ? (
            <span className="flex items-center gap-2">
              <span className="flex items-center gap-1 text-xs text-success">
                <KeyRound className="size-3.5" />
                {t("settings.apiKeySaved")}
              </span>
              <Button size="sm" variant="ghost" onClick={() => actions.deleteKey.mutate()}>
                {t("settings.remove")}
              </Button>
            </span>
          ) : (
            <form
              className="flex items-center gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                if (key.trim()) actions.saveKey.mutate(key.trim(), { onSuccess: () => setKey("") });
              }}
            >
              <Input
                type="password"
                autoComplete="off"
                value={key}
                placeholder="sk-…"
                aria-label={t("settings.apiKey")}
                onChange={(event) => setKey(event.target.value)}
                onKeyDown={(event) => event.stopPropagation()}
                className="h-7 w-56"
              />
              <Button size="sm" type="submit" disabled={key.trim().length < 8}>
                {t("settings.save")}
              </Button>
            </form>
          )}
        </Row>
        <Row label={t("settings.cloudModel")}>
          <TextSetting
            value={model ?? cloud.model}
            onChange={setModel}
            onCommit={(value) => update.mutate({ cloud_model: value })}
            label={t("settings.cloudModel")}
          />
        </Row>
        <Row label={t("settings.baseUrl")}>
          <TextSetting
            value={baseUrl ?? cloud.base_url}
            onChange={setBaseUrl}
            onCommit={(value) => update.mutate({ cloud_base_url: value })}
            label={t("settings.baseUrl")}
          />
        </Row>
        <Row label="">
          <span className="flex flex-col items-end gap-1.5">
            <Button
              size="sm"
              variant="secondary"
              disabled={!cloud.has_key || actions.test.isPending}
              onClick={() => actions.test.mutate()}
            >
              {actions.test.isPending && <Loader2 className="size-3.5 animate-spin" />}
              {actions.test.isPending ? t("settings.testing") : t("settings.test")}
            </Button>
            {test && (
              <span className="flex max-w-80 items-start gap-1.5 text-right text-xs">
                {test.ok && test.vision ? (
                  <CheckCircle2 className="mt-px size-3.5 shrink-0 text-success" />
                ) : (
                  <XCircle className="mt-px size-3.5 shrink-0 text-warning" />
                )}
                <span className="select-text">
                  {test.ok
                    ? test.vision
                      ? t("settings.visionYes")
                      : t("settings.visionNo")
                    : test.message}
                </span>
              </span>
            )}
          </span>
        </Row>
      </dl>
      <Toggle
        checked={settings.data.cloud_include_location}
        disabled={update.isPending}
        onChange={(checked) => update.mutate({ cloud_include_location: checked })}
        label={t("settings.locationDefault")}
      />
    </div>
  );
}

function TextSetting({
  value,
  onChange,
  onCommit,
  label,
}: {
  value: string;
  onChange: (value: string) => void;
  onCommit: (value: string) => void;
  label: string;
}) {
  return (
    <Input
      value={value}
      aria-label={label}
      onChange={(event) => onChange(event.target.value)}
      onBlur={(event) => event.target.value.trim() && onCommit(event.target.value.trim())}
      onKeyDown={(event) => {
        event.stopPropagation();
        if (event.key === "Enter") event.currentTarget.blur();
      }}
      className="h-7 w-64 font-mono text-xs"
    />
  );
}

function Toggle({
  checked,
  disabled,
  onChange,
  label,
  hint,
}: {
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  hint?: string;
}) {
  return (
    <label className="flex cursor-pointer items-start gap-3">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
        className="mt-0.5 size-4 accent-[var(--highlight)]"
      />
      <span>
        <span className="block text-[13px]">{label}</span>
        {hint && (
          <span className="mt-1 block max-w-lg select-text text-xs leading-relaxed text-subtle-foreground">
            {hint}
          </span>
        )}
      </span>
    </label>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-h-11 items-center justify-between gap-4 px-4 py-2">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="flex justify-end">{children}</dd>
    </div>
  );
}
