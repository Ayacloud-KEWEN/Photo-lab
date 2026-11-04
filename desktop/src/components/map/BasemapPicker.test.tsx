import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Providers, stubBackend } from "@/test/backend";

import { BasemapPicker, offlinePalette } from "./BasemapPicker";

beforeEach(() => localStorage.clear());
afterEach(() => {
  vi.unstubAllGlobals();
});

function names() {
  return screen.getAllByRole("radio").map((radio) => radio.textContent);
}

describe("BasemapPicker", () => {
  it("offers the four online styles and saves the choice", async () => {
    const { requests } = stubBackend({ mapOnline: true });
    render(
      <Providers>
        <BasemapPicker />
      </Providers>,
    );
    await waitFor(() => expect(names()).toEqual(["深色", "彩色", "明亮", "浅灰"]));
    expect(screen.getByRole("radio", { name: "深色" })).toHaveAttribute("aria-checked", "true");

    await userEvent.click(screen.getByRole("radio", { name: "浅灰" }));
    await waitFor(() =>
      expect(screen.getByRole("radio", { name: "浅灰" })).toHaveAttribute("aria-checked", "true"),
    );
    const patch = requests.find((r) => r.method === "PATCH" && r.url.pathname === "/api/v1/settings");
    expect(patch?.body).toEqual({ map_style: "positron" });
  });

  it("offers a dark and a light map offline", async () => {
    stubBackend();
    render(
      <Providers>
        <BasemapPicker compact />
      </Providers>,
    );
    await waitFor(() => expect(names()).toEqual(["深色", "浅色"]));
    expect(offlinePalette("dark")).toBe("dark");
    expect((["liberty", "bright", "positron"] as const).map(offlinePalette)).toEqual([
      "light",
      "light",
      "light",
    ]);
  });
});
