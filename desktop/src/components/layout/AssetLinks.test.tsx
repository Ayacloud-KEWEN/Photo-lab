import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { makeAsset, makeDetail, Providers, root, stubBackend } from "@/test/backend";

import { AssetDetails } from "./Inspector";

afterEach(() => {
  vi.unstubAllGlobals();
});

const located = {
  ...makeDetail(makeAsset(3, { is_live: true })),
  location: { latitude: 48.8584, longitude: 2.2945, altitude_m: null, source: "exif" as const },
};

describe("AssetDetails links", () => {
  it("opens the location in Google Maps and shows each file in Explorer", async () => {
    const { requests } = stubBackend({ roots: [{ ...root, status: "ready" }] });
    render(
      <Providers>
        <AssetDetails asset={located} />
      </Providers>,
    );
    await userEvent.click(screen.getByRole("button", { name: "在谷歌地图中打开" }));
    const reveal = await screen.findAllByRole("button", { name: "在资源管理器中显示" });
    expect(reveal).toHaveLength(2); // the photo and its Live Photo clip
    await waitFor(() => expect(reveal[1]).toBeEnabled());
    await userEvent.click(reveal[1]!);
    await waitFor(() =>
      expect(requests.map((r) => `${r.method} ${r.url.pathname}`)).toEqual(
        expect.arrayContaining(["POST /api/v1/assets/3/open-map", "POST /api/v1/files/31/reveal"]),
      ),
    );
  });

  it("cannot show files whose drive is unplugged", async () => {
    stubBackend({ roots: [{ ...root, status: "offline", is_available: false }] });
    render(
      <Providers>
        <AssetDetails asset={located} />
      </Providers>,
    );
    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: "在资源管理器中显示" })[0]).toBeDisabled(),
    );
    expect(screen.getAllByRole("button", { name: "在资源管理器中显示" })[0]).toHaveAttribute(
      "title",
      "硬盘未连接",
    );
  });
});
