/**
 * "Moments": an episode with the patient's in-the-moment answer.
 *
 * Shared by the clinician view (every assigned patient) and the patient view
 * (the patient's own history). Shows when it happened, what the patient said,
 * how unusual it was for that person, and, for clinicians, how fast LinuxONE
 * reacted. Never any generated text about the patient (CLAUDE.md section 5.5).
 *
 * @module moments
 */

import { formatClock, millisecondsBetween } from "./api-client.js";

/** Human labels for the Activity enum (services/common/schemas.py). */
export const ACTIVITY_LABELS = {
  exercise: "Physical activity",
  work: "Working or studying",
  rest: "Resting",
  social: "With other people",
  commute: "On the move",
  other: "Something else",
};

/** Human labels for the AnswerDetails follow-ups, in the order they are asked. */
export const DETAIL_LABELS = {
  exercise_intensity: { light: "light intensity", moderate: "moderate intensity", vigorous: "intense" },
  usual_for_you: { true: "usual for them at this time", false: "not usual at this time" },
  workload: { light: "calm workload", normal: "normal workload", demanding: "very demanding workload" },
  rest_state: { awake: "awake", falling_asleep: "trying to sleep", just_woke_up: "just woke up" },
  company: {
    family: "with family",
    partner: "with partner",
    friends: "with friends",
    colleagues: "with colleagues",
    strangers: "with people they don't know",
  },
  social_tone: { pleasant: "pleasant", neutral: "neutral", tense: "tense" },
  travel_mode: {
    walking: "walking",
    cycling: "cycling",
    public_transport: "public transport",
    car: "by car",
  },
  in_a_hurry: { true: "in a hurry", false: "not in a hurry" },
  emotion: {
    calm: "calm",
    happy: "happy",
    energetic: "energetic",
    tired: "tired",
    sad: "sad",
    anxious: "nervous",
    irritable: "irritable",
    overwhelmed: "overwhelmed",
  },
  something_happened: { true: "something happened just before", false: "nothing happened before" },
};

/**
 * Turn an answer's follow-up details into short phrases.
 *
 * @param {object | null | undefined} details - AnswerDetails contract object.
 * @returns {string[]} One phrase per answered follow-up.
 */
export function describeDetails(details) {
  if (!details) {
    return [];
  }
  return Object.entries(DETAIL_LABELS)
    .filter(([key]) => details[key] !== null && details[key] !== undefined)
    .map(([key, labels]) => labels[String(details[key])] ?? String(details[key]));
}

const SAFETY_LABELS = {
  call_112_simulated: "Pressed “Call 112” (simulated, nobody was called)",
  notify_contact_simulated: "Pressed “Notify my trusted contact” (simulated)",
};

const MOOD_LEVELS = 5;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) {
    node.className = className;
  }
  if (text !== undefined) {
    node.textContent = text;
  }
  return node;
}

function formatDay(iso) {
  return new Date(iso).toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
}

function formatZ(value) {
  return typeof value === "number" ? `${value >= 0 ? "+" : ""}${value.toFixed(1)} SD` : "—";
}

function moodDots(mood) {
  const dots = element("span", "mood-dots");
  dots.setAttribute("aria-hidden", "true");
  for (let level = 1; level <= MOOD_LEVELS; level += 1) {
    dots.append(element("span", level <= mood ? "is-on" : ""));
  }
  return dots;
}

function describeAnswer(answer) {
  const line = element("p", "moment__answer");
  if (!answer) {
    line.classList.add("moment__answer--missing");
    line.textContent = "No answer";
    return line;
  }
  const parts = [];
  if (answer.safety_action) {
    parts.push(SAFETY_LABELS[answer.safety_action] ?? answer.safety_action);
  }
  if (answer.activity) {
    parts.push(ACTIVITY_LABELS[answer.activity] ?? answer.activity);
  }
  parts.push(...describeDetails(answer.details));
  if (answer.activity_text) {
    parts.push(`“${answer.activity_text}”`);
  }
  line.textContent = parts.join(" · ") || "Answered";
  if (answer.mood_1_5) {
    line.append(` · felt ${answer.mood_1_5}/5`);
    line.append(moodDots(answer.mood_1_5));
  }
  return line;
}

/**
 * Render one moment.
 *
 * @param {{episode: object, answer: object | null}} item - Episode and its answer.
 * @param {object} options - Rendering options.
 * @param {boolean} options.forClinician - Show signal z-scores and LinuxONE timings.
 * @param {boolean} [options.isNew] - Highlight it briefly (it just arrived).
 * @returns {HTMLLIElement} The list item.
 */
export function renderMoment({ episode, answer }, { forClinician, isNew = false }) {
  const extreme = episode.severity === "extreme";
  const item = element(
    "li",
    `moment${extreme ? " moment--extreme" : ""}${isNew ? " moment--new" : ""}`,
  );

  const when = element("div");
  when.append(
    element("div", "moment__time", formatClock(episode.detected_at).slice(0, 5)),
    element("div", "moment__date", formatDay(episode.detected_at)),
  );

  const body = element("div");
  if (extreme) {
    body.append(element("span", "tag tag--alert", "Strong change · safety question shown"));
  }
  body.append(describeAnswer(answer));

  if (forClinician) {
    const features = episode.features ?? {};
    const stamps = episode.timestamps ?? {};
    const inference = millisecondsBetween(stamps.ingested_at, stamps.inferred_at);
    const signals = element("p", "moment__signals");
    const pairs = [
      ["Heart rate", formatZ(features.hr_z)],
      ["Movement", formatZ(features.acc_mag_z)],
      ["EDA", formatZ(features.eda_z)],
      ["LinuxONE inference", inference === null ? "—" : `${inference} ms`],
    ];
    for (const [label, value] of pairs) {
      const span = element("span", "", `${label} `);
      span.append(element("strong", "", value));
      signals.append(span);
    }
    body.append(signals);
  }

  item.append(when, body);
  return item;
}

/**
 * Render a list of moments, newest first.
 *
 * @param {HTMLElement} container - List element (`<ol>`).
 * @param {Array<{episode: object, answer: object | null}>} items - Moments.
 * @param {object} options - Same options as {@link renderMoment}, plus `knownIds`.
 * @param {Set<string>} [options.knownIds] - Episode ids already shown; others are new.
 * @returns {Set<string>} The ids now shown.
 */
export function renderMoments(container, items, { forClinician, knownIds }) {
  const sorted = [...items].sort(
    (a, b) => new Date(b.episode.detected_at) - new Date(a.episode.detected_at),
  );
  container.replaceChildren(
    ...sorted.map((item) =>
      renderMoment(item, {
        forClinician,
        isNew: Boolean(knownIds && knownIds.size && !knownIds.has(item.episode.episode_id)),
      }),
    ),
  );
  return new Set(sorted.map((item) => item.episode.episode_id));
}
