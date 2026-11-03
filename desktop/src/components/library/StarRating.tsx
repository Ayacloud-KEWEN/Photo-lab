import { Star } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";

interface StarRatingProps {
  value: number;
  onChange: (rating: number) => void;
  size?: "sm" | "md";
  disabled?: boolean;
}

/** Five clickable stars; clicking the current rating clears it. Keys 0–5 work elsewhere. */
export function StarRating({ value, onChange, size = "md", disabled }: StarRatingProps) {
  const { t } = useTranslation();
  const [hover, setHover] = useState<number | null>(null);
  const shown = hover ?? value;
  return (
    <div
      role="radiogroup"
      aria-label={t("inspector.rating")}
      className="flex items-center"
      onMouseLeave={() => setHover(null)}
    >
      {[1, 2, 3, 4, 5].map((star) => (
        <button
          key={star}
          type="button"
          role="radio"
          aria-checked={value === star}
          aria-label={`${star}★`}
          disabled={disabled}
          onMouseEnter={() => setHover(star)}
          onClick={() => onChange(value === star ? 0 : star)}
          className={cn("p-0.5 disabled:opacity-50", size === "sm" ? "p-px" : "p-0.5")}
        >
          <Star
            className={cn(
              size === "sm" ? "size-3.5" : "size-4",
              star <= shown ? "fill-warning text-warning" : "text-subtle-foreground",
            )}
            strokeWidth={1.5}
          />
        </button>
      ))}
    </div>
  );
}
