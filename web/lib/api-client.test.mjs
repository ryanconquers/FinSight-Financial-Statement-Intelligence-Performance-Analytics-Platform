import test from "node:test";
import assert from "node:assert/strict";
import { requestData } from "./api-client.mjs";

const jsonResponse = (body, status = 200) => new Response(JSON.stringify(body), {
  status,
  headers: { "content-type": "application/json" },
});
const validStatus = {
  project_status: "under_development",
  data_availability: "empty",
  source_backed_observation_count: 0,
  real_financial_data_onboarded: false,
};

test("requestData returns data from the API envelope and requests the expected URL", async () => {
  let requestedUrl = "";
  const result = await requestData("https://api.example.test/", "/api/status", {
    fetchImpl: async (url) => {
      requestedUrl = url;
      return jsonResponse({ data: validStatus, meta: {} });
    },
  });

  assert.equal(requestedUrl, "https://api.example.test/api/status");
  assert.deepEqual(result, validStatus);
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
      return jsonResponse({ data: validStatus });
    },
  });

  assert.equal(attempts, 2);
  assert.deepEqual(result, validStatus);
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

test("requestData rejects a missing data envelope without retrying", async () => {
  let attempts = 0;
  await assert.rejects(
    requestData("https://api.example.test", "/api/status", {
      retries: 2,
      waitImpl: async () => {},
      fetchImpl: async () => { attempts += 1; return jsonResponse({ meta: {} }); },
    }),
    /did not contain a data field/,
  );
  assert.equal(attempts, 1);
});

test("requestData rejects an object where the companies endpoint requires an array", async () => {
  let attempts = 0;
  await assert.rejects(
    requestData("https://api.example.test", "/api/companies", {
      retries: 2,
      waitImpl: async () => {},
      fetchImpl: async () => { attempts += 1; return jsonResponse({ data: {}, meta: {} }); },
    }),
    /data must be an array/,
  );
  assert.equal(attempts, 1);
});

test("requestData rejects incorrectly typed status and company fields", async () => {
  await assert.rejects(
    requestData("https://api.example.test", "/api/status", {
      fetchImpl: async () => jsonResponse({ data: { ...validStatus, source_backed_observation_count: "0" } }),
    }),
    /invalid response for \/api\/status/,
  );
  await assert.rejects(
    requestData("https://api.example.test", "/api/companies", {
      fetchImpl: async () => jsonResponse({ data: [{ company_id: 5 }], meta: {} }),
    }),
    /data\[0\] has an unexpected shape/,
  );
});

test("requestData rejects malformed metric and provenance response items", async () => {
  await assert.rejects(
    requestData("https://api.example.test", "/api/companies/ACME/metrics", {
      fetchImpl: async () => jsonResponse({ data: [{ metric_id: "revenue_growth" }], meta: {} }),
    }),
    /data\[0\] has an unexpected shape/,
  );
  await assert.rejects(
    requestData("https://api.example.test", "/api/companies/ACME/provenance", {
      fetchImpl: async () => jsonResponse({ data: [{ source_id: "source" }], meta: {} }),
    }),
    /data\[0\] has an unexpected shape/,
  );
});

test("requestData reports malformed JSON as a controlled error", async () => {
  await assert.rejects(
    requestData("https://api.example.test", "/api/status", {
      fetchImpl: async () => new Response("{broken", { status: 200, headers: { "content-type": "application/json" } }),
    }),
    /unreadable response/,
  );
});

test("requestData accepts valid empty collections and nullable provenance URLs", async () => {
  const emptyCompanies = await requestData("https://api.example.test", "/api/companies", {
    fetchImpl: async () => jsonResponse({ data: [], meta: { count: 0 } }),
  });
  const provenance = await requestData("https://api.example.test", "/api/companies/ACME/provenance", {
    fetchImpl: async () => jsonResponse({ data: [{
      source_id: "s1", publisher: "Publisher", source_url: null, publication_date: null,
      retrieved_at: "2026-01-01T00:00:00Z", financial_year: "FY2025",
      statement_basis: "consolidated", statement_type: "income_statement",
    }], meta: { count: 1 } }),
  });
  assert.deepEqual(emptyCompanies, []);
  assert.equal(provenance[0].source_url, null);
});

test("requestData validates the company-analysis response and its evidence", async () => {
  const data = {
    company_id: "TEST_CO",
    statement_basis: "consolidated",
    configuration_version: "m4a-risk-v1",
    assessments: [{
      rule_id: "revenue_decline", title: "Revenue decline", status: "flagged",
      company_id: "TEST_CO", statement_basis: "consolidated", financial_year: "FY2025",
      configuration_version: "m4a-risk-v1", thresholds: { growth_below: "0", consecutive_years: 2 },
      periods: ["FY2024", "FY2025"], comparison: "growth below zero",
      fact: "Revenue declined in both periods.", interpretation: "Analytical signal for review.",
      reason: "Configured threshold met.",
      observed: [{ metric_id: "revenue_growth", financial_year: "FY2025", value: "-0.1", unit: "ratio", currency: null, status: "calculated" }],
      evidence: [{
        metric_id: "revenue_growth", metric_name: "Revenue growth", company_id: "TEST_CO",
        financial_year: "FY2025", period_start: "2024-04-01", period_end: "2025-03-31",
        statement_basis: "consolidated", value: "-0.1", unit: "ratio", currency: null,
        status: "calculated", explanation: "Calculated", formula: "growth", formula_version: "v1",
        inputs: [{ observation_id: 2, line_item_id: "revenue", statement_type: "income_statement", value: "90", unit: "INR_crore", currency: "INR", source_id: "TEST_SOURCE", financial_year: "FY2025", period_start: "2024-04-01", period_end: "2025-03-31" }],
        warnings: [],
      }],
    }],
  };
  const result = await requestData("https://api.example.test", "/api/companies/TEST_CO/analysis?statement_basis=consolidated", {
    fetchImpl: async () => jsonResponse({ data, meta: { count: 1 } }),
  });
  assert.equal(result.assessments[0].evidence[0].inputs[0].source_id, "TEST_SOURCE");

  await assert.rejects(
    requestData("https://api.example.test", "/api/companies/TEST_CO/analysis", {
      fetchImpl: async () => jsonResponse({ data: { ...data, assessments: [{ ...data.assessments[0], status: "distressed" }] }, meta: {} }),
    }),
    /data\[0\] has an unexpected shape/,
  );
});
