import { useQuery } from "@tanstack/react-query";
import { ChevronRight, Folder as FolderIcon, FolderOpen, HardDrive, Search, X } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { useConnection, useStorageRoots } from "@/api/hooks";
import type { AssetQuery, QueryPatch } from "@/api/query";
import type { Folder } from "@/api/types";
import { Input } from "@/components/ui/input";
import { formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Folders compare without case; "/" is the top of a library folder. */
const same = (a: string, b: string) => a.toLowerCase() === b.toLowerCase();

/**
 * The library by its folders on disk: library folders, then their subfolders (loaded as
 * they open), with a search over folder names. Choosing one filters the library.
 */
export function FolderPanel({
  query,
  onChange,
}: {
  query: AssetQuery;
  onChange: (patch: QueryPatch) => void;
}) {
  const { t } = useTranslation();
  const conn = useConnection();
  const roots = useStorageRoots();
  const [text, setText] = useState("");
  const wanted = text.trim();
  const found = useQuery({
    queryKey: ["library", "folders", "search", wanted],
    queryFn: () => api.searchFolders(conn!, wanted),
    enabled: !!conn && wanted.length > 0,
  });
  const choose = (rootId: number, path: string) =>
    onChange({ storage_root_id: rootId, folder: path, subfolders: query.subfolders });

  return (
    <aside
      aria-label={t("folders.title")}
      className="flex w-64 shrink-0 flex-col border-r border-white/10"
    >
      <div className="shrink-0 space-y-2 px-3 pb-2 pt-3">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            type="search"
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder={t("folders.search")}
            aria-label={t("folders.search")}
            className="h-8 pl-8 text-[12.5px]"
          />
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto pb-3 text-[12.5px]">
        {wanted ? (
          found.data?.items.length === 0 ? (
            <p className="px-4 py-2 text-muted-foreground">{t("folders.noMatch")}</p>
          ) : (
            <ul aria-label={t("folders.found")}>
              {found.data?.items.map((folder) => (
                <li key={`${folder.storage_root_id}:${folder.path}`}>
                  <button
                    type="button"
                    onClick={() => choose(folder.storage_root_id, folder.path)}
                    className="flex w-full flex-col px-4 py-1.5 text-left hover:bg-white/5"
                  >
                    <span className="flex items-center gap-1.5">
                      <FolderIcon className="size-3.5 shrink-0 text-muted-foreground" />
                      <span className="truncate font-medium">{folder.name}</span>
                      <Count value={folder.count} />
                    </span>
                    <span className="truncate pl-5 text-[11px] text-subtle-foreground">
                      {rootName(roots.data, folder.storage_root_id)}
                      {folder.path.includes("/") &&
                        ` › ${folder.path.split("/").slice(0, -1).join(" › ")}`}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )
        ) : (
          <ul role="tree" aria-label={t("folders.title")}>
            {roots.data?.map((root) => (
              <Node
                key={root.id}
                rootId={root.id}
                path="/"
                name={root.display_name}
                depth={0}
                query={query}
                onChoose={choose}
                isRoot
              />
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}

function rootName(roots: { id: number; display_name: string }[] | undefined, id: number) {
  return roots?.find((root) => root.id === id)?.display_name ?? "";
}

function Count({ value }: { value: number }) {
  const { i18n } = useTranslation();
  return (
    <span className="ml-auto shrink-0 pl-2 text-[11px] text-subtle-foreground">
      {formatNumber(value, i18n.language)}
    </span>
  );
}

function Node({
  rootId,
  path,
  name,
  depth,
  query,
  onChoose,
  folder,
  isRoot = false,
}: {
  rootId: number;
  path: string;
  name: string;
  depth: number;
  query: AssetQuery;
  onChoose: (rootId: number, path: string) => void;
  folder?: Folder;
  isRoot?: boolean;
}) {
  const conn = useConnection();
  const inside =
    query.storage_root_id === rootId &&
    query.folder !== undefined &&
    (path === "/" || same(query.folder, path) || query.folder.toLowerCase().startsWith(`${path.toLowerCase()}/`));
  const [open, setOpen] = useState(isRoot || inside);
  const expandable = isRoot || !!folder?.has_children;
  const children = useQuery({
    queryKey: ["library", "folders", rootId, path],
    queryFn: () => api.listFolders(conn!, rootId, path),
    enabled: !!conn && open && expandable,
  });
  const current =
    query.storage_root_id === rootId && query.folder !== undefined && same(query.folder, path);
  const Icon = isRoot ? HardDrive : current || open ? FolderOpen : FolderIcon;

  return (
    <li role="treeitem" aria-expanded={expandable ? open : undefined} aria-selected={current}>
      <div
        className={cn("flex items-center hover:bg-white/5", current && "bg-white/10")}
        style={{ paddingLeft: `${8 + depth * 14}px` }}
      >
        <button
          type="button"
          tabIndex={-1}
          aria-hidden
          disabled={!expandable}
          onClick={() => setOpen(!open)}
          className="flex size-5 shrink-0 items-center justify-center text-muted-foreground disabled:opacity-0"
        >
          <ChevronRight className={cn("size-3.5 transition-transform", open && "rotate-90")} />
        </button>
        <button
          type="button"
          onClick={() => {
            onChoose(rootId, path);
            if (expandable) setOpen(true);
          }}
          className="flex min-w-0 flex-1 items-center gap-1.5 py-1 pr-3 text-left"
        >
          <Icon className="size-3.5 shrink-0 text-muted-foreground" />
          <span className={cn("truncate", (current || isRoot) && "font-medium")}>{name}</span>
          {folder && <Count value={folder.count} />}
        </button>
      </div>
      {open && expandable && (
        <ul role="group">
          {children.data?.items.map((child) => (
            <Node
              key={child.path}
              rootId={rootId}
              path={child.path}
              name={child.name}
              depth={depth + 1}
              query={query}
              onChoose={onChoose}
              folder={child}
            />
          ))}
        </ul>
      )}
    </li>
  );
}

/** Above the photos while a folder is chosen: where, its subfolders or not, and clear. */
export function FolderCrumbs({
  query,
  onChange,
}: {
  query: AssetQuery;
  onChange: (patch: QueryPatch) => void;
}) {
  const { t } = useTranslation();
  const conn = useConnection();
  const roots = useStorageRoots();
  if (query.folder === undefined || query.storage_root_id === undefined) return null;
  const rootId = query.storage_root_id;
  const parts = query.folder.split("/").filter(Boolean);
  const go = (depth: number) => onChange({ folder: parts.slice(0, depth).join("/") || "/" });
  return (
    <nav
      aria-label={t("folders.path")}
      className="flex flex-wrap items-center gap-1 text-[12.5px] text-muted-foreground"
    >
      <FolderOpen className="size-3.5" />
      <button type="button" onClick={() => go(0)} className="hover:text-foreground">
        {rootName(roots.data, rootId)}
      </button>
      {parts.map((part, index) => (
        <span key={`${index}:${part}`} className="flex items-center gap-1">
          <ChevronRight className="size-3" />
          <button
            type="button"
            onClick={() => go(index + 1)}
            className={cn("hover:text-foreground", index === parts.length - 1 && "text-foreground")}
          >
            {part}
          </button>
        </span>
      ))}
      <label className="ml-3 flex items-center gap-1.5">
        <input
          type="checkbox"
          checked={query.subfolders !== false}
          onChange={(event) => onChange({ subfolders: event.target.checked ? undefined : false })}
        />
        {t("folders.subfolders")}
      </label>
      <button
        type="button"
        onClick={() => conn && void api.revealFolder(conn, rootId, query.folder ?? "")}
        className="ml-2 hover:text-foreground"
      >
        {t("folders.reveal")}
      </button>
      <button
        type="button"
        aria-label={t("folders.clear")}
        title={t("folders.clear")}
        onClick={() =>
          onChange({ storage_root_id: undefined, folder: undefined, subfolders: undefined })
        }
        className="ml-1 rounded p-0.5 hover:bg-white/10 hover:text-foreground"
      >
        <X className="size-3.5" />
      </button>
    </nav>
  );
}
