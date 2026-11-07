import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useLibraryState } from "@/library/state";
import { makeAsset, Providers, stubBackend, type Request } from "@/test/backend";

import { LocationDialog, parseCoordinates } from "./LocationDialog";
import { shifted, TimeShiftDialog } from "./TimeShiftDialog";

// MapLibre needs WebGL: the picker shows its point and picks one when clicked.
vi.mock("@/components/map/LocationPicker", () => ({
  default: ({
    value,
    onPick,
  }: {
    value: { lat: number; lon: number } | null;
    onPick: (lat: number, lon: number) => void;
  }) => (
    <button type="button" onClick={() => onPick(42.4247, 18.7712)}>
      {value ? `pin ${value.lat.toFixed(3)},${value.lon.toFixed(3)}` : "no pin"}
    </button>
  ),
}));

const assets = [1, 2, 3].map((id) => makeAsset(id));
const body = (requests: Request[], path: string) =>
  requests.find((r) => r.url.pathname === path)?.body;

function Open({ kind, ids }: { kind: "location" | "time"; ids: number[] }) {
  const { openLocation, openTimeShift } = useLibraryState();
  useEffect(() => {
    if (kind === "location") openLocation(ids);
    else openTimeShift(ids, "2025-10-20T12:30:00");
  }, [kind, ids, openLocation, openTimeShift]);
  return null;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("location helpers", () => {
  it("reads coordinates as copied from a map", () => {
    expect(parseCoordinates("48.8566, 2.3522")).toEqual({ lat: 48.8566, lon: 2.3522 });
    expect(parseCoordinates(" -33.86 151.21 ")).toEqual({ lat: -33.86, lon: 151.21 });
    expect(parseCoordinates("91, 0")).toBeNull();
    expect(parseCoordinates("Paris")).toBeNull();
  });

  it("moves a capture time", () => {
    expect(shifted("2025-10-20T12:30:00", -7 * 3600)).toBe("2025-10-20T05:30:00");
    expect(shifted("2025-12-31T23:00:00", 3600)).toBe("2026-01-01T00:00:00");
  });
});

describe("LocationDialog", () => {
  it("sets a place found by name, on the map or typed as coordinates", async () => {
    const { requests } = stubBackend({ assets });
    render(
      <Providers>
        <Open kind="location" ids={[1, 2]} />
        <LocationDialog />
      </Providers>,
    );
    const dialog = await screen.findByRole("dialog", { name: "设置位置" });
    const save = within(dialog).getByRole("button", { name: "设为这个位置（2 张）" });
    expect(save).toBeDisabled();

    await userEvent.type(within(dialog).getByRole("textbox", { name: "搜索地点" }), "saraj");
    const results = await within(dialog).findByRole("list", { name: "搜索结果" });
    await userEvent.click(within(results).getByRole("button", { name: /塞拉耶佛/ }));
    expect(await within(dialog).findByText("pin 43.849,18.356")).toBeInTheDocument();
    expect(within(dialog).getByRole("textbox", { name: "坐标" })).toHaveValue("43.84864, 18.35644");

    await userEvent.click(within(dialog).getByRole("button", { name: /^pin/ }));
    const coordinates = within(dialog).getByRole("textbox", { name: "坐标" });
    expect(coordinates).toHaveValue("42.42470, 18.77120");
    await userEvent.clear(coordinates);
    await userEvent.type(coordinates, "48.8566, 2.3522");
    await userEvent.click(save);
    await waitFor(() =>
      expect(body(requests, "/api/v1/assets/location")).toEqual({
        asset_ids: [1, 2],
        latitude: 48.8566,
        longitude: 2.3522,
      }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("borrows locations by capture time after a preview", async () => {
    const { requests } = stubBackend({ assets });
    render(
      <Providers>
        <Open kind="location" ids={[1, 2, 3]} />
        <LocationDialog />
      </Providers>,
    );
    const dialog = await screen.findByRole("dialog", { name: "设置位置" });
    await userEvent.click(within(dialog).getByRole("radio", { name: /按时间借用/ }));
    expect(await within(dialog).findByText("2 张找到了附近有位置的照片 · 1 张附近没有")).toBeInTheDocument();
    await userEvent.selectOptions(within(dialog).getByRole("combobox"), "6");
    await waitFor(() =>
      expect(
        requests.filter((r) => r.url.pathname === "/api/v1/assets/location/nearby").at(-1)?.body,
      ).toEqual({ asset_ids: [1, 2, 3], max_hours: 6, apply: false }),
    );
    await userEvent.click(await within(dialog).findByRole("button", { name: "设置 2 张" }));
    await waitFor(() =>
      expect(
        requests.filter((r) => r.url.pathname === "/api/v1/assets/location/nearby").at(-1)?.body,
      ).toEqual({ asset_ids: [1, 2, 3], max_hours: 6, apply: true }),
    );
  });

  it("goes back to the photos' own location", async () => {
    const { requests } = stubBackend({ assets });
    render(
      <Providers>
        <Open kind="location" ids={[3]} />
        <LocationDialog />
      </Providers>,
    );
    const dialog = await screen.findByRole("dialog", { name: "设置位置" });
    await userEvent.click(within(dialog).getByRole("button", { name: "恢复为照片里的位置" }));
    await waitFor(() =>
      expect(body(requests, "/api/v1/assets/location/restore")).toEqual({ asset_ids: [3] }),
    );
  });
});

describe("TimeShiftDialog", () => {
  it("moves capture times and previews the result", async () => {
    const { requests } = stubBackend({ assets });
    render(
      <Providers>
        <Open kind="time" ids={[1]} />
        <TimeShiftDialog />
      </Providers>,
    );
    const dialog = await screen.findByRole("dialog", { name: "调整拍摄时间" });
    const apply = within(dialog).getByRole("button", { name: "调整 1 张" });
    expect(apply).toBeDisabled();
    await userEvent.selectOptions(within(dialog).getByRole("combobox", { name: "方向" }), "-1");
    const hours = within(dialog).getByRole("spinbutton", { name: "小时" });
    await userEvent.clear(hours);
    await userEvent.type(hours, "7");
    expect(within(dialog).getByRole("status")).toHaveTextContent("→");
    await userEvent.click(apply);
    await waitFor(() =>
      expect(body(requests, "/api/v1/assets/time-shift")).toEqual({
        asset_ids: [1],
        seconds: -25200,
      }),
    );
  });
});
