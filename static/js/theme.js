// Theme toggle wiring — flips data-theme + data-bs-theme on <html>,
// persists the choice in localStorage, and updates the toggle button's
// emoji and aria-label. The synchronous init in <head> handles first
// paint (FOUC prevention); this script handles user clicks afterward.

(function () {
  var STORAGE_KEY = 'vp.theme';

  function applyIcon(button, theme) {
    if (!button) return;
    var iconEl = button.querySelector('[data-theme-toggle-icon]');
    // Show the icon the user would click TO switch to — moon means
    // "click to go dark", sun means "click to go light".
    if (iconEl) {
      iconEl.textContent = theme === 'dark' ? '☀️' : '🌙';
    }
    button.setAttribute(
      'aria-label',
      theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'
    );
  }

  function setTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    document.documentElement.setAttribute('data-bs-theme', theme);
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch (e) {
      // Private browsing — toggle still works for the session.
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    var button = document.querySelector('[data-theme-toggle]');
    if (!button) return;

    // Sync the icon + label with whatever the init script chose.
    applyIcon(button, document.documentElement.getAttribute('data-theme') || 'light');

    button.addEventListener('click', function () {
      var current = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
      var next = current === 'dark' ? 'light' : 'dark';
      setTheme(next);
      applyIcon(button, next);
    });
  });
})();
