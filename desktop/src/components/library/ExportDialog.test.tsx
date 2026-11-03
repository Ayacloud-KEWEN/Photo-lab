import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useLibraryState } from "@/library/state";
import { makeAsset, Providers, stubBackend } from "@/test/backend";

import { ExportDialog } from "./ExportDialog";

vi.mock("@/lib/dialogs", () => ({
  pickDirectory: vi.fn(() => Promise.resolve("D:\\Exports")),
  confirmAction: vi.fn(() => Promise.resolve(true)),
}));

function OpenOnMount({ ids }: { ids: number[] }) {
  const { openExport } = useLibraryState();
  useEffect(() => openExport(ids), [openExport, ids]);
  return null;
}

function renderDialog(ids = [1, 2, 3]) {
  render(
    <Providers>
      <OpenOnMount ids={ids} />
      <ExportDialog />
    </Providers>,
  );
}

beforeEach(() => localStorage.clear());
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ExportDialog", () => {
  it("exports with the chosen options and reports the outcome", async () => {
    const { requests } = stubBackend({ assets: [1, 2, 3].map((id) => makeAsset(id)) });
    renderDialog();
    const dialog = await screen.findByRole("dialog", { name: "导出" });
    const start = within(dialog).getByRole("button", { name: "导出 3 项" });
    expect(start).toBeDisabled(); // no folder yet

    await userEvent.click(within(dialog).getByRole("button", { name: "选择…" }));
    expect(within(dialog).getByDisplayValue("D:\\Exports")).toBeInTheDocument();
    fireEvent.change(within(dialog).getAllByRole("combobox")[0]!, { target: { value: "2048" } });
    // Location is off by default, and only possible with the photo information.
    const location = within(dialog).getByRole("checkbox", { name: "包含位置（GPS）" });
    expect(location).not.toBeChecked();
    await userEvent.click(within(dialog).getByRole("checkbox", { name: "保留拍摄信息（EXIF）" }));
    expect(location).toBeDisabled();

    await userEvent.click(start);
    await waitFor(() =>
      expect(requests.find((r) => r.url.pathname === "/api/v1/exports")?.body).toEqual({
        asset_ids: [1, 2, 3],
        destination: "D:\\Exports",
        long_edge: 2048,
        quality: 90,
        include_metadata: false,
        include_location: false,
        video_mode: "copy",
      }),
    );
    expect(await within(dialog).findByText("已导出 2 项到 D:\\Exports")).toBeInTheDocument();
    expect(within(dialog).getByText(/跳过 1 项/)).toBeInTheDocument();

    // The choices (but not the location) are remembered for next time.
    expect(JSON.parse(localStorage.getItem("lumen.export")!)).toMatchObject({
      destination: "D:\\Exports",
      long_edge: 2048,
      include_metadata: false,
    });
    await userEvent.click(within(dialog).getAllByRole("button", { name: "关闭" }).at(-1)!);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows why a folder cannot be used", async () => {
    stubBackend({ assets: [makeAsset(1)] });
    renderDialog([1]);
    const dialog = await screen.findByRole("dialog", { name: "导出" });
    await userEvent.type(within(dialog).getByRole("textbox"), "relative\\folder");
    await userEvent.click(within(dialog).getByRole("button", { name: "导出 1 项" }));
    expect(await within(dialog).findByText("The folder does not exist")).toBeInTheDocument();
  });
});
