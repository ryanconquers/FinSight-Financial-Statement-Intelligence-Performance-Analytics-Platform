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

function isInsight(item) {
  return isRecord(item)
    && isString(item.insight_id)
    && ["observed_trend", "screening_indicator", "coincident_indicators", "contrasting_indicators", "peer_comparison"].includes(item.category)
    && isString(item.finding)
    && Array.isArray(item.periods)
    && item.periods.every(isString)
    && isString(item.rule)
    && Array.isArray(item.observed_values)
    && item.observed_values.every((value) => isRecord(value)
      && isString(value.metric_id)
      && isString(value.financial_year)
      && isNullableString(value.value)
      && isString(value.unit)
      && isNullableString(value.currency)
      && ["calculated", "unavailable", "invalid_input"].includes(value.status)
      && (value.rule_id === undefined || isString(value.rule_id)))
    && isString(item.limitations)
    && Array.isArray(item.evidence)
    && item.evidence.every(isMetric);
}

function isBenchmark(item) {
  return isRecord(item)
    && isString(item.company_id)
    && ["standalone", "consolidated"].includes(item.statement_basis)
    && (item.financial_year === null || isString(item.financial_year))
    && ["available", "insufficient_data"].includes(item.status)
    && Array.isArray(item.peers_requested)
    && item.peers_requested.every(isString)
    && Number.isInteger(item.maximum_compatible_peer_count_for_any_metric)
    && isString(item.sample_disclosure)
    && isRecord(item.exclusions)
    && Object.values(item.exclusions).every((reasons) => Array.isArray(reasons) && reasons.every(isString))
    && Array.isArray(item.metrics)
    && item.metrics.every((metric) => isRecord(metric)
      && isString(metric.metric_id)
      && ["available", "insufficient_data"].includes(metric.status)
      && (metric.target_value === undefined || isNullableString(metric.target_value))
      && (metric.peer_median === undefined || isNullableString(metric.peer_median))
      && (metric.peer_count === undefined || isNonNegativeInteger(metric.peer_count))
      && (metric.exclusions === undefined || (isRecord(metric.exclusions) && Object.values(metric.exclusions).every(isString)))
      && Array.isArray(metric.values)
      && metric.values.every(isPeerValue));
}

function isPeerValue(value) {
  return isRecord(value)
    && isString(value.company_id)
    && isNullableString(value.value)
    && isString(value.unit)
    && isNullableString(value.currency)
    && isString(value.period_start)
    && isString(value.period_end)
    && typeof value.is_target === "boolean"
    && (value.evidence === null || isMetric(value.evidence))
    && (value.sources === undefined || (Array.isArray(value.sources) && value.sources.every(isSource)));
}

function isSource(source) {
  return isRecord(source)
    && isString(source.source_id)
    && isString(source.publisher)
    && isNullableString(source.source_url)
    && isNullableString(source.publication_date)
    && isString(source.retrieved_at)
    && isString(source.financial_year)
    && isString(source.statement_basis)
    && isString(source.statement_type);
}

function isForecastPeriod(period) {
  return isRecord(period) && isString(period.financial_year)
    && ["actual", "forecast"].includes(period.period_type)
    && Array.isArray(period.unavailable || [])
    && (period.values === undefined || (isRecord(period.values) && Object.values(period.values).every(isNullableString)))
    && isString(period.currency) && isString(period.unit);
}

