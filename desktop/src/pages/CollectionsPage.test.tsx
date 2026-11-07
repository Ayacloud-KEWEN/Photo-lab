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

// MapLibre needs WebGL: the map shows what it was given instead.
vi.mock("@/components/map/PhotoMap", () => ({
  default: (props: {
    points: { id: number }[];
    stops?: unknown[];
    focus?: { ids?: number[] } | null;
    children?: React.ReactNode;
  }) => (
    <div data-testid={props.stops ? "route-map" : "photo-map"}>
      {`points:${props.points.map((p) => p.id).join(",")}`}
      {props.stops && ` stops:${props.stops.length}`}
      {props.focus?.ids && ` focus:${props.focus.ids.join(",")}`}
      {props.children}
    </div>
  ),
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

  it("chooses the cover in a picker and goes back to the default", async () => {
    const { requests } = stubBackend({
      assets,
      collections: [{ name: "Alps", assetIds: [1, 2, 3] }],
    });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /Alps/ }));
    await userEvent.click(await screen.findByRole("button", { name: "封面" }));
    let picker = await screen.findByRole("dialog", { name: "选择封面" });
    expect(within(picker).getByRole("button", { name: "IMG_1.JPG" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(within(picker).getByRole("button", { name: "恢复默认（第一张）" })).toBeDisabled();
    await userEvent.click(within(picker).getByRole("button", { name: "IMG_3.JPG" }));
    await waitFor(() =>
      expect(calls(requests, "PATCH", "/api/v1/collections/1").at(-1)?.body).toEqual({
        cover_asset_id: 3,
      }),
    );
    expect(screen.queryByRole("dialog", { name: "选择封面" })).not.toBeInTheDocument();
    const third = within(await screen.findByRole("list")).getAllByRole("listitem")[2]!;
    await waitFor(() =>
      expect(within(third).getByRole("button", { name: "设为封面" })).toHaveAttribute(
        "aria-pressed",
        "true",
      ),
    );

    await userEvent.click(screen.getByRole("button", { name: "封面" }));
    picker = await screen.findByRole("dialog", { name: "选择封面" });
    await userEvent.click(within(picker).getByRole("button", { name: "恢复默认（第一张）" }));
    await waitFor(() =>
      expect(calls(requests, "PATCH", "/api/v1/collections/1").at(-1)?.body).toEqual({
        cover_asset_id: null,
      }),
    );
  });

  it("shows a portfolio's photos on a map and its route by day", async () => {
    stubBackend({
      assets,
      collections: [{ name: "Alps", kind: "trip", assetIds: [1, 2, 3] }],
      located: { 1: [46.02, 7.75], 3: [46.5, 8.0] },
    });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /Alps/ }));
    const views = await screen.findByRole("tablist", { name: "视图" });

    await userEvent.click(within(views).getByRole("tab", { name: "地图" }));
    const map = await screen.findByTestId("photo-map");
    expect(map).toHaveTextContent("points:1,3");
    expect(map).toHaveTextContent("1 张没有位置信息，未显示在地图上");

    await userEvent.click(within(views).getByRole("tab", { name: "路线" }));
    expect(await screen.findByTestId("route-map")).toHaveTextContent("stops:2");
    const list = screen.getByRole("complementary", { name: "路线" });
    expect(within(list).getByText("2 个地点 · 2 天 · 约 1,234 公里")).toBeInTheDocument();
    const day = within(list).getByRole("region", { name: "第 1 天" });
    await userEvent.click(within(day).getByRole("button", { name: /采尔马特/ }));
    expect(screen.getByTestId("route-map")).toHaveTextContent("focus:1");
    expect(within(list).getByRole("region", { name: "第 2 天" })).toHaveTextContent("未命名地点");

    await userEvent.click(within(views).getByRole("tab", { name: "照片" }));
    expect(await screen.findByRole("list")).toBeInTheDocument();
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
