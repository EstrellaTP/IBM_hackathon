/**
 * Thin client for the LinuxONE API, shared by every page.
 *
 * Paths and message formats follow docs/api.md. The API origin comes from
 * config.js: same origin when the pages are served by the LinuxONE gateway,
 * the gateway's public origin when they are served by a static host (Vercel).
 * Every request carries the signed-in user's token; LinuxONE checks what each
 * role may read or write (issue #14).
 *
 * Add `?mock=1` to any page, or sign in with a demo account in offline mode, to
 * run without a backend: the client then produces contract-compliant fake data.
 *
 * @module api-client
 */

import { API_BASE, webSocketOrigin } from "./config.js";
import { clearSession, getSession, goToLogin } from "./session.js";

const RECONNECT_DELAY_MS = 2000;
const MAX_RECONNECT_DELAY_MS = 30000;
const MOCK_FIRST_EPISODE_DELAY_MS = 4000;
const MOCK_SESSION_HOURS = 12;

/**
 * Whether the page runs on fake data (offline demo).
 *
 * @returns {boolean} True with `?mock=1` or a session opened in offline mode.
 */
export function isMock() {
  return (
    new URLSearchParams(window.location.search).get("mock") === "1" ||
    Boolean(getSession()?.mock)
  );
}

/**
 * Fetch from the API with the session token; sign out on 401.
 *
 * @param {string} path - Path under /api/v1, starting with "/".
 * @param {RequestInit} [init] - Fetch options.
 * @returns {Promise<Response>} The response (never a 401).
 * @throws {Error} When the session is no longer valid (after redirecting).
 */
async function apiFetch(path, init = {}) {
  const headers = new Headers(init.headers ?? {});
  headers.set("Accept", "application/json");
  const token = getSession()?.token;
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (response.status === 401) {
    clearSession();
    goToLogin("Your session has ended. Sign in again.");
    throw new Error("Your session has ended.");
  }
  return response;
}

/**
 * Sign in on LinuxONE.
 *
 * @param {string} username - Account name.
 * @param {string} password - Password.
 * @param {boolean} offline - Open an offline demo session with fake data instead.
 * @returns {Promise<import("./session.js").Session>} The new session.
 * @throws {Error} With a message to show under the form.
 */
