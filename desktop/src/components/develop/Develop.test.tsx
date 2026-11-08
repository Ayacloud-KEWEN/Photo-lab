import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { StrictMode, useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Viewer } from "@/components/viewer/Viewer";
import { useLibraryState } from "@/library/state";
import { makeAsset, Providers, stubBackend, type Request } from "@/test/backend";

function OpenOnMount({ ids, id }: { ids: number[]; id: number }) {
  const { openViewer } = useLibraryState();
  useEffect(() => openViewer(ids, id), [openViewer, ids, id]);
  return null;
}

// StrictMode, like the app: effects must survive React's development-mode remount.
function renderViewer(ids = [1, 2]) {
  return render(
    <StrictMode>
      <Providers>
        <OpenOnMount ids={ids} id={ids[0]!} />
        <Viewer />
      </Providers>
    </StrictMode>,
  );
}

const previews = (requests: Request[]) =>
  requests.filter((r) => r.url.pathname.endsWith("/develop/preview"));
const saves = (requests: Request[]) =>
  requests.filter((r) => r.method === "PUT" && r.url.pathname.endsWith("/edit"));

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Develop", () => {
  it("chooses a Live Photo's frame and effect", async () => {
    const { requests } = stubBackend({
      assets: [makeAsset(1, { is_live: true, file_name: "IMG_1.HEIC", width: 4032, height: 3024 })],
    });
    renderViewer([1]);
    const dialog = await screen.findByRole("dialog", { name: "IMG_1.HEIC" });
    fireEvent.keyDown(dialog, { key: "d" });
    const panel = await screen.findByRole("complementary", { name: "显影" });
    const live = await within(panel).findByRole("region", { name: "实况" });
    expect(within(live).getByRole("radio", { name: "实况" })).toHaveAttribute("aria-checked", "true");
    expect(await within(live).findByText("原照片")).toBeInTheDocument();

    // Dragging over the frames shows the clip at once; letting go saves the frame.
    const frame = await within(live).findByRole("slider", { name: "封面帧" });
    expect(frame).toHaveValue("5"); // the still's position
    fireEvent.change(frame, { target: { value: "3" } });
    expect(document.querySelector("video[src*='/motion']")).not.toBeNull();
    fireEvent.pointerUp(frame);
    await waitFor(() => expect(saves(requests).at(-1)?.body).toMatchObject({ live_frame_ms: 300 }));
    expect(within(live).getByText("此帧 1920×1440（原照片 4032×3024）")).toBeInTheDocument();
    await waitFor(() =>
      expect(previews(requests).at(-1)?.body).toMatchObject({ recipe: { live_frame_ms: 300 } }),
    );

    fireEvent.click(within(live).getByRole("button", { name: /最清晰的一帧/ }));
    await waitFor(() => expect(saves(requests).at(-1)?.body).toMatchObject({ live_frame_ms: 700 }));
    fireEvent.click(within(live).getByRole("button", { name: /用原照片/ }));
    await waitFor(() => expect(saves(requests).at(-1)?.body).toMatchObject({ live_frame_ms: null }));

    // A loop plays as it will look; a long exposure has no frame to choose.
    fireEvent.click(within(live).getByRole("radio", { name: "循环" }));
    await waitFor(() => expect(saves(requests).at(-1)?.body).toMatchObject({ live_effect: "loop" }));
    expect(within(live).getByLabelText("实况效果预览").getAttribute("src")).toContain("effect=loop");
    fireEvent.click(within(live).getByRole("radio", { name: "长曝光" }));
    await waitFor(() =>
      expect(saves(requests).at(-1)?.body).toMatchObject({ live_effect: "long_exposure" }),
    );
    expect(within(live).queryByRole("slider", { name: "封面帧" })).not.toBeInTheDocument();
    expect(within(live).getByText(/把整段实况叠成一张照片/)).toBeInTheDocument();
  });

  it("has no Live group for ordinary photos", async () => {
    stubBackend({ assets: [makeAsset(1)] });
    renderViewer([1]);
    fireEvent.keyDown(await screen.findByRole("dialog", { name: "IMG_1.JPG" }), { key: "d" });
    const panel = await screen.findByRole("complementary", { name: "显影" });
    await within(panel).findByLabelText("曝光");
    expect(within(panel).queryByRole("region", { name: "实况" })).not.toBeInTheDocument();
  });

  it("edits a photo: live preview, saved history, undo and leaving", async () => {
    const { requests } = stubBackend({ assets: [makeAsset(1), makeAsset(2)] });
    renderViewer();
    const dialog = await screen.findByRole("dialog", { name: "IMG_1.JPG" });

    fireEvent.keyDown(dialog, { key: "d" });
    const panel = await screen.findByRole("complementary", { name: "显影" });
    expect(within(panel).getByText("JPG")).toBeInTheDocument();
    await waitFor(() => expect(previews(requests).length).toBeGreaterThan(0));
    expect(await screen.findByRole("img", { name: "直方图" })).toBeInTheDocument();

    const exposure = await within(panel).findByLabelText("曝光");
    fireEvent.change(exposure, { target: { value: "1.5" } });
    await waitFor(() =>
      expect(previews(requests).at(-1)?.body).toMatchObject({ recipe: { exposure: 1.5 } }),
    );
    expect(within(panel).getByText("+1.50")).toBeInTheDocument();
    fireEvent.pointerUp(exposure);
    await waitFor(() => expect(saves(requests)).toHaveLength(1));
    expect(saves(requests)[0]!.body).toMatchObject({ exposure: 1.5, contrast: 0 });
    // The history names the change; the original is listed last.
    const history = within(panel).getByRole("region", { name: "历史记录" });
    expect(await within(history).findByRole("button", { name: /曝光/ })).toHaveAttribute(
      "aria-current",
      "step",
    );

    fireEvent.keyDown(dialog, { key: "z", ctrlKey: true });
    await waitFor(() =>
      expect(requests.some((r) => r.url.pathname.endsWith("/edit/undo"))).toBe(true),
    );
    await waitFor(() => expect(within(panel).queryByText("+1.50")).not.toBeInTheDocument());
    expect(within(history).getByRole("button", { name: "原图" })).toHaveAttribute(
      "aria-current",
      "step",
    );

    // Escape leaves develop first (from a focused slider), then closes the viewer.
    exposure.focus();
    fireEvent.keyDown(exposure, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByRole("complementary", { name: "显影" })).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(dialog).toHaveFocus(); // the slider is gone; the viewer keeps the keyboard
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("saves pending changes when moving to the next photo", async () => {
    const { requests } = stubBackend({ assets: [makeAsset(1), makeAsset(2)] });
    renderViewer();
    const dialog = await screen.findByRole("dialog", { name: "IMG_1.JPG" });
    fireEvent.click(screen.getByRole("button", { name: "编辑 (D)" }));
    const panel = await screen.findByRole("complementary", { name: "显影" });
    await waitFor(() => expect(previews(requests).length).toBeGreaterThan(0));

    fireEvent.change(await within(panel).findByLabelText("对比度"), { target: { value: "30" } });
    fireEvent.keyDown(dialog, { key: "ArrowRight" });
    await screen.findByRole("dialog", { name: "IMG_2.JPG" });
    await waitFor(() => expect(saves(requests)).toHaveLength(1));
    expect(saves(requests)[0]!.url.pathname).toBe("/api/v1/assets/1/edit");
    expect(saves(requests)[0]!.body).toMatchObject({ contrast: 30 });
    // Still developing, now the second photo.
    await waitFor(() =>
      expect(previews(requests).at(-1)?.url.pathname).toBe("/api/v1/assets/2/develop/preview"),
    );
  });

  it("rotates and toggles the before view without saving the before view", async () => {
    const { requests } = stubBackend({ assets: [makeAsset(1)] });
    renderViewer([1]);
    const dialog = await screen.findByRole("dialog", { name: "IMG_1.JPG" });
    fireEvent.keyDown(dialog, { key: "d" });
    const panel = await screen.findByRole("complementary", { name: "显影" });

    fireEvent.click(await within(panel).findByRole("button", { name: "向右旋转" }));
    await waitFor(() => expect(saves(requests).at(-1)?.body).toMatchObject({ rotate: 1 }));

    // Shortcuts still work while a slider has the focus (after dragging it).
    const slider = within(panel).getByLabelText("曝光");
    fireEvent.keyDown(slider, { key: "\\" });
    await waitFor(() =>
      expect(previews(requests).at(-1)?.body).toMatchObject({ recipe: { rotate: 0 } }),
    );
    expect(screen.getAllByText("原图").length).toBeGreaterThan(0);
    expect(saves(requests)).toHaveLength(1);
    // …but its arrow keys move the slider, not to another photo.
    fireEvent.keyDown(slider, { key: "ArrowRight" });
    expect(screen.getByRole("dialog", { name: "IMG_1.JPG" })).toBeInTheDocument();
  });

  it("applies presets and pastes copied settings onto another photo", async () => {
    const { requests } = stubBackend({ assets: [makeAsset(1), makeAsset(2)] });
    renderViewer();
    const dialog = await screen.findByRole("dialog", { name: "IMG_1.JPG" });
    fireEvent.keyDown(dialog, { key: "d" });
    const panel = await screen.findByRole("complementary", { name: "显影" });

    fireEvent.click(await within(panel).findByRole("button", { name: "黑白" }));
    expect(within(panel).getByLabelText("饱和度")).toHaveValue("-100");
    await waitFor(() =>
      expect(saves(requests).at(-1)?.body).toMatchObject({ saturation: -100, contrast: 15 }),
    );

    fireEvent.click(within(panel).getByRole("button", { name: "拷贝设置 (Ctrl+Shift+C)" }));
    fireEvent.keyDown(dialog, { key: "ArrowRight" });
    await screen.findByRole("dialog", { name: "IMG_2.JPG" });
    const next = await screen.findByRole("complementary", { name: "显影" });
    await within(next).findByLabelText("饱和度");
    fireEvent.keyDown(dialog, { key: "v", ctrlKey: true, shiftKey: true });
    await waitFor(() =>
      expect(saves(requests).find((r) => r.url.pathname === "/api/v1/assets/2/edit")?.body)
        .toMatchObject({ saturation: -100, contrast: 15, rotate: 0 }),
    );
  });

  it("trims, turns and mutes a video, and exports a frame", async () => {
    localStorage.setItem("lumen.export", JSON.stringify({ destination: "D:\\Exports" }));
    const { requests } = stubBackend({
      assets: [makeAsset(1, { media_type: "video", file_name: "clip.mp4" })],
    });
    renderViewer([1]);
    const dialog = await screen.findByRole("dialog", { name: "clip.mp4" });
    fireEvent.click(screen.getByRole("button", { name: "编辑 (D)" }));
    const panel = await screen.findByRole("complementary", { name: "视频剪辑" });
    const videoSaves = () =>
      requests.filter((r) => r.method === "PUT" && r.url.pathname.endsWith("/video-edit"));

    fireEvent.change(await within(panel).findByLabelText("起点"), { target: { value: "1000" } });
    expect(within(panel).getByText("保留 0:03.0 / 共 0:04.0")).toBeInTheDocument();
    fireEvent.click(within(panel).getByRole("button", { name: "静音" }));
    fireEvent.click(within(panel).getByRole("button", { name: "向右旋转" }));
    await waitFor(() =>
      expect(videoSaves().at(-1)?.body).toEqual({
        version: 1, kind: "video", trim_start_ms: 1000, trim_end_ms: null, rotate: 1, mute: true,
      }), // prettier-ignore
    );
    expect(videoSaves()).toHaveLength(1); // the changes were saved together

    fireEvent.click(within(panel).getByRole("button", { name: "导出当前帧" }));
    expect(await within(panel).findByText(/已保存：D:\\Exports/)).toBeInTheDocument();
    expect(requests.find((r) => r.url.pathname.endsWith("/frame-export"))?.body).toEqual({
      time_ms: 1000, // setting the start moved the playhead there
      destination: "D:\\Exports",
    });

    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByRole("complementary", { name: "视频剪辑" })).not.toBeInTheDocument(),
    );
    localStorage.clear();
  });

  it("plays an edited video as edited", async () => {
    stubBackend({
      assets: [makeAsset(1, { media_type: "video", file_name: "clip.mp4", is_edited: true })],
      videoEdits: { 1: { trim_start_ms: 500, rotate: 1, mute: true } },
    });
    renderViewer([1]);
    const dialog = await screen.findByRole("dialog", { name: "clip.mp4" });
    await waitFor(() => expect(dialog.querySelector("video")).not.toBeNull());
    const video = dialog.querySelector("video")!;
    expect(video.muted).toBe(true);
    expect(video.parentElement?.style.transform).toContain("rotate(90deg)");
    expect(within(dialog).getByRole("button", { name: "播放" })).toBeInTheDocument();
  });
});
