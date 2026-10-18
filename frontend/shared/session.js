/**
 * The signed-in user's session, kept for the browser tab only.
 *
 * The token is issued by LinuxONE (`POST /api/v1/sessions`, issue #14) and sent
 * with every request; LinuxONE decides what each role may read or write. The
 * browser only remembers it in sessionStorage, so closing the tab signs out.
 *
 * @module session
 */

const STORAGE_KEY = "holter.session";
const LOGIN_PAGE = "/index.html";

/**
 * @typedef {object} Session
 * @property {string} token - Bearer token issued by the server.
 * @property {"patient" | "clinician"} role - What the user can see.
 * @property {string} display_name - Name shown in the header.
 * @property {string | null} patient_id - The patient's own pseudonymous id.
 * @property {string} expires_at - ISO 8601 expiry time.
 * @property {boolean} [mock] - True for the offline demo mode.
 */

/**
 * Read the current session, dropping it if it has expired.
 *
 * @returns {Session | null} The session, or null when signed out.
 */
export function getSession() {
  try {
    const session = JSON.parse(window.sessionStorage.getItem(STORAGE_KEY) ?? "null");
    if (!session || new Date(session.expires_at) <= new Date()) {
      clearSession();
      return null;
    }
    return session;
  } catch {
    return null;
  }
}

/**
 * Remember a session for this tab.
 *
 * @param {Session} session - Session returned by the login endpoint.
 */
export function saveSession(session) {
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session));
  } catch {
    // Storage can be blocked (private mode): the app still works until reload.
  }
}

/** Forget the session. */
export function clearSession() {
  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Nothing to clear.
  }
}

/**
 * Send the user to the login page, remembering where they were.
 *
 * @param {string} [reason] - Short message to show on the login page.
 */
export function goToLogin(reason) {
  const next = encodeURIComponent(window.location.pathname + window.location.search);
  const query = new URLSearchParams({ next: decodeURIComponent(next) });
  if (reason) {
    query.set("reason", reason);
  }
  window.location.assign(`${LOGIN_PAGE}?${query}`);
}

/**
 * Return the session or redirect to the login page.
 *
 * @param {"patient" | "clinician"} [role] - Required role, if any.
 * @returns {Session | null} The session when allowed, null after redirecting.
 */
export function requireSession(role) {
  const session = getSession();
  if (!session) {
    goToLogin();
    return null;
  }
  if (role && session.role !== role) {
    window.location.assign("/app/");
    return null;
  }
  return session;
}
