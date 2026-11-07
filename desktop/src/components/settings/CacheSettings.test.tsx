import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { confirmAction, pickDirectory } from "@/lib/dialogs";
import { Providers, stubBackend, type StubOptions } from "@/test/backend";
import { makeTask } from "@/test/tasks";

import { CacheSettings, cacheTarget } from "./CacheSettings";

vi.mock("@/lib/dialogs", () => ({
  pickDirectory: vi.fn(() => Promise.resolve("D:\\")),
  pickDatabaseFile: vi.fn(() => Promise.resolve(null)),
  confirmAction: vi.fn(() => Promise.resolve(true)),
}));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.mocked(confirmAction).mockClear();
  vi.mocked(pickDirectory).mockClear();
});

function renderSection(options: StubOptions = {}) {
  const backend = stubBackend(options);
  render(
    <Providers>
      <CacheSettings />
    </Providers>,
  );
  return backend;
}

const moves = (requests: { method: string; url: URL; body: unknown }[]) =>
  requests.filter((r) => r.method === "POST" && r.url.pathname === "/api/v1/cache/move");

describe("CacheSettings", () => {
  it("shows where the cache is and what it holds", async () => {
    renderSection();
    expect(await screen.findByText(/LUMEN Studio\\cache$/)).toBeInTheDocument();
    expect(screen.getByText("109 GB")).toBeInTheDocument();
    expect(screen.getByText(/预览图 103 GB · 缩略图 6.7 GB/)).toBeInTheDocument();
    expect(screen.getByText("所在磁盘剩余 80 GB")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "恢复默认" })).not.toBeInTheDocument();
  });

  it("moves the cache to a chosen drive after confirmation", async () => {
    const { requests } = renderSection();
    await userEvent.click(await screen.findByRole("button", { name: /更改/ }));
    expect(confirmAction).toHaveBeenCalledWith(
      expect.stringContaining("把 109 GB 的缓存移动到 D:\\LUMEN Studio\\cache？"),
      expect.anything(),
    );
    await waitFor(() =>
      expect(moves(requests)[0]?.body).toEqual({ folder: "D:\\LUMEN Studio\\cache" }),
    );
  });

  it("does nothing when the move is not confirmed", async () => {
    vi.mocked(confirmAction).mockResolvedValueOnce(false);
    const { requests } = renderSection();
    await userEvent.click(await screen.findByRole("button", { name: /更改/ }));
    await waitFor(() => expect(confirmAction).toHaveBeenCalledOnce());
    expect(moves(requests)).toHaveLength(0);
  });

  it("explains a target drive without enough space", async () => {
    renderSection({ cache: { noSpace: true } });
    await userEvent.click(await screen.findByRole("button", { name: /更改/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "目标磁盘空间不够：需要 114 GB，只剩 50 GB。",
    );
  });

  it("shows the move's progress and disables changes meanwhile", async () => {
    renderSection({
      tasks: [makeTask(7, "move_cache", { progress_current: 278_307, progress_total: 556_614 })],
    });
    expect(await screen.findByRole("status")).toHaveTextContent("正在移动缓存（50%）");
    expect(screen.getByRole("button", { name: /更改/ })).toBeDisabled();
  });

  it("moves the cache back to the default folder", async () => {
    const { requests } = renderSection({ cache: { folder: "D:\\LUMEN Studio\\cache" } });
    await userEvent.click(await screen.findByRole("button", { name: "恢复默认" }));
    await waitFor(() =>
      expect(moves(requests)[0]?.body).toEqual({
        folder: "C:\\Users\\me\\AppData\\Local\\LUMEN Studio\\cache",
      }),
    );
  });

  it("warns when the chosen folder's drive was missing at startup", async () => {
    renderSection({ cache: { folder: "D:\\LUMEN Studio\\cache", missing: true } });
    expect(
      await screen.findByText(/找不到设置的缓存文件夹 D:\\LUMEN Studio\\cache/),
    ).toBeInTheDocument();
  });
});

describe("cacheTarget", () => {
  it("puts the cache in its own folder on a drive root", () => {
    expect(cacheTarget("D:\\")).toBe("D:\\LUMEN Studio\\cache");
    expect(cacheTarget("D:")).toBe("D:\\LUMEN Studio\\cache");
    expect(cacheTarget("D:\\Cache")).toBe("D:\\Cache");
  });
});
