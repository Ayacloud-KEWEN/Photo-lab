import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

import i18n from "@/i18n";

void i18n.changeLanguage("zh-CN");

afterEach(() => {
  cleanup();
});
