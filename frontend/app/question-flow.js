/**
 * In-the-moment question as a short flow of screens, one question per screen.
 *
 * The two main questions of CLAUDE.md section 5.1 (what were you doing, how do
 * you feel) each open their own follow-ups: physical activity asks for its
 * intensity and whether it is usual, a low mood asks which emotion fits, and so
 * on. Only the follow-ups of the chosen answer are shown, so a patient sees
 * between four and seven short screens. Every follow-up value comes from a closed
 * list in the AnswerDetails contract (services/common/schemas.py).
 *
 * @module question-flow
 */

/** Main activity choices; values from the Activity enum. */
const ACTIVITIES = [
  ["exercise", "Physical activity"],
  ["work", "Working or studying"],
  ["rest", "Resting"],
  ["social", "With people"],
  ["commute", "On the way somewhere"],
  ["other", "Something else"],
];

const YES_NO = [
  ["yes", "Yes"],
  ["no", "No"],
];

/**
 * Follow-up questions for each activity. `key` is the AnswerDetails field;
 * `boolean` marks yes/no questions stored as true or false.
 */
const ACTIVITY_FOLLOW_UPS = {
  exercise: [
    {
      key: "exercise_intensity",
      title: "How intense is it?",
      choices: [
        ["light", "Light"],
        ["moderate", "Moderate"],
        ["vigorous", "Intense"],
      ],
    },
    { key: "usual_for_you", title: "Do you usually do this at this time?", choices: YES_NO, boolean: true },
  ],
  work: [
    {
      key: "workload",
      title: "How is the workload right now?",
      choices: [
        ["light", "Calm"],
        ["normal", "Normal"],
        ["demanding", "Very demanding"],
      ],
    },
  ],
  rest: [
    {
      key: "rest_state",
      title: "Which fits best?",
      choices: [
        ["awake", "Awake, resting"],
        ["falling_asleep", "Trying to sleep"],
        ["just_woke_up", "Just woke up"],
      ],
    },
  ],
  social: [
    {
      key: "company",
      title: "Who are you with?",
      choices: [
        ["family", "Family"],
        ["partner", "Partner"],
        ["friends", "Friends"],
        ["colleagues", "Colleagues"],
        ["strangers", "People I don't know"],
      ],
    },
    {
      key: "social_tone",
      title: "How is it going?",
      choices: [
        ["pleasant", "Pleasant"],
        ["neutral", "Neutral"],
        ["tense", "Tense"],
      ],
    },
  ],
  commute: [
    {
      key: "travel_mode",
      title: "How are you getting there?",
      choices: [
        ["walking", "Walking"],
        ["cycling", "Cycling"],
        ["public_transport", "Public transport"],
        ["car", "Car"],
      ],
    },
    { key: "in_a_hurry", title: "Are you in a hurry?", choices: YES_NO, boolean: true },
  ],
  other: [],
};

/** Emotion choices depend on the mood: low moods (1-2) get the difficult ones first. */
const EMOTIONS_LOW = [
  ["sad", "Sad"],
  ["anxious", "Nervous"],
  ["irritable", "Irritable"],
  ["tired", "Tired"],
  ["overwhelmed", "Overwhelmed"],
];
const EMOTIONS_OTHER = [
  ["calm", "Calm"],
  ["happy", "Happy"],
  ["energetic", "Energetic"],
  ["tired", "Tired"],
];
const LOW_MOOD_MAX = 2;

const MOOD_CHOICES = [1, 2, 3, 4, 5].map((value) => [String(value), String(value)]);
const NOTE_MAX_LENGTH = 280; // QuestionAnswer.activity_text
const ADVANCE_DELAY_MS = 180; // lets the patient see the choice before the next screen

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

function choiceStep(name, title, choices, current, gridClass) {
  const fieldset = element("fieldset", "choice-group flow__step");
  fieldset.append(element("legend", "flow__title", title));
  const grid = element("div", gridClass);
  for (const [value, label] of choices) {
    const wrapper = element("div", "choice");
    const input = document.createElement("input");
    input.type = "radio";
    input.name = name;
    input.id = `flow-${name}-${value}`;
    input.value = value;
    input.checked = current === value;
    const text = element("label", "", label);
    text.htmlFor = input.id;
    wrapper.append(input, text);
    grid.append(wrapper);
  }
  fieldset.append(grid);
  return fieldset;
}

/**
 * Build the question flow for one episode.
 *
 * @param {object} options - Flow options.
 * @param {HTMLElement} options.header - Card header (brand and recording status).
 * @param {string} options.title - Heading of the first screen.
 * @param {(answer: {activity: string|null, activity_text: string|null, mood_1_5: number|null, details: object|null}) => void} options.onSubmit
 *   Called with the answer fields when the patient presses Send or Skip.
 * @returns {HTMLFormElement} The flow, ready to insert.
 */
