import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

import i18n from "@/i18n";

void i18n.changeLanguage("zh-CN");

afterEach(() => {
  cleanup();
});

// jsdom has no layout engine: give the virtualized grid a fixed size.
class ResizeObserverStub {
  constructor(private readonly callback: ResizeObserverCallback) {}
  observe(target: Element) {
    this.callback(
      [{ target, contentRect: { width: 800, height: 600 } } as unknown as ResizeObserverEntry],
      this as unknown as ResizeObserver,
    );
  }
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;

// Object URLs for develop previews (Node's own only accept Node's Blob, not jsdom's).
let nextObjectUrl = 0;
Object.assign(URL, {
  createObjectURL: () => `blob:lumen/${++nextObjectUrl}`,
  revokeObjectURL: () => undefined,
});
