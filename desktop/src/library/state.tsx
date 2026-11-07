import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

import type { AssetQuery, QueryPatch } from "@/api/query";
import type { AnalysisKind, EditRecipe, RecipeField } from "@/api/types";

/**
 * State shared across pages: filters (library, timeline, map, AI search), the
 * full-screen viewer, "find similar" and the cloud analysis dialog.
 */
interface LibraryState {
  query: AssetQuery;
  setQuery: (update: AssetQuery | ((current: AssetQuery) => AssetQuery)) => void;
  viewer: ViewerState | null;
  openViewer: (ids: readonly number[], id: number) => void;
  closeViewer: () => void;
  /** Asset whose look-alikes the AI search page shows (null: text search). */
  similarTo: SimilarRequest | null;
  findSimilar: (id: number | null) => void;
  cloudRequest: CloudDialogRequest | null;
  openCloud: (kind: AnalysisKind, assetIds: number[]) => void;
  closeCloud: () => void;
  /** Develop settings copied from one photo, to paste onto others. */
  copiedSettings: CopiedSettings | null;
  copySettings: (settings: CopiedSettings) => void;
  exportRequest: ExportDialogRequest | null;
  openExport: (assetIds: number[], options?: { numbered?: boolean }) => void;
  closeExport: () => void;
  /** Assets to add to a collection (the picker dialog is open while set). */
  collectRequest: CollectRequest | null;
  openCollect: (assetIds: number[]) => void;
  closeCollect: () => void;
  /** Photos whose location is being set (the location dialog is open while set). */
  locationRequest: AssetsRequest | null;
  openLocation: (assetIds: number[], current?: { lat: number; lon: number } | null) => void;
  closeLocation: () => void;
  /** Photos whose capture time is being corrected. */
  timeRequest: AssetsRequest | null;
  openTimeShift: (assetIds: number[], sampleTime?: string | null) => void;
  closeTimeShift: () => void;
  /** Photos to send to MapWeb (the send dialog is open while set). */
  mapSendRequest: MapSendRequest | null;
  openMapSend: (assetIds: number[], options?: { description?: string }) => void;
  closeMapSend: () => void;
}

export interface AssetsRequest {
  assetIds: number[];
  /** The photo's location (one photo): where the map starts. */
  current: { lat: number; lon: number } | null;
  /** A capture time to preview the shift with (one photo). */
  sampleTime: string | null;
  nonce: number;
}

export interface MapSendRequest {
  assetIds: number[];
  /** Text for new footprints (the portfolio's name). */
  description: string | null;
  nonce: number;
}

export interface CollectRequest {
  assetIds: number[];
  nonce: number;
}

export interface CopiedSettings {
  recipe: EditRecipe;
  fields: RecipeField[];
}

export interface ExportDialogRequest {
  assetIds: number[];
  /** Number the files in this order (exports of a collection). */
  numbered: boolean;
  nonce: number;
}

export interface ViewerState {
  ids: readonly number[];
  index: number;
  /** Changes on every open, so the viewer restarts even for the same photo. */
  nonce: number;
}

export interface SimilarRequest {
  id: number;
  /** Changes on every request, so the app navigates even for the same photo. */
  nonce: number;
}

export interface CloudDialogRequest {
  kind: AnalysisKind;
  assetIds: number[];
  nonce: number;
}

const LibraryContext = createContext<LibraryState | null>(null);

