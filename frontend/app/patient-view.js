/**
 * Patient view: recording status, the in-the-moment question and the patient's
 * own history (patient control over their data, CLAUDE.md section 11).
 *
 * Flow (CLAUDE.md sections 5.1 and 5.4): an EpisodeEvent arrives over the
 * WebSocket; a normal one shows the question, an extreme one first shows
 * "Are you OK?" with buttons the patient chooses from. Nothing is sent
 * automatically; the safety buttons only record the choice in this prototype.
 *
 * @module patient-view
 */

import {
  fetchMyTimeline,
  formatClock,
  isMock,
  nowIso,
  postAnswer,
  subscribeToQuestions,
} from "../shared/api-client.js";
import { brandElement } from "../shared/brand.js";
import { BRAND_NAME } from "../shared/config.js";
import { renderMoments } from "../shared/moments.js";

/** Activity choices on the phone (mock-up labels; values from the Activity enum). */
const PHONE_ACTIVITIES = [
  ["rest", "Resting"],
  ["work", "Working"],
  ["commute", "Walking"],
  ["social", "With people"],
];

const HISTORY_REFRESH_MS = 10000;

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

function choiceGroup(name, legend, choices, gridClass = "button-grid") {
  const fieldset = element("fieldset", "choice-group");
  fieldset.append(element("legend", "", legend));
  const grid = element("div", gridClass);
  for (const [value, label] of choices) {
    const wrapper = element("div", "choice");
    const input = document.createElement("input");
    input.type = "radio";
    input.name = name;
    input.id = `${name}-${value}`;
    input.value = value;
    const text = element("label", "", label);
    text.htmlFor = input.id;
    wrapper.append(input, text);
    grid.append(wrapper);
  }
  fieldset.append(grid);
  return fieldset;
}

/**
 * Mount the patient view.
 *
 * @param {HTMLElement} root - Container.
 * @param {import("../shared/session.js").Session} session - Signed-in patient.
 */
