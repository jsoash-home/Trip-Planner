/*
 * Branded confirm dialog wiring.
 *
 * Forms opt in by adding:
 *   data-confirm="Delete \"Italy\"?"          (required — the title)
 *   data-confirm-detail="This can't be undone." (optional — second line)
 *   data-confirm-label="Remove"                 (optional — OK button text)
 *
 * On submit we preventDefault, show the modal <dialog>, and only fire
 * the real form.submit() after the user clicks OK. Cancel, Escape, and
 * backdrop click all dismiss without submitting. Focus returns to the
 * triggering button on close.
 *
 * Native <dialog>.showModal() handles backdrop, Escape, and Tab focus
 * trapping for us, so we don't reimplement those.
 */
(function () {
  'use strict';

  var dialog = document.getElementById('vp-confirm');
  if (!dialog || typeof dialog.showModal !== 'function') {
    // No dialog in the page (e.g. login screen) or no native support —
    // fall through and let the form submit normally. Modern browsers
    // (Safari 15.4+, Chrome 37+, Firefox 98+) all support showModal.
    return;
  }

  var titleEl = dialog.querySelector('#vp-confirm-title');
  var detailEl = dialog.querySelector('#vp-confirm-detail');
  var okBtn = dialog.querySelector('[data-confirm-ok]');
  var cancelBtn = dialog.querySelector('[data-confirm-cancel]');

  // The form whose submission we intercepted, and the button the user
  // clicked to trigger it. We restore focus to that button on close.
  var activeForm = null;
  var triggerEl = null;
  // Set to true just before we call form.submit() programmatically so
  // our submit listener lets that submission through.
  var confirmed = false;

  function openFor(form, submitter) {
    activeForm = form;
    triggerEl = submitter || form.querySelector('button[type=submit]');

    titleEl.textContent = form.getAttribute('data-confirm') || 'Are you sure?';

    var detail = form.getAttribute('data-confirm-detail');
    if (detail) {
      detailEl.textContent = detail;
      detailEl.hidden = false;
    } else {
      detailEl.textContent = '';
      detailEl.hidden = true;
    }

    okBtn.textContent = form.getAttribute('data-confirm-label') || 'Delete';

    dialog.showModal();
    // Default focus to Cancel — safer for destructive actions and
    // matches the Cancel-then-primary tab order used in form footers.
    cancelBtn.focus();
  }

  function cancelClose() {
    if (dialog.open) dialog.close('cancel');
  }

  cancelBtn.addEventListener('click', function () {
    cancelClose();
  });

  // Click on the dialog backdrop (i.e. outside the .vp-confirm-card)
  // also cancels. The <dialog> element fills the viewport when modal,
  // but visually only the card is opaque — so any mousedown whose
  // target is the dialog itself is a backdrop click.
  dialog.addEventListener('mousedown', function (e) {
    if (e.target === dialog) cancelClose();
  });

  dialog.addEventListener('close', function () {
    var wasConfirmed = dialog.returnValue === 'confirm';
    var formToSubmit = activeForm;
    var focusTarget = triggerEl;

    activeForm = null;
    triggerEl = null;

    if (wasConfirmed && formToSubmit) {
      confirmed = true;
      formToSubmit.submit();
      // We don't restore focus here — the page is navigating away.
      return;
    }

    // Cancelled. Return focus to whatever the user clicked to open us.
    if (focusTarget && typeof focusTarget.focus === 'function') {
      focusTarget.focus();
    }
  });

  document.querySelectorAll('form[data-confirm]').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      if (confirmed) {
        // Programmatic submit triggered by us — let it through.
        confirmed = false;
        return;
      }
      e.preventDefault();
      openFor(form, e.submitter);
    });
  });
})();
