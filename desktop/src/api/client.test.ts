import { afterEach, describe, expect, it, vi } from "vitest";

import { api, ApiError } from "./client";

const conn = { baseUrl: "http://127.0.0.1:5000", token: "tok" };

function mockFetch(response: Response | Error) {
  const fn = vi.fn(() =>
    response instanceof Error ? Promise.reject(response) : Promise.resolve(response),
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("api client", () => {
  it("sends the bearer token and JSON body", async () => {
    const fetch = mockFetch(json(201, { id: 1 }));
    await api.createStorageRoot(conn, { path: "D:\\Photos" });

    expect(fetch).toHaveBeenCalledWith("http://127.0.0.1:5000/api/v1/storage-roots", {
      method: "POST",
      headers: { Authorization: "Bearer tok", "Content-Type": "application/json" },
      body: JSON.stringify({ path: "D:\\Photos" }),
    });
  });

  it("turns the error envelope into an ApiError", async () => {
    mockFetch(json(409, { error: { code: "conflict", message: "already", details: { id: 3 } } }));
    const error = await api.createStorageRoot(conn, { path: "D:\\x" }).catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 409, code: "conflict", details: { id: 3 } });
  });

  it("handles 204 responses", async () => {
    mockFetch(new Response(null, { status: 204 }));
    await expect(api.deleteStorageRoot(conn, 1)).resolves.toBeUndefined();
  });

  it("reports network failures", async () => {
    mockFetch(new TypeError("Failed to fetch"));
    await expect(api.getHealth(conn)).rejects.toMatchObject({ code: "network_error", status: 0 });
  });
});
