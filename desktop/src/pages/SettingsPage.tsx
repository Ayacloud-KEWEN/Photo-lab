import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { useBackendStatus } from "@/api/backend-context";
import { useHealth, useSettings, useUpdateSettings } from "@/api/hooks";
import { CloudSettings, LocalAiSettings } from "@/components/settings/AiSettings";
import { LANGUAGES, setLanguage, type LanguageCode } from "@/i18n";
import { cn } from "@/lib/utils";

export function SettingsPage() {
  const { t, i18n } = useTranslation();
  const backend = useBackendStatus();
  const health = useHealth();
  const settings = useSettings();
  const updateSettings = useUpdateSettings();
  const online = settings.data?.map_online_tiles ?? false;

  const backendLabel =
    backend.state === "failed"
      ? t("status.failed")
      : health.data
        ? t("status.connected")
        : t("status.starting");

  return (
    <div className="h-full overflow-y-auto">
    <div className="mx-auto max-w-2xl px-8 py-7">
      <h1 className="text-lg font-medium">{t("settings.title")}</h1>

      <Section title={t("settings.language")}>
        <div role="radiogroup" aria-label={t("settings.language")} className="flex gap-2">
          {LANGUAGES.map((language) => {
            const active = i18n.language === language.code;
            return (
              <button
                key={language.code}
                type="button"
                role="radio"
                aria-checked={active}
                onClick={() => setLanguage(language.code as LanguageCode)}
                className={cn(
                  "h-8 rounded-md border px-3 text-[13px] transition-colors",
                  active
                    ? "border-highlight/70 bg-accent text-foreground"
                    : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
                )}
              >
                {language.label}
              </button>
            );
          })}
        </div>
        <p className="mt-2 text-xs text-subtle-foreground">{t("settings.languageHint")}</p>
      </Section>

      <Section title={t("settings.map")}>
        <label className="flex cursor-pointer items-start gap-3">
          <input
            type="checkbox"
            checked={online}
            disabled={!settings.data || updateSettings.isPending}
            onChange={(event) => updateSettings.mutate({ map_online_tiles: event.target.checked })}
            className="mt-0.5 size-4 accent-[var(--highlight)]"
          />
          <span>
            <span className="block text-[13px]">{t("settings.mapOnline")}</span>
            <span className="mt-1 block max-w-lg text-xs leading-relaxed text-subtle-foreground">
              {t("settings.mapOnlineHint")}
            </span>
          </span>
        </label>
      </Section>

      <Section title={t("settings.ai")}>
        <LocalAiSettings />
      </Section>

      <Section title={t("settings.cloud")}>
        <CloudSettings />
      </Section>

      <Section title={t("settings.about")}>
        <dl className="divide-y rounded-lg border bg-card">
          <Row label={t("settings.appVersion")}>{health.data?.app_version ?? "—"}</Row>
          <Row label={t("settings.apiVersion")}>{health.data?.api_version ?? "—"}</Row>
          <Row label={t("settings.schemaVersion")}>
            {health.data?.database.schema_version ?? "—"}
          </Row>
          <Row label={t("settings.backend")}>{backendLabel}</Row>
        </dl>
      </Section>
    </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-7">
      <h2 className="mb-3 text-[11px] font-medium uppercase tracking-wider text-subtle-foreground">
        {title}
      </h2>
      {children}
    </section>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between px-4 py-2.5">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="select-text font-mono text-[12px]">{children}</dd>
    </div>
  );
}
