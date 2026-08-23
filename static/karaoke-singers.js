(() => {
  const formatNames = (names) => {
    if (!names.length) return '';
    if (names.length === 1) return names[0];
    if (names.length === 2) return `${names[0]} & ${names[1]}`;
    return `${names.slice(0, -1).join(', ')} & ${names[names.length - 1]}`;
  };

  document.querySelectorAll('[data-karaoke-singers]').forEach((editor) => {
    const rows = editor.querySelector('[data-karaoke-singer-rows]');
    const template = editor.querySelector('[data-karaoke-singer-template]');
    const addButton = editor.querySelector('[data-karaoke-add-singer]');
    const status = editor.querySelector('[data-karaoke-singer-status]');
    const maxSingers = Math.max(1, Number(editor.dataset.maxSingers || 4));
    const customValue = editor.dataset.customValue || '__custom__';

    const rowElements = () => Array.from(rows?.querySelectorAll('[data-karaoke-singer-row]') || []);

    const updateCustomField = (row) => {
      const select = row.querySelector('[data-karaoke-singer-select]');
      const customLabel = row.querySelector('[data-karaoke-custom-label]');
      const customInput = row.querySelector('[data-karaoke-custom-name]');
      const isCustom = select?.value === customValue;
      if (customLabel) customLabel.hidden = !isCustom;
      if (customInput) customInput.required = isCustom;
    };

    const singerName = (row) => {
      const select = row.querySelector('[data-karaoke-singer-select]');
      const customInput = row.querySelector('[data-karaoke-custom-name]');
      if (!select?.value) return '';
      if (select.value === customValue) return (customInput?.value || '').trim();
      return (select.selectedOptions[0]?.textContent || '').trim();
    };

    const validateDuplicates = (currentRows) => {
      const seenSelections = new Set();
      const seenNames = new Set();
      currentRows.forEach((row) => {
        const select = row.querySelector('[data-karaoke-singer-select]');
        const customInput = row.querySelector('[data-karaoke-custom-name]');
        select?.setCustomValidity('');
        customInput?.setCustomValidity('');
        const name = singerName(row);
        if (!select?.value || !name) return;
        const normalizedName = name.toLocaleLowerCase();
        const duplicateSelection = select.value !== customValue && seenSelections.has(select.value);
        const duplicateName = seenNames.has(normalizedName);
        if (duplicateSelection || duplicateName) {
          const message = 'Each singer can only be added once.';
          if (select.value === customValue) customInput?.setCustomValidity(message);
          else select.setCustomValidity(message);
        }
        if (select.value !== customValue) seenSelections.add(select.value);
        seenNames.add(normalizedName);
      });
    };

    const refresh = () => {
      const currentRows = rowElements();
      currentRows.forEach((row, index) => {
        updateCustomField(row);
        const label = row.querySelector('[data-karaoke-singer-select]')?.closest('label')?.querySelector('span');
        if (label) label.textContent = `Singer ${index + 1}`;
        const removeButton = row.querySelector('[data-karaoke-remove-singer]');
        if (removeButton) removeButton.hidden = currentRows.length === 1;
      });
      validateDuplicates(currentRows);
      const names = currentRows.map(singerName).filter(Boolean);
      editor.dataset.singerLabel = formatNames(names);
      if (status) status.textContent = `${currentRows.length} of ${maxSingers} singers`;
      if (addButton) addButton.disabled = currentRows.length >= maxSingers;
      editor.dispatchEvent(new CustomEvent('karaoke:singers-change', {
        bubbles: true,
        detail: { names, label: editor.dataset.singerLabel },
      }));
    };

    editor.addEventListener('change', (event) => {
      if (event.target.matches('[data-karaoke-singer-select]')) refresh();
    });
    editor.addEventListener('input', (event) => {
      if (event.target.matches('[data-karaoke-custom-name]')) refresh();
    });
    editor.addEventListener('click', (event) => {
      const removeButton = event.target.closest('[data-karaoke-remove-singer]');
      if (removeButton) {
        removeButton.closest('[data-karaoke-singer-row]')?.remove();
        refresh();
        return;
      }
      if (event.target.closest('[data-karaoke-add-singer]') && template && rows) {
        if (rowElements().length >= maxSingers) return;
        rows.appendChild(template.content.cloneNode(true));
        refresh();
        rowElements().at(-1)?.querySelector('[data-karaoke-singer-select]')?.focus();
      }
    });

    refresh();
  });
})();
