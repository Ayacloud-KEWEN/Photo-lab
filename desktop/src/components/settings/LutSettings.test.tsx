import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode, useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Viewer } from "@/components/viewer/Viewer";
import { useLibraryState } from "@/library/state";
import { makeAsset, makeLut, Providers, stubBackend, type Request } from "@/test/backend";

import { LutSettings } from "./LutSettings";

vi.mock("@/lib/dialogs", () => ({
  pickDirectory: vi.fn(() => Promise.resolve("D:\\LUT")),
  pickDatabaseFile: vi.fn(() => Promise.resolve(null)),
  confirmAction: vi.fn(() => Promise.resolve(true)),
}));

afterEach(() => {
  vi.unstubAllGlobals();
});

const LUTS = [
  makeLut(1, { name: "LD - Pacific Coast 2", pack: "Lens Distortions" }),
  makeLut(2, { name: "Joker", pack: "Hollywood", used: 3 }),
  makeLut(3, { name: "Interstellar - Log-C", pack: "科幻片 Log LUT", kind: "log" }),
];

describe("LutSettings", () => {
  it("imports a folder and keeps LUTs for log footage apart", async () => {
    const { requests } = stubBackend({ luts: LUTS });
    render(
      <Providers>
        <LutSettings />
      </Providers>,
    );
    expect(await screen.findByText("可以直接用（2）")).toBeInTheDocument();
    expect(screen.getByText("需要 Log 素材（1）")).toBeInTheDocument();
    expect(screen.getByText(/Hollywood · 33³ · 3 项在用/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /选择文件夹/ }));
    expect(screen.getByDisplayValue("D:\\LUT")).toBeInTheDocument();
    fireEvent.change(screen.getAllByRole("combobox", { name: "色彩空间" })[0]!, {
      target: { value: "p3" },
    });
    await userEvent.click(screen.getByRole("button", { name: "导入" }));
    await waitFor(() =>
      expect(requests.find((r) => r.url.pathname === "/api/v1/luts/import")?.body).toEqual({
        paths: ["D:\\LUT"],
        color_space: "p3",
      }),
    );
    expect(await screen.findByText(/导入了 2 个，1 个已经导入过 · 1 个文件无法使用/)).toBeInTheDocument();

    const joker = screen.getByRole("listitem", { name: "Joker" });
    fireEvent.change(within(joker).getByRole("combobox", { name: "色彩空间" }), {
      target: { value: "p3" },
    });
    await waitFor(() =>
      expect(requests.find((r) => r.method === "PATCH")?.body).toEqual({ color_space: "p3" }),
    );
    await userEvent.click(within(joker).getByRole("button", { name: "删除" }));
    await waitFor(() => expect(requests.some((r) => r.method === "DELETE")).toBe(true));
  });
});

// --- Develop and video ------------------------------------------------------------------------

function OpenOnMount({ id }: { id: number }) {
  const { openViewer } = useLibraryState();
  useEffect(() => openViewer([id], id), [openViewer, id]);
  return null;
}

const saves = (requests: Request[]) =>
  requests.filter((r) => r.method === "PUT" && r.url.pathname.endsWith("/edit"));

describe("LUTs in Develop", () => {
  it("offers looks as small previews and saves the chosen one with its strength", async () => {
    const { requests } = stubBackend({ assets: [makeAsset(1)], luts: LUTS });
    render(
      <StrictMode>
        <Providers>
          <OpenOnMount id={1} />
          <Viewer />
        </Providers>
      </StrictMode>,
    );
    fireEvent.keyDown(await screen.findByRole("dialog", { name: "IMG_1.JPG" }), { key: "d" });
    const panel = await screen.findByRole("complementary", { name: "显影" });
    const group = await within(panel).findByRole("radiogroup", { name: "LUT" });
    // Log LUTs are left out unless asked for.
    expect(within(group).queryByRole("radio", { name: /Interstellar/ })).not.toBeInTheDocument();
    const joker = await within(group).findByRole("radio", { name: "Joker" });
    const preview = joker.querySelector("img")!;
    expect(new URL(preview.src).pathname).toBe("/api/v1/assets/1/lut-preview");
    expect(new URL(preview.src).searchParams.get("lut")).toBe(LUTS[1]!.ref);

    fireEvent.click(joker);
    await waitFor(() => expect(saves(requests).at(-1)?.body).toMatchObject({ lut: LUTS[1]!.ref }));
    const strength = within(panel).getByLabelText("LUT 强度");
    fireEvent.change(strength, { target: { value: "60" } });
    fireEvent.pointerUp(strength);
    await waitFor(() =>
      expect(saves(requests).at(-1)?.body).toMatchObject({ lut: LUTS[1]!.ref, lut_strength: 60 }),
    );

    await userEvent.click(within(panel).getByRole("checkbox", { name: /需要 Log 素材/ }));
    fireEvent.click(within(group).getByRole("radio", { name: /Interstellar/ }));
    expect(await within(panel).findByText(/给 Log 素材用的/)).toBeInTheDocument();
    fireEvent.click(within(group).getByRole("radio", { name: "无" }));
    await waitFor(() => expect(saves(requests).at(-1)?.body).toMatchObject({ lut: null }));
  });

  it("grades a video with a LUT and previews a frame", async () => {
    const { requests } = stubBackend({
      assets: [makeAsset(1, { media_type: "video", file_name: "clip.mp4", duration_ms: 8000 })],
      luts: LUTS,
    });
    render(
      <Providers>
        <OpenOnMount id={1} />
        <Viewer />
      </Providers>,
    );
    fireEvent.keyDown(await screen.findByRole("dialog", { name: "clip.mp4" }), { key: "d" });
    const panel = await screen.findByRole("complementary", { name: "视频剪辑" });
    const choose = await within(panel).findByRole("combobox", { name: "LUT" });
    expect(within(choose).queryByRole("option", { name: /Interstellar/ })).not.toBeInTheDocument();
    fireEvent.change(choose, { target: { value: LUTS[0]!.ref } });
    await userEvent.click(within(panel).getByRole("button", { name: "查看当前帧效果" }));
    await waitFor(() =>
      expect(
        requests.find((r) => r.method === "PUT" && r.url.pathname.endsWith("/video-edit"))?.body,
      ).toMatchObject({ lut: LUTS[0]!.ref }),
    );
    const frame = await within(panel).findByRole("img", { name: "查看当前帧效果" });
    expect(new URL(frame.getAttribute("src")!).pathname).toBe("/api/v1/assets/1/video-preview");
    expect(within(panel).getByText(/导出时才会套用 LUT/)).toBeInTheDocument();
  });
});
