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
 *
 * Hero ticker target:
 *   data-countdown-target uses ISO format WITHOUT a timezone (e.g.
 *   "2026-08-17T00:00:00"). `new Date()` interprets this as local time,
 *   which is what we want — trips have no time-of-day, so "midnight on
 *   the trip's start date in the traveler's local time" is the only
 *   sensible target. Don't add "Z" — that would make it UTC and break
 *   the countdown for anyone outside UTC.
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

  function pad2(n) {
    return n < 10 ? '0' + n : '' + n;
  }

  function tickHero(hero) {
    var target = new Date(hero.getAttribute('data-countdown-target'));
    if (isNaN(target.getTime())) return;
    var now = new Date();
    var diffMs = target - now;
    if (diffMs <= 0) {
      // Trip started — page will refresh and switch to in-progress UI on next visit.
      return;
    }
    var totalSeconds = Math.floor(diffMs / 1000);
    var days = Math.floor(totalSeconds / 86400);
    var hours = Math.floor((totalSeconds % 86400) / 3600);
    var minutes = Math.floor((totalSeconds % 3600) / 60);
    var seconds = totalSeconds % 60;

    var daysEl = hero.querySelector('[data-countdown-days]');
    if (daysEl) daysEl.textContent = days;
    var hEl = hero.querySelector('[data-countdown-h]');
    if (hEl) hEl.textContent = pad2(hours);
    var mEl = hero.querySelector('[data-countdown-m]');
    if (mEl) mEl.textContent = pad2(minutes);
    var sEl = hero.querySelector('[data-countdown-s]');
    if (sEl) sEl.textContent = pad2(seconds);
  }

  function startTickers() {
    var heroes = document.querySelectorAll('[data-countdown-hero][data-countdown-target]');
    if (!heroes.length) return;
    heroes.forEach(tickHero);
    setInterval(function () {
      heroes.forEach(tickHero);
    }, 1000);
  }

  var MILESTONES = [30, 14, 7, 3, 1];

  var MILESTONE_COPY = {
    30: '🎉 One month to go!',
    14: '🧳 Two weeks!',
    7: '⏰ One week!',
    3: '✨ Just three days!',
    1: '🛫 Tomorrow!'
  };

  function celebratedKey(tripId, threshold) {
    return 'vp.celebrated.' + tripId + '.' + threshold;
  }

  function alreadyCelebrated(tripId, threshold) {
    try {
      return window.localStorage.getItem(celebratedKey(tripId, threshold)) !== null;
    } catch (e) {
      return true;  // pretend we already did, to avoid re-firing on every reload
    }
  }

  function markCelebrated(tripId, threshold) {
    try {
      window.localStorage.setItem(celebratedKey(tripId, threshold), '1');
    } catch (e) {
      // best-effort
    }
  }

  function prefersReducedMotion() {
    return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  function fireConfetti() {
    if (prefersReducedMotion()) return;
    // Lazy-load canvas-confetti only when a milestone actually fires, so we
    // don't pay ~10KB on every page load just for the rare celebration.
    // Reduced-motion already returned above, so we never import for users
    // who wouldn't see the burst anyway.
    import('https://cdn.jsdelivr.net/npm/canvas-confetti@1.9.3/dist/confetti.browser.mjs')
      .then(function (mod) {
        mod.default({
          particleCount: 120,
          spread: 70,
          origin: { y: 0.3 }
        });
      })
      .catch(function () {
        // Offline / CDN blocked — overlay still shows, just no burst.
      });
  }

  function showMilestoneOverlay(hero, copy) {
    var overlay = document.createElement('div');
    overlay.className = 'countdown-hero-milestone';
    overlay.textContent = copy;
    hero.appendChild(overlay);
    // Fade it out after 4s so the regular hero shows again.
    setTimeout(function () {
      overlay.classList.add('countdown-hero-milestone--dismissing');
    }, 4000);
    setTimeout(function () {
      overlay.remove();
    }, 4600);
  }

  function checkMilestones() {
    var heroes = document.querySelectorAll('[data-countdown-hero][data-trip-id][data-countdown-target]');
    heroes.forEach(function (hero) {
      var tripId = hero.getAttribute('data-trip-id');
      var target = new Date(hero.getAttribute('data-countdown-target'));
      if (isNaN(target.getTime())) return;
      var now = new Date();
      var diffMs = target - now;
      if (diffMs <= 0) return;
      // Math.floor (not ceil) so the milestone fires the moment the hero
      // ticker drops to N days — otherwise the celebration lags ~24 hours
      // behind what the user sees in the big number.
      var totalDays = Math.floor(diffMs / 86400000);
      for (var i = 0; i < MILESTONES.length; i++) {
        var t = MILESTONES[i];
        if (totalDays === t && !alreadyCelebrated(tripId, t)) {
          showMilestoneOverlay(hero, MILESTONE_COPY[t]);
          fireConfetti();
          markCelebrated(tripId, t);
          break;
        }
      }
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    applyUnit(readUnit());
    wireToggle();
    revealToggleIfRelevant();
    startTickers();
    checkMilestones();
  });
})();
