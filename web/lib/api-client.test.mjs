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

test("requestData validates insights and benchmark response shapes", async () => {
  const insights = await requestData("https://api.example.test", "/api/companies/TEST_CO/insights", {
    fetchImpl: async () => jsonResponse({ data: { company_id: "TEST_CO", statement_basis: "consolidated", insights: [] }, meta: { count: 0 } }),
  });
  assert.deepEqual(insights.insights, []);

  const benchmark = await requestData("https://api.example.test", "/api/companies/TEST_CO/benchmark?peer_ids=PEER", {
    fetchImpl: async () => jsonResponse({ data: {
      company_id: "TEST_CO", statement_basis: "consolidated", financial_year: "FY2025",
      status: "insufficient_data", peers_requested: ["PEER"], maximum_compatible_peer_count_for_any_metric: 0,
      sample_disclosure: "Selected group only.", exclusions: { PEER: [] }, metrics: [],
    }, meta: { metric_count: 0 } }),
  });
  assert.equal(benchmark.status, "insufficient_data");

  await assert.rejects(
    requestData("https://api.example.test", "/api/companies/TEST_CO/benchmark?peer_ids=PEER", {
      fetchImpl: async () => jsonResponse({ data: { ...benchmark, metrics: [{ metric_id: "revenue_growth", status: "available", peer_median: {}, values: [] }] }, meta: {} }),
    }),
    /unexpected benchmark shape/,
  );

  await assert.rejects(
    requestData("https://api.example.test", "/api/companies/TEST_CO/insights", {
      fetchImpl: async () => jsonResponse({ data: { company_id: "TEST_CO", statement_basis: "mixed", insights: [] }, meta: {} }),
    }),
    /invalid response/,
  );
  await assert.rejects(
    requestData("https://api.example.test", "/api/companies/TEST_CO/insights", {
      fetchImpl: async () => jsonResponse({ data: { company_id: "TEST_CO", statement_basis: "consolidated", insights: [{ insight_id: "x", category: "observed_trend", finding: "change", periods: ["FY2025"], rule: "compare", observed_values: [{ value: 4 }], limitations: "test", evidence: [] }] }, meta: {} }),
    }),
    /data\[0\] has an unexpected shape/,
  );
  await assert.rejects(
    requestData("https://api.example.test", "/api/companies/TEST_CO/insights", {
      fetchImpl: async () => jsonResponse({ data: { company_id: "TEST_CO", statement_basis: "consolidated", peer_benchmark_status: 500, insights: [] }, meta: {} }),
    }),
    /invalid response/,
  );
});

test("requestData validates original reported observation fields", async () => {
  const observation = {
    observation_id: 7, company_id: "TEST_CO", financial_year: "FY2025",
    period_start: "2024-04-01", period_end: "2025-03-31", statement_basis: "consolidated",
    statement_type: "income_statement", line_item_id: "revenue", reported_label: "Revenue as reported",
    value: "100", unit: "INR_crore", currency: "INR", source_id: "TEST_SOURCE", publisher: "Test Publisher",
    source_url: "https://example.invalid/source", publication_date: null, retrieved_at: "2026-10-27",
  };
  const values = await requestData("https://api.example.test", "/api/companies/TEST_CO/observations?statement_basis=consolidated", {
    fetchImpl: async () => jsonResponse({ data: [observation], meta: { count: 1 } }),
  });
  assert.equal(values[0].reported_label, "Revenue as reported");
  await assert.rejects(
    requestData("https://api.example.test", "/api/companies/TEST_CO/observations", {
      fetchImpl: async () => jsonResponse({ data: [{ ...observation, value: 100 }], meta: {} }),
    }),
    /unexpected shape/,
  );
});

