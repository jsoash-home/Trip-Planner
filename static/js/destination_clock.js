/**
 * destination_clock.js — destination clock ticker + offset label.
 *
 * DOM contract:
 *   [data-vp-clock][data-clock-iana="Europe/Paris"][data-clock-city="Paris"]
 *     <span data-clock-time>3:47 PM</span>
 *     <span data-clock-offset></span>
 *
 * Ticks once per second (mirrors countdown.js). Offset vs the viewer's
 * local timezone is computed once on boot and cached per element —
 * recomputing formatToParts every second would be wasteful.
 */
(function () {
  'use strict';

  function formatTimeForZone(date, iana) {
    try {
      return new Intl.DateTimeFormat([], {
        timeZone: iana,
        hour: 'numeric',
        minute: '2-digit'
      }).format(date);
    } catch (e) {
      console.warn('destination_clock: cannot format time for zone', iana, e);
      return null;
    }
  }

  function getOffsetMinutesForZone(date, iana) {
    var parts = new Intl.DateTimeFormat('en-US', {
      timeZone: iana,
      timeZoneName: 'longOffset',
      hour: 'numeric'
    }).formatToParts(date);
    var tzName = null;
    for (var i = 0; i < parts.length; i++) {
      if (parts[i].type === 'timeZoneName') {
        tzName = parts[i];
        break;
      }
    }
    if (!tzName) return null;
    // tzName.value is "GMT+02:00", "GMT-05:30", or "GMT".
    var match = /^GMT([+-])(\d{2}):(\d{2})$/.exec(tzName.value);
    if (!match) return tzName.value === 'GMT' ? 0 : null;
    var sign = match[1] === '+' ? 1 : -1;
    var h = parseInt(match[2], 10);
    var m = parseInt(match[3], 10);
    return sign * (h * 60 + m);
  }

  function computeOffsetMinutes(viewerIana, destIana) {
    if (!viewerIana || !destIana) return null;
    try {
      var now = new Date();
      var vMin = getOffsetMinutesForZone(now, viewerIana);
      var dMin = getOffsetMinutesForZone(now, destIana);
      if (vMin === null || dMin === null) return null;
      return dMin - vMin;
    } catch (e) {
      return null;
    }
  }

  function friendlyOffsetLabel(minutes) {
    if (minutes === null || minutes === undefined) return '';
    if (minutes === 0) return '(same time)';
    var direction = minutes > 0 ? 'ahead' : 'behind';
    var abs = Math.abs(minutes);
    var hours = Math.floor(abs / 60);
    var mins = abs % 60;
    if (mins === 0) {
      return '(' + hours + ' h ' + direction + ')';
    }
    return '(' + hours + ' h ' + mins + ' min ' + direction + ')';
  }

  function paintClock(el, viewerIana, now) {
    var destIana = el.getAttribute('data-clock-iana');
    if (!destIana) return;
    var formatted = formatTimeForZone(now, destIana);
    if (formatted === null) {
      el.style.display = 'none';
      return;
    }
    var timeEl = el.querySelector('[data-clock-time]');
    if (timeEl) timeEl.textContent = formatted;
    // Offset only changes when the user crosses a DST boundary mid-session,
    // which is rare enough that "once per page load" is correct.
    if (!el.dataset.clockOffsetPainted) {
      var offsetEl = el.querySelector('[data-clock-offset]');
      if (offsetEl) {
        offsetEl.textContent = friendlyOffsetLabel(
          computeOffsetMinutes(viewerIana, destIana)
        );
      }
      el.dataset.clockOffsetPainted = '1';
    }
  }

  function startClocks() {
    var clocks = document.querySelectorAll('[data-vp-clock]');
    if (!clocks.length) return;
    var viewerIana;
    try {
      viewerIana = Intl.DateTimeFormat().resolvedOptions().timeZone;
    } catch (e) {
      viewerIana = null;
    }
    function tick() {
      var now = new Date();
      clocks.forEach(function (el) {
        paintClock(el, viewerIana, now);
      });
    }
    tick();
    setInterval(tick, 1000);
  }

  document.addEventListener('DOMContentLoaded', function () {
    startClocks();
  });
})();
