import type { LucideIcon } from "lucide-react";
import { useTranslation } from "react-i18next";

interface PlaceholderPageProps {
  page: "timeline" | "map" | "aiSearch" | "collections";
  icon: LucideIcon;
  phase: string;
}

/** Shown for modules planned in later phases (see docs/phases.md). */
export function PlaceholderPage({ page, icon: Icon, phase }: PlaceholderPageProps) {
  const { t } = useTranslation();
  return (
    <div className="flex h-full flex-col items-center justify-center px-8 text-center">
      <Icon className="mb-5 size-9 text-subtle-foreground" strokeWidth={1.25} />
      <h1 className="text-lg font-medium">{t(`nav.${page}`)}</h1>
      <p className="mt-2 max-w-sm leading-relaxed text-muted-foreground">
        {t(`placeholder.${page}`)}
      </p>
      <span className="mt-5 rounded-full border px-2.5 py-0.5 text-[11px] text-subtle-foreground">
        {t("placeholder.comingIn", { phase })}
      </span>
    </div>
  );
}
