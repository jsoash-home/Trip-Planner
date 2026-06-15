/**
 * prep.js — small progressive enhancement for the prep paste-or-type input.
 *
 * When a user pastes a URL into a prep input field (name="input"), show a
 * brief "Fetching link…" badge next to the input as a hint that the server
 * will try to expand it into a title + category. The badge disappears when
 * the form submits, or after 6 seconds as a safety net.
 *
 * Best-effort UX only — no functional dependency on this script. The form
 * still works the same way without JS; the badge is purely a visible
 * acknowledgement that the paste was registered.
 *
 * No external deps. No localStorage today. If we ever add storage here,
 * wrap it in try/catch (private browsing).
 */
(function () {
  "use strict";

  function looksLikeUrl(text) {
    if (!text) return false;
    return /^https?:\/\/\S+$/i.test(text.trim());
  }

  function showFetchingBadge(input) {
    // Don't stack multiple badges if the user pastes twice.
    var existing = input.parentNode && input.parentNode.querySelector(".prep-fetching-badge");
    if (existing) existing.parentNode.removeChild(existing);

    var badge = document.createElement("span");
    badge.className = "prep-fetching-badge text-muted small ms-2";
    badge.setAttribute("aria-live", "polite");
    badge.textContent = "Fetching link…";
    input.insertAdjacentElement("afterend", badge);

    var form = input.form;
    var timer = setTimeout(function () {
      if (badge.parentNode) badge.parentNode.removeChild(badge);
    }, 6000);

    if (form) {
      form.addEventListener(
        "submit",
        function () {
          clearTimeout(timer);
          if (badge.parentNode) badge.parentNode.removeChild(badge);
        },
        { once: true }
      );
    }
  }

  document.addEventListener("paste", function (event) {
    var target = event.target;
    if (!(target instanceof HTMLInputElement)) return;
    // Only enhance prep input fields.
    if (target.name !== "input") return;
    // Get the clipboard text (defensive — clipboardData may be absent).
    var text = (event.clipboardData && event.clipboardData.getData("text")) || "";
    if (looksLikeUrl(text)) {
      // Defer slightly so the input has the pasted value when the badge appears.
      setTimeout(function () { showFetchingBadge(target); }, 0);
    }
  });
})();
