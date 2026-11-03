import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { fakeViewport, makeAsset, Providers, stubBackend, type StubOptions } from "@/test/backend";

import { AISearchPage } from "./AISearchPage";

function renderPage(options: StubOptions) {
  const backend = stubBackend(options);
  render(
    <Providers>
      <AISearchPage onSelect={vi.fn()} />
    </Providers>,
  );
  return backend;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("AISearchPage", () => {
  it("offers to turn AI on, which enables it in settings", async () => {
    const { requests } = renderPage({ ai: { enabled: false } });
    const button = await screen.findByRole("button", { name: /启用 AI（下载约 4.5 GB 模型）/ });
    expect(screen.getByText(/NVIDIA GeForce RTX 4070 SUPER/)).toBeInTheDocument();
    await userEvent.click(button);
    await waitFor(() =>
      expect(requests.find((r) => r.method === "PATCH")?.body).toEqual({ ai_enabled: true }),
    );
  });

  it("explains how to install the AI components when missing", async () => {
    renderPage({ ai: { installed: false } });
    expect(await screen.findByText(/pip install -e \.\[ai\]/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /启用 AI/ })).not.toBeInTheDocument();
  });

  it("searches with a natural-language description", async () => {
    fakeViewport();
    const { requests } = renderPage({
      ai: { enabled: true, downloaded: true },
      assets: [1, 2, 3].map((id) => makeAsset(id)),
    });
    const input = await screen.findByRole("textbox", { name: /描述你想找的画面/ });
    await userEvent.type(input, "雪山下的湖泊");
    fireEvent.submit(input.closest("form")!);

    expect(await screen.findByRole("img", { name: "IMG_3.JPG" })).toBeInTheDocument();
    const search = requests.find((r) => r.url.pathname === "/api/v1/ai/search");
    expect(search?.url.searchParams.get("text")).toBe("雪山下的湖泊");
    // Only clear matches first; weaker ones on request.
    expect(screen.getByText("2 个结果")).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: "IMG_1.JPG" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "显示 1 张相关度较低的照片" }));
    expect(await screen.findByRole("img", { name: "IMG_1.JPG" })).toBeInTheDocument();
  });

  it("runs an example query with one click", async () => {
    const { requests } = renderPage({ ai: { enabled: true, downloaded: true }, assets: [makeAsset(1)] });
    await userEvent.click(await screen.findByRole("button", { name: "城市夜景" }));
    await waitFor(() =>
      expect(
        requests.some((r) => r.url.searchParams.get("text") === "城市夜景"),
      ).toBe(true),
    );
  });
});
