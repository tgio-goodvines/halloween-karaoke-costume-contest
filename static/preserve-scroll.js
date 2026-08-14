(() => {
  const storageKey = "halloween:pending-view";
  const maxAgeMs = 30000;
  let adminRequestInFlight = false;
  const replacementControlValues = {
    enable_game: "disable_game",
    disable_game: "enable_game",
    enable_two_truths_game: "disable_two_truths_game",
    disable_two_truths_game: "enable_two_truths_game",
    pause_display_rotation: "resume_display_rotation",
    resume_display_rotation: "pause_display_rotation",
  };

  if ("scrollRestoration" in history) history.scrollRestoration = "manual";

  const normalizedText = (value) => String(value || "").replace(/\s+/g, " ").trim().toLowerCase();

  const elementKey = (element, root = document) => {
    if (!(element instanceof Element)) return "";
    if (element.dataset.viewKey) return `view:${element.dataset.viewKey}`;
    if (element.id) return `id:${element.id}`;
    if (element instanceof HTMLDetailsElement) {
      const label = normalizedText(element.querySelector(":scope > summary")?.textContent);
      const matches = Array.from(root.querySelectorAll("details")).filter(
        (candidate) => normalizedText(candidate.querySelector(":scope > summary")?.textContent) === label,
      );
      return `details:${label}:${Math.max(0, matches.indexOf(element))}`;
    }
    const heading = element.querySelector(":scope > header h2, :scope > header h3, :scope > header h4, :scope > h2, :scope > h3, :scope > h4, :scope > h5");
    if (heading) return `${element.tagName.toLowerCase()}:${normalizedText(heading.textContent)}`;
    return "";
  };

  const keyedElements = (root) => Array.from(root.querySelectorAll("[data-view-key], [id], details, article, section"));

  const findByKey = (root, key) => {
    if (!key) return null;
    return keyedElements(root).find((element) => elementKey(element, root) === key) || null;
  };

  const nearestAnchor = (element, root) => {
    if (!(element instanceof Element)) return root;
    return element.closest("[data-view-key], [id], details, article, section") || root;
  };

  const captureView = (source = document.activeElement) => {
    const panel = document.querySelector(".admin-panel") || document.body;
    const anchor = nearestAnchor(source, panel);
    const openDetails = Array.from(panel.querySelectorAll("details[open]")).map((details) => elementKey(details, panel));
    const submitter = source instanceof HTMLButtonElement || source instanceof HTMLInputElement ? source : null;
    return {
      page: `${window.location.pathname}${window.location.search}`,
      x: window.scrollX,
      y: window.scrollY,
      anchorKey: elementKey(anchor, panel),
      anchorTop: anchor?.getBoundingClientRect().top ?? 0,
      openDetails,
      controlName: submitter?.name || "",
      controlValue: submitter?.value || "",
      savedAt: Date.now(),
    };
  };

  const storeView = (source) => {
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(captureView(source)));
    } catch (_error) {
      // Storage may be disabled; navigation and form submission still work.
    }
  };

  const readStoredView = () => {
    let saved;
    try {
      saved = JSON.parse(sessionStorage.getItem(storageKey) || "null");
    } catch (_error) {
      sessionStorage.removeItem(storageKey);
      return null;
    }
    if (!saved || Date.now() - saved.savedAt > maxAgeMs) {
      sessionStorage.removeItem(storageKey);
      return null;
    }
    return saved;
  };

  const reopenDetails = (root, saved) => {
    const openKeys = new Set(saved?.openDetails || []);
    root.querySelectorAll("details").forEach((details) => {
      if (openKeys.has(elementKey(details, root))) details.open = true;
    });
  };

  const focusReplacement = (panel, saved) => {
    const anchor = findByKey(panel, saved.anchorKey) || panel;
    let control = null;
    if (saved.controlName) {
      const controls = Array.from(anchor.querySelectorAll("button, input[type='submit']"));
      control = controls.find(
        (candidate) => candidate.name === saved.controlName && candidate.value === saved.controlValue,
      );
      const replacementValue = replacementControlValues[saved.controlValue];
      control ||= controls.find(
        (candidate) => candidate.name === saved.controlName && candidate.value === replacementValue,
      );
      control ||= controls.find((candidate) => candidate.name === saved.controlName && !candidate.disabled);
    }
    if (control instanceof HTMLElement && !control.disabled) {
      control.focus({ preventScroll: true });
    }
  };

  const restoreView = (panel, saved, { focus = false } = {}) => {
    if (!saved) return;
    const adjust = () => {
      const anchor = findByKey(panel, saved.anchorKey);
      if (anchor) {
        const delta = anchor.getBoundingClientRect().top - Number(saved.anchorTop || 0);
        if (Math.abs(delta) > 1) window.scrollBy(0, delta);
      } else {
        const maxY = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
        window.scrollTo(Number(saved.x || 0), Math.min(Number(saved.y || 0), maxY));
      }
    };
    requestAnimationFrame(() => requestAnimationFrame(() => {
      adjust();
      if (focus) focusReplacement(panel, saved);
    }));
    window.setTimeout(adjust, 120);
    if (document.fonts?.ready) document.fonts.ready.then(adjust).catch(() => {});
  };

  const restoreAfterNavigation = () => {
    const saved = readStoredView();
    const currentPage = `${window.location.pathname}${window.location.search}`;
    if (!saved || saved.page !== currentPage) return;
    sessionStorage.removeItem(storageKey);
    const panel = document.querySelector(".admin-panel") || document.body;
    reopenDetails(panel, saved);
    restoreView(panel, saved, { focus: true });
  };

  const shouldEnhanceAdminForm = (form) => {
    const panel = form.closest(".admin-panel");
    if (!panel || panel.matches("[data-admin-inline='false']") || form.dataset.fullNavigation !== undefined) return false;
    const method = (form.method || "get").toLowerCase();
    if (method !== "post" || form.target && form.target !== "_self") return false;
    const action = new URL(form.getAttribute("action") || window.location.href, window.location.href);
    return action.origin === window.location.origin && action.pathname.startsWith("/admin");
  };

  const showRequestError = (panel, message) => {
    const existing = panel.querySelector("[data-admin-inline-error]");
    const notice = existing || document.createElement("div");
    notice.dataset.adminInlineError = "";
    notice.className = "flash flash--error";
    notice.setAttribute("role", "alert");
    notice.textContent = message;
    if (!existing) panel.querySelector(".admin-workspace-nav")?.insertAdjacentElement("afterend", notice);
  };

  const submitAdminForm = async (form, submitter, saved) => {
    if (adminRequestInFlight) return;
    adminRequestInFlight = true;
    const currentPanel = form.closest(".admin-panel");
    const originalDisabled = Boolean(submitter?.disabled);
    if (submitter) submitter.disabled = true;
    currentPanel.setAttribute("aria-busy", "true");

    const body = new FormData(form);
    if (submitter?.name) body.set(submitter.name, submitter.value);
    try {
      const response = await fetch(form.getAttribute("action") || window.location.href, {
        method: "POST",
        credentials: "same-origin",
        headers: { Accept: "text/html", "X-Admin-Inline": "1" },
        body,
      });
      const html = await response.text();
      const parsed = new DOMParser().parseFromString(html, "text/html");
      const nextPanel = parsed.querySelector(".admin-panel");
      if (!nextPanel) {
        if (response.redirected) {
          storeView(submitter);
          window.location.assign(response.url);
          return;
        }
        throw new Error(response.ok ? "The updated admin workspace was unavailable." : html.trim() || `Request failed (${response.status}).`);
      }
      reopenDetails(nextPanel, saved);
      currentPanel.replaceWith(nextPanel);
      sessionStorage.removeItem(storageKey);
      const responseUrl = new URL(response.url, window.location.href);
      if (`${responseUrl.pathname}${responseUrl.search}` !== `${window.location.pathname}${window.location.search}`) {
        history.replaceState(history.state, "", `${responseUrl.pathname}${responseUrl.search}${responseUrl.hash}`);
      }
      restoreView(nextPanel, saved, { focus: true });
      document.dispatchEvent(new CustomEvent("admin:panel-updated", { detail: { panel: nextPanel } }));
    } catch (error) {
      currentPanel.removeAttribute("aria-busy");
      if (submitter) submitter.disabled = originalDisabled;
      showRequestError(currentPanel, error.message || "The admin action could not be completed. Please try again.");
      restoreView(currentPanel, saved, { focus: true });
    } finally {
      adminRequestInFlight = false;
    }
  };

  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || event.defaultPrevented || form.dataset.noScrollRestore !== undefined) return;
    const method = (form.method || "get").toLowerCase();
    if (method !== "post") return;
    const submitter = event.submitter || document.activeElement;
    const saved = captureView(submitter);
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(saved));
    } catch (_error) {
      // A same-page form still works when session storage is unavailable.
    }
    if (!shouldEnhanceAdminForm(form)) return;
    event.preventDefault();
    submitAdminForm(form, submitter, saved);
  });

  window.AdminViewState = { save: storeView };
  window.addEventListener("pageshow", restoreAfterNavigation, { once: true });
})();
