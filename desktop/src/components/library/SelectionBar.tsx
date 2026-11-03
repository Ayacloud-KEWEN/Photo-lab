import { BookOpen, Heart, HeartOff, Trophy, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useBatchUpdate } from "@/api/hooks";
import { Button } from "@/components/ui/button";
import { useLibraryState } from "@/library/state";

import { StarRating } from "./StarRating";
import { TagInput } from "./TagInput";

interface SelectionBarProps {
  ids: number[];
  onClear: () => void;
  onError: (error: unknown) => void;
}

/** Batch actions for a multi-selection. */
export function SelectionBar({ ids, onClear, onError }: SelectionBarProps) {
  const { t } = useTranslation();
  const batch = useBatchUpdate();
  const { openCloud } = useLibraryState();
  const apply = (changes: { rating?: number; is_favorite?: boolean; add_tags?: string[] }) =>
    batch.mutateAsync({ asset_ids: ids, ...changes }).catch(onError);

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-md border border-highlight/40 bg-highlight/10 px-3 py-1.5">
      <span className="text-xs font-medium">{t("selection.count", { count: ids.length })}</span>
      <StarRating size="sm" value={0} onChange={(rating) => void apply({ rating })} disabled={batch.isPending} />
      <Button variant="ghost" size="sm" onClick={() => void apply({ rating: 0 })} disabled={batch.isPending}>
        {t("selection.clearRating")}
      </Button>
      <Button variant="ghost" size="sm" onClick={() => void apply({ is_favorite: true })} disabled={batch.isPending}>
        <Heart className="size-3.5" />
        {t("selection.favorite")}
      </Button>
      <Button variant="ghost" size="sm" onClick={() => void apply({ is_favorite: false })} disabled={batch.isPending}>
        <HeartOff className="size-3.5" />
        {t("selection.unfavorite")}
      </Button>
      <TagInput
        placeholder={t("selection.addTag")}
        onAdd={(name) => void apply({ add_tags: [name] })}
        className="w-40"
      />
      {ids.length >= 2 && ids.length <= 12 && (
        <Button variant="ghost" size="sm" onClick={() => openCloud("select_best", ids)}>
          <Trophy className="size-3.5" />
          {t("ai.selectBest")}
        </Button>
      )}
      {ids.length >= 2 && ids.length <= 30 && (
        <Button variant="ghost" size="sm" onClick={() => openCloud("story", ids)}>
          <BookOpen className="size-3.5" />
          {t("ai.story")}
        </Button>
      )}
      <Button variant="ghost" size="sm" className="ml-auto" onClick={onClear}>
        <X className="size-3.5" />
        {t("selection.clear")}
      </Button>
    </div>
  );
}
