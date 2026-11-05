import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Providers, stubBackend } from "@/test/backend";
import { makeTask } from "@/test/tasks";

import { StatusBar } from "./StatusBar";

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderBar(tasks: ReturnType<typeof makeTask>[]) {
  stubBackend({ tasks });
  render(
    <Providers>
      <StatusBar />
    </Providers>,
  );
}

describe("StatusBar", () => {
  it("shows the quality assessment while it runs", async () => {
    renderBar([
      makeTask(23, "quality_score_assets", { progress_current: 75392, progress_total: 85293 }),
      makeTask(24, "ai_index_assets", { status: "pending", started_at: null }),
    ]);
    expect(await screen.findByText("正在评估画质 75,392 / 85,293")).toBeInTheDocument();
  });

  it("names a queued task that has no folder", async () => {
    renderBar([makeTask(24, "ai_index_assets", { status: "pending", started_at: null })]);
    expect(await screen.findByText("AI 分析 排队中")).toBeInTheDocument();
    expect(screen.queryByText(/AI 分析照片/)).not.toBeInTheDocument();
  });
});
