import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { StaticBackendProvider } from "@/api/backend-context";
import type { StorageRoot } from "@/api/types";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { BackendStatus } from "@/lib/backend";

import { LibraryPage } from "./LibraryPage";

vi.mock("@/lib/dialogs", () => ({
  pickDirectory: vi.fn(() => Promise.resolve("D:\\Photos")),
  confirmAction: vi.fn(() => Promise.resolve(true)),
}));

const ready: BackendStatus = { state: "ready", baseUrl: "http://127.0.0.1:1", token: "t" };

const root: StorageRoot = {
  id: 7,
  path: "D:\\Photos",
  display_name: "Photos",
  status: "pending_scan",
  is_available: true,
  volume_serial: "1234ABCD",
  volume_label: "Data",
  last_scanned_at: null,
  created_at: "2026-11-03T08:00:00.000Z",
  updated_at: "2026-11-03T08:00:00.000Z",
};

function renderPage(status: BackendStatus = ready) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onSelectRoot = vi.fn();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <StaticBackendProvider value={status}>
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>{children}</TooltipProvider>
      </QueryClientProvider>
    </StaticBackendProvider>
  );
  render(<LibraryPage selectedRootId={null} onSelectRoot={onSelectRoot} />, { wrapper });
  return { onSelectRoot };
}

/** Minimal in-memory backend for the storage-roots endpoints. */
function stubBackend(initial: StorageRoot[]) {
  let roots = [...initial];
  const fetch = vi.fn((url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (method === "GET") return Promise.resolve(Response.json({ items: roots }));
    if (method === "POST") {
      roots = [...roots, root];
      return Promise.resolve(Response.json(root, { status: 201 }));
    }
    roots = roots.filter((r) => !url.endsWith(`/${r.id}`));
    return Promise.resolve(new Response(null, { status: 204 }));
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("LibraryPage", () => {
  it("shows the empty state and registers a picked folder", async () => {
    const fetch = stubBackend([]);
    const { onSelectRoot } = renderPage();

    const button = await screen.findByRole("button", { name: "选择照片文件夹" });
    expect(screen.getByText("开始建立你的照片库")).toBeInTheDocument();

    await userEvent.click(button);

    await waitFor(() => expect(onSelectRoot).toHaveBeenCalledWith(7));
    expect(fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:1/api/v1/storage-roots",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ path: "D:\\Photos" }) }),
    );
    expect(await screen.findByText("D:\\Photos")).toBeInTheDocument();
    expect(screen.getByText("等待扫描")).toBeInTheDocument();
  });

  it("removes a folder after confirmation", async () => {
    stubBackend([root]);
    renderPage();

    await userEvent.click(await screen.findByRole("button", { name: "移除 Photos" }));

    expect(await screen.findByText("开始建立你的照片库")).toBeInTheDocument();
  });

  it("explains when the backend failed to start", () => {
    renderPage({ state: "failed", message: "boom" });
    expect(screen.getByText("无法连接后端服务：boom")).toBeInTheDocument();
  });
});
