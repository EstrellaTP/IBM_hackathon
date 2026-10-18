/**
 * Where the API lives.
 *
 * The web app can be served from two places:
 *   - the HTTPS gateway on the LinuxONE VM itself (port 8443), where the API is
 *     the same origin, so relative URLs are used;
 *   - a static host such as Vercel, which only serves these files. The browser
 *     then talks to the LinuxONE API directly, so no health data ever passes
 *     through the static host (data sovereignty, CLAUDE.md section 12).
 *
 * Override with `?api=<origin>` for testing another VM.
 *
 * @module config
 */

/** Public HTTPS origin of the LinuxONE gateway. */
export const LINUXONE_API_ORIGIN = "https://148.100.99.58:8443";

function resolveApiOrigin() {
  const override = new URLSearchParams(window.location.search).get("api");
  if (override) {
    return override.replace(/\/$/, "");
  }
  // Served by the LinuxONE gateway itself: same origin.
  if (window.location.origin === LINUXONE_API_ORIGIN) {
    return "";
  }
  return LINUXONE_API_ORIGIN;
}

/** API origin to prefix every request with ("" means same origin). */
export const API_ORIGIN = resolveApiOrigin();

/** Base path of the versioned REST API. */
export const API_BASE = `${API_ORIGIN}/api/v1`;

/**
 * WebSocket origin matching {@link API_ORIGIN}.
 *
 * @returns {string} Such as "wss://148.100.99.58:8443".
 */
export function webSocketOrigin() {
  const origin = API_ORIGIN || window.location.origin;
  return origin.replace(/^http/, "ws");
}

/** Product name shown in the interface (from the team's mock-up). */
export const BRAND_NAME = "Raul";
