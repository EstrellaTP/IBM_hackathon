/**
 * Clinician view: assigned patients on the left, the selected patient on the
 * right with two tabs, "Evidence" (run a suspicion module, CLAUDE.md 5.2) and
 * "Moments" (episodes with the patient's answers, refreshed live).
 *
 * LinuxONE only returns patients assigned to this clinician (issue #14).
 *
 * @module clinician-view
 */

import { fetchEpisodes, fetchMyPatients, formatClock, isMock } from "../shared/api-client.js";
import { renderMoments } from "../shared/moments.js";
import { initEvidencePanel } from "../clinician/evidence-panel.js";

const MOMENTS_REFRESH_MS = 5000;
const DEFAULT_PERIOD_DAYS = 35;

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

function patientMeta(patient) {
  if (!patient.last_episode_at) {
    return "Recording available · no moments yet";
  }
  const day = new Date(patient.last_episode_at).toLocaleDateString([], {
    day: "numeric",
    month: "short",
  });
  return `${patient.episodes} moments · ${patient.answered} answered · last ${day} ${formatClock(patient.last_episode_at).slice(0, 5)}`;
}

/**
 * Build the evidence tab: the module form wired to the shared evidence panel.
 *
 * @param {() => string} getPatientId - Returns the selected patient.
 * @param {() => Array<object>} getMoments - Returns the patient's latest moments.
 * @returns {HTMLElement} The tab content.
 */
function buildEvidenceTab(getPatientId, getMoments) {
  const panel = element("section", "tab-panel");
  panel.id = "panel-evidence";
  panel.setAttribute("role", "tabpanel");
  panel.setAttribute("aria-labelledby", "tab-evidence");
  panel.append(
    element(
      "p",
      "muted",
      "Choose what you want to check. Only that module runs, on this patient's recording, inside LinuxONE. It supports your judgement; it does not replace it.",
    ),
  );

  const form = element("form", "module-form");
  const suspicion = element("label");
  suspicion.append(element("span", "", "Suspicion"));
  const select = element("select", "text-input");
  select.name = "suspicion";
  select.append(new Option("Depression", "depression"));
  suspicion.append(select);

  const period = element("label");
  period.append(element("span", "", "Period (last days)"));
  const days = element("input", "text-input");
  days.name = "days";
  days.type = "number";
  days.min = "4";
  days.max = "90";
  days.value = String(DEFAULT_PERIOD_DAYS);
  period.append(days);

  const run = element("button", "button button--primary", "Run module");
  run.type = "submit";
  form.append(suspicion, period, run);

  const status = element("p", "muted");
  status.setAttribute("role", "status");
  const output = element("div");
  panel.append(form, status, output);

  initEvidencePanel({ form, output, status, getPatientId, getMoments, mock: isMock() });
  return panel;
}

/**
 * Mount the clinician view.
 *
 * @param {HTMLElement} root - Container.
 */
export function mountClinicianView(root) {
  const workspace = element("div", "workspace");
  const listSide = element("nav", "patient-list");
  listSide.setAttribute("aria-label", "Your patients");
  listSide.append(element("h2", "", "Your patients"));
  const list = element("ul");
  listSide.append(list);

  const detail = element("section", "patient-detail");
  workspace.append(listSide, detail);
  root.replaceChildren(workspace);

  let selected = null;
  let knownIds = new Set();
  let refreshTimer = null;
  let lastMoments = [];

  const header = element("header", "patient-detail__header");
  const title = element("h1");
  const summary = element("p", "muted");
  header.append(title, summary);

  const tabs = element("div", "tabs");
  tabs.setAttribute("role", "tablist");
  const evidenceTab = element("button", "tab", "Evidence");
  const momentsTab = element("button", "tab", "Moments");
  evidenceTab.id = "tab-evidence";
  momentsTab.id = "tab-moments";
  for (const tab of [evidenceTab, momentsTab]) {
    tab.type = "button";
    tab.setAttribute("role", "tab");
    tabs.append(tab);
  }

  const evidencePanel = buildEvidenceTab(
    () => selected?.patient_id ?? "",
    () => lastMoments,
  );
  const momentsPanel = element("section", "tab-panel");
  momentsPanel.id = "panel-moments";
  momentsPanel.setAttribute("role", "tabpanel");
  momentsPanel.setAttribute("aria-labelledby", "tab-moments");
  const momentsHint = element(
    "p",
    "muted",
    "A moment is when the heart rate rose above this patient's own baseline and movement did not explain it. The patient was asked right then. Updates every few seconds.",
  );
  const moments = element("ol", "moments");
  momentsPanel.append(momentsHint, moments);

  const selectTab = (tab) => {
    for (const [button, panel] of [
      [evidenceTab, evidencePanel],
      [momentsTab, momentsPanel],
    ]) {
      const active = button === tab;
      button.setAttribute("aria-selected", String(active));
      button.tabIndex = active ? 0 : -1;
      panel.hidden = !active;
    }
  };
  evidenceTab.addEventListener("click", () => selectTab(evidenceTab));
  momentsTab.addEventListener("click", () => selectTab(momentsTab));
  tabs.addEventListener("keydown", (event) => {
    if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
      const next = document.activeElement === evidenceTab ? momentsTab : evidenceTab;
      selectTab(next);
      next.focus();
    }
  });

  const refreshMoments = async () => {
    if (!selected) {
      return;
    }
    try {
      const items = await fetchEpisodes(selected.patient_id, isMock());
      lastMoments = [...items].sort(
        (a, b) => new Date(b.episode.detected_at) - new Date(a.episode.detected_at),
      );
      knownIds = renderMoments(moments, items, { forClinician: true, knownIds });
      if (items.length === 0) {
        moments.replaceChildren(
          element("li", "empty-state", "No moments for this patient in the recording."),
        );
      }
      const answered = items.filter((item) => item.answer).length;
      summary.textContent = `${items.length} moments · ${answered} answered`;
    } catch (error) {
      moments.replaceChildren(element("li", "notice notice--alert", error.message));
    }
  };

  const select = (patient, button) => {
    selected = patient;
    knownIds = new Set();
    lastMoments = [];
    for (const item of list.querySelectorAll(".patient-item")) {
      item.setAttribute("aria-current", String(item === button));
    }
    title.textContent = patient.patient_id;
    summary.textContent = "";
    evidencePanel.querySelector("[role=status]").textContent = "";
    evidencePanel.querySelector(".module-form + p + div")?.replaceChildren();
    detail.replaceChildren(header, tabs, evidencePanel, momentsPanel);
    selectTab(patient.episodes > 0 ? momentsTab : evidenceTab);
    window.clearInterval(refreshTimer);
    refreshMoments();
    refreshTimer = window.setInterval(refreshMoments, MOMENTS_REFRESH_MS);
  };

  const load = async () => {
    detail.replaceChildren(element("p", "muted", "Loading your patients from LinuxONE…"));
    try {
      const patients = await fetchMyPatients();
      if (patients.length === 0) {
        detail.replaceChildren(element("p", "empty-state", "No patients are assigned to you yet."));
        return;
      }
      list.replaceChildren(
        ...patients.map((patient) => {
          const item = element("li");
          const button = element("button", "patient-item");
          button.type = "button";
          button.append(
            element("span", "patient-item__id", patient.patient_id),
            element("span", "patient-item__meta", patientMeta(patient)),
          );
          button.addEventListener("click", () => select(patient, button));
          item.append(button);
          return item;
        }),
      );
      select(patients[0], list.querySelector(".patient-item"));
    } catch (error) {
      detail.replaceChildren(element("p", "notice notice--alert", error.message));
    }
  };

  load();
}