export function mountPatientView(root, session) {
  const mock = isMock();
  const page = element("div", "patient-home");

  const live = element("span", "live-dot live-dot--offline", "Connecting");
  const ring = element("section", "status-ring status-ring--offline");
  ring.setAttribute("aria-live", "polite");
  const ringText = element("div", "status-ring__text");
  const ringTitle = element("strong", "", "Connecting…");
  const ringHint = element("span", "", "Your band's data goes to LinuxONE.");
  ringText.append(ringTitle, ringHint);
  ring.append(element("span", "status-ring__dot"), ringText, live);

  const questionSlot = element("div");
  const confirmation = element("p", "notice notice--ok");
  confirmation.setAttribute("role", "status");
  confirmation.hidden = true;

  const historyTitle = element("h2", "section-title", "Your recent moments");
  const historyHint = element(
    "p",
    "muted",
    "Each moment is a time your band noticed something unusual for you, with what you answered. Your clinician sees the same.",
  );
  const history = element("ol", "moments");
  const replay = element(
    "p",
    "muted",
    "Demo: the signal is recorded data (WESAD) replayed in real time, not a live band.",
  );

  page.append(ring, questionSlot, confirmation, historyTitle, historyHint, history, replay);
  root.replaceChildren(page);

  let knownIds = new Set();
  const refreshHistory = async () => {
    try {
      const items = await fetchMyTimeline();
      knownIds = renderMoments(history, items, { forClinician: false, knownIds });
      if (items.length === 0) {
        history.replaceChildren(element("li", "empty-state", "No moments yet."));
      }
    } catch (error) {
      history.replaceChildren(element("li", "notice notice--alert", error.message));
    }
  };

  const send = async (answer, message) => {
    try {
      await postAnswer(answer, null, mock);
      questionSlot.replaceChildren();
      ring.hidden = false;
      confirmation.textContent = message;
      confirmation.hidden = false;
      refreshHistory();
    } catch (error) {
      const note = element("p", "notice notice--alert", `${error.message} Try again.`);
      note.setAttribute("role", "alert");
      questionSlot.append(note);
    }
  };

  const cardHeader = () => {
    const header = element("div", "question__header");
    header.append(brandElement(), element("span", "live-dot", "Recording"));
    return header;
  };

  const showQuestion = (episode, receivedAt) => {
    const form = element("form", "question");
    form.append(
      cardHeader(),
      element("h2", "", `${BRAND_NAME} noticed a change`),
      choiceGroup("activity", "What were you doing just now?", PHONE_ACTIVITIES),
      choiceGroup(
        "mood",
        "How do you feel right now?",
        [1, 2, 3, 4, 5].map((value) => [String(value), String(value)]),
        "mood-row",
      ),
      element(
        "p",
        "muted",
        `1 = very bad, 5 = very good. Detected ${formatClock(episode.detected_at)}, reached you ${formatClock(receivedAt)}.`,
      ),
    );
    const button = element("button", "button button--primary", "Send");
    button.type = "submit";
    button.disabled = true;
    form.append(button);
    form.addEventListener("change", () => {
      button.disabled = !form.querySelector("input:checked");
    });
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const value = (name) => form.querySelector(`input[name="${name}"]:checked`)?.value ?? null;
      const mood = value("mood");
      send(
        {
          episode_id: episode.episode_id,
          activity: value("activity"),
          activity_text: null,
          mood_1_5: mood === null ? null : Number(mood),
          safety_action: null,
          answered_at: nowIso(),
        },
        "Answer sent. It is now with your clinician.",
      );
    });
    ring.hidden = true;
    questionSlot.replaceChildren(form);
    form.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const showSafety = (episode, receivedAt) => {
    const box = element("section", "question question--safety");
    box.append(
      cardHeader(),
      element("h2", "", "Are you OK?"),
      element("p", "", "Your band picked up a very strong change. You decide what to do."),
    );
    const grid = element("div", "button-grid");
    const ok = element("button", "button button--primary", "I'm OK");
    const contact = element("button", "button button--outline", "Notify my trusted contact");
    const call = element("button", "button button--outline", "Call 112");
    for (const button of [ok, contact, call]) {
      button.type = "button";
      grid.append(button);
    }
    ok.addEventListener("click", () => showQuestion(episode, receivedAt));
    call.addEventListener("click", () =>
      send(
        { episode_id: episode.episode_id, safety_action: "call_112_simulated", answered_at: nowIso() },
        "Simulation: no call was made. In a real deployment this opens your phone's dialler and only you place the call.",
      ),
    );
    contact.addEventListener("click", () =>
      send(
        {
          episode_id: episode.episode_id,
          safety_action: "notify_contact_simulated",
          answered_at: nowIso(),
        },
        "Simulation: no message was sent. In a real deployment your trusted contact would be notified.",
      ),
    );
    box.append(grid, element("p", "muted", "Nothing is ever sent automatically."));
    ring.hidden = true;
    questionSlot.replaceChildren(box);
    box.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  subscribeToQuestions({
    patientId: session.patient_id,
    token: session.token,
    mock,
    onStatus: (connected) => {
      ring.classList.toggle("status-ring--offline", !connected);
      live.classList.toggle("live-dot--offline", !connected);
      live.textContent = connected ? "Recording" : "Reconnecting";
      ringTitle.textContent = connected ? "Recording" : "Reconnecting…";
      ringHint.textContent = connected
        ? "If something unusual for you happens, a short question will appear here."
        : "Keep this page open; it reconnects on its own.";
    },
    onEpisode: (episode) => {
      const receivedAt = nowIso();
      confirmation.hidden = true;
      if ("vibrate" in navigator) {
        navigator.vibrate(200);
      }
      if (episode.severity === "extreme") {
        showSafety(episode, receivedAt);
      } else {
        showQuestion(episode, receivedAt);
      }
    },
  });

  refreshHistory();
  window.setInterval(refreshHistory, HISTORY_REFRESH_MS);
}
