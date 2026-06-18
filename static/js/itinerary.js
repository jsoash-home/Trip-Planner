/*
 * Itinerary mobile day-picker.
 *
 * The page renders the chip bar and all day-columns on every viewport.
 * On desktop (>=768px) CSS hides the chip bar and shows all columns, so
 * this script is effectively a no-op visually — but it still keeps the
 * --active classes accurate so a viewport resize works without reload.
 *
 * Behaviors:
 *   - Click a chip: mark that day active, update location.hash.
 *   - ArrowLeft / ArrowRight on a focused chip: move to neighbor.
 *   - Initial selection: location.hash (#day-N) if valid, else the
 *     server-rendered .itin-day-chip--active fallback.
 *   - hashchange (e.g. back/forward): re-sync the active day.
 */
(function () {
  'use strict';

  var root = document.querySelector('[data-itin-day-chips]');
  if (!root) return;

  var chips = root.querySelectorAll('[data-itin-day-target]');
  var columns = document.querySelectorAll('.day-column[data-day-index]');
  if (!chips.length || !columns.length) return;

  function activate(index, updateHash) {
    var key = String(index);
    chips.forEach(function (c) {
      var match = c.getAttribute('data-itin-day-target') === key;
      c.classList.toggle('itin-day-chip--active', match);
      if (match) c.setAttribute('aria-current', 'true');
      else c.removeAttribute('aria-current');
    });
    columns.forEach(function (col) {
      col.classList.toggle(
        'day-column--active',
        col.getAttribute('data-day-index') === key
      );
    });
    if (updateHash) {
      history.replaceState(null, '', '#day-' + index);
    }
  }

  function indexFromHash() {
    var m = (location.hash || '').match(/^#day-(\d+)$/);
    if (!m) return null;
    var n = parseInt(m[1], 10);
    if (!n || n < 1 || n > chips.length) return null;
    return n;
  }

  chips.forEach(function (chip) {
    chip.addEventListener('click', function (e) {
      e.preventDefault();
      var idx = parseInt(chip.getAttribute('data-itin-day-target'), 10);
      activate(idx, true);
      chip.focus();
    });
  });

  root.addEventListener('keydown', function (e) {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    var current = root.querySelector('.itin-day-chip--active');
    if (!current) return;
    var idx = parseInt(current.getAttribute('data-itin-day-target'), 10);
    var next = e.key === 'ArrowLeft' ? idx - 1 : idx + 1;
    if (next < 1 || next > chips.length) return;
    e.preventDefault();
    activate(next, true);
    var nextChip = root.querySelector('[data-itin-day-target="' + next + '"]');
    if (nextChip) nextChip.focus();
  });

  window.addEventListener('hashchange', function () {
    var idx = indexFromHash();
    if (idx) activate(idx, false);
  });

  var initial = indexFromHash();
  if (!initial) {
    var preActive = root.querySelector('.itin-day-chip--active');
    initial = preActive
      ? parseInt(preActive.getAttribute('data-itin-day-target'), 10)
      : 1;
  }
  activate(initial, false);

  // Item-level arrival flash. If the page loaded with #item-N in the
  // URL (e.g. from the bookings-list chip), briefly highlight that chip
  // using the existing data-just-synced animation.
  var itemMatch = (location.hash || '').match(/^#item-(\d+)$/);
  if (itemMatch) {
    var target = document.getElementById('item-' + itemMatch[1]);
    if (target) {
      target.setAttribute('data-just-synced', 'true');
      setTimeout(function () {
        target.removeAttribute('data-just-synced');
      }, 1400);
    }
  }
}());
