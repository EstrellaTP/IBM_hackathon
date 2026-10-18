/**
 * Clinician page, Phase 1: timeline of episodes with the patient's answers.
 *
 * Shows, for each episode, when it happened, how unusual it was for this
 * patient, what the patient answered in the moment, and how long each stage
 * took (to make the LinuxONE latency visible in the demo). It never shows
 * generated text about the patient (CLAUDE.md section 5.5). The evidence
 * charts of the suspicion module are added in Phase 2 (F2-FE-01).
 *
 * @module clinician
 */

import {
  fetchEpisodes,
  formatClock,
  millisecondsBetween,
  readPageOptions,
} from "../shared/api-client.js";

const REFRESH_INTERVAL_MS = 5000;

/** Human labels for the Activity enum (services/common/schemas.py). */
const ACTIVITY_LABELS = {
  work: "Working or studying",
  rest: "Resting",
  social: "With other people",
  commute: "On the move",
  other: "Something else",
};

/** Human labels for the SafetyAction enum. Both actions are simulated only. */
const SAFETY_LABELS = {
  call_112_simulated: "Patient pressed “Call 112” (simulated)",
  notify_contact_simulated: "Patient pressed “Notify my trusted contact” (simulated)",
};

const options = readPageOptions();
const elements = {
  form: document.getElementById("patient-form"),
  input: document.getElementById("patient-input"),
  lastUpdated: document.getElementById("last-updated"),
  summary: document.getElementById("summary"),
  error: document.getElementById("load-error"),
  timeline: document.getElementById("timeline"),
};

let currentPatientId = options.patientId;
let refreshTimer = null;

/**
 * Build a definition list row such as "Heart rate vs baseline: +3.1 SD".
 *
 * @param {Array<[string, string]>} pairs - Label and value pairs.
 * @returns {HTMLDListElement} The rendered list.
 */
function definitionRow(pairs) {
  const list = document.createElement("dl");
  list.className = "definition-row";
  for (const [label, value] of pairs) {
    const term = document.createElement("dt");
    term.textContent = label;
    const detail = document.createElement("dd");
    detail.textContent = value;
    list.append(term, detail);
  }
  return list;
}

function formatZ(value) {
  return typeof value === "number" ? `${value >= 0 ? "+" : ""}${value.toFixed(1)} SD` : "—";
}

function formatMs(value) {
  return value === null ? "—" : `${value} ms`;
}

function formatDate(iso) {
  return new Date(iso).toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
}

function describeAnswer(answer) {
  if (!answer) {
    return [["Answer", "No answer"]];
  }
  const pairs = [];
  if (answer.safety_action) {
    pairs.push(["Safety", SAFETY_LABELS[answer.safety_action] ?? answer.safety_action]);
  }
  if (answer.activity) {
    pairs.push(["Doing", ACTIVITY_LABELS[answer.activity] ?? answer.activity]);
  }
  if (answer.activity_text) {
    pairs.push(["Note", answer.activity_text]);
  }
  if (answer.mood_1_5 !== null && answer.mood_1_5 !== undefined) {
    pairs.push(["Felt", `${answer.mood_1_5} / 5`]);
  }
  pairs.push(["Answered", formatClock(answer.answered_at)]);
  return pairs;
}

/**
 * Render one episode with its answer.
 *
 * @param {{episode: object, answer: object | null}} item - Episode and linked answer.
 * @returns {HTMLLIElement} Timeline item.
 */
function renderItem({ episode, answer }) {
  const item = document.createElement("li");
  const extreme = episode.severity === "extreme";
  item.className = `timeline__item${extreme ? " timeline__item--extreme" : ""}`;

  const meta = document.createElement("div");
  meta.className = "timeline__meta";
  const when = document.createElement("strong");
  when.textContent = `${formatDate(episode.detected_at)} · ${formatClock(episode.detected_at)}`;
  const tag = document.createElement("span");
  tag.className = `tag ${extreme ? "tag--alert" : "tag--normal"}`;
  tag.textContent = extreme ? "Strong change · safety question shown" : "Unusual for this patient";
  meta.append(when, tag);

  const features = episode.features ?? {};
  const signal = definitionRow([
    ["Heart rate vs own baseline", formatZ(features.hr_z)],
    ["Movement vs own baseline", formatZ(features.acc_mag_z)],
    ["EDA vs own baseline", formatZ(features.eda_z)],
  ]);

  const stamps = episode.timestamps ?? {};
  const latency = definitionRow([
    ["Inference on LinuxONE", formatMs(millisecondsBetween(stamps.ingested_at, stamps.inferred_at))],
    ["Push to phone", formatMs(millisecondsBetween(stamps.inferred_at, stamps.pushed_at))],
  ]);
  latency.classList.add("muted");

  item.append(meta, definitionRow(describeAnswer(answer)), signal, latency);
  return item;
}

function renderSummary(items) {
  const answered = items.filter((item) => item.answer).length;
  const strong = items.filter((item) => item.episode.severity === "extreme").length;
  elements.summary.textContent =
    items.length === 0
      ? "No episodes recorded yet for this patient."
      : `${items.length} episodes · ${answered} answered · ${strong} with the safety question`;
}

async function refresh() {
  try {
    const items = await fetchEpisodes(currentPatientId, options.mock);
    items.sort((a, b) => new Date(b.episode.detected_at) - new Date(a.episode.detected_at));
    elements.timeline.replaceChildren(...items.map(renderItem));
    renderSummary(items);
    elements.error.hidden = true;
    elements.lastUpdated.textContent = `Updated ${formatClock(new Date().toISOString())}`;
  } catch (error) {
    elements.error.textContent = error.message;
    elements.error.hidden = false;
  }
}

function start(patientId) {
  currentPatientId = patientId;
  const url = new URL(window.location.href);
  url.searchParams.delete("patient");
  url.searchParams.set("patient_id", patientId);
  window.history.replaceState(null, "", url);
  window.clearInterval(refreshTimer);
  refresh();
  refreshTimer = window.setInterval(refresh, REFRESH_INTERVAL_MS);
}

elements.input.value = currentPatientId;
elements.form.addEventListener("submit", (event) => {
  event.preventDefault();
  start(elements.input.value.trim());
});
start(currentPatientId);
