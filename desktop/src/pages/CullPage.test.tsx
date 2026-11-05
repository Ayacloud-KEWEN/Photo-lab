import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeAsset, Providers, stubBackend } from "@/test/backend";

import { CullPage } from "./CullPage";

beforeEach(() => localStorage.clear());
afterEach(() => {
  vi.unstubAllGlobals();
});

const assets = [1, 2, 3, 4].map((id) => makeAsset(id));
const batches = (requests: { method: string; url: URL; body: unknown }[]) =>
  requests.filter((r) => r.url.pathname === "/api/v1/assets/batch").map((r) => r.body);

describe("CullPage", () => {
  it("keeps the recommended photo of a similar group and rejects the others", async () => {
    const { requests } = stubBackend({ assets, similar: [1, 2, 3] });
    render(
      <Providers>
        <CullPage onShowLibrary={() => {}} />
      </Providers>,
    );
    const group = await screen.findByRole("article", { name: "3 张相似照片" });
    expect(within(group).getByText("推荐")).toBeInTheDocument();
    expect(screen.getByText("共 1 组，1 组待处理")).toBeInTheDocument();
    await userEvent.click(within(group).getByRole("button", { name: /保留推荐，淘汰其余/ }));
    await waitFor(() =>
      expect(batches(requests)).toEqual([
        { asset_ids: [2], cull_flag: "pick" },
        { asset_ids: [1, 3], cull_flag: "reject" },
      ]),
    );
  });

  it("lists likely rejects and rejects the ones shown", async () => {
    const { requests } = stubBackend({ assets, suspects: [4] });
    const onShowLibrary = vi.fn();
    render(
      <Providers>
        <CullPage onShowLibrary={onShowLibrary} />
      </Providers>,
    );
    await userEvent.click(await screen.findByRole("tab", { name: "疑似废片" }));
    expect(await screen.findByText("可能模糊")).toBeInTheDocument();
    expect(screen.getByText("清晰度 10")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "淘汰显示的 1 张" }));
    await waitFor(() => expect(batches(requests)).toEqual([{ asset_ids: [4], cull_flag: "reject" }]));

    await userEvent.click(screen.getByRole("button", { name: /在图库中查看淘汰的/ }));
    expect(onShowLibrary).toHaveBeenCalledOnce();
  });

  it("merges duplicate copies, keeping the chosen copy's details", async () => {
    const { requests } = stubBackend({ assets, duplicates: [[1, 2], [3, 4]] });
    render(
      <Providers>
        <CullPage onShowLibrary={() => {}} />
      </Providers>,
    );
    await userEvent.click(await screen.findByRole("tab", { name: "重复文件" }));
    expect(await screen.findByText(/2 组重复，多余副本共占用/)).toBeInTheDocument();
    const [first] = screen.getAllByRole("article", { name: "2 份副本" });
    expect(within(first!).getByRole("radio", { name: /保留这份的信息/ })).toBeChecked();
    expect(within(first!).getByText("2 个标签")).toBeInTheDocument();

    await userEvent.click(within(first!).getByRole("radio", { name: /改为保留这份/ }));
    await userEvent.click(within(first!).getByRole("button", { name: /合并为一张/ }));
    await waitFor(() =>
      expect(requests.find((r) => r.url.pathname === "/api/v1/duplicates/merge")?.body).toEqual({
        groups: [{ asset_ids: [1, 2], keep_asset_id: 2 }],
      }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent("已合并 1 组");

    await userEvent.click(within(first!).getAllByRole("button", { name: "在资源管理器中显示" })[0]!);
    await waitFor(() =>
      expect(requests.some((r) => r.url.pathname === "/api/v1/files/10/reveal")).toBe(true),
    );
    // All groups (not only the ones loaded) are merged by a background task.
    await userEvent.click(screen.getByRole("button", { name: /全部合并（2 组）/ }));
    await waitFor(() =>
      expect(requests.some((r) => r.url.pathname === "/api/v1/duplicates/merge-all")).toBe(true),
    );
    expect(await screen.findByRole("status")).toHaveTextContent("已开始在后台合并全部重复文件");
  });
});
