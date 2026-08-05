(() => {
  const storageKey = "halloween:pending-scroll";
  const maxAgeMs = 30000;

  function savePagePosition(form) {
    if (!(form instanceof HTMLFormElement)) return;
    if (form.dataset.noScrollRestore !== undefined) return;
    const method = (form.method || "get").toLowerCase();
    if (method !== "post") return;

    const openDetails = Array.from(document.querySelectorAll("details"))
      .flatMap((details, index) => (details.open ? [index] : []));
    try {
      sessionStorage.setItem(storageKey, JSON.stringify({
        path: window.location.pathname,
        x: window.scrollX,
        y: window.scrollY,
        openDetails,
        savedAt: Date.now(),
      }));
    } catch (_error) {
      // Storage may be disabled; the form should still submit normally.
    }
  }

  function restorePagePosition() {
    let saved;
    try {
      saved = JSON.parse(sessionStorage.getItem(storageKey) || "null");
    } catch (_error) {
      sessionStorage.removeItem(storageKey);
      return;
    }

    sessionStorage.removeItem(storageKey);
    if (!saved || saved.path !== window.location.pathname || Date.now() - saved.savedAt > maxAgeMs) return;

    const details = document.querySelectorAll("details");
    for (const index of saved.openDetails || []) {
      if (details[index]) details[index].open = true;
    }

    if ("scrollRestoration" in history) history.scrollRestoration = "manual";
    requestAnimationFrame(() => requestAnimationFrame(() => {
      const maxY = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
      window.scrollTo(saved.x || 0, Math.min(saved.y || 0, maxY));
    }));
  }

  document.addEventListener("submit", (event) => savePagePosition(event.target), true);
  window.addEventListener("pageshow", restorePagePosition, { once: true });
})();
