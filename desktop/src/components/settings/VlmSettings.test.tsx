import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AssetDetails } from "@/components/layout/Inspector";
import { makeAsset, makeDetail, Providers, stubBackend, type StubOptions } from "@/test/backend";
import { makeTask } from "@/test/tasks";

import { VlmSettings } from "./VlmSettings";

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderSettings(options: StubOptions = {}) {
  const backend = stubBackend(options);
  render(
    <Providers>
      <VlmSettings />
    </Providers>,
  );
  return backend;
}

describe("VlmSettings", () => {
  it("offers the download first, and cannot be turned on without the model", async () => {
    const { requests } = renderSettings();
    const enable = await screen.findByRole("checkbox", { name: /用本地模型识别照片/ });
    await waitFor(() => expect(enable).toBeDisabled());
    expect(screen.getByText("还没有 llama.cpp：下载模型时会一并下载。")).toBeInTheDocument();
    const models = screen.getAllByRole("listitem");
    expect(within(models[0]!).getByText(/默认模型 · 23.4 GB · Apache-2.0/)).toBeInTheDocument();
    expect(within(models[1]!).getByText(/精细识别 · 17.4 GB/)).toBeInTheDocument();

    await userEvent.click(within(models[0]!).getByRole("button", { name: "下载" }));
    await waitFor(() =>
      expect(requests.find((r) => r.url.pathname === "/api/v1/vlm/download")?.body).toEqual({
        model: "qwen3.6-35b-a3b",
      }),
    );
  });

  it("is turned on and shows how far reading has got", async () => {
    const reading = makeTask(5, "vlm_describe_assets");
    const { requests } = renderSettings({
      vlm: { installed: true },
      tasks: [{ ...reading, progress_current: 40, progress_total: 3400 }],
    });
    const enable = await screen.findByRole("checkbox", { name: /用本地模型识别照片/ });
    await waitFor(() => expect(enable).toBeEnabled());
    expect(screen.getByText("已识别 120 张")).toBeInTheDocument();
    expect(screen.getByText("正在识别照片 40 / 3,400")).toBeInTheDocument();
    await userEvent.click(enable);
    await waitFor(() =>
      expect(requests.some((r) => r.method === "PATCH" && (r.body as { vlm_enabled?: boolean }).vlm_enabled === true)).toBe(true),
    );
    await userEvent.click(screen.getByRole("radio", { name: /全部照片/ }));
    await waitFor(() =>
      expect(requests.some((r) => r.method === "PATCH" && (r.body as { vlm_scope?: string }).vlm_scope === "all")).toBe(true),
    );
    await userEvent.click(screen.getByRole("button", { name: "暂停" }));
    await waitFor(() =>
      expect(requests.some((r) => r.url.pathname === "/api/v1/tasks/5/cancel")).toBe(true),
    );
  });
});

describe("PhotoDescription", () => {
  it("shows what the model saw and read, and reads again on request", async () => {
    const asset = makeAsset(1);
    const { requests } = stubBackend({
      assets: [asset],
      vlm: {
        descriptions: {
          1: {
            description: "两个孩子在海边喂海鸥。",
            text: "Stari Grad\nKotor",
            keywords: ["海边", "海鸥"],
          },
        },
      },
    });
    const detail = {
      ...makeDetail(asset),
      description: {
        description: "两个孩子在海边喂海鸥。",
        text: "Stari Grad\nKotor",
        keywords: ["海边", "海鸥"],
        model: "qwen3.6-35b-a3b",
        model_label: "Qwen3.6-35B-A3B (MoE, Q4_K_M)",
        fine: false,
        truncated: true,
        created_at: "2026-11-08T10:00:00.000Z",
      },
    };
    render(
      <Providers>
        <AssetDetails asset={detail} />
      </Providers>,
    );
    const block = screen.getByRole("region", { name: "AI 描述" });
    expect(within(block).getByText("两个孩子在海边喂海鸥。")).toBeInTheDocument();
    expect(within(block).getByText(/Stari Grad/)).toBeInTheDocument();
    expect(within(block).getByText("海边 · 海鸥")).toBeInTheDocument();
    expect(
      within(block).getByText("由 Qwen3.6-35B-A3B (MoE, Q4_K_M) 生成，可能有误 · 文字可能不完整"),
    ).toBeInTheDocument();

    await userEvent.click(within(block).getByRole("button", { name: "精细识别" }));
    await waitFor(() =>
      expect(requests.find((r) => r.url.pathname === "/api/v1/vlm/describe")?.body).toEqual({
        asset_ids: [1],
        fine: true,
      }),
    );
    expect(await within(block).findByText(/已排队/)).toBeInTheDocument();
  });

  it("says when a photo has not been read, and nothing for videos", () => {
    stubBackend({ assets: [makeAsset(1), makeAsset(2, { media_type: "video" })] });
    const { unmount } = render(
      <Providers>
        <AssetDetails asset={makeDetail(makeAsset(1))} />
      </Providers>,
    );
    expect(screen.getByText("还没有识别。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "识别这张照片" })).toBeInTheDocument();
    unmount();
    render(
      <Providers>
        <AssetDetails asset={makeDetail(makeAsset(2, { media_type: "video" }))} />
      </Providers>,
    );
    expect(screen.queryByRole("region", { name: "AI 描述" })).not.toBeInTheDocument();
  });
});
