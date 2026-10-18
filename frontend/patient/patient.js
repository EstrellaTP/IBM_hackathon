/**
 * Patient page: receives the in-the-moment question and sends the answer.
 *
 * Flow (CLAUDE.md sections 5.1 and 5.4):
 *   1. The page listens on a WebSocket for EpisodeEvent messages from the detector.
 *   2. A normal episode shows the question: what were you doing, how do you feel.
 *   3. An extreme episode first shows "Are you OK?" with buttons the patient
 *      chooses from; nothing is sent automatically.
 *   4. The answer is posted as a QuestionAnswer linked to its episode.
 *
 * @module patient
 */

import {
  formatClock,
  millisecondsBetween,
  nowIso,
  postAnswer,
  readPageOptions,
  subscribeToQuestions,
} from "../shared/api-client.js";

/** Activity options, matching the Activity enum in services/common/schemas.py. */
const ACTIVITIES = [
  { value: "work", label: "Working or studying" },
  { value: "rest", label: "Resting" },
  { value: "social", label: "With other people" },
  { value: "commute", label: "On the move" },
  { value: "other", label: "Something else" },
];

const MOOD_VALUES = [1, 2, 3, 4, 5];

const options = readPageOptions();
const elements = {
  connectionDot: document.getElementById("connection-dot"),
  connectionText: document.getElementById("connection-text"),
  replayNotice: document.getElementById("replay-notice"),
  idleCard: document.getElementById("idle-card"),
  patientId: document.getElementById("patient-id"),
  safetyCard: document.getElementById("safety-card"),
  questionCard: document.getElementById("question-card"),
  episodeTiming: document.getElementById("episode-timing"),
  activityOptions: document.getElementById("activity-options"),
  activityText: document.getElementById("activity-text"),
  moodOptions: document.getElementById("mood-options"),
  sendAnswer: document.getElementById("send-answer"),
  formError: document.getElementById("form-error"),
  confirmation: document.getElementById("confirmation"),
};

/** Episode currently waiting for an answer, or null. */
let pendingEpisode = null;

/**
 * Render a group of radio buttons styled as large touch targets.
 *
 * @param {HTMLElement} container - Element that receives the options.
 * @param {string} name - Radio group name.
 * @param {Array<{value: string, label: string}>} choices - Options to render.
 */
function renderChoices(container, name, choices) {
  container.replaceChildren(
    ...choices.map(({ value, label }) => {
      const wrapper = document.createElement("div");
      wrapper.className = "choice";
      const input = document.createElement("input");
      input.type = "radio";
      input.name = name;
      input.id = `${name}-${value}`;
      input.value = value;
      const text = document.createElement("label");
      text.htmlFor = input.id;
      text.textContent = label;
      wrapper.append(input, text);
      return wrapper;
    }),
  );
}

function setConnection(connected) {
  elements.connectionDot.classList.toggle("status-dot--live", connected);
  elements.connectionDot.classList.toggle("status-dot--offline", !connected);
  elements.connectionText.textContent = connected ? "Recording" : "Reconnecting…";
}

function showOnly(section) {
  for (const candidate of [elements.idleCard, elements.safetyCard, elements.questionCard]) {
    candidate.hidden = candidate !== section;
  }
}

function selectedValue(name) {
  return elements.questionCard.querySelector(`input[name="${name}"]:checked`)?.value ?? null;
}

function updateSendButton() {
  const hasActivity = selectedValue("activity") !== null || elements.activityText.value.trim();
  const hasMood = selectedValue("mood") !== null;
  elements.sendAnswer.disabled = !(hasActivity || hasMood);
}

/**
 * Show the timing of the episode, so the demo makes the latency visible.
 *
 * The reception time comes from the phone's clock, the detection time from the
 * server's; a small skew between the two is possible and is labelled as such.
 *
 * @param {object} episode - The EpisodeEvent being answered.
 * @param {string} receivedAt - When the phone received it (ISO 8601).
 */
function renderTiming(episode, receivedAt) {
  const serverMs = millisecondsBetween(
    episode.timestamps?.ingested_at,
    episode.timestamps?.inferred_at,
  );
  const parts = [
    `Episode detected ${formatClock(episode.detected_at)}`,
    `question received ${formatClock(receivedAt)}`,
  ];
  if (serverMs !== null) {
    parts.push(`inference on LinuxONE ${serverMs} ms`);
  }
  elements.episodeTiming.textContent = parts.join(" · ");
}

function showQuestion() {
  elements.questionCard.reset();
  elements.formError.hidden = true;
  updateSendButton();
  showOnly(elements.questionCard);
  elements.questionCard.querySelector("input")?.focus();
}

function handleEpisode(episode) {
  const receivedAt = nowIso();
  pendingEpisode = episode;
  elements.confirmation.hidden = true;
  renderTiming(episode, receivedAt);
  if ("vibrate" in navigator) {
    navigator.vibrate(200);
  }
  if (episode.severity === "extreme") {
    showOnly(elements.safetyCard);
    document.getElementById("safety-ok").focus();
  } else {
    showQuestion();
  }
}

async function sendAnswer(answer, confirmationText) {
  try {
    await postAnswer(answer, options.token, options.mock);
    pendingEpisode = null;
    showOnly(elements.idleCard);
    elements.confirmation.textContent = confirmationText;
    elements.confirmation.hidden = false;
  } catch (error) {
    elements.formError.textContent = `${error.message} Please try again.`;
    elements.formError.hidden = false;
  }
}

function sendSafetyAction(action, confirmationText) {
  if (!pendingEpisode) {
    return;
  }
  sendAnswer(
    { episode_id: pendingEpisode.episode_id, safety_action: action, answered_at: nowIso() },
    confirmationText,
  );
}

function init() {
  elements.patientId.textContent = options.patientId;
  elements.replayNotice.hidden = !options.replayNotice;
  renderChoices(elements.activityOptions, "activity", ACTIVITIES);
  renderChoices(
    elements.moodOptions,
    "mood",
    MOOD_VALUES.map((value) => ({ value: String(value), label: String(value) })),
  );

  elements.questionCard.addEventListener("change", updateSendButton);
  elements.activityText.addEventListener("input", updateSendButton);
  elements.questionCard.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!pendingEpisode) {
      return;
    }
    const mood = selectedValue("mood");
    const text = elements.activityText.value.trim();
    sendAnswer(
      {
        episode_id: pendingEpisode.episode_id,
        activity: selectedValue("activity"),
        activity_text: text || null,
        mood_1_5: mood === null ? null : Number(mood),
        safety_action: null,
        answered_at: nowIso(),
      },
      "Thank you. Your answer has been added for your clinician.",
    );
  });

  document.getElementById("safety-ok").addEventListener("click", () => {
    if (pendingEpisode) {
      showQuestion();
    }
  });
  document.getElementById("safety-call").addEventListener("click", () =>
    sendSafetyAction(
      "call_112_simulated",
      "Simulation: no call was made. In a real deployment this button would open your " +
        "phone's dialler with 112, and only you would place the call.",
    ),
  );
  document.getElementById("safety-contact").addEventListener("click", () =>
    sendSafetyAction(
      "notify_contact_simulated",
      "Simulation: no message was sent. In a real deployment your trusted contact " +
        "would receive a notification.",
    ),
  );

  subscribeToQuestions({
    patientId: options.patientId,
    token: options.token,
    mock: options.mock,
    onEpisode: handleEpisode,
    onStatus: setConnection,
  });
}

init();
