(() => {
  const initializeMenuForms = (root = document) => {
    root.querySelectorAll("[data-menu-item-form]").forEach((form) => {
      if (form.dataset.menuFieldsReady === "true") return;
      const category = form.querySelector("[data-menu-category]");
      if (!(category instanceof HTMLSelectElement)) return;

      const syncDrinkFields = () => {
        const isDrink = category.value === "drink";
        form.querySelectorAll("[data-menu-drink-fields]").forEach((field) => {
          field.hidden = !isDrink;
          field.querySelectorAll("input, select, textarea").forEach((control) => {
            control.disabled = !isDrink;
          });
        });
      };

      category.addEventListener("change", syncDrinkFields);
      form.dataset.menuFieldsReady = "true";
      syncDrinkFields();
    });
  };

  document.addEventListener("DOMContentLoaded", () => initializeMenuForms());
  document.addEventListener("admin:panel-updated", (event) => {
    initializeMenuForms(event.detail?.panel || document);
  });
})();
