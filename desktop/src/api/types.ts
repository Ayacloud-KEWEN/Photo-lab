import type { components } from "./schema";

type Schemas = components["schemas"];

export type HealthResponse = Schemas["HealthResponse"];
export type StorageRoot = Schemas["StorageRoot"];
export type StorageRootStatus = StorageRoot["status"];
export type StorageRootCreate = Schemas["StorageRootCreate"];
export type StorageRootList = Schemas["StorageRootList"];
export type ErrorBody = Schemas["ErrorBody"];
export type StorageRootStats = Schemas["StorageRootStats"];
export type Task = Schemas["Task"];
export type TaskList = Schemas["TaskList"];
export type AssetSummary = Schemas["AssetSummary"];
export type AssetPage = Schemas["AssetPage"];
export type AssetDetail = Schemas["AssetDetail"];
export type AssetFile = Schemas["AssetFile"];
export type DuplicateReport = Schemas["DuplicateReport"];
export type RenditionVariant = "thumb" | "preview";
