document.addEventListener('DOMContentLoaded', () => {
  const dataElement = document.getElementById('entries-data');
  const card = document.querySelector('[data-display-card]');
  const emptyState = document.querySelector('[data-empty-state]');

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

  const typeElement = card.querySelector('[data-entry-type]');
  const primaryElement = card.querySelector('[data-entry-primary]');
  const secondaryElement = card.querySelector('[data-entry-secondary]');
  const tertiaryElement = card.querySelector('[data-entry-tertiary]');

  const showEmptyState = entries.length === 0;

  if (showEmptyState) {
    emptyState.classList.add('is-visible');
    card.classList.remove('active');
    card.setAttribute('hidden', '');
    return;
  }

  emptyState.classList.remove('is-visible');
  card.removeAttribute('hidden');

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
  };

  let currentIndex = 0;
  applyEntry(entries[currentIndex]);
  card.classList.add('active');

  if (entries.length === 1) {
    return;
  }

  const cycleDelay = 8000;
  const transitionDelay = 450;

  setInterval(() => {
    card.classList.remove('active');

    setTimeout(() => {
      currentIndex = (currentIndex + 1) % entries.length;
      applyEntry(entries[currentIndex]);
      card.classList.add('active');
    }, transitionDelay);
  }, cycleDelay);
});
