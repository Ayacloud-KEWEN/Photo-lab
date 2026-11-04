import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { BackendStatus } from "@/lib/backend";
import { fakeViewport, makeAsset, Providers, root, stubBackend } from "@/test/backend";

import { LibraryPage } from "./LibraryPage";

vi.mock("@/lib/dialogs", () => ({
  pickDirectory: vi.fn(() => Promise.resolve("D:\\Photos")),
  confirmAction: vi.fn(() => Promise.resolve(true)),
}));

function renderPage(status?: BackendStatus) {
  const onSelect = vi.fn();
  render(
    <Providers {...(status ? { status } : {})}>
      <LibraryPage selection={null} onSelect={onSelect} />
    </Providers>,
  );
  return { onSelect };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("LibraryPage", () => {
  it("shows the empty state and registers a picked folder", async () => {
    const { requests } = stubBackend();
    const { onSelect } = renderPage();

    const button = await screen.findByRole("button", { name: "选择照片文件夹" });
    expect(screen.getByText("开始建立你的照片库")).toBeInTheDocument();
    await userEvent.click(button);

    await waitFor(() => expect(onSelect).toHaveBeenCalledWith({ kind: "root", id: 7 }));
    const post = requests.find((r) => r.method === "POST");
    expect(post?.url.pathname).toBe("/api/v1/storage-roots");
    expect(post?.body).toEqual({ path: "D:\\Photos" });
    expect(await screen.findByText("D:\\Photos")).toBeInTheDocument();
    expect(screen.getByText("等待扫描")).toBeInTheDocument();
  });

  it("removes a folder after confirmation", async () => {
    stubBackend({ roots: [root] });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "移除 Photos" }));
    expect(await screen.findByText("开始建立你的照片库")).toBeInTheDocument();
  });

  it("shows media, selects with click, ctrl+click and shift+click", async () => {
    stubBackend({
      roots: [{ ...root, status: "ready" }],
      assets: [1, 2, 3, 4].map((id) => makeAsset(id)),
    });
    fakeViewport();
    const { onSelect } = renderPage();

    const first = await screen.findByRole("img", { name: "IMG_1.JPG" });
    expect(new URL(first.getAttribute("src")!).searchParams.get("token")).toBe("t");
    expect(screen.getByText("4 项")).toBeInTheDocument();

    await userEvent.click(first);
    await waitFor(() => expect(onSelect).toHaveBeenCalledWith({ kind: "asset", id: 1 }));
    fireEvent.click(screen.getByRole("img", { name: "IMG_3.JPG" }), { shiftKey: true });
    expect(await screen.findByText("已选择 3 项")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("img", { name: "IMG_2.JPG" }), { ctrlKey: true });
    expect(await screen.findByText("已选择 2 项")).toBeInTheDocument();
  });

  it("marks Live Photos on the wall", async () => {
    stubBackend({
      roots: [{ ...root, status: "ready" }],
      assets: [makeAsset(1, { is_live: true, formats: ["HEIC", "MOV"] }), makeAsset(2)],
    });
    fakeViewport();
    renderPage();

    await screen.findByRole("img", { name: "IMG_1.JPG" });
    expect(screen.getAllByRole("img", { name: "实况" })).toHaveLength(1);
  });

  it("marks edited photos on the wall", async () => {
    stubBackend({
      roots: [{ ...root, status: "ready" }],
      assets: [makeAsset(1, { is_edited: true }), makeAsset(2)],
    });
    fakeViewport();
    renderPage();

    await screen.findByRole("img", { name: "IMG_1.JPG" });
    expect(screen.getAllByRole("img", { name: "已编辑" })).toHaveLength(1);
  });

  it("plays a Live Photo's clip on the wall while its badge is hovered", async () => {
    stubBackend({
      roots: [{ ...root, status: "ready" }],
      assets: [makeAsset(1, { is_live: true, formats: ["HEIC", "MOV"] })],
    });
    fakeViewport();
    renderPage();

    const badge = await screen.findByRole("img", { name: "实况" });
    const tile = screen.getByRole("gridcell");
    expect(tile.querySelector("video")).toBeNull(); // nothing preloaded

    fireEvent.mouseEnter(badge);
    expect(tile.querySelector("video")).toBeNull(); // not before the hover delay
    await waitFor(() => expect(tile.querySelector("video")).not.toBeNull());
    const video = tile.querySelector("video")!;
    expect(new URL(video.src).pathname).toBe("/api/v1/assets/1/motion");
    expect(video.muted).toBe(true);
    fireEvent.playing(video);
    expect(badge).toHaveAttribute("data-playing", "true");

    fireEvent.mouseLeave(badge);
    expect(tile.querySelector("video")).toBeNull();

    fireEvent.mouseEnter(badge);
    await waitFor(() => expect(tile.querySelector("video")).not.toBeNull());
    fireEvent.error(tile.querySelector("video")!); // e.g. no HEVC decoder
    expect(tile.querySelector("video")).toBeNull();
    expect(screen.getByRole("img", { name: "IMG_1.JPG" })).toBeInTheDocument();
  });

  it("does not load a clip when the badge is only swept past", async () => {
    stubBackend({
      roots: [{ ...root, status: "ready" }],
      assets: [makeAsset(1, { is_live: true, formats: ["HEIC", "MOV"] })],
    });
    fakeViewport();
    renderPage();

    const badge = await screen.findByRole("img", { name: "实况" });
    fireEvent.mouseEnter(badge);
    fireEvent.mouseLeave(badge);
    await new Promise((resolve) => setTimeout(resolve, 400));
    expect(screen.getByRole("gridcell").querySelector("video")).toBeNull();
  });

  it("rates the selection from the keyboard and selects all with Ctrl+A", async () => {
    const { requests } = stubBackend({
      roots: [{ ...root, status: "ready" }],
      assets: [1, 2, 3].map((id) => makeAsset(id)),
    });
    fakeViewport();
    renderPage();

    await userEvent.click(await screen.findByRole("img", { name: "IMG_2.JPG" }));
    const wall = screen.getByRole("grid");
    fireEvent.keyDown(wall, { key: "4" });
    await waitFor(() =>
      expect(requests.find((r) => r.url.pathname === "/api/v1/assets/batch")?.body).toEqual({
        asset_ids: [2],
        rating: 4,
      }),
    );
    // X rejects (culling), P keeps.
    fireEvent.keyDown(wall, { key: "x" });
    await waitFor(() =>
      expect(
        requests.filter((r) => r.url.pathname === "/api/v1/assets/batch").map((r) => r.body),
      ).toContainEqual({ asset_ids: [2], cull_flag: "reject" }),
    );

    fireEvent.keyDown(wall, { key: "a", ctrlKey: true });
    expect(await screen.findByText("已选择 3 项")).toBeInTheDocument();
    fireEvent.keyDown(wall, { key: "Escape" });
    await waitFor(() => expect(screen.queryByText("已选择 3 项")).not.toBeInTheDocument());
  });

  it("applies a preset to the selection", async () => {
    const { requests } = stubBackend({
      roots: [{ ...root, status: "ready" }],
      assets: [1, 2, 3].map((id) => makeAsset(id)),
    });
    fakeViewport();
    renderPage();

    await userEvent.click(await screen.findByRole("img", { name: "IMG_1.JPG" }));
    fireEvent.click(screen.getByRole("img", { name: "IMG_3.JPG" }), { shiftKey: true });
    fireEvent.change(await screen.findByRole("combobox", { name: "应用预设…" }), {
      target: { value: "warm" },
    });
    await waitFor(() =>
      expect(requests.find((r) => r.url.pathname === "/api/v1/edits/batch")?.body).toEqual({
        asset_ids: [1, 2, 3],
        recipe: expect.objectContaining({ temperature: 25, tint: 5, vibrance: 10, exposure: 0 }),
        fields: ["temperature", "tint", "vibrance"],
      }),
    );
    expect(screen.getByRole("button", { name: "导出" })).toBeInTheDocument();
  });

  it("filters by media type", async () => {
    const { requests } = stubBackend({
      roots: [{ ...root, status: "ready" }],
      assets: [makeAsset(1)],
    });
    renderPage();
    await userEvent.click(await screen.findByRole("radio", { name: "视频" }));
    await waitFor(() =>
      expect(
        requests.some(
          (r) => r.url.pathname === "/api/v1/assets" && r.url.searchParams.get("media_type") === "video",
        ),
      ).toBe(true),
    );
  });

  it("explains when the backend failed to start", () => {
    renderPage({ state: "failed", message: "boom" });
    expect(screen.getByText("无法连接后端服务：boom")).toBeInTheDocument();
  });
});
