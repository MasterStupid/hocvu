// Apply the saved theme before the stylesheet paints either page.
(() => {
  let theme = 'light';
  try {
    if (localStorage.getItem('hv_theme') === 'dark') theme = 'dark';
  } catch (_) { /* Storage may be unavailable in a restricted browser. */ }
  document.documentElement.dataset.theme = theme;
})();