function isForecast(item) {
  return isRecord(item) && isString(item.forecast_id) && isString(item.company_id)
    && ["standalone", "consolidated"].includes(item.statement_basis)
    && isString(item.baseline_year) && isNonNegativeInteger(item.forecast_horizon)
    && isString(item.methodology_version) && isRecord(item.assumptions)
    && (item.result === undefined || (isRecord(item.result) && isRecord(item.result.scenarios)
      && (item.result.created_from_observation_ids === undefined || (Array.isArray(item.result.created_from_observation_ids) && item.result.created_from_observation_ids.every(isNonNegativeInteger)))
      && (item.result.created_from_source_ids === undefined || (Array.isArray(item.result.created_from_source_ids) && item.result.created_from_source_ids.every(isString)))
      && (item.result.source_provenance === undefined || (Array.isArray(item.result.source_provenance) && item.result.source_provenance.every(isSource)))
      && (item.result.missing_historical_years === undefined || (Array.isArray(item.result.missing_historical_years) && item.result.missing_historical_years.every(isString)))
      && ["base", "bull", "bear"].every((name) => isRecord(item.result.scenarios[name])
        && isForecastPeriod(item.result.scenarios[name].actual_baseline)
        && (item.result.scenarios[name].actual_history === undefined || (Array.isArray(item.result.scenarios[name].actual_history) && item.result.scenarios[name].actual_history.every(isForecastPeriod)))
        && Array.isArray(item.result.scenarios[name].periods)
        && item.result.scenarios[name].periods.every(isForecastPeriod))));
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
  if (/^\/api\/companies\/[^/]+\/insights$/.test(endpoint)) {
    if (!isRecord(data) || !isString(data.company_id) || !["standalone", "consolidated"].includes(data.statement_basis)
      || (data.peer_benchmark_status !== undefined && data.peer_benchmark_status !== null && !["available", "insufficient_data"].includes(data.peer_benchmark_status))) {
      throw invalidResponse(path, "data must contain company and statement basis fields.");
    }
    validateArray(data.insights, path, isInsight);
    return;
  }
  if (/^\/api\/companies\/[^/]+\/benchmark$/.test(endpoint)) {
    if (!isBenchmark(data)) throw invalidResponse(path, "data has an unexpected benchmark shape.");
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
    return;
  }
  if (/^\/api\/companies\/[^/]+\/observations$/.test(endpoint)) {
    validateArray(data, path, (item) => isRecord(item)
      && isNonNegativeInteger(item.observation_id)
      && isString(item.company_id)
      && isString(item.financial_year)
      && isString(item.period_start)
      && isString(item.period_end)
      && ["standalone", "consolidated"].includes(item.statement_basis)
      && isString(item.statement_type)
      && isString(item.line_item_id)
      && isString(item.reported_label)
      && isNullableString(item.value)
      && isString(item.unit)
      && isString(item.currency)
      && isString(item.source_id)
      && isString(item.publisher)
      && isNullableString(item.source_url)
      && isNullableString(item.publication_date)
      && isString(item.retrieved_at));
    return;
  }
  if (/^\/api\/companies\/[^/]+\/forecasts$/.test(endpoint) || /^\/api\/companies\/[^/]+\/forecasts\/[^/]+$/.test(endpoint)) {
    if (Array.isArray(data)) validateArray(data, path, isForecast);
    else if (!isForecast(data)) throw invalidResponse(path, "data has an unexpected forecast shape.");
    return;
  }
  if (/^\/api\/companies\/[^/]+\/forecasts\/[^/]+\/revisions$/.test(endpoint)) {
    validateArray(data, path, (revision) => isRecord(revision) && isNonNegativeInteger(revision.revision)
      && isRecord(revision.assumptions) && isString(revision.input_fingerprint) && isString(revision.saved_at));
    return;
  }
  if (/^\/api\/companies\/[^/]+\/forecasts\/[^/]+\/revisions\/\d+$/.test(endpoint)) {
    if (!isForecast(data) || typeof data.current !== "boolean") throw invalidResponse(path, "data has an unexpected forecast revision shape.");
    return;
  }
  if (/^\/api\/companies\/[^/]+\/forecasts\/[^/]+\/sensitivity$/.test(endpoint)) {
    if (!isRecord(data) || !isString(data.methodology_version) || data.saved_assumptions_unchanged !== true || !Array.isArray(data.sensitivity)
      || !data.sensitivity.every((cell) => isRecord(cell) && isString(cell.revenue_growth) && isString(cell.ebitda_margin)
        && Array.isArray(cell.base) && cell.base.every(isForecastPeriod))) throw invalidResponse(path, "data has an unexpected sensitivity shape.");
    return;
  }
  if (/^\/api\/companies\/[^/]+\/forecasts\/[^/]+\/actual-vs-forecast$/.test(endpoint)) {
    if (!isRecord(data) || !isString(data.company_id) || !["standalone", "consolidated"].includes(data.statement_basis) || !Array.isArray(data.periods) || !data.periods.every(isForecastPeriod) || typeof data.input_data_stale !== "boolean") throw invalidResponse(path, "data has an unexpected actual-versus-forecast shape.");
  }
}

/**
 * Fetch data from the FinSight API envelope, retrying transient Render/network failures.
 * @template T
 * @param {string} apiBase
 * @param {string} path
 * @param {{fetchImpl?: typeof fetch, timeoutMs?: number, retries?: number, waitImpl?: (milliseconds: number) => Promise<void>, method?: string, body?: unknown}} [options]
 * @returns {Promise<T>}
 */
export async function requestData(apiBase, path, options = {}) {
  const {
    fetchImpl = globalThis.fetch,
    timeoutMs = 90_000,
    retries = 2,
    waitImpl = wait,
    method = "GET",
    body,
  } = options;
  const attemptsAllowed = method === "GET" ? retries : 0;
  const url = `${apiBase.replace(/\/$/, "")}${path}`;
  let lastError;

  for (let attempt = 0; attempt <= attemptsAllowed; attempt += 1) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    let response;
    try {
      response = await fetchImpl(url, {
        method,
        headers: { Accept: "application/json", ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
        cache: "no-store",
        signal: controller.signal,
      });
    } catch (error) {
      if (attempt === attemptsAllowed) {
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
        if (attempt === attemptsAllowed) {
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
        if (attempt === attemptsAllowed) {
          throw new Error(`The FinSight API is temporarily unavailable after retries. It may be waking after inactivity. (${error.message})`);
        }
        lastError = error;
      }
    }

    if (attempt === attemptsAllowed) {
      const reason = lastError instanceof Error ? lastError.message : "Network request failed.";
      throw new Error(`Could not reach the FinSight API. It may be waking after inactivity; please try again shortly. (${reason})`);
    }
    await waitImpl(Math.min(1_000 * (2 ** attempt), 4_000));
  }

  throw lastError ?? new Error("Could not reach the FinSight API.");
}
