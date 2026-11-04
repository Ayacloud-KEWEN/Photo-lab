import { Album, FolderPlus, Plane, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import { useCollectionActions, useCollections } from "@/api/hooks";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useLibraryState, type CollectRequest } from "@/library/state";

/** Pick a collection (or make a new one) for the selected photos and videos. */
export function AddToCollectionDialog() {
  const { collectRequest, closeCollect } = useLibraryState();
  if (!collectRequest) return null;
  return <Body key={collectRequest.nonce} request={collectRequest} onClose={closeCollect} />;
}

function Body({ request, onClose }: { request: CollectRequest; onClose: () => void }) {
  const { t } = useTranslation();
  const rootRef = useRef<HTMLDivElement>(null);
  const collections = useCollections();
  const actions = useCollectionActions();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => rootRef.current?.focus(), []);

  const run = async (work: () => Promise<string>) => {
    setBusy(true);
    setError(null);
    try {
      setMessage(await work());
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };
  const addTo = (id: number, collectionName: string) =>
    run(async () => {
      const { changed } = await actions.add(id, request.assetIds);
      return t("collections.added", { count: changed, name: collectionName });
    });
  const create = () =>
    run(async () => {
      const created = await actions.create({
        name: name.trim(),
        kind: "album",
        asset_ids: request.assetIds,
      });
      return t("collections.added", { count: created.item_count, name: created.name });
    });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6">
      <div
        ref={rootRef}
        role="dialog"
        aria-modal
        aria-label={t("collections.addTo")}
        tabIndex={-1}
        onKeyDown={(event) => {
          if (event.key === "Escape") onClose();
          event.stopPropagation();
        }}
        className="w-[380px] max-w-full rounded-lg border bg-popover p-5 shadow-xl outline-none"
      >
        <div className="mb-3 flex items-center gap-2">
          <FolderPlus className="size-4 text-muted-foreground" />
          <h2 className="text-[14px] font-medium">{t("collections.addTo")}</h2>
          <span className="text-[12px] text-muted-foreground">
            {t("export.count", { count: request.assetIds.length })}
          </span>
          <Button
            variant="ghost"
            size="icon-sm"
            className="ml-auto"
            aria-label={t("export.close")}
            onClick={onClose}
          >
            <X />
          </Button>
        </div>

        {message ? (
          <div className="space-y-4 text-[12.5px]">
            <p>{message}</p>
            <div className="flex justify-end">
              <Button onClick={onClose}>{t("export.close")}</Button>
            </div>
          </div>
        ) : (
          <div className="space-y-3 text-[12.5px]">
            <ul className="max-h-64 space-y-px overflow-y-auto">
              {collections.data?.map((collection) => (
                <li key={collection.id}>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void addTo(collection.id, collection.name)}
                    className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left hover:bg-white/10"
                  >
                    {collection.kind === "trip" ? (
                      <Plane className="size-3.5 text-muted-foreground" />
                    ) : (
                      <Album className="size-3.5 text-muted-foreground" />
                    )}
                    <span className="min-w-0 flex-1 truncate">{collection.name}</span>
                    <span className="text-[11px] text-subtle-foreground">
                      {collection.item_count}
                    </span>
                  </button>
                </li>
              ))}
              {collections.data?.length === 0 && (
                <li className="px-2 py-1.5 text-muted-foreground">{t("collections.none")}</li>
              )}
            </ul>
            <form
              className="flex gap-2 border-t border-white/10 pt-3"
              onSubmit={(event) => {
                event.preventDefault();
                if (name.trim()) void create();
              }}
            >
              <Input
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={t("collections.newName")}
                aria-label={t("collections.newName")}
              />
              <Button type="submit" disabled={busy || !name.trim()}>
                {t("collections.create")}
              </Button>
            </form>
            {error && <p className="text-destructive">{error}</p>}
          </div>
        )}
      </div>
    </div>
  );
}