export function LibraryStateProvider({ children }: { children: ReactNode }) {
  const [query, setQuery] = useState<AssetQuery>({});
  const [viewer, setViewer] = useState<ViewerState | null>(null);
  const [similarTo, setSimilarTo] = useState<SimilarRequest | null>(null);
  const [cloudRequest, setCloudRequest] = useState<CloudDialogRequest | null>(null);
  const [copiedSettings, setCopiedSettings] = useState<CopiedSettings | null>(null);
  const [exportRequest, setExportRequest] = useState<ExportDialogRequest | null>(null);
  const [collectRequest, setCollectRequest] = useState<CollectRequest | null>(null);

  const openViewer = useCallback((ids: readonly number[], id: number) => {
    const index = ids.indexOf(id);
    setViewer({ ids, index: index < 0 ? 0 : index, nonce: Date.now() });
  }, []);
  const closeViewer = useCallback(() => setViewer(null), []);
  const findSimilar = useCallback(
    (id: number | null) => setSimilarTo(id === null ? null : { id, nonce: Date.now() }),
    [],
  );
  const openCloud = useCallback(
    (kind: AnalysisKind, assetIds: number[]) =>
      setCloudRequest({ kind, assetIds, nonce: Date.now() }),
    [],
  );
  const closeCloud = useCallback(() => setCloudRequest(null), []);
  const openExport = useCallback(
    (assetIds: number[], options: { numbered?: boolean } = {}) =>
      setExportRequest({ assetIds, numbered: options.numbered ?? false, nonce: Date.now() }),
    [],
  );
  const closeExport = useCallback(() => setExportRequest(null), []);
  const openCollect = useCallback(
    (assetIds: number[]) => setCollectRequest({ assetIds, nonce: Date.now() }),
    [],
  );
  const closeCollect = useCallback(() => setCollectRequest(null), []);
  const [locationRequest, setLocationRequest] = useState<AssetsRequest | null>(null);
  const openLocation = useCallback(
    (assetIds: number[], current: { lat: number; lon: number } | null = null) =>
      setLocationRequest({ assetIds, current, sampleTime: null, nonce: Date.now() }),
    [],
  );
  const closeLocation = useCallback(() => setLocationRequest(null), []);
  const [timeRequest, setTimeRequest] = useState<AssetsRequest | null>(null);
  const openTimeShift = useCallback(
    (assetIds: number[], sampleTime: string | null = null) =>
      setTimeRequest({ assetIds, current: null, sampleTime, nonce: Date.now() }),
    [],
  );
  const closeTimeShift = useCallback(() => setTimeRequest(null), []);
  const [mapSendRequest, setMapSendRequest] = useState<MapSendRequest | null>(null);
  const openMapSend = useCallback(
    (assetIds: number[], options: { description?: string } = {}) =>
      setMapSendRequest({ assetIds, description: options.description ?? null, nonce: Date.now() }),
    [],
  );
  const closeMapSend = useCallback(() => setMapSendRequest(null), []);

  const value = useMemo(
    () => ({
      query,
      setQuery,
      viewer,
      openViewer,
      closeViewer,
      similarTo,
      findSimilar,
      cloudRequest,
      openCloud,
      closeCloud,
      copiedSettings,
      copySettings: setCopiedSettings,
      exportRequest,
      openExport,
      closeExport,
      collectRequest,
      openCollect,
      closeCollect,
      mapSendRequest,
      openMapSend,
      closeMapSend,
      locationRequest,
      openLocation,
      closeLocation,
      timeRequest,
      openTimeShift,
      closeTimeShift,
    }),
    [
      query,
      viewer,
      openViewer,
      closeViewer,
      similarTo,
      findSimilar,
      cloudRequest,
      openCloud,
      closeCloud,
      copiedSettings,
      exportRequest,
      openExport,
      closeExport,
      collectRequest,
      openCollect,
      closeCollect,
      mapSendRequest,
      openMapSend,
      closeMapSend,
      locationRequest,
      openLocation,
      closeLocation,
      timeRequest,
      openTimeShift,
      closeTimeShift,
    ],
  );
  return <LibraryContext.Provider value={value}>{children}</LibraryContext.Provider>;
}

export function useLibraryState(): LibraryState {
  const state = useContext(LibraryContext);
  if (!state) throw new Error("useLibraryState must be used inside LibraryStateProvider");
  return state;
}

/** Remove keys whose value is undefined/empty so query keys stay stable. */
export function cleanQuery(query: QueryPatch): AssetQuery {
  return Object.fromEntries(
    Object.entries(query).filter(
      ([, value]) =>
        value !== undefined && value !== "" && !(Array.isArray(value) && value.length === 0),
    ),
  ) as AssetQuery;
}
