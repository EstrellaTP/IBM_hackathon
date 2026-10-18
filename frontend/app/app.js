/**
 * App shell: checks the session and opens the view for the user's role.
 *
 * Patients see their own recording and the in-the-moment question; clinicians
 * see their assigned patients, the evidence of a suspicion module and the
 * moments. LinuxONE enforces the same split on every request (issue #14).
 *
 * @module app
 */

import { isMock } from "../shared/api-client.js";
import { brandElement } from "../shared/brand.js";
import { API_ORIGIN, LINUXONE_API_ORIGIN } from "../shared/config.js";
import { clearSession, goToLogin, requireSession } from "../shared/session.js";
import { mountClinicianView } from "./clinician-view.js";
import { mountPatientView } from "./patient-view.js";

const ROLE_LABELS = { patient: "Patient", clinician: "Clinician" };

const session = requireSession();
if (session) {
  document.querySelector(".topbar__brand").replaceChildren(brandElement());
  document.getElementById("user-name").textContent = session.display_name;
  document.getElementById("user-role").textContent = ROLE_LABELS[session.role] ?? session.role;
  document.getElementById("data-origin").textContent = isMock()
    ? "Offline demo: fake data generated in this browser, nothing is sent to LinuxONE."
    : `Data is read from IBM LinuxONE (${(API_ORIGIN || LINUXONE_API_ORIGIN).replace("https://", "")}), encrypted in transit and at rest. This page stores nothing.`;
  document.getElementById("sign-out").addEventListener("click", () => {
    clearSession();
    goToLogin("You have signed out.");
  });

  const view = document.getElementById("view");
  if (session.role === "clinician") {
    mountClinicianView(view, session);
  } else {
    mountPatientView(view, session);
  }
}
