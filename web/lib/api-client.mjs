const RETRYABLE_STATUSES = new Set([502, 503, 504]);

const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

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
        if (!payload || !Object.hasOwn(payload, "data")) {
          throw new Error("The FinSight API response did not contain a data field.");
        }
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
