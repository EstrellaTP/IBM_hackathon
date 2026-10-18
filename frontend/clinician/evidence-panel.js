/**
 * Evidence panel (phase 2): the clinician runs one suspicion module and reads
 * the evidence, one chart per metric against the reference band.
 *
 * What it shows (CLAUDE.md sections 5.2 and 5.5):
 *   - the outcome as "signals compatible / not compatible with …" and the
 *     calibrated confidence; borderline results are labelled as such;
 *   - "not compatible" always says it does not rule anything out, next to the
 *     recording quality (valid days, missing hours);
 *   - four charts, the ones that drove the result tagged "Evidence" in text;
 *   - the model version and the reference group, for transparency.
 * It never shows generated text about the patient: only numbers and charts.
 *
 * @module evidence-panel
 */

import { runModule } from "../shared/api-client.js";
import { METRIC_TEXT, renderEvidenceChart } from "./evidence-chart.js";

/** Below this confidence the outcome is labelled "borderline" (suggested in issue #11). */
const BORDERLINE_CONFIDENCE = 0.6;
const DEFAULT_PERIOD_DAYS = 35;
const DAY_MS = 86400000;

/** Human names of the suspicion modules (Suspicion enum in services/common/schemas.py). */
const SUSPICION_LABELS = { depression: "depression" };

/** Chart order on the dashboard. */
const METRIC_ORDER = ["sleep", "circadian_rhythm", "daytime_activity", "heart_rate"];

/**
 * Turn a reference key such as "F_30-39" into "women aged 30–39".
 *
 * @param {string} group - Reference group key from the ModuleResult.
 * @returns {string} Readable description.
 */
export function describeGroup(group) {
  const [sex, ages] = group.split("_");
  const people = { F: "women", M: "men" }[sex] ?? "people";
  return ages ? `${people} aged ${ages.replace("-", "–")}` : people;
}

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

function buildRequest(patientId, suspicion, days) {
  const to = new Date();
  to.setUTCHours(23, 59, 59, 0);
  const from = new Date(to.getTime() - (days - 1) * DAY_MS);
  from.setUTCHours(0, 0, 0, 0);
  return {
    patient_id: patientId,
    suspicion,
    period: { from: from.toISOString(), to: to.toISOString() },
    requested_by: "clinician_dashboard",
  };
}

function renderOutcome(result) {
  const compatible = result.result === "compatible";
  const label = SUSPICION_LABELS[result.suspicion] ?? result.suspicion;
  const borderline = result.confidence < BORDERLINE_CONFIDENCE;
  const quality = result.data_quality ?? {};

  const box = element("div", `outcome ${compatible ? "outcome--compatible" : "outcome--not"}`);
  const meta = element("p", "outcome__meta");
  meta.append(
    element("span", "", `Patient ${result.patient_id}`),
    element("span", "", `${quality.valid_days ?? "—"} valid days`),
  );
  box.append(
    meta,
    element("p", "outcome__title", `Pattern ${compatible ? "compatible" : "not compatible"} with ${label}`),
  );

  const percent = Math.round(result.confidence * 100);
  const confidence = element("div", "confidence");
  const track = element("div", "confidence__track");
  const fill = element("div", "confidence__fill");
  fill.style.width = `${percent}%`;
  track.append(fill);
  track.setAttribute("role", "img");
  track.setAttribute("aria-label", `Confidence ${percent} %`);
  confidence.append(
    element("span", "", "Confidence"),
    track,
    element("span", "confidence__value", `${percent} %${borderline ? " · borderline" : ""}`),
  );
  box.append(confidence);

  if (borderline) {
    box.append(
      element(
        "p",
        "outcome__note",
        "Borderline result: the evidence points both ways. Read the charts before weighing it.",
      ),
    );
  }

  const facts = element("dl", "definition-row");
  for (const [term, value] of [
    ["Missing hours", quality.missing_hours],
    ["Model", result.model_version],
  ]) {
    facts.append(element("dt", "", term), element("dd", "", String(value ?? "—")));
  }
  box.append(facts);
  return box;
}

const ACTIVITY_SHORT = {
  work: "Working",
  rest: "Resting",
  social: "With people",
  commute: "On the move",
  other: "Something else",
};

