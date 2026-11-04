import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AddToCollectionDialog } from "@/components/collections/AddToCollectionDialog";
import { ExportDialog } from "@/components/library/ExportDialog";
import { useLibraryState } from "@/library/state";
import { makeAsset, Providers, stubBackend, type Request } from "@/test/backend";

import { CollectionsPage } from "./CollectionsPage";

vi.mock("@/lib/dialogs", () => ({
  pickDirectory: vi.fn(() => Promise.resolve("D:\\Exports")),
  confirmAction: vi.fn(() => Promise.resolve(true)),
}));

const assets = [1, 2, 3, 4].map((id) => makeAsset(id));
const calls = (requests: Request[], method: string, path: string) =>
  requests.filter((r) => r.method === method && r.url.pathname === path);

function renderPage() {
  render(
    <Providers>
      <CollectionsPage />
      <ExportDialog />
    </Providers>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("CollectionsPage", () => {
  it("creates an album and turns a suggested trip into a portfolio", async () => {
    const { requests } = stubBackend({
      assets,
      trips: [{ start: "2023-02-03", end: "2023-02-05", assetIds: [2, 3, 4], cities: ["采尔马特"] }],
    });
    renderPage();
    expect(await screen.findByText(/还没有作品集/)).toBeInTheDocument();

    const suggestions = await screen.findByRole("region", { name: "旅行建议" });
    expect(within(suggestions).getByText("3 项 · 距家约 514 公里")).toBeInTheDocument();
    await userEvent.click(within(suggestions).getByRole("button", { name: "创建旅行作品集" }));
    await waitFor(() =>
      expect(calls(requests, "POST", "/api/v1/collections")[0]?.body).toMatchObject({
        kind: "trip",
        start_date: "2023-02-03",
        end_date: "2023-02-05",
        asset_ids: [2, 3, 4],
        place: "采尔马特",
      }),
    );
    // The new trip opens, named after its place (offline place names).
    expect(await screen.findByRole("textbox", { name: "名称" })).toHaveValue(
      "采尔马特 · 2023年2月3日 – 2023年2月5日",
    );
    await userEvent.click(screen.getByRole("button", { name: "返回作品集" }));

    await userEvent.type(await screen.findByRole("textbox", { name: "新作品集名称" }), "精选");
    await userEvent.click(screen.getByRole("button", { name: "新建" }));
    expect(await screen.findByRole("textbox", { name: "名称" })).toHaveValue("精选");
    expect(screen.getByText(/这个作品集还是空的/)).toBeInTheDocument();
  });

  it("orders, captions, covers, removes and exports a portfolio's items", async () => {
    const { requests } = stubBackend({
      assets,
      collections: [{ name: "Alps", kind: "trip", assetIds: [1, 2, 3] }],
    });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /Alps/ }));
    const list = await screen.findByRole("list");
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(3);

    // Drag the third photo onto the first.
    fireEvent.dragStart(items[2]!);
    fireEvent.dragOver(items[0]!);
    fireEvent.drop(items[0]!);
    await waitFor(() =>
      expect(calls(requests, "PUT", "/api/v1/collections/1/order")[0]?.body).toEqual({
        asset_ids: [3, 1, 2],
      }),
    );

    const caption = screen.getByRole("textbox", { name: "IMG_1.JPG 的说明" });
    await userEvent.type(caption, "雪山");
    fireEvent.blur(caption);
    await waitFor(() =>
      expect(calls(requests, "PATCH", "/api/v1/collections/1/items/1")[0]?.body).toEqual({
        caption: "雪山",
      }),
    );

    const second = within(list).getAllByRole("listitem")[1]!;
    await userEvent.click(within(second).getByRole("button", { name: "设为封面" }));
    await waitFor(() =>
      expect(calls(requests, "PATCH", "/api/v1/collections/1").at(-1)?.body).toEqual({
        cover_asset_id: 1,
      }),
    );
    await userEvent.click(within(second).getByRole("button", { name: "从作品集中移除" }));
    await waitFor(() => expect(within(screen.getByRole("list")).getAllByRole("listitem")).toHaveLength(2));

    // Exports keep the portfolio's order in the file names.
    await userEvent.click(screen.getByRole("button", { name: "导出" }));
    const dialog = await screen.findByRole("dialog", { name: "导出" });
    expect(within(dialog).getByRole("checkbox", { name: "按顺序编号文件名（001_…）" })).toBeChecked();
    expect(within(dialog).getByText("2 项")).toBeInTheDocument();
  });

  it("deletes a portfolio after confirmation", async () => {
    const { requests } = stubBackend({ assets, collections: [{ name: "Old", assetIds: [1] }] });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /Old/ }));
    await userEvent.click(await screen.findByRole("button", { name: "删除作品集" }));
    await waitFor(() => expect(calls(requests, "DELETE", "/api/v1/collections/1")).toHaveLength(1));
    expect(await screen.findByText(/还没有作品集/)).toBeInTheDocument();
  });
});

function OpenOnMount({ ids }: { ids: number[] }) {
  const { openCollect } = useLibraryState();
  useEffect(() => openCollect(ids), [openCollect, ids]);
  return null;
}

describe("AddToCollectionDialog", () => {
  it("adds the selection to a portfolio or a new one", async () => {
    const { requests } = stubBackend({ assets, collections: [{ name: "Alps", assetIds: [1] }] });
    render(
      <Providers>
        <OpenOnMount ids={[1, 2]} />
        <AddToCollectionDialog />
      </Providers>,
    );
    const dialog = await screen.findByRole("dialog", { name: "加入作品集" });
    await userEvent.click(await within(dialog).findByRole("button", { name: /Alps/ }));
    expect(await within(dialog).findByText("已加入「Alps」（新增 1 项）")).toBeInTheDocument();
    expect(calls(requests, "POST", "/api/v1/collections/1/items")[0]?.body).toEqual({
      asset_ids: [1, 2],
    });
  });

  it("creates a portfolio with the selection", async () => {
    const { requests } = stubBackend({ assets });
    render(
      <Providers>
        <OpenOnMount ids={[3, 4]} />
        <AddToCollectionDialog />
      </Providers>,
    );
    const dialog = await screen.findByRole("dialog", { name: "加入作品集" });
    expect(await within(dialog).findByText("还没有作品集。")).toBeInTheDocument();
    await userEvent.type(within(dialog).getByRole("textbox"), "家人");
    await userEvent.click(within(dialog).getByRole("button", { name: "新建" }));
    expect(await within(dialog).findByText("已加入「家人」（新增 2 项）")).toBeInTheDocument();
    expect(calls(requests, "POST", "/api/v1/collections")[0]?.body).toEqual({
      name: "家人",
      kind: "album",
      asset_ids: [3, 4],
    });
  });
});
