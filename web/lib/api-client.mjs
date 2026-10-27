const RETRYABLE_STATUSES = new Set([502, 503, 504]);

const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

const isRecord = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
const isString = (value) => typeof value === "string";
const isNullableString = (value) => value === null || isString(value);
const isNonNegativeInteger = (value) => Number.isInteger(value) && value >= 0;

function invalidResponse(path, detail) {
  return new Error(`The FinSight API returned an invalid response for ${path}: ${detail}`);
}

function validateArray(data, path, validateItem) {
  if (!Array.isArray(data)) throw invalidResponse(path, "data must be an array.");
  for (const [index, item] of data.entries()) {
    if (!validateItem(item)) throw invalidResponse(path, `data[${index}] has an unexpected shape.`);
  }
}

function isMetric(item) {
  return isRecord(item)
    && isString(item.metric_id)
    && isString(item.metric_name)
    && isString(item.company_id)
    && isString(item.financial_year)
    && isString(item.period_start)
    && isString(item.period_end)
    && isString(item.statement_basis)
    && isNullableString(item.value)
    && isString(item.unit)
    && isNullableString(item.currency)
    && ["calculated", "unavailable", "invalid_input"].includes(item.status)
    && isString(item.explanation)
    && isString(item.formula)
    && Array.isArray(item.inputs)
    && item.inputs.every((input) => isRecord(input) && isString(input.source_id) && Number.isInteger(input.observation_id))
    && Array.isArray(item.warnings)
    && item.warnings.every(isString);
}

function isAssessment(item) {
  return isRecord(item)
    && isString(item.rule_id)
    && isString(item.title)
    && ["flagged", "not_flagged", "insufficient_data", "invalid_input"].includes(item.status)
    && isString(item.company_id)
    && ["standalone", "consolidated"].includes(item.statement_basis)
    && isString(item.financial_year)
    && isString(item.configuration_version)
    && isRecord(item.thresholds)
    && Object.values(item.thresholds).every((value) => isString(value) || Number.isInteger(value))
    && Array.isArray(item.periods)
    && item.periods.every(isString)
    && isString(item.comparison)
    && isString(item.fact)
    && isString(item.interpretation)
    && isNullableString(item.reason)
    && Array.isArray(item.observed)
    && item.observed.every((value) => isRecord(value)
      && isString(value.metric_id)
      && isString(value.financial_year)
      && isNullableString(value.value)
      && isString(value.unit)
      && isNullableString(value.currency)
      && ["calculated", "unavailable", "invalid_input"].includes(value.status))
    && Array.isArray(item.evidence)
    && item.evidence.every(isMetric);
}

function validateData(path, data) {
  const endpoint = path.split("?", 1)[0];
  if (endpoint === "/api/status") {
    if (!isRecord(data)
      || !isString(data.project_status)
      || !["empty", "available"].includes(data.data_availability)
      || !isNonNegativeInteger(data.source_backed_observation_count)
      || typeof data.real_financial_data_onboarded !== "boolean") {
      throw invalidResponse(path, "data must contain valid project status, availability, observation count, and onboarding fields.");
    }
    return;
  }
  if (endpoint === "/api/health") {
    if (!isRecord(data) || data.status !== "ok") throw invalidResponse(path, "data.status must be 'ok'.");
    return;
  }
  if (endpoint === "/api/companies") {
    validateArray(data, path, (item) => isRecord(item)
      && isString(item.company_id)
      && isString(item.company_name)
      && isNullableString(item.ticker)
      && isString(item.reporting_currency)
      && isNonNegativeInteger(item.financial_year_count)
      && isString(item.first_financial_year)
      && isString(item.last_financial_year));
    return;
  }
  if (/^\/api\/companies\/[^/]+\/metrics$/.test(endpoint)) {
    validateArray(data, path, isMetric);
    return;
  }
  if (/^\/api\/companies\/[^/]+\/analysis$/.test(endpoint)) {
    if (!isRecord(data)
      || !isString(data.company_id)
      || !["standalone", "consolidated"].includes(data.statement_basis)
      || !isString(data.configuration_version)) {
      throw invalidResponse(path, "data must contain company, statement basis, and configuration version fields.");
    }
    validateArray(data.assessments, path, isAssessment);
    return;
  }
  if (/^\/api\/companies\/[^/]+\/provenance$/.test(endpoint)) {
    validateArray(data, path, (item) => isRecord(item)
      && isString(item.source_id)
      && isString(item.publisher)
      && isNullableString(item.source_url)
      && isNullableString(item.publication_date)
      && isString(item.retrieved_at)
      && isString(item.financial_year)
      && isString(item.statement_basis)
      && isString(item.statement_type));
  }
}

/**
 * Fetch data from the FinSight API envelope, retrying transient Render/network failures.
 * @template T
 * @param {string} apiBase
 * @param {string} path
 * @param {{fetchImpl?: typeof fetch, timeoutMs?: number, retries?: number, waitImpl?: (milliseconds: number) => Promise<void>}} [options]
 * @returns {Promise<T>}
 */
export async function requestData(apiBase, path, options = {}) {
  const {
    fetchImpl = globalThis.fetch,
    timeoutMs = 90_000,
    retries = 2,
    waitImpl = wait,
  } = options;
  const url = `${apiBase.replace(/\/$/, "")}${path}`;
  let lastError;

  for (let attempt = 0; attempt <= retries; attempt += 1) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    let response;
    try {
      response = await fetchImpl(url, {
        headers: { Accept: "application/json" },
        cache: "no-store",
        signal: controller.signal,
      });
    } catch (error) {
      if (attempt === retries) {
        const reason = error instanceof Error ? error.message : "Network request failed.";
        throw new Error(`Could not reach the FinSight API. It may be waking after inactivity; please try again shortly. (${reason})`);
      }
      lastError = error instanceof Error ? error : new Error("Network request failed.");
    } finally {
      clearTimeout(timeout);
    }

    if (response) {
      let payload;
      try {
        payload = await response.json();
      } catch {
        if (!RETRYABLE_STATUSES.has(response.status)) {
          throw new Error(`The FinSight API returned an unreadable response (HTTP ${response.status}).`);
        }
        if (attempt === retries) {
          throw new Error(`The FinSight API is temporarily unavailable after retries. It may be waking after inactivity. (HTTP ${response.status})`);
        }
        lastError = new Error(`FinSight API is temporarily unavailable (HTTP ${response.status}).`);
      }

      if (payload !== undefined && response.ok) {
        if (!isRecord(payload) || !Object.hasOwn(payload, "data")) {
          throw new Error("The FinSight API response did not contain a data field.");
        }
        validateData(path, payload.data);
        return payload.data;
      }
      if (payload !== undefined && !response.ok) {
        const error = new Error(payload?.error?.message || `FinSight API request failed (HTTP ${response.status}).`);
        if (!RETRYABLE_STATUSES.has(response.status)) throw error;
        if (attempt === retries) {
          throw new Error(`The FinSight API is temporarily unavailable after retries. It may be waking after inactivity. (${error.message})`);
        }
        lastError = error;
      }
    }

    if (attempt === retries) {
      const reason = lastError instanceof Error ? lastError.message : "Network request failed.";
      throw new Error(`Could not reach the FinSight API. It may be waking after inactivity; please try again shortly. (${reason})`);
    }
    await waitImpl(Math.min(1_000 * (2 ** attempt), 4_000));
  }

  throw lastError ?? new Error("Could not reach the FinSight API.");
}
