import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MapWebSettings } from "@/components/settings/MapWebSettings";
import { MapWebSync } from "@/components/settings/MapWebSync";
import { useLibraryState } from "@/library/state";
import { makeAsset, Providers, stubBackend, type Request } from "@/test/backend";

import { MapSendDialog } from "./MapSendDialog";

const assets = [1, 2, 3, 4, 5, 6].map((id) => makeAsset(id));
const sent = (requests: Request[]) =>
  requests.find((r) => r.url.pathname === "/api/v1/mapweb/send")?.body;

vi.mock("@/lib/dialogs", () => ({
  confirmAction: vi.fn(() => Promise.resolve(true)),
  pickDirectory: vi.fn(() => Promise.resolve(null)),
}));

function OpenOnMount({ ids, description }: { ids: number[]; description: string }) {
  const { openMapSend } = useLibraryState();
  useEffect(() => openMapSend(ids, { description }), [openMapSend, ids, description]);
  return null;
}

function renderDialog(ids: number[], onOpenSettings = () => {}) {
  render(
    <Providers>
      <OpenOnMount ids={ids} description="巴尔干半岛旅行" />
      <MapSendDialog onOpenSettings={onOpenSettings} />
    </Providers>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("MapSendDialog", () => {
  it("shows where the photos go and sends them in the background", async () => {
    const { requests } = stubBackend({ assets, mapweb: { url: "http://kevin:8788" } });
    renderDialog([1, 2, 3, 4, 5, 6]);
    const dialog = await screen.findByRole("dialog", { name: "发送到地图" });
    expect(await within(dialog).findByText("发送到 http://kevin:8788，按拍摄时间和位置放到足迹上：")).toBeInTheDocument();
    expect(within(dialog).getByText("加到已有足迹：1 个，共 2 张")).toBeInTheDocument();
    expect(within(dialog).getByText("Kotor 老城")).toBeInTheDocument();
    expect(within(dialog).getByText("新建足迹：1 个，共 3 张")).toBeInTheDocument();
    expect(within(dialog).getByText("1 张以前发过，跳过")).toBeInTheDocument();
    expect(within(dialog).getByText("1 个视频不发送（地图程序只收照片）")).toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole("button", { name: "发送 5 张" }));
    await waitFor(() =>
      expect(sent(requests)).toEqual({
        asset_ids: [1, 2, 3, 4, 5, 6],
        language: "zh-CN",
        description: "巴尔干半岛旅行",
      }),
    );
    expect(await within(dialog).findByRole("status")).toHaveTextContent(
      "已开始在后台发送 5 张，进度见底部状态栏。",
    );
  });

  it("asks for MapWeb's address first", async () => {
    const { requests } = stubBackend({ assets });
    const onOpenSettings = vi.fn();
    renderDialog([1, 2], onOpenSettings);
    const dialog = await screen.findByRole("dialog", { name: "发送到地图" });
    expect(await within(dialog).findByText("还没有设置地图程序（MapWeb）的地址。")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "去设置" }));
    expect(onOpenSettings).toHaveBeenCalledOnce();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(sent(requests)).toBeUndefined();
  });

  it("says when MapWeb cannot be reached", async () => {
    stubBackend({ assets, mapweb: { url: "http://kevin:8788", down: true } });
    renderDialog([1]);
    expect(await screen.findByRole("alert")).toHaveTextContent("连接不上 MapWeb（timed out）");
    expect(screen.queryByRole("button", { name: /^发送 / })).toBeDisabled();
  });
});

describe("MapWebSettings", () => {
  it("tests and saves the address", async () => {
    const { requests } = stubBackend({ assets });
    render(
      <Providers>
        <MapWebSettings />
      </Providers>,
    );
    const address = await screen.findByRole("textbox", { name: "MapWeb 地址" });
    await userEvent.type(address, "http://kevin:8788");
    await userEvent.click(screen.getByRole("button", { name: "测试连接" }));
    expect(await screen.findByRole("status")).toHaveTextContent("已连接 · 地图上有 310 个足迹");
    await userEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() =>
      expect(
        requests.find((r) => r.method === "PATCH" && r.url.pathname === "/api/v1/settings")?.body,
      ).toEqual({ mapweb_url: "http://kevin:8788" }),
    );
    expect(await screen.findByRole("button", { name: "移除" })).toBeInTheDocument();
  });
});

describe("MapWebSync", () => {
  it("shows the photos on the map, updates edited ones and turns automatic sending on", async () => {
    const { requests } = stubBackend({
      assets: [
        makeAsset(1, { on_map: "yes" }),
        makeAsset(2, { on_map: "outdated" }),
        makeAsset(3),
      ],
      mapweb: { url: "http://kevin:8788" },
    });
    render(
      <Providers>
        <MapWebSync />
      </Providers>,
    );
    const section = await screen.findByRole("region", { name: "和地图同步" });
    expect(within(section).getByRole("status")).toHaveTextContent(
      "图库里有 2 张照片在地图上 · 1 张发出后又修改过",
    );
    await userEvent.click(within(section).getByRole("button", { name: "更新地图上的旧版本（1）" }));
    await waitFor(() =>
      expect(requests.find((r) => r.url.pathname === "/api/v1/mapweb/update")?.body).toEqual({
        asset_ids: null,
      }),
    );
    await userEvent.click(within(section).getByRole("checkbox", { name: /自动发送到地图/ }));
    await waitFor(() =>
      expect(
        requests.find((r) => r.method === "PATCH" && r.url.pathname === "/api/v1/settings")?.body,
      ).toEqual({ mapweb_auto_send: true }),
    );
  });

  it("explains that an older map can only receive photos", async () => {
    stubBackend({ assets: [makeAsset(1)], mapweb: { url: "http://kevin:8788", old: true } });
    render(
      <Providers>
        <MapWebSync />
      </Providers>,
    );
    expect(await screen.findByText(/这台地图程序的版本较旧/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "检查地图上的照片" })).not.toBeInTheDocument();
  });
});
