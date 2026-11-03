import type zhCN from "./locales/zh-CN";

type Widen<T> = { -readonly [K in keyof T]: T[K] extends string ? string : Widen<T[K]> };

/** Shape every locale must match: same keys as zh-CN, any string values. */
export type LocaleResource = Widen<typeof zhCN>;
