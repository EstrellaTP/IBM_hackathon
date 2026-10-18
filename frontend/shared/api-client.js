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
 * @returns {{patientId: string, mock: boolean, replayNotice: boolean}} Page options.
 */
export function readPageOptions() {
  const params = new URLSearchParams(window.location.search);
  return {
    patientId: params.get("patient_id") ?? params.get("patient") ?? "p_7f3a2b",
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
 * @param {boolean} options.mock - Generate fake episodes instead of connecting.
 * @param {(episode: object) => void} options.onEpisode - Called with each EpisodeEvent.
 *   The server wraps it as `{type: "question", episode}` and also sends
 *   `{type: "ping"}` keep-alives, which are ignored here.
 * @param {(connected: boolean) => void} options.onStatus - Called when the link changes.
 * @returns {() => void} Function that closes the subscription.
 */
export function subscribeToQuestions({ patientId, mock, onEpisode, onStatus }) {
  if (mock) {
    return subscribeToMockQuestions({ patientId, onEpisode, onStatus });
  }

  let socket = null;
  let closed = false;
  let delay = RECONNECT_DELAY_MS;

  const connect = () => {
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    const path = `${API_BASE}/patients/${encodeURIComponent(patientId)}/questions`;
    const url = `${scheme}://${window.location.host}${path}`;
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
 * @param {boolean} mock - Skip the network call.
 * @returns {Promise<void>} Resolves when the server has stored the answer.
 * @throws {Error} If the server rejects the answer.
 */
export async function postAnswer(answer, mock) {
  if (mock) {
    mockStore.answers.set(answer.episode_id, answer);
    return;
  }
  const response = await fetch(`${API_BASE}/answers`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(answer),
  });
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