test("requestData posts forecast assumptions and validates saved scenario responses", async () => {
  const body = { baseline_year: "FY2024", forecast_horizon: 1, assumptions: { revenue_growth: [0.1] } };
  let requestInit;
  const result = await requestData("https://api.example.test", "/api/companies/TEST_CO/forecasts?statement_basis=consolidated", {
    method: "POST", body,
    fetchImpl: async (_url, init) => {
      requestInit = init;
      return jsonResponse({ data: {
        forecast_id: "f-1", company_id: "TEST_CO", statement_basis: "consolidated", baseline_year: "FY2024",
        forecast_horizon: 1, methodology_version: "finsight-driver-forecast-v1", assumptions: {}, revision: 1,
        result: { scenarios: Object.fromEntries(["base", "bull", "bear"].map((name) => [name, {
          actual_baseline: { financial_year: "FY2024", period_type: "actual", currency: "INR", unit: "INR_crore", values: {} },
          periods: [{ financial_year: "FY2025", period_type: "forecast", currency: "INR", unit: "INR_crore", unavailable: [] }],
        }])) },
      }, meta: {} }, 201);
    },
  });
  assert.equal(requestInit.method, "POST");
  assert.deepEqual(JSON.parse(requestInit.body), body);
  assert.equal(result.forecast_id, "f-1");
});

test("requestData rejects malformed saved forecasts and validates actual-forecast states", async () => {
  await assert.rejects(requestData("https://api.example.test", "/api/companies/TEST_CO/forecasts/f-1", {
    fetchImpl: async () => jsonResponse({ data: { forecast_id: "f-1", company_id: "TEST_CO" }, meta: {} }),
  }), /unexpected forecast shape/);
  const comparison = await requestData("https://api.example.test", "/api/companies/TEST_CO/forecasts/f-1/actual-vs-forecast", {
    fetchImpl: async () => jsonResponse({ data: { company_id: "TEST_CO", statement_basis: "consolidated", periods: [{ financial_year: "FY2024", period_type: "actual", currency: "INR", unit: "INR_crore" }], input_data_stale: false }, meta: {} }),
  });
  assert.equal(comparison.periods[0].period_type, "actual");
});

test("requestData does not retry forecast mutations after an ambiguous network failure", async () => {
  let attempts = 0;
  await assert.rejects(requestData("https://api.example.test", "/api/companies/TEST_CO/forecasts?statement_basis=consolidated", {
    method: "POST", body: { baseline_year: "FY2024" }, retries: 3, waitImpl: async () => {},
    fetchImpl: async () => { attempts += 1; throw new TypeError("connection closed after request"); },
  }), /may be waking after inactivity/);
  assert.equal(attempts, 1);
});

test("requestData validates forecast revision histories and immutable snapshots", async () => {
  const summaries = await requestData("https://api.example.test", "/api/companies/TEST_CO/forecasts/f-1/revisions", {
    fetchImpl: async () => jsonResponse({ data: [{ revision: 1, assumptions: {}, input_fingerprint: "sha", saved_at: "2026-01-01T00:00:00Z" }], meta: { count: 1 } }),
  });
  assert.equal(summaries[0].revision, 1);
  const snapshot = await requestData("https://api.example.test", "/api/companies/TEST_CO/forecasts/f-1/revisions/1", {
    fetchImpl: async () => jsonResponse({ data: {
      forecast_id: "f-1", company_id: "TEST_CO", statement_basis: "consolidated", baseline_year: "FY2024",
      forecast_horizon: 1, methodology_version: "finsight-driver-forecast-v1", assumptions: {}, revision: 1,
      input_fingerprint: "sha", current: false, input_data_stale: false, saved_at: "2026-01-01T00:00:00Z",
      result: { scenarios: Object.fromEntries(["base", "bull", "bear"].map((name) => [name, {
        actual_baseline: { financial_year: "FY2024", period_type: "actual", currency: "INR", unit: "INR_crore", values: {} },
        periods: [{ financial_year: "FY2025", period_type: "forecast", currency: "INR", unit: "INR_crore" }],
      }])) },
    }, meta: {} }),
  });
  assert.equal(snapshot.current, false);
});
