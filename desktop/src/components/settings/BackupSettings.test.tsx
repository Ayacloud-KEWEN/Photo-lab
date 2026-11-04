import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { confirmAction } from "@/lib/dialogs";
import { Providers, stubBackend } from "@/test/backend";

import { BackupSettings } from "./BackupSettings";

vi.mock("@/lib/dialogs", () => ({
  pickDirectory: vi.fn(() => Promise.resolve("E:\LUMEN backups")),
  pickDatabaseFile: vi.fn(() => Promise.resolve(null)),
  confirmAction: vi.fn(() => Promise.resolve(true)),
}));

beforeEach(() => localStorage.clear());
afterEach(() => {
  vi.unstubAllGlobals();
  vi.mocked(confirmAction).mockClear();
});

const calls = (requests: { method: string; url: URL; body: unknown }[], method: string, path: string) =>
  requests.filter((r) => r.method === method && r.url.pathname === path);

describe("BackupSettings", () => {
  it("backs up now, lists backups and restores one after confirmation", async () => {
    const { requests } = stubBackend();
    render(
      <Providers>
        <BackupSettings />
      </Providers>,
    );
    const list = await screen.findByRole("list", { name: "备份列表" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("自动备份 · 676 项");
    expect(screen.getByRole("checkbox", { name: /自动备份数据库/ })).toBeChecked();

    await userEvent.click(screen.getByRole("button", { name: "立即备份" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "已备份：lumen-backup-20261104-120000-000.db",
    );

    await userEvent.click(within(rows[1]!).getByRole("button", { name: "恢复" }));
    expect(confirmAction).toHaveBeenCalledOnce();
    await waitFor(() =>
      expect(calls(requests, "POST", "/api/v1/backups/restore")[0]?.body).toEqual({
        name: "lumen-backup-20261020-180000-000.db",
      }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      "恢复前的数据已另存为 lumen-before-restore-20261104-120100-000.db",
    );
  });

  it("changes the backup folder and the schedule", async () => {
    const { requests } = stubBackend();
    render(
      <Providers>
        <BackupSettings />
      </Providers>,
    );
    await userEvent.click(await screen.findByRole("button", { name: "更改…" }));
    await waitFor(() =>
      expect(calls(requests, "PATCH", "/api/v1/settings")[0]?.body).toEqual({
        backup_folder: "E:\LUMEN backups",
      }),
    );
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "频率" }), "1");
    await waitFor(() =>
      expect(calls(requests, "PATCH", "/api/v1/settings")[1]?.body).toEqual({
        backup_interval_days: 1,
      }),
    );
  });
});
