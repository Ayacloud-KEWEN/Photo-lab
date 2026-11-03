import { describe, expect, it } from "vitest";

import en from "./locales/en";
import fr from "./locales/fr";
import zhCN from "./locales/zh-CN";

function keys(value: object, prefix = ""): string[] {
  return Object.entries(value).flatMap(([key, child]) =>
    typeof child === "object" && child !== null
      ? keys(child as object, `${prefix}${key}.`)
      : [`${prefix}${key}`],
  );
}

describe("locales", () => {
  it.each([
    ["en", en],
    ["fr", fr],
  ])("%s has exactly the zh-CN keys", (_, locale) => {
    expect(keys(locale).sort()).toEqual(keys(zhCN).sort());
  });

  it("has no empty strings", () => {
    for (const locale of [zhCN, en, fr]) {
      const values = JSON.stringify(locale);
      expect(values).not.toContain('""');
    }
  });
});