export function buildQuestionFlow({ header, title, onSubmit }) {
  const state = { activity: null, mood: null, note: "", values: {} };
  let index = 0;

  const form = element("form", "question flow");
  const bar = element("div", "flow__bar");
  const back = element("button", "flow__back", "‹");
  back.type = "button";
  back.setAttribute("aria-label", "Previous question");
  const progress = element("span", "flow__progress");
  progress.setAttribute("aria-live", "polite");
  bar.append(back, progress);
  const kicker = element("p", "flow__kicker", title);
  const slot = element("div", "flow__slot");
  form.append(header, bar, kicker, slot);

  // The list of screens depends on the answers given so far.
  const screens = () => {
    const list = [{ type: "activity" }];
    for (const question of ACTIVITY_FOLLOW_UPS[state.activity] ?? []) {
      list.push({ type: "follow-up", question });
    }
    list.push({ type: "mood" });
    if (state.mood !== null) {
      list.push({
        type: "follow-up",
        question: {
          key: "emotion",
          title: "Which word fits best?",
          choices: state.mood <= LOW_MOOD_MAX ? EMOTIONS_LOW : EMOTIONS_OTHER,
        },
      });
    }
    list.push({
      type: "follow-up",
      question: {
        key: "something_happened",
        title: "Did something happen just before?",
        choices: YES_NO,
        boolean: true,
      },
    });
    list.push({ type: "note" });
    return list;
  };

  const details = () => {
    const keys = new Set(
      screens()
        .filter((screen) => screen.type === "follow-up")
        .map((screen) => screen.question.key),
    );
    const picked = Object.entries(state.values).filter(([key]) => keys.has(key));
    return picked.length ? Object.fromEntries(picked) : null;
  };

  const submit = (withNote) => {
    const note = withNote ? state.note.trim() : "";
    onSubmit({
      activity: state.activity,
      activity_text: note || null,
      mood_1_5: state.mood,
      details: details(),
    });
  };

  const next = () => {
    index = Math.min(index + 1, screens().length - 1);
    render();
  };

  const render = () => {
    const list = screens();
    const screen = list[index];
    progress.textContent = `${index + 1} of ${list.length}`;
    back.hidden = index === 0;
    kicker.hidden = index !== 0;

    let content;
    if (screen.type === "activity") {
      content = choiceStep(
        "activity",
        "What are you doing right now?",
        ACTIVITIES,
        state.activity,
        "button-grid",
      );
      content.addEventListener("change", (event) => {
        state.activity = event.target.value;
        window.setTimeout(next, ADVANCE_DELAY_MS);
      });
    } else if (screen.type === "mood") {
      content = choiceStep(
        "mood",
        "How do you feel right now?",
        MOOD_CHOICES,
        state.mood === null ? null : String(state.mood),
        "mood-row",
      );
      const scale = element("p", "flow__scale");
      scale.append(element("span", "", "Very bad"), element("span", "", "Very good"));
      content.append(scale);
      content.addEventListener("change", (event) => {
        state.mood = Number(event.target.value);
        window.setTimeout(next, ADVANCE_DELAY_MS);
      });
    } else if (screen.type === "follow-up") {
      const { key, title: question, choices, boolean } = screen.question;
      const stored = state.values[key];
      const current = boolean && stored !== undefined ? (stored ? "yes" : "no") : stored;
      content = choiceStep(key, question, choices, current, "button-grid");
      content.addEventListener("change", (event) => {
        state.values[key] = boolean ? event.target.value === "yes" : event.target.value;
        window.setTimeout(next, ADVANCE_DELAY_MS);
      });
    } else {
      content = element("div", "flow__step");
      const label = element(
        "label",
        "flow__title",
        state.activity === "other" ? "What are you doing?" : "Anything you want to add?",
      );
      label.htmlFor = "flow-note";
      const note = document.createElement("textarea");
      note.id = "flow-note";
      note.className = "text-input flow__note";
      note.maxLength = NOTE_MAX_LENGTH;
      note.rows = 4;
      note.value = state.note;
      note.addEventListener("input", () => {
        state.note = note.value;
      });
      const send = element("button", "button button--primary", "Send");
      send.type = "submit";
      const skip = element("button", "button button--outline", "Send without a note");
      skip.type = "button";
      skip.addEventListener("click", () => submit(false));
      const actions = element("div", "flow__actions");
      actions.append(send, skip);
      content.append(label, element("p", "muted", "Optional."), note, actions);
    }
    slot.replaceChildren(content);
    const focusTarget = content.querySelector("input:checked, input, textarea");
    focusTarget?.focus({ preventScroll: true });
  };

  back.addEventListener("click", () => {
    index = Math.max(index - 1, 0);
    render();
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    submit(true);
  });

  render();
  return form;
}
