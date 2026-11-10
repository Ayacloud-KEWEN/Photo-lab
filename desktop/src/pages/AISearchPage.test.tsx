import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { fakeViewport, makeAsset, Providers, stubBackend, type StubOptions } from "@/test/backend";
import { makeTask } from "@/test/tasks";

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
  localStorage.clear();
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

  it("says the analysis is queued rather than running", async () => {
    renderPage({
      ai: { enabled: true, downloaded: true, indexed: 1 },
      assets: [1, 2, 3].map((id) => makeAsset(id)),
      tasks: [makeTask(1, "ai_index_assets", { status: "pending" })],
    });
    expect(await screen.findByText(/已分析 1 \/ 3 张照片，其余的在排队/)).toBeInTheDocument();
    expect(screen.queryByText(/正在分析照片/)).not.toBeInTheDocument();
  });

  it("shows the analysis progress while it runs", async () => {
    renderPage({
      ai: { enabled: true, downloaded: true, indexed: 1 },
      assets: [1, 2, 3].map((id) => makeAsset(id)),
      tasks: [makeTask(1, "ai_index_assets")],
    });
    expect(await screen.findByText(/正在分析照片 1 \/ 3/)).toBeInTheDocument();
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

describe("Ask the library", () => {
  it("answers a question with the local model, citing photos", async () => {
    const assets = [1, 2, 3].map((id) => makeAsset(id));
    const { requests } = renderPage({ assets, vlm: { installed: true } });
    await userEvent.click(await screen.findByRole("tab", { name: "问图库" }));
    const box = await screen.findByRole("textbox", { name: /用一句话问你的图库/ });
    await userEvent.type(box, "去年在日本吃过哪些拉面？{Enter}");
    await waitFor(() =>
      expect(requests.find((r) => r.method === "POST" && r.url.pathname === "/api/v1/ask")?.body).toEqual({
        question: "去年在日本吃过哪些拉面？",
        language: "zh-CN",
      }),
    );
    const answer = await screen.findByRole("article", { name: "去年在日本吃过哪些拉面？" });
    expect(await within(answer).findByText(/去年在东京吃过两次拉面/)).toBeInTheDocument();
    // How the question was understood, the counts and the cited photos.
    expect(within(answer).getByText("2025-01-01 至 2026-01-01")).toBeInTheDocument();
    expect(within(answer).getByText("内容含：拉面")).toBeInTheDocument();
    expect(within(answer).getByText("共 2 张符合")).toBeInTheDocument();
    expect(within(answer).getByText("依据 40 张已识别内容的照片")).toBeInTheDocument();
    expect(within(answer).getByRole("list", { name: "统计" })).toHaveTextContent("东京");
    expect(within(answer).getByRole("button", { name: "[1]" })).toBeInTheDocument();
    expect(within(answer).getAllByRole("button", { name: /^\[\d\] IMG_/ })).toHaveLength(2);

    // Kept in the history; deleted from there.
    const history = screen.getByRole("complementary", { name: "提过的问题" });
    await userEvent.click(
      await within(history).findByRole("button", { name: "删除问题“去年在日本吃过哪些拉面？”" }),
    );
    await waitFor(() =>
      expect(within(history).queryByText("去年在日本吃过哪些拉面？")).not.toBeInTheDocument(),
    );
  });

  it("needs the local model", async () => {
    renderPage({ assets: [makeAsset(1)] });
    await userEvent.click(await screen.findByRole("tab", { name: "问图库" }));
    expect(await screen.findByText(/需要先在“设置 › 本地视觉模型”里下载本地模型/)).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: /用一句话问你的图库/ })).toBeDisabled();
  });
});
