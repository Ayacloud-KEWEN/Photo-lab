import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { makeAsset, Providers, stubBackend } from "@/test/backend";

import { PeriplusLayers } from "./PeriplusLayers";

// The real MapLibre needs WebGL; the layers only need these few calls.
vi.mock("@/components/map/maplibre", () => {
  class LngLatBounds {
    west = Infinity;
    south = Infinity;
    east = -Infinity;
    north = -Infinity;
    constructor(a?: { lng: number; lat: number }, b?: { lng: number; lat: number }) {
      if (a) this.extend(a);
      if (b) this.extend(b);
    }
    extend(p: [number, number] | { lng: number; lat: number }) {
      const [lng, lat] = Array.isArray(p) ? p : [p.lng, p.lat];
      this.west = Math.min(this.west, lng);
      this.east = Math.max(this.east, lng);
      this.south = Math.min(this.south, lat);
      this.north = Math.max(this.north, lat);
      return this;
    }
    isEmpty() {
      return this.west === Infinity;
    }
    contains([lng, lat]: [number, number]) {
      return lng >= this.west && lng <= this.east && lat >= this.south && lat <= this.north;
    }
  }
  return { maplibregl: { LngLatBounds } };
});

type Handler = (event: unknown) => void;

function fakeMap() {
  const sources = new Map<string, { data: unknown }>();
  const layers = new Set<string>();
  const handlers = new Map<string, Handler[]>();
  const key = (event: string, layer?: string) => `${event}:${layer ?? ""}`;
  return {
    sources,
    layers,
    fitted: [] as unknown[],
    click(layer: string, properties: Record<string, unknown>) {
      handlers.get(key("click", layer))?.forEach((h) =>
        h({ features: [{ properties, geometry: { type: "Point", coordinates: [0, 0] } }] }),
      );
    },
    isStyleLoaded: () => true,
    getStyle: () => ({}),
    getCanvas: () => ({ style: {} as Record<string, string> }),
    getSource: (id: string) =>
      sources.has(id) ? { setData: (data: unknown) => sources.set(id, { data }) } : undefined,
    addSource(id: string, spec: { data: unknown }) {
      sources.set(id, { data: spec.data });
    },
    addLayer(layer: { id: string }) {
      layers.add(layer.id);
    },
    getLayer: (id: string) => layers.has(id),
    removeLayer: (id: string) => layers.delete(id),
    removeSource: (id: string) => sources.delete(id),
    on(event: string, layerOrHandler: string | Handler, handler?: Handler) {
      const k = typeof layerOrHandler === "string" ? key(event, layerOrHandler) : key(event);
      handlers.set(k, [...(handlers.get(k) ?? []), handler ?? (layerOrHandler as Handler)]);
    },
    off() {},
    fitBounds(bounds: unknown) {
      this.fitted.push(bounds);
    },
    easeTo() {},
    unproject: ([x, y]: [number, number]) => ({ lng: x / 10, lat: y / 10 }),
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("PeriplusLayers", () => {
  it("shows footprints, the photos that belong to one, and sends them there", async () => {
    const map = fakeMap();
    const { requests } = stubBackend({
      assets: [makeAsset(1), makeAsset(2, { on_map: "yes" })],
      mapweb: { url: "http://kevin:8788" },
    });
    render(
      <Providers>
        <PeriplusLayers map={map as never} points={[]} />
      </Providers>,
    );
    await userEvent.click(await screen.findByRole("button", { name: /Periplus/ }));
    const panel = screen.getByRole("group", { name: "Periplus 图层" });
    await userEvent.click(within(panel).getByRole("checkbox", { name: /足迹/ }));
    await waitFor(() => expect(map.layers.has("periplus-footprint-points")).toBe(true));
    expect((map.sources.get("periplus-footprints")!.data as { features: unknown[] }).features).toHaveLength(1);

    map.click("periplus-footprint-points", { id: 7 });
    const card = await screen.findByRole("complementary", { name: "详情" });
    expect(within(card).getByText(/Kotor 老城/)).toBeInTheDocument();
    // IMG_2 is on the map already; IMG_1 is picked to be sent.
    expect(await within(card).findByRole("checkbox", { name: "选中 IMG_1.JPG" })).toBeChecked();
    await userEvent.click(within(card).getByRole("button", { name: "发到这个足迹（1）" }));
    await waitFor(() =>
      expect(requests.find((r) => r.url.pathname === "/api/v1/mapweb/send")?.body).toEqual({
        asset_ids: [1],
        point_id: 7,
        language: "zh-CN",
      }),
    );
  });

  it("draws a plan with its stops, and sends the photos in a box", async () => {
    const map = fakeMap();
    stubBackend({ assets: [makeAsset(1), makeAsset(2)], mapweb: { url: "http://kevin:8788" } });
    render(
      <Providers>
        <PeriplusLayers
          map={map as never}
          points={[
            { id: 1, lat: 4, lon: 2, v: "v1", p: null },
            { id: 2, lat: 40, lon: 20, v: "v2", p: null },
          ]}
        />
      </Providers>,
    );
    await userEvent.click(await screen.findByRole("button", { name: /Periplus/ }));
    const select = await screen.findByRole("combobox", { name: "行程" });
    await waitFor(() => expect(within(select).getByRole("option", { name: /巴尔干/ })).toBeInTheDocument());
    await userEvent.selectOptions(select, "1");
    await waitFor(() => expect(map.layers.has("periplus-plan-stops")).toBe(true));
    expect(map.fitted).toHaveLength(1);
    map.click("periplus-plan-stops", { day: 1, index: 0 });
    const card = await screen.findByRole("complementary", { name: "详情" });
    expect(within(card).getByText("当天在附近拍了 1 张")).toBeInTheDocument();

    // A box around the first photo only (the fake map's coordinates are pixels / 10).
    await userEvent.click(screen.getByRole("button", { name: /框选发送/ }));
    const area = screen.getByRole("application", { name: "框选区域" });
    vi.spyOn(area, "getBoundingClientRect").mockReturnValue({ left: 0, top: 0 } as DOMRect);
    fireEvent.pointerDown(area, { clientX: 0, clientY: 0, pointerId: 1 });
    fireEvent.pointerMove(area, { clientX: 100, clientY: 100, pointerId: 1 });
    fireEvent.pointerUp(area, { clientX: 100, clientY: 100, pointerId: 1 });
    expect(screen.queryByRole("application", { name: "框选区域" })).not.toBeInTheDocument();
  });

  it("is hidden without a MapWeb address", () => {
    stubBackend({ assets: [] });
    render(
      <Providers>
        <PeriplusLayers map={fakeMap() as never} points={[]} />
      </Providers>,
    );
    expect(screen.queryByRole("button", { name: /Periplus/ })).not.toBeInTheDocument();
  });
});