function renderAnswerChips(moments) {
  const answered = moments.filter((item) => item.answer && !item.answer.safety_action).slice(0, 3);
  if (answered.length === 0) {
    return null;
  }
  const wrapper = element("section");
  wrapper.append(element("h3", "evidence-card__title", "What the patient said in the moment"));
  for (const { episode, answer } of answered) {
    const chip = element("p", "answer-chip");
    const time = element("time", "", new Date(episode.detected_at).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    }));
    time.dateTime = episode.detected_at;
    const parts = [ACTIVITY_SHORT[answer.activity] ?? "Answered"];
    if (answer.mood_1_5) {
      parts.push(`feels ${answer.mood_1_5} of 5`);
    }
    chip.append(time, element("span", "", parts.join(" · ")));
    wrapper.append(chip);
  }
  return wrapper;
}

function renderMetricCard(metric, tooltip) {
  const text = METRIC_TEXT[metric.name] ?? { title: metric.name, help: "" };
  const card = element("article", `evidence-card${metric.is_evidence ? " evidence-card--evidence" : ""}`);
  const header = element("header", "evidence-card__header");
  header.append(element("h3", "evidence-card__title", text.title));
  if (metric.is_evidence) {
    header.append(element("span", "tag tag--evidence", "Evidence"));
  }
  card.append(header, element("p", "evidence-card__help muted", text.help));
  card.append(renderEvidenceChart(metric, tooltip));
  return card;
}

function renderResult(container, result, tooltip, moments) {
  const metrics = [...(result.metrics ?? [])].sort(
    (a, b) => METRIC_ORDER.indexOf(a.name) - METRIC_ORDER.indexOf(b.name),
  );
  const group = metrics.find((metric) => metric.reference)?.reference?.group;
  const grid = element("div", "evidence-grid");
  for (const metric of metrics) {
    grid.append(renderMetricCard(metric, tooltip));
  }
  const legend = element(
    "p",
    "muted evidence-legend",
    `Line: this patient, one point per valid day; the last day in orange. Shaded band: ` +
      `reference range (10th to 90th percentile, dashed line = median) for ${
        group ? describeGroup(group) : "the reference group"
      } in NHANES. Hollow points fall outside it. ` +
      '"Evidence" marks the metrics that weighed most in this result.',
  );
  const chips = renderAnswerChips(moments);
  const footnote = element(
    "p",
    "outcome__footnote",
    "Not compatible does not mean ruled out. The clinician decides.",
  );
  container.replaceChildren(
    ...[renderOutcome(result), chips, legend, grid, footnote].filter(Boolean),
  );
}

/**
 * Wire the evidence panel to its form and result container.
 *
 * @param {object} options - Panel options.
 * @param {HTMLFormElement} options.form - Form with `suspicion` and `days` fields.
 * @param {HTMLElement} options.output - Element that receives the result.
 * @param {HTMLElement} options.status - Live region for progress and errors.
 * @param {() => string} options.getPatientId - Returns the selected patient.
 * @param {boolean} options.mock - Use fake data instead of the server.
 * @param {() => Array<{episode: object, answer: object | null}>} [options.getMoments] -
 *   The patient's recent moments, shown next to the evidence.
 */
export function initEvidencePanel({ form, output, status, getPatientId, mock, getMoments }) {
  const tooltip = element("div", "chart-tooltip");
  tooltip.hidden = true;
  tooltip.setAttribute("role", "tooltip");
  document.body.append(tooltip);

  form.elements.days.value = String(DEFAULT_PERIOD_DAYS);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector("button[type=submit]");
    const days = Number(form.elements.days.value) || DEFAULT_PERIOD_DAYS;
    const request = buildRequest(getPatientId(), form.elements.suspicion.value, days);
    button.disabled = true;
    status.className = "muted";
    status.textContent = "Running the module on LinuxONE…";
    try {
      const started = performance.now();
      const result = await runModule(request, mock);
      renderResult(output, result, tooltip, getMoments ? getMoments() : []);
      status.textContent = `Module run in ${Math.round(performance.now() - started)} ms.`;
    } catch (error) {
      output.replaceChildren();
      status.className = "notice notice--alert";
      status.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  });
}
