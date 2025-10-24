document.addEventListener('DOMContentLoaded', () => {
  const dataElement = document.getElementById('entries-data');
  const overrideElement = document.getElementById('override-data');
  const card = document.querySelector('[data-display-card]');
  const emptyState = document.querySelector('[data-empty-state]');
  const overrideContainer = document.querySelector('[data-override-state]');
  const overrideTitleElement = overrideContainer ? overrideContainer.querySelector('[data-override-title]') : null;
  const overrideHighlightElement = overrideContainer ? overrideContainer.querySelector('[data-override-highlight]') : null;
  const overrideMessageElement = overrideContainer ? overrideContainer.querySelector('[data-override-message]') : null;
  const overrideDetailsElement = overrideContainer ? overrideContainer.querySelector('[data-override-details]') : null;
  const costumeCountElement = document.querySelector('[data-costume-count]');
  const karaokeCountElement = document.querySelector('[data-karaoke-count]');
  const dataEndpoint = (document.body && document.body.dataset && document.body.dataset.displayApi) || '/api/display-data';

  if (!dataElement || !card || !emptyState) {
    return;
  }

  let entries = [];
  try {
    entries = JSON.parse(dataElement.textContent || '[]');
    if (!Array.isArray(entries)) {
      entries = [];
    }
  } catch (error) {
    console.error('Unable to parse display entries', error);
    entries = [];
  }

  let entriesSignature;
  try {
    entriesSignature = JSON.stringify(entries);
  } catch (error) {
    entriesSignature = '[]';
  }

  let initialOverrideState = null;
  if (overrideElement) {
    try {
      const parsed = JSON.parse(overrideElement.textContent || 'null');
      if (parsed && typeof parsed === 'object') {
        initialOverrideState = parsed;
      }
    } catch (error) {
      console.error('Unable to parse override state', error);
    }
  }

  let overrideState = null;
  let overrideSignature = 'null';

  const defaultContent = card.querySelector('[data-entry-default]');
  const ctaLayout = card.querySelector('[data-cta-layout]');
  const ctaLedeElement = card.querySelector('[data-cta-lede]');
  const ctaWifiNetworkElement = card.querySelector('[data-cta-wifi-network]');
  const ctaWifiPasswordElement = card.querySelector('[data-cta-wifi-password]');
  const ctaPortalLinkElement = card.querySelector('[data-cta-portal-link]');
  const ctaPortalNoteElement = card.querySelector('[data-cta-portal-note]');
  const ctaReminderElement = card.querySelector('[data-cta-reminder]');
  const typeElement = card.querySelector('[data-entry-type]');
  const primaryElement = card.querySelector('[data-entry-primary]');
  const secondaryElement = card.querySelector('[data-entry-secondary]');
  const tertiaryElement = card.querySelector('[data-entry-tertiary]');
  const linkElement = card.querySelector('[data-entry-link]');

  const updateOverrideContent = () => {
    if (!overrideContainer) {
      return;
    }

    if (overrideTitleElement) {
      overrideTitleElement.textContent = overrideState && overrideState.title ? overrideState.title : '';
    }

    if (overrideHighlightElement) {
      const highlight = overrideState && overrideState.highlight ? overrideState.highlight : '';
      if (highlight) {
        overrideHighlightElement.textContent = highlight;
        overrideHighlightElement.removeAttribute('hidden');
      } else {
        overrideHighlightElement.textContent = '';
        overrideHighlightElement.setAttribute('hidden', '');
      }
    }

    if (overrideMessageElement) {
      overrideMessageElement.textContent = overrideState && overrideState.message ? overrideState.message : '';
    }

    if (overrideDetailsElement) {
      overrideDetailsElement.innerHTML = '';
      const details = overrideState && Array.isArray(overrideState.details) ? overrideState.details : [];
      if (details.length) {
        details.forEach((detail) => {
          const item = document.createElement('li');
          item.textContent = detail;
          overrideDetailsElement.appendChild(item);
        });
        overrideDetailsElement.removeAttribute('hidden');
      } else {
        overrideDetailsElement.setAttribute('hidden', '');
      }
    }
  };

  const updateOverrideDisplay = () => {
    if (!overrideContainer) {
      return;
    }

    if (overrideState) {
      overrideContainer.removeAttribute('hidden');
      if (card) {
        card.classList.remove('active');
        card.setAttribute('hidden', '');
      }
      if (emptyState) {
        emptyState.classList.remove('is-visible');
        emptyState.setAttribute('hidden', '');
      }
    } else {
      overrideContainer.setAttribute('hidden', '');
      if (emptyState) {
        emptyState.removeAttribute('hidden');
      }
      if (card) {
        card.removeAttribute('hidden');
      }
    }
  };

  const applyEntry = (entry) => {
    typeElement.textContent = entry.category || '';
    primaryElement.textContent = entry.primary || '';
    secondaryElement.textContent = entry.secondary || '';

    if (entry.tertiary) {
      tertiaryElement.textContent = entry.tertiary;
      tertiaryElement.removeAttribute('hidden');
    } else {
      tertiaryElement.textContent = '';
      tertiaryElement.setAttribute('hidden', '');
    }

    const ctaDetails = entry.cta_details || {};
    const shouldShowCtaLayout = Boolean(entry.cta && ctaLayout && defaultContent);

    if (shouldShowCtaLayout) {
      defaultContent.setAttribute('hidden', '');
      ctaLayout.removeAttribute('hidden');

      if (ctaLedeElement) {
        ctaLedeElement.textContent = ctaDetails.lede || entry.secondary || entry.primary || '';
      }

      if (ctaWifiNetworkElement) {
        ctaWifiNetworkElement.textContent = ctaDetails.wifi_network || '';
      }

      if (ctaWifiPasswordElement) {
        ctaWifiPasswordElement.textContent = ctaDetails.wifi_password || '';
      }

      if (ctaPortalLinkElement) {
        const portalUrl = ctaDetails.portal_url || entry.link || '';
        const portalLabel = ctaDetails.portal_label || portalUrl;

        if (portalUrl) {
          ctaPortalLinkElement.textContent = portalLabel || portalUrl;
          ctaPortalLinkElement.setAttribute('href', portalUrl);
        } else {
          ctaPortalLinkElement.textContent = '';
          ctaPortalLinkElement.removeAttribute('href');
        }
      }

      if (ctaPortalNoteElement) {
        ctaPortalNoteElement.textContent = ctaDetails.portal_note || '';
      }

      if (ctaReminderElement) {
        ctaReminderElement.textContent = ctaDetails.reminder || entry.tertiary || '';
      }
    } else {
      if (defaultContent) {
        defaultContent.removeAttribute('hidden');
      }
      if (ctaLayout) {
        ctaLayout.setAttribute('hidden', '');
      }
      if (ctaLedeElement) {
        ctaLedeElement.textContent = '';
      }
      if (ctaWifiNetworkElement) {
        ctaWifiNetworkElement.textContent = '';
      }
      if (ctaWifiPasswordElement) {
        ctaWifiPasswordElement.textContent = '';
      }
      if (ctaPortalLinkElement) {
        ctaPortalLinkElement.textContent = '';
        ctaPortalLinkElement.removeAttribute('href');
      }
      if (ctaPortalNoteElement) {
        ctaPortalNoteElement.textContent = '';
      }
      if (ctaReminderElement) {
        ctaReminderElement.textContent = '';
      }
    }

    if (entry.cta) {
      card.classList.add('cta');
    } else {
      card.classList.remove('cta');
    }

    if (linkElement) {
      if (entry.link && !entry.cta) {
        linkElement.textContent = entry.link_label || entry.link;
        linkElement.setAttribute('href', entry.link);
        linkElement.removeAttribute('hidden');
      } else {
        linkElement.textContent = '';
        linkElement.removeAttribute('href');
        linkElement.setAttribute('hidden', '');
      }
    }
  };

  const cycleDelay = 8000;
  const transitionDelay = 450;
  let currentIndex = 0;
  let rotationTimerId = null;

  const stopRotation = () => {
    if (rotationTimerId) {
      window.clearInterval(rotationTimerId);
      rotationTimerId = null;
    }
  };

  const swapEntry = (useTransition) => {
    if (!entries.length) {
      return;
    }

    const show = () => {
      applyEntry(entries[currentIndex]);
      card.classList.add('active');
    };

    if (useTransition) {
      card.classList.remove('active');
      window.setTimeout(show, transitionDelay);
    } else {
      show();
    }
  };

  const renderEntries = ({ resetIndex = false, animate = false } = {}) => {
    updateOverrideDisplay();

    if (overrideState) {
      stopRotation();
      return;
    }

    if (entries.length === 0) {
      stopRotation();
      emptyState.classList.add('is-visible');
      card.classList.remove('active');
      card.setAttribute('hidden', '');
      return;
    }

    if (resetIndex) {
      currentIndex = 0;
    } else {
      currentIndex = currentIndex % entries.length;
    }

    emptyState.classList.remove('is-visible');
    card.removeAttribute('hidden');

    stopRotation();
    swapEntry(animate);

    if (entries.length > 1) {
      rotationTimerId = window.setInterval(() => {
        currentIndex = (currentIndex + 1) % entries.length;
        swapEntry(true);
      }, cycleDelay);
    }
  };

  const setOverrideState = (state, { force = false } = {}) => {
    let signature = 'null';
    try {
      signature = JSON.stringify(state ?? null);
    } catch (error) {
      signature = 'null';
    }

    if (!force && signature === overrideSignature) {
      return;
    }

    overrideSignature = signature;
    overrideState = state && typeof state === 'object' ? state : null;
    updateOverrideContent();
    renderEntries({ resetIndex: true });
  };

  setOverrideState(initialOverrideState ?? null, { force: true });

  const updateCounts = (costumeCount, karaokeCount) => {
    if (costumeCountElement && Number.isFinite(costumeCount)) {
      costumeCountElement.textContent = costumeCount;
    }

    if (karaokeCountElement && Number.isFinite(karaokeCount)) {
      karaokeCountElement.textContent = karaokeCount;
    }
  };

  const refreshInterval = 30000;

  const fetchLatestEntries = async () => {
    try {
      const response = await fetch(dataEndpoint, { cache: 'no-store' });

      if (!response.ok) {
        throw new Error(`Request failed with status ${response.status}`);
      }

      const payload = await response.json();
      const {
        entries: newEntries,
        costume_count: costumeCount,
        karaoke_count: karaokeCount,
        override: newOverride,
      } = payload;

      updateCounts(costumeCount, karaokeCount);
      setOverrideState(newOverride || null);

      if (Array.isArray(newEntries)) {
        const newSignature = JSON.stringify(newEntries);
        if (newSignature !== entriesSignature) {
          entries = newEntries;
          entriesSignature = newSignature;
          renderEntries({ resetIndex: true, animate: true });
        }
      }
    } catch (error) {
      console.error('Unable to refresh display data', error);
    }
  };

  fetchLatestEntries();
  window.setInterval(fetchLatestEntries, refreshInterval);
});