export async function login(username, password, offline) {
  if (offline) {
    return mockSession(username);
  }
  let response;
  try {
    response = await fetch(`${API_BASE}/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ username, password }),
    });
  } catch {
    throw new Error("LinuxONE cannot be reached right now. Check the connection and try again.");
  }
  if (response.status === 401) {
    throw new Error("The username or password is not correct.");
  }
  if (!response.ok) {
    throw new Error(`Sign-in failed on the server (HTTP ${response.status}).`);
  }
  return response.json();
}

/**
 * Read page options from the query string.
 *
 * The patient link carries a per-patient access token (`?token=`) issued by the
 * server (issue #14). The page sends it with every patient-side request; without a
 * valid token the server refuses to push questions or store answers.
 *
 * @returns {{patientId: string, token: string, mock: boolean, replayNotice: boolean}}
 *   Page options.
 */
export function readPageOptions() {
  const params = new URLSearchParams(window.location.search);
  return {
    patientId: params.get("patient_id") ?? params.get("patient") ?? "p_7f3a2b",
    token: params.get("token") ?? "",
    mock: params.get("mock") === "1",
    // The demo replays recorded WESAD signals; the patient page says so on screen.
    replayNotice: params.get("replay") !== "0",
  };
}

/**
 * Current time as an ISO 8601 string in UTC, as required by the contracts.
 *
 * @returns {string} Timestamp such as "2026-10-18T09:00:00.000Z".
 */
export function nowIso() {
  return new Date().toISOString();
}

/**
 * Format an ISO timestamp as local wall-clock time with seconds.
 *
 * @param {string | null | undefined} iso - ISO 8601 timestamp.
 * @returns {string} Time such as "12:03:15", or "—" when missing.
 */
export function formatClock(iso) {
  if (!iso) {
    return "—";
  }
  return new Date(iso).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

/**
 * Milliseconds between two ISO timestamps.
 *
 * @param {string | null | undefined} startIso - Earlier timestamp.
 * @param {string | null | undefined} endIso - Later timestamp.
 * @returns {number | null} Difference in milliseconds, or null if either is missing.
 */
export function millisecondsBetween(startIso, endIso) {
  if (!startIso || !endIso) {
    return null;
  }
  return new Date(endIso).getTime() - new Date(startIso).getTime();
}

/**
 * Subscribe to the questions pushed to one patient's phone.
 *
 * Reconnects with exponential back-off when the connection drops, because a
 * phone on mobile data loses the socket often.
 *
 * @param {object} options - Subscription options.
 * @param {string} options.patientId - Pseudonymous patient id.
 * @param {string} options.token - The patient's session token.
 * @param {boolean} options.mock - Generate fake episodes instead of connecting.
 * @param {(episode: object) => void} options.onEpisode - Called with each EpisodeEvent.
 *   The server wraps it as `{type: "question", episode}` and also sends
 *   `{type: "ping"}` keep-alives, which are ignored here.
 * @param {(connected: boolean) => void} options.onStatus - Called when the link changes.
 * @returns {() => void} Function that closes the subscription.
 */
export function subscribeToQuestions({ patientId, token, mock, onEpisode, onStatus }) {
  if (mock) {
    return subscribeToMockQuestions({ patientId, onEpisode, onStatus });
  }

  let socket = null;
  let closed = false;
  let delay = RECONNECT_DELAY_MS;

  const connect = () => {
    const path = `/api/v1/patients/${encodeURIComponent(patientId)}/questions`;
    // Browsers cannot set headers on a WebSocket, so the token goes in the query
    // string; the gateway sends Referrer-Policy: no-referrer so it is not leaked.
    const url = `${webSocketOrigin()}${path}?token=${encodeURIComponent(token)}`;
    socket = new WebSocket(url);
    socket.addEventListener("open", () => {
      delay = RECONNECT_DELAY_MS;
      onStatus(true);
    });
    socket.addEventListener("message", (message) => {
      try {
        const payload = JSON.parse(message.data);
        if (payload.type === "question" && payload.episode) {
          onEpisode(payload.episode);
        }
      } catch (error) {
        console.error("Ignoring malformed episode message", error);
      }
    });
    socket.addEventListener("close", () => {
      onStatus(false);
      if (!closed) {
        window.setTimeout(connect, delay);
        delay = Math.min(delay * 2, MAX_RECONNECT_DELAY_MS);
      }
    });
  };

  connect();
  return () => {
    closed = true;
    socket?.close();
  };
}

/**
 * Send the patient's answer to an episode.
 *
 * @param {object} answer - A QuestionAnswer contract object.
 * @param {string} token - Unused; kept for the legacy page (the session token is sent).
 * @param {boolean} mock - Skip the network call.
 * @returns {Promise<void>} Resolves when the server has stored the answer.
 * @throws {Error} If the server rejects the answer.
 */
export async function postAnswer(answer, token, mock) {
  if (mock) {
    mockStore.answers.set(answer.episode_id, answer);
    return;
  }
  const response = await apiFetch("/answers", {
    method: "POST",
    headers: tokenHeader(token),
    body: JSON.stringify(answer),
  });
  if (response.status === 403) {
    throw new Error("This question belongs to another account, so the answer was not saved.");
  }
  if (!response.ok) {
    throw new Error(`The answer was not saved (HTTP ${response.status}).`);
  }
}

/**
 * Fetch one patient's episodes with the answer linked to each of them.
 *
 * @param {string} patientId - Pseudonymous patient id.
 * @param {boolean} mock - Return fake data instead of calling the server.
 * @returns {Promise<Array<{episode: object, answer: object | null}>>} Newest first.
 * @throws {Error} If the request fails.
 */
export async function fetchEpisodes(patientId, mock) {
  if (mock) {
    return mockEpisodeList(patientId);
  }
  const path = `/clinician/patients/${encodeURIComponent(patientId)}/timeline`;
  const response = await apiFetch(path);
  if (response.status === 403) {
    throw new Error("This patient is not assigned to you.");
  }
  if (response.status === 404) {
    return [];
  }
  if (!response.ok) {
    throw new Error(`Episodes could not be loaded (HTTP ${response.status}).`);
  }
  const body = await response.json();
  return body.items ?? [];
}

/**
 * Run the suspicion module selected by the clinician on one patient's recording.
 *
 * Only the requested module runs on LinuxONE (CLAUDE.md section 5.2).
 *
 * @param {object} request - A ModuleRequest contract object.
 * @param {boolean} mock - Return a fake ModuleResult instead of calling the server.
 * @returns {Promise<object>} The ModuleResult.
 * @throws {Error} With a readable message for 404 (no recording), 422 (too few
 *   valid days) and 503 (model not available).
 */
export async function runModule(request, mock) {
  if (mock) {
    return mockModuleResult(request);
  }
  const response = await apiFetch("/module-runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (response.ok) {
    return response.json();
  }
  const reasons = {
    403: "This patient is not assigned to you.",
    404: "There is no recording for this patient.",
    422: "The selected period has too few valid days to run the module.",
    503: "The module is not available on the server right now.",
  };
  throw new Error(reasons[response.status] ?? `The module could not run (HTTP ${response.status}).`);
}

/**
 * The clinician's assigned patients.
 *
 * @returns {Promise<Array<{patient_id: string, episodes: number, answered: number,
 *   last_episode_at: string | null}>>} Patients, most recent activity first.
 * @throws {Error} If the request fails.
 */
export async function fetchMyPatients() {
  if (isMock()) {
    return mockPatients();
  }
  const response = await apiFetch("/clinician/patients");
  if (!response.ok) {
    throw new Error(`Patients could not be loaded (HTTP ${response.status}).`);
  }
  const patients = await response.json();
  return patients.sort((a, b) =>
    String(b.last_episode_at ?? "").localeCompare(String(a.last_episode_at ?? "")),
  );
}

/**
 * The signed-in patient's own episodes and answers.
 *
 * @returns {Promise<Array<{episode: object, answer: object | null}>>} Newest first.
 * @throws {Error} If the request fails.
 */
export async function fetchMyTimeline() {
  const session = getSession();
  if (isMock()) {
    return mockEpisodeList(session?.patient_id ?? "p_7f3a2b");
  }
  const response = await apiFetch("/patients/me/timeline");
  if (!response.ok) {
    throw new Error(`Your history could not be loaded (HTTP ${response.status}).`);
  }
  const body = await response.json();
  return body.items ?? [];
}

function tokenHeader(token) {
  // The legacy patient page may carry a link token; the session token wins.
  const headers = { "Content-Type": "application/json" };
  if (token && !getSession()) {
    headers.Authorization = `Bearer ${token}`;
  }
  return headers;
}

// --------------------------------------------------------------------------
// Mock mode: contract-compliant fake data so the pages work without a backend.
// --------------------------------------------------------------------------

const mockStore = { episodes: [], answers: new Map() };

function randomHex(length) {
  const bytes = new Uint8Array(length / 2);
  window.crypto.getRandomValues(bytes);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function mockEpisode(patientId, severity) {
  const detected = new Date();
  const iso = (offsetMs) => new Date(detected.getTime() + offsetMs).toISOString();
  return {
    episode_id: `e_${randomHex(16)}`,
    patient_id: patientId,
    start: iso(-60000),
    detected_at: iso(0),
    severity,
    score: severity === "extreme" ? 6.4 : 3.1,
    method: "zscore",
    features: { hr_z: severity === "extreme" ? 6.4 : 3.1, acc_mag_z: 0.2, eda_z: 1.8 },
    timestamps: {
      sample_t: iso(-150),
      ingested_at: iso(-40),
      inferred_at: iso(-28),
      pushed_at: iso(-25),
      received_at: null,
    },
  };
}

function subscribeToMockQuestions({ patientId, onEpisode, onStatus }) {
  onStatus(true);
  let count = 0;
  const emit = () => {
    // Every third mock episode is extreme, to exercise the safety protocol.
    count += 1;
    const episode = mockEpisode(patientId, count % 3 === 0 ? "extreme" : "normal");
    mockStore.episodes.unshift(episode);
    onEpisode(episode);
  };
  const first = window.setTimeout(emit, MOCK_FIRST_EPISODE_DELAY_MS);
  const repeat = window.setInterval(emit, 45000);
  return () => {
    window.clearTimeout(first);
    window.clearInterval(repeat);
  };
}

function mockEpisodeList(patientId) {
  if (mockStore.episodes.length === 0) {
    const activities = ["work", "commute", "rest", "social"];
    for (let index = 0; index < 6; index += 1) {
      const episode = mockEpisode(patientId, index === 2 ? "extreme" : "normal");
      const shiftMs = (index + 1) * 3.5 * 3600 * 1000;
      for (const key of ["start", "detected_at"]) {
        episode[key] = new Date(new Date(episode[key]).getTime() - shiftMs).toISOString();
      }
      for (const [key, value] of Object.entries(episode.timestamps)) {
        if (value) {
          episode.timestamps[key] = new Date(new Date(value).getTime() - shiftMs).toISOString();
        }
      }
      mockStore.episodes.push(episode);
      if (index !== 4) {
        mockStore.answers.set(episode.episode_id, {
          episode_id: episode.episode_id,
          activity: activities[index % activities.length],
          activity_text: null,
          mood_1_5: 1 + (index % 5),
          safety_action: index === 2 ? "notify_contact_simulated" : null,
          answered_at: new Date(new Date(episode.detected_at).getTime() + 40000).toISOString(),
        });
      }
    }
  }
  return mockStore.episodes.map((episode) => ({
    episode,
    answer: mockStore.answers.get(episode.episode_id) ?? null,
  }));
}

function mockSeries(days, center, spread, seed) {
  // Deterministic pseudo-random values so screenshots are stable between runs.
  let state = seed;
  const next = () => {
    state = (state * 9301 + 49297) % 233280;
    return state / 233280 - 0.5;
  };
  const today = Date.now();
  return Array.from({ length: days }, (_, index) => {
    const day = new Date(today - (days - 1 - index) * 86400000).toISOString().slice(0, 10);
    return { day, value: Number((center + spread * next()).toFixed(3)) };
  });
}

function mockModuleResult(request) {
  const days = 14;
  const group = "F_30-39";
  return {
    patient_id: request.patient_id,
    suspicion: request.suspicion,
    result: "compatible",
    confidence: 0.74,
    model_version: "mock-0",
    data_quality: { valid_days: days, missing_hours: 24 },
    metrics: [
      {
        name: "sleep",
        unit: "h/day",
        patient_series: mockSeries(days, 11.2, 3, 7),
        reference: { p10: 6.2, p50: 8.1, p90: 10.0, group },
        is_evidence: true,
        shap: 0.41,
        available: true,
      },
      {
        name: "circadian_rhythm",
        unit: "0-1",
        patient_series: mockSeries(days, 0.62, 0.25, 11),
        reference: { p10: 0.71, p50: 0.84, p90: 0.93, group },
        is_evidence: true,
        shap: 0.33,
        available: true,
      },
      {
        name: "daytime_activity",
        unit: "x own M10",
        patient_series: mockSeries(days, 0.62, 0.3, 3),
        reference: { p10: 0.55, p50: 0.78, p90: 1.02, group },
        is_evidence: false,
        shap: 0.05,
        available: true,
      },
      { name: "heart_rate", unit: "bpm", patient_series: [], reference: null, available: false },
    ],
    episodes: [],
    generated_at: new Date().toISOString(),
  };
}

const MOCK_ACCOUNTS = {
  "patient.demo": { role: "patient", display_name: "Demo patient", patient_id: "p_7f3a2b9c1d4e5f60" },
  "clinician.demo": { role: "clinician", display_name: "Dr. Demo", patient_id: null },
};

function mockSession(username) {
  const account = MOCK_ACCOUNTS[username.trim().toLowerCase()];
  if (!account) {
    throw new Error("Offline demo accounts are patient.demo and clinician.demo.");
  }
  return {
    token: "offline-demo",
    ...account,
    expires_at: new Date(Date.now() + MOCK_SESSION_HOURS * 3600000).toISOString(),
    mock: true,
  };
}

function mockPatients() {
  const now = Date.now();
  return [
    { patient_id: "p_7f3a2b9c1d4e5f60", episodes: 6, answered: 5, last_episode_at: new Date(now - 3600000).toISOString() },
    { patient_id: "p_dec052417c41", episodes: 0, answered: 0, last_episode_at: null },
    { patient_id: "p_dec0ecf80c4a", episodes: 0, answered: 0, last_episode_at: null },
    { patient_id: "p_dec0d611e801", episodes: 0, answered: 0, last_episode_at: null },
  ];
}
