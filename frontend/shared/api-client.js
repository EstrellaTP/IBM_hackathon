/**
 * Thin client for the backend API, shared by the patient and clinician pages.
 *
 * Every page is served by the HTTPS gateway on the LinuxONE VM (port 8443), so
 * all URLs are relative and the WebSocket uses the same origin. Paths and message
 * formats follow docs/api.md, the API contract the gateway routes.
 *
 * Add `?mock=1` to any page to run it without a backend: the client then
 * produces contract-compliant fake data (services/common/contracts/*.example.json),
 * which is how the pages were developed before the services existed.
 *
 * @module api-client
 */

const API_BASE = "/api/v1";
const RECONNECT_DELAY_MS = 2000;
const MAX_RECONNECT_DELAY_MS = 30000;
const MOCK_FIRST_EPISODE_DELAY_MS = 4000;

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
 * @param {string} options.token - Patient access token from the link.
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
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    const path = `${API_BASE}/patients/${encodeURIComponent(patientId)}/questions`;
    // Browsers cannot set headers on a WebSocket, so the token goes in the query
    // string; the gateway sends Referrer-Policy: no-referrer so it is not leaked.
    const url = `${scheme}://${window.location.host}${path}?token=${encodeURIComponent(token)}`;
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
 * @param {string} token - Patient access token from the link.
 * @param {boolean} mock - Skip the network call.
 * @returns {Promise<void>} Resolves when the server has stored the answer.
 * @throws {Error} If the server rejects the answer.
 */
export async function postAnswer(answer, token, mock) {
  if (mock) {
    mockStore.answers.set(answer.episode_id, answer);
    return;
  }
  const response = await fetch(`${API_BASE}/answers`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(answer),
  });
  if (response.status === 401 || response.status === 403) {
    throw new Error("This link is not valid any more. Ask your clinician for a new one.");
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
  const url = `${API_BASE}/clinician/patients/${encodeURIComponent(patientId)}/timeline`;
  const response = await fetch(url, { headers: { Accept: "application/json" } });
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
  const response = await fetch(`${API_BASE}/module-runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(request),
  });
  if (response.ok) {
    return response.json();
  }
  const reasons = {
    404: "There is no recording for this patient.",
    422: "The selected period has too few valid days to run the module.",
    503: "The module is not available on the server right now.",
  };
  throw new Error(reasons[response.status] ?? `The module could not run (HTTP ${response.status}).`);
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
