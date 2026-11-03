import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useLibraryState } from "@/library/state";
import { makeAsset, Providers, stubBackend } from "@/test/backend";

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
});
