import type { components } from "./schema";

type Schemas = components["schemas"];

export type HealthResponse = Schemas["HealthResponse"];
export type StorageRoot = Schemas["StorageRoot"];
export type StorageRootStatus = StorageRoot["status"];
export type StorageRootCreate = Schemas["StorageRootCreate"];
export type StorageRootList = Schemas["StorageRootList"];
export type ErrorBody = Schemas["ErrorBody"];
