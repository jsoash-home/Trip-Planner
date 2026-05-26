/*
 * Navbar trip switcher dropdown.
 *
 * Pure CSS / minimal JS — no Bootstrap JS. The trigger is a <button>
 * with aria-expanded; the menu is a sibling <div role="menu"> that
 * we toggle the [hidden] attribute on. CSS handles position + caret
 * rotation off the aria-expanded state.
 *
 * Behaviors:
 *   - Click trigger: toggle open/closed.
 *   - Escape (when open): close, restore focus to trigger.
 *   - Click outside the dropdown root: close.
 *   - ArrowDown on the trigger: open and focus the first menu item.
 */
(function () {
  'use strict';

  document.querySelectorAll('[data-nav-dropdown]').forEach(function (root) {
    var trigger = root.querySelector('[data-nav-dropdown-trigger]');
    var menu = root.querySelector('[role="menu"]');
    if (!trigger || !menu) return;

    function isOpen() {
      return trigger.getAttribute('aria-expanded') === 'true';
    }

    function open() {
      trigger.setAttribute('aria-expanded', 'true');
      menu.hidden = false;
    }

    function close(returnFocus) {
      trigger.setAttribute('aria-expanded', 'false');
      menu.hidden = true;
      if (returnFocus) trigger.focus();
    }

    trigger.addEventListener('click', function (e) {
      e.preventDefault();
      if (isOpen()) close(false); else open();
    });

    trigger.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        open();
        var first = menu.querySelector('[role="menuitem"]');
        if (first) first.focus();
      }
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && isOpen()) {
        e.preventDefault();
        close(true);
      }
    });

    document.addEventListener('click', function (e) {
      if (isOpen() && !root.contains(e.target)) close(false);
    });
  });
}());
