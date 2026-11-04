import { Ban, Check } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { CullFlag } from "@/api/types";
import { cn } from "@/lib/utils";

/** Keep (P) and reject (X) buttons; pressing the active one clears the flag. */
export function CullFlagToggle({
  value,
  onChange,
  dark = false,
}: {
  value: CullFlag;
  onChange: (flag: CullFlag) => void;
  /** On the viewer's black background. */
  dark?: boolean;
}) {
  const { t } = useTranslation();
  const button = (flag: "pick" | "reject") => {
    const active = value === flag;
    const Icon = flag === "pick" ? Check : Ban;
    return (
      <button
        type="button"
        aria-pressed={active}
        aria-label={t(`cull.${flag === "pick" ? "keep" : "reject"}`)}
        title={`${t(`cull.${flag === "pick" ? "keep" : "reject"}`)} (${flag === "pick" ? "P" : "X"})`}
        onClick={() => onChange(active ? "none" : flag)}
        className={cn(
          "rounded p-1 transition-colors",
          dark ? "hover:bg-white/10" : "hover:bg-accent",
          active && flag === "pick" && "text-emerald-400",
          active && flag === "reject" && "text-red-400",
          !active && "text-subtle-foreground",
        )}
      >
        <Icon className="size-4" />
      </button>
    );
  };
  return (
    <span className="flex items-center gap-0.5">
      {button("pick")}
      {button("reject")}
    </span>
  );
}
