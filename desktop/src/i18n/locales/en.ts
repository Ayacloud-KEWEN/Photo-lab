import type { LocaleResource } from "../types";

const en: LocaleResource = {
  app: {
    name: "LUMEN Studio",
  },
  nav: {
    library: "Library",
    timeline: "Timeline",
    map: "Map",
    aiSearch: "AI Search",
    collections: "Collections",
    settings: "Settings",
  },
  topbar: {
    searchPlaceholder: "Search photos, places, cameras, tags…",
    showInspector: "Show inspector",
    hideInspector: "Hide inspector",
  },
  status: {
    starting: "Starting backend…",
    connected: "Backend connected",
    disconnected: "Backend connection lost",
    failed: "Backend failed to start",
    schema: "Database v{{version}}",
    roots_one: "{{count}} source",
    roots_other: "{{count}} sources",
  },
  inspector: {
    title: "Inspector",
    empty: "Select an item to see its details",
    path: "Path",
    status: "Status",
    availability: "Availability",
    available: "Reachable",
    unavailable: "Unreachable (drive disconnected?)",
    volumeLabel: "Volume label",
    volumeSerial: "Volume serial",
    addedAt: "Added",
    lastScanned: "Last scanned",
    never: "Never",
  },
  library: {
    title: "Library",
    subtitle_one: "{{count}} photo source",
    subtitle_other: "{{count}} photo sources",
    emptyTitle: "Start building your library",
    emptyDescription:
      "Choose a local folder that contains your photos. LUMEN Studio only reads files — it never moves, renames or modifies your originals.",
    emptyFormats: "Supports RAW, JPEG, HEIC, MP4 and MOV",
    selectFolder: "Choose photo folder",
    addFolder: "Add folder",
    pickerTitle: "Choose photo folder",
    sources: "Photo sources",
    remove: "Remove",
    removeConfirmTitle: "Remove photo source",
    removeConfirmMessage:
      "Remove “{{name}}” from the library?\n\nOnly LUMEN Studio's index records are deleted. Files on disk are not affected.",
    removeConfirmOk: "Remove",
    cancel: "Cancel",
    scanNotice:
      "Media scanning arrives in the next phase (Phase 2). Added folders are queued for scanning.",
    connecting: "Connecting to backend…",
    backendUnavailable: "Cannot reach the backend service: {{message}}",
    retry: "Retry",
    rootStatus: {
      pending_scan: "Waiting for scan",
      scanning: "Scanning",
      ready: "Ready",
      offline: "Offline",
      error: "Error",
    },
    errors: {
      conflict: "This folder is already added, or overlaps with a folder that is.",
      invalid_path: "This folder cannot be used: {{message}}",
      network_error: "Cannot reach the backend service.",
      generic: "Operation failed: {{message}}",
    },
  },
  placeholder: {
    comingIn: "Coming in {{phase}}",
    timeline: "Browse photos and videos by capture date.",
    map: "See geotagged photos on a map.",
    aiSearch: "Find photos by describing them, e.g. “a lake below snowy mountains”.",
    collections: "Organize photos into collections and travel projects.",
  },
  settings: {
    title: "Settings",
    language: "Interface language",
    languageHint: "Changes apply immediately.",
    about: "About",
    appVersion: "App version",
    apiVersion: "API version",
    schemaVersion: "Database schema version",
    backend: "Backend service",
  },
};

export default en;
