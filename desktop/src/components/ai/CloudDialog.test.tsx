import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AnalysisKind } from "@/api/types";
import { useLibraryState } from "@/library/state";
import { makeAsset, Providers, stubBackend, type Request, type StubOptions } from "@/test/backend";

import { CloudDialog } from "./CloudDialog";

function Open({ kind, ids }: { kind: AnalysisKind; ids: number[] }) {
  const { openCloud } = useLibraryState();
  useEffect(() => openCloud(kind, ids), [openCloud, kind, ids]);
  return null;
}

const ids = [1];

function renderDialog(options: StubOptions = {}, onOpenSettings = vi.fn()) {
  const backend = stubBackend({ assets: [makeAsset(1), makeAsset(2)], ...options });
  render(
    <Providers>
      <Open kind="critique" ids={ids} />
      <CloudDialog onOpenSettings={onOpenSettings} />
    </Providers>,
  );
  return { ...backend, onOpenSettings };
}

/** Bodies of the requests that actually sent something to the cloud. */
const analyzeCalls = (requests: Request[]) =>
  requests
    .filter((r) => r.url.pathname === "/api/v1/ai/cloud/analyze")
    .map((r) => r.body as Record<string, unknown>);

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("CloudDialog", () => {
  it("shows what will be sent and uploads only after confirmation", async () => {
    const { requests } = renderDialog();
    expect(await screen.findByText(/将发送给 api\.deepseek\.com（模型 deepseek-flash）/)).toBeInTheDocument();
    expect(screen.getByText("Canon EOS R5")).toBeInTheDocument();
    expect(screen.getByText(/缩小到长边 1024 像素/)).toBeInTheDocument();
    expect(screen.queryByText(/31\.2/)).not.toBeInTheDocument(); // no GPS by default
    expect(analyzeCalls(requests)).toHaveLength(0);

    await userEvent.click(screen.getByRole("button", { name: "确认发送" }));
    expect(await screen.findByRole("heading", { name: "点评" })).toBeInTheDocument();
    const [call] = analyzeCalls(requests);
    expect(call).toMatchObject({ kind: "critique", asset_ids: [1], confirmed: true, include_location: false });
    expect(screen.getByText(/输入 100 \/ 输出 50 tokens/)).toBeInTheDocument();
  });

  it("includes GPS only when ticked", async () => {
    const { requests } = renderDialog();
    await userEvent.click(await screen.findByRole("checkbox", { name: "附带 GPS 位置" }));
    expect(await screen.findByText("31.20000, 121.40000")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "确认发送" }));
    await waitFor(() => expect(analyzeCalls(requests)).toHaveLength(1));
    expect(analyzeCalls(requests)[0]?.include_location).toBe(true);
  });

  it("offers a text-only fallback when the model refuses images", async () => {
    const { requests } = renderDialog({ cloud: "no_vision" });
    await userEvent.click(await screen.findByRole("button", { name: "确认发送" }));
    await userEvent.click(await screen.findByRole("button", { name: "改为仅发送文字" }));
    expect(await screen.findByText("不上传图片，只发送下面的文字信息。")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "确认发送" }));
    expect(await screen.findByText("仅基于文字信息")).toBeInTheDocument();
    expect(analyzeCalls(requests).at(-1)?.text_only).toBe(true);
  });

  it("points to Settings when the cloud is not configured", async () => {
    const { onOpenSettings } = renderDialog({ cloud: "not_configured" });
    await userEvent.click(await screen.findByRole("button", { name: "确认发送" }));
    await userEvent.click(await screen.findByRole("button", { name: "打开设置" }));
    expect(onOpenSettings).toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});
