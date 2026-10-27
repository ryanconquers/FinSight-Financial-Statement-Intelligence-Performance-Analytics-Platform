import test from "node:test";
import assert from "node:assert/strict";
import { requestData } from "./api-client.mjs";

const jsonResponse = (body, status = 200) => new Response(JSON.stringify(body), {
  status,
  headers: { "content-type": "application/json" },
});

test("requestData returns data from the API envelope and requests the expected URL", async () => {
  let requestedUrl = "";
  const result = await requestData("https://api.example.test/", "/api/status", {
    fetchImpl: async (url) => {
      requestedUrl = url;
      return jsonResponse({ data: { data_availability: "empty" }, meta: {} });
    },
  });

  assert.equal(requestedUrl, "https://api.example.test/api/status");
  assert.deepEqual(result, { data_availability: "empty" });
});

test("requestData retries Render cold-start responses and succeeds", async () => {
  let attempts = 0;
  const result = await requestData("https://api.example.test", "/api/companies", {
    retries: 2,
    waitImpl: async () => {},
    fetchImpl: async () => {
      attempts += 1;
      return attempts === 1
        ? jsonResponse({ detail: "service waking" }, 503)
        : jsonResponse({ data: [], meta: { count: 0 } });
    },
  });

  assert.equal(attempts, 2);
  assert.deepEqual(result, []);
});

test("requestData retries transient network failures", async () => {
  let attempts = 0;
  const result = await requestData("https://api.example.test", "/api/status", {
    retries: 1,
    waitImpl: async () => {},
    fetchImpl: async () => {
      attempts += 1;
      if (attempts === 1) throw new TypeError("fetch failed");
      return jsonResponse({ data: "ready" });
    },
  });

  assert.equal(attempts, 2);
  assert.equal(result, "ready");
});

test("requestData does not retry non-transient API errors", async () => {
  let attempts = 0;
  await assert.rejects(
    requestData("https://api.example.test", "/api/private", {
      retries: 2,
      waitImpl: async () => {},
      fetchImpl: async () => {
        attempts += 1;
        return jsonResponse({ error: { message: "Not found" } }, 404);
      },
    }),
    /Not found/,
  );
  assert.equal(attempts, 1);
});

test("requestData reports an actionable error after retries are exhausted", async () => {
  await assert.rejects(
    requestData("https://api.example.test", "/api/status", {
      retries: 1,
      waitImpl: async () => {},
      fetchImpl: async () => { throw new TypeError("offline"); },
    }),
    /may be waking after inactivity/,
  );
});

test("requestData explains exhausted Render 503 retries", async () => {
  await assert.rejects(
    requestData("https://api.example.test", "/api/status", {
      retries: 1,
      waitImpl: async () => {},
      fetchImpl: async () => jsonResponse({ detail: "service unavailable" }, 503),
    }),
    /temporarily unavailable after retries.*waking after inactivity/s,
  );
});
