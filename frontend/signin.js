/**
 * Sign-in page: one door for patients and clinicians.
 *
 * The credentials go to LinuxONE (`POST /api/v1/sessions`); the returned role
 * decides which view opens. "Offline demo data" opens a session with fake data so
 * the interface can be shown without a connection to the VM.
 *
 * @module signin
 */

import { login } from "./shared/api-client.js";
import { getSession, saveSession } from "./shared/session.js";

const form = document.getElementById("signin-form");
const errorBox = document.getElementById("signin-error");
const reasonBox = document.getElementById("signin-reason");
const button = document.getElementById("signin-button");

/**
 * Where to go after signing in: the page the user came from, if it is ours.
 *
 * @returns {string} A same-site path.
 */
function nextPath() {
  const next = new URLSearchParams(window.location.search).get("next");
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/app/";
}

function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = false;
}

const reason = new URLSearchParams(window.location.search).get("reason");
if (reason) {
  reasonBox.textContent = reason;
  reasonBox.hidden = false;
}
if (getSession()) {
  window.location.replace(nextPath());
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  errorBox.hidden = true;
  const username = form.elements.username.value.trim();
  const password = form.elements.password.value;
  const offline = document.getElementById("offline").checked;
  if (!username || (!password && !offline)) {
    showError("Enter your username and password.");
    return;
  }
  button.disabled = true;
  button.textContent = "Signing in…";
  try {
    const session = await login(username, password, offline);
    saveSession(session);
    window.location.assign(nextPath());
  } catch (error) {
    showError(error.message);
    button.disabled = false;
    button.textContent = "Sign in";
  }
});
