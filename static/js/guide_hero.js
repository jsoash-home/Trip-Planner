/**
 * guide_hero.js — copy-to-clipboard for the Trip Guide share URL.
 *
 * DOM convention:
 *   <button data-share-url="https://...">Copy link</button>
 *
 * Clicking the button copies the URL to the clipboard and briefly shows
 * "Copied!" as feedback. Falls back to window.prompt() when the
 * Clipboard API is unavailable (e.g., non-secure context).
 */
(function () {
  'use strict';

  function init() {
    document.querySelectorAll('[data-share-url]').forEach(function (btn) {
      btn.addEventListener('click', async function (e) {
        e.preventDefault();
        var url = btn.dataset.shareUrl;
        try {
          await navigator.clipboard.writeText(url);
          var original = btn.textContent;
          btn.textContent = 'Copied!';
          setTimeout(function () { btn.textContent = original; }, 1800);
        } catch (err) {
          window.prompt('Copy this link:', url);
        }
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
