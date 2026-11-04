import { describe, expect, it } from "vitest";

import { placeLine, placeName, tripPlace } from "./places";

const kl = { name: "Kuala Lumpur", zh: "吉隆坡", fr: "Kuala Lumpur" };
const malaysia = { name: "Malaysia", zh: "马来西亚", fr: "Malaisie" };
const paris = { name: "Paris", zh: "巴黎", fr: "Paris" };
const france = { name: "France", zh: "法国", fr: "France" };

describe("place names", () => {
  it("picks the interface language and drops repeats", () => {
    expect(placeName(malaysia, "fr")).toBe("Malaisie");
    expect(placeName(malaysia, "en")).toBe("Malaysia");
    expect(placeLine([kl, kl, malaysia], "zh-CN")).toBe("吉隆坡 · 马来西亚");
    expect(placeLine([kl, null, malaysia], "en")).toBe("Kuala Lumpur · Malaysia");
  });

  it("names a trip after its towns, or its countries when it crosses borders", () => {
    expect(tripPlace({ cities: [paris, kl], countries: [france] }, "zh-CN")).toBe("巴黎、吉隆坡");
    expect(tripPlace({ cities: [paris], countries: [france, malaysia] }, "fr")).toBe(
      "France, Malaisie",
    );
    expect(tripPlace({ cities: [], countries: [] }, "en")).toBe("");
  });
});
