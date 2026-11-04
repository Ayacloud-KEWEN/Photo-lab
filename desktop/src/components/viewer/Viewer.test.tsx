import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useLibraryState } from "@/library/state";
import { makeAsset, Providers, root, stubBackend } from "@/test/backend";

import { Viewer } from "./Viewer";

function OpenOnMount({ ids, id }: { ids: number[]; id: number }) {
  const { openViewer } = useLibraryState();
  useEffect(() => openViewer(ids, id), [openViewer, ids, id]);
  return null;
}

const ids = [1, 2, 3];

function renderViewer(start = 2) {
  return render(
    <Providers>
      <OpenOnMount ids={ids} id={start} />
      <Viewer />
    </Providers>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Viewer", () => {
  it("says when the drive with the original is unplugged", async () => {
    stubBackend({
      assets: ids.map((id) => makeAsset(id)),
      roots: [{ ...root, display_name: "照片整理", status: "offline", is_available: false }],
    });
    renderViewer();
    expect(await screen.findByRole("status")).toHaveTextContent(
      "原图所在的硬盘（照片整理）未连接",
    );
  });

  it("shows the preview and moves with the arrow keys", async () => {
    stubBackend({ assets: ids.map((id) => makeAsset(id)) });
    renderViewer();

    const dialog = await screen.findByRole("dialog", { name: "IMG_2.JPG" });
    expect(screen.getByText("2 / 3")).toBeInTheDocument();
    const image = dialog.querySelector("img")!;
    expect(new URL(image.src).searchParams.get("variant")).toBe("preview");

    fireEvent.keyDown(dialog, { key: "ArrowRight" });
    expect(await screen.findByRole("dialog", { name: "IMG_3.JPG" })).toBeInTheDocument();
    fireEvent.keyDown(dialog, { key: "ArrowRight" }); // already last
    expect(screen.getByText("3 / 3")).toBeInTheDocument();
  });

  it("rates with number keys and closes with Escape", async () => {
    const { requests } = stubBackend({ assets: ids.map((id) => makeAsset(id)) });
    renderViewer(1);
    const dialog = await screen.findByRole("dialog", { name: "IMG_1.JPG" });

    fireEvent.keyDown(dialog, { key: "3" });
    await waitFor(() =>
      expect(requests.find((r) => r.method === "PATCH")).toMatchObject({ body: { rating: 3 } }),
    );
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("plays videos from the original file", async () => {
    stubBackend({ assets: [makeAsset(1, { media_type: "video", file_name: "clip.mp4" })] });
    render(
      <Providers>
        <OpenOnMount ids={[1]} id={1} />
        <Viewer />
      </Providers>,
    );
    const dialog = await screen.findByRole("dialog", { name: "clip.mp4" });
    await waitFor(() => expect(dialog.querySelector("video")).not.toBeNull());
    expect(new URL(dialog.querySelector("video")!.src).pathname).toBe("/api/v1/assets/1/original");
  });

  it("plays a Live Photo's clip over the still while LIVE is hovered", async () => {
    const play = vi
      .spyOn(HTMLMediaElement.prototype, "play")
      .mockImplementation(() => Promise.resolve());
    const pause = vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
    stubBackend({ assets: [makeAsset(1, { is_live: true, file_name: "IMG_1.HEIC" })] });
    render(
      <Providers>
        <OpenOnMount ids={[1]} id={1} />
        <Viewer />
      </Providers>,
    );
    const live = await screen.findByRole("button", { name: "悬停播放实况" });
    const dialog = screen.getByRole("dialog");
    const video = dialog.querySelector("video")!;
    expect(new URL(video.src).pathname).toBe("/api/v1/assets/1/motion");
    expect(video.muted).toBe(true);
    expect(dialog.querySelector("img")).not.toBeNull(); // the still stays underneath

    fireEvent.mouseEnter(live);
    expect(play).toHaveBeenCalledOnce();
    expect(live).toHaveAttribute("aria-pressed", "true");
    fireEvent.mouseLeave(live);
    expect(pause).toHaveBeenCalled();
    expect(live).toHaveAttribute("aria-pressed", "false");

    fireEvent.error(video); // e.g. no HEVC decoder: fall back to the still alone
    expect(screen.queryByRole("button", { name: "悬停播放实况" })).not.toBeInTheDocument();
    play.mockRestore();
    pause.mockRestore();
  });

  it("zooms with the wheel, double-click and Z, loading the full-size photo", async () => {
    stubBackend({
      assets: [makeAsset(1, { file_name: "IMG_1.HEIC", width: 4000, height: 3000 })],
    });
    render(
      <Providers>
        <OpenOnMount ids={[1]} id={1} />
        <Viewer />
      </Providers>,
    );
    const dialog = await screen.findByRole("dialog", { name: "IMG_1.HEIC" });
    const preview = await waitFor(() => {
      const image = dialog.querySelector("img");
      expect(image).not.toBeNull();
      return image!;
    });
    // jsdom loads no images: give the preview its size (the stage is 800 x 600).
    Object.defineProperty(preview, "naturalWidth", { value: 2048 });
    Object.defineProperty(preview, "naturalHeight", { value: 1536 });
    fireEvent.load(preview);
    const stage = dialog.querySelector<HTMLElement>("[data-zoom]")!;
    expect(stage.dataset.zoom).toBe("1.000");

    fireEvent.wheel(stage, { deltaY: -400, clientX: 400, clientY: 300 });
    expect(Number(stage.dataset.zoom)).toBeGreaterThan(1.5);
    expect(screen.getByText(/^\d+%$/)).toBeInTheDocument();
    // Zoomed in: the full-size rendition (HEIC cannot be shown by the webview).
    const variants = [...dialog.querySelectorAll("img")].map((image) =>
      new URL(image.src).searchParams.get("variant"),
    );
    expect(variants).toEqual(["preview", "full"]);

    fireEvent.keyDown(dialog, { key: "Escape" }); // first back to fit…
    expect(stage.dataset.zoom).toBe("1.000");
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    fireEvent.doubleClick(stage, { clientX: 400, clientY: 300 });
    expect(stage.dataset.zoom).toBe("5.000"); // 100%: 4000 px shown 800 px wide
    fireEvent.keyDown(dialog, { key: "z" });
    expect(stage.dataset.zoom).toBe("1.000");
    fireEvent.keyDown(dialog, { key: "Escape" }); // …then closes the viewer
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("shows ordinary photos without a LIVE button", async () => {
    stubBackend({ assets: [makeAsset(1)] });
    render(
      <Providers>
        <OpenOnMount ids={[1]} id={1} />
        <Viewer />
      </Providers>,
    );
    const dialog = await screen.findByRole("dialog", { name: "IMG_1.JPG" });
    await waitFor(() => expect(dialog.querySelector("img")).not.toBeNull());
    expect(screen.queryByRole("button", { name: "悬停播放实况" })).not.toBeInTheDocument();
    expect(dialog.querySelector("video")).toBeNull();
  });
});
