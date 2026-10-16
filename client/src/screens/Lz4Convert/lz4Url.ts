import { safeGetItem, safeRemoveItem, safeSetItem } from "../../lib/safeStorage";

/** The port the LZ4 Compression engine (lz4/) serves its page and API on. */
export const LZ4_PORT = 5920;
const KEY_LZ4_URL = "ps5upload.lz4_url";

/** Trim and drop any trailing slash; a bare host or host:port gets http://. */
export function normalizeLz4Url(raw: string): string {
  const v = raw.trim().replace(/\/+$/, "");
  if (!v) return "";
  return /^https?:\/\//i.test(v) ? v : `http://${v}`;
}

/** Where the LZ4 engine is when nothing is set: the same host as the ps5upload engine
 *  (the Docker compose file runs both on one server), on the LZ4 port. */
export function defaultLz4Url(engineUrl: string): string {
  try {
    const u = new URL(engineUrl);
    return `${u.protocol}//${u.hostname}:${LZ4_PORT}`;
  } catch {
    return `http://127.0.0.1:${LZ4_PORT}`;
  }
}

export function loadLz4Url(): string | null {
  const v = safeGetItem(KEY_LZ4_URL);
  return v ? normalizeLz4Url(v) || null : null;
}

/** An empty value forgets the setting, so the default applies again. */
export function saveLz4Url(url: string): void {
  const v = normalizeLz4Url(url);
  if (v) safeSetItem(KEY_LZ4_URL, v);
  else safeRemoveItem(KEY_LZ4_URL);
}
