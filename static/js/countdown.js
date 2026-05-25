/**
 * countdown.js — countdown unit toggle, ticker, and milestone celebrations.
 *
 * State (in localStorage):
 *   vp.countdown.unit            "days" | "sleeps"   (default "days")
 *   vp.celebrated.<id>.<thresh>  any value           (presence = celebrated)
 *
 * DOM convention:
 *   <span data-countdown-unit>
 *     <span data-countdown-form="days">…</span>
 *     <span data-countdown-form="sleeps" hidden>…</span>
 *   </span>
 *
 * Toggle:
 *   <button data-countdown-toggle="days"   aria-pressed="…">…</button>
 *   <button data-countdown-toggle="sleeps" aria-pressed="…">…</button>
 */
(function () {
  'use strict';

  var STORAGE_KEY = 'vp.countdown.unit';
  var VALID_UNITS = ['days', 'sleeps'];

  function readUnit() {
    try {
      var v = window.localStorage.getItem(STORAGE_KEY);
      if (VALID_UNITS.indexOf(v) !== -1) return v;
    } catch (e) {
      // localStorage blocked (e.g., private browsing) — fall through.
    }
    return 'days';
  }

  function writeUnit(unit) {
    try {
      window.localStorage.setItem(STORAGE_KEY, unit);
    } catch (e) {
      // Best-effort; toggle still works for the current page.
    }
  }

  function applyUnit(unit) {
    document.querySelectorAll('[data-countdown-unit]').forEach(function (wrap) {
      wrap.querySelectorAll('[data-countdown-form]').forEach(function (form) {
        var matches = form.getAttribute('data-countdown-form') === unit;
        form.hidden = !matches;
      });
    });
    document.querySelectorAll('[data-countdown-toggle]').forEach(function (btn) {
      var matches = btn.getAttribute('data-countdown-toggle') === unit;
      btn.setAttribute('aria-pressed', matches ? 'true' : 'false');
    });
  }

  function wireToggle() {
    document.querySelectorAll('[data-countdown-toggle]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var unit = btn.getAttribute('data-countdown-toggle');
        if (VALID_UNITS.indexOf(unit) === -1) return;
        writeUnit(unit);
        applyUnit(unit);
      });
    });
  }

  function revealToggleIfRelevant() {
    // The toggle is hidden by default in the navbar; only show it on pages
    // that actually have something to toggle.
    if (!document.querySelector('[data-countdown-unit]')) return;
    document.querySelectorAll('.vp-unit-toggle').forEach(function (el) {
      el.hidden = false;
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    applyUnit(readUnit());
    wireToggle();
    revealToggleIfRelevant();
  });
})();
