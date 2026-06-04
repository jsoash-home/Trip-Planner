/*
 * Yearbook front-end JS.
 *
 * Two responsibilities (built up over Tasks 4, 6, 9):
 *   1. Star toggle on itinerary cards (Task 4 — here).
 *   2. Mount the Mapbox GL map on the yearbook page (Task 6, later).
 *   3. Share / visibility controls on the yearbook page (Task 9, later).
 *
 * Each behavior is gated on the relevant DOM hook so unrelated pages
 * skip the work. No dependencies — vanilla ES5-ish JS.
 */
(function () {
  'use strict';

  // ─── Star toggle ────────────────────────────────────────────────
  var stars = document.querySelectorAll('.star-toggle');
  if (stars.length) {
    stars.forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        if (btn.disabled) return;

        var tripId = btn.getAttribute('data-trip-id');
        var itemId = btn.getAttribute('data-item-id');
        if (!tripId || !itemId) return;

        // Optimistic flip.
        var wasOn = btn.getAttribute('aria-pressed') === 'true';
        applyStarState(btn, !wasOn);
        btn.disabled = true;  // guard against rapid double-click

        fetch('/trips/' + tripId + '/items/' + itemId + '/star', {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Accept': 'application/json' },
        })
          .then(function (r) {
            if (!r.ok) throw new Error('star toggle failed: ' + r.status);
            return r.json();
          })
          .then(function (data) {
            // Server is authoritative — sync to whatever it returned.
            applyStarState(btn, !!data.starred);
          })
          .catch(function (err) {
            // Revert optimistic change; brief inline notice.
            applyStarState(btn, wasOn);
            flashErrorChip(btn);
            if (window.console) console.warn(err);
          })
          .then(function () {
            btn.disabled = false;
          });
      });
    });
  }

  function applyStarState(btn, on) {
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    btn.setAttribute(
      'aria-label',
      (on ? 'Unstar' : 'Star') + ' this highlight'
    );
    var icon = btn.querySelector('.star-icon');
    if (icon) icon.textContent = on ? '★' : '☆';
  }

  function flashErrorChip(btn) {
    var chip = document.createElement('span');
    chip.className = 'star-toggle-error';
    chip.textContent = 'Could not save — try again';
    btn.parentNode.appendChild(chip);
    setTimeout(function () {
      chip.classList.add('is-fading');
    }, 1200);
    setTimeout(function () {
      if (chip.parentNode) chip.parentNode.removeChild(chip);
    }, 2200);
  }
}());
