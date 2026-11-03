import { useId, type CSSProperties } from "react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";

import { formatSlider, type SliderSpec } from "./recipe";

/** One labelled adjustment. Double-clicking the label (or the slider) resets it. */
export function Slider({
  spec,
  value,
  onChange,
  onCommit,
  disabled = false,
}: {
  spec: SliderSpec;
  value: number;
  onChange: (value: number) => void;
  /** The drag (or key press) ended: a good moment to save. */
  onCommit: () => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const id = useId();
  const reset = () => {
    onChange(0);
    onCommit();
  };

  return (
    <div className={cn("group/slider py-1", disabled && "opacity-50")}>
      <div className="flex items-center justify-between text-[12px]">
        <label
          htmlFor={id}
          title={t("develop.resetSlider")}
          onDoubleClick={reset}
          className="cursor-default select-none text-muted-foreground"
        >
          {t(`develop.fields.${spec.key}`)}
        </label>
        <span
          className={cn(
            "tabular-nums text-[11.5px]",
            value === 0 ? "text-subtle-foreground" : "text-foreground",
          )}
        >
          {formatSlider(spec.key, value)}
        </span>
      </div>
      <input
        id={id}
        type="range"
        min={spec.min}
        max={spec.max}
        step={spec.step}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(Number(event.target.value))}
        onPointerUp={onCommit}
        onKeyUp={onCommit}
        onDoubleClick={reset}
        className="develop-slider w-full"
        style={spec.track ? ({ "--track": spec.track } as CSSProperties) : undefined}
      />
    </div>
  );
}
