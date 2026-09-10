/**
 * Data access. In development Vite proxies these to the Python service on 8765; in the
 * built panel they are same-origin because Python serves the built files too.
 */

async function getJson(path, signal) {
  const res = await fetch(path, { signal });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      detail = (await res.json()).error || detail;
    } catch {
      /* a non-JSON error body is still an error; keep the status */
    }
    throw new Error(detail);
  }
  return res.json();
}

export const getPortfolio = (signal) => getJson("/api/portfolio", signal);
export const getSuppliers = (signal) => getJson("/api/suppliers", signal);

/**
 * Stream one screening. Returns an unsubscribe function.
 *
 * The server sends one event per real pipeline step. `pace` slows the *display* only --
 * every step carries its true elapsed_ms, so never present the pacing as compute time.
 */
export function streamScreening(supplierId, { pace = 550, onStep, onResult, onError, onDone }) {
  const source = new EventSource(
    `/api/stream?supplier=${encodeURIComponent(supplierId)}&pace=${pace}`
  );
  source.addEventListener("step", (e) => onStep?.(JSON.parse(e.data)));
  source.addEventListener("result", (e) => onResult?.(JSON.parse(e.data)));
  source.addEventListener("done", () => {
    onDone?.();
    source.close();
  });
  source.addEventListener("error", (e) => {
    let message = "Stream failed. Is the screening service running?";
    try {
      message = JSON.parse(e.data).message;
    } catch {
      /* transport-level failure carries no payload */
    }
    onError?.(message);
    source.close();
  });
  return () => source.close();
}
