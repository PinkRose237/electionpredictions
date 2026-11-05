/**
 * archive-gate.js — the 2026 midterm site is retired to an admin-only archive.
 * Loaded synchronously in <head> of every archived page: without the admin sign-in (same key the admin page
 * sets) the visitor is sent to the admin login, which returns here afterwards. Like any gate on a static site
 * this is a UI gate; the files themselves are not secret.
 */
(function () {
  var ok = false;
  try { ok = sessionStorage.getItem('admin-ok') === '1' || localStorage.getItem('admin-ok') === '1'; } catch (e) { ok = false; }
  if (!ok) {
    document.documentElement.style.display = 'none';
    var page = (location.pathname.split('/').pop() || 'index.html') + location.search;
    location.replace('../../admin.html?next=' + encodeURIComponent('archive/2026/' + page));
    return;
  }
  document.addEventListener('DOMContentLoaded', function () {
    var bar = document.createElement('div');
    bar.className = 'archive-banner';
    bar.setAttribute('role', 'note');
    bar.innerHTML = '<div class="container"><strong>Archive · 2026 midterms</strong> — admin-only view of the retired midterm site (final forecast frozen Nov 3, 2026). '
      + '<a href="../../admin.html">Admin home</a> · <a href="../../index.html">2028 forecast</a></div>';
    document.body.insertBefore(bar, document.body.firstChild);
  });
})();
