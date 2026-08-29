(() => {
  const connect = (root = document) => {
    root.querySelectorAll("[data-wrapup-attendees]").forEach((fieldset) => {
      if (fieldset.dataset.wrapupConnected === "true") return;
      fieldset.dataset.wrapupConnected = "true";
      const checkboxes = () => [
        ...fieldset.querySelectorAll('input[name="attendee_account_ids"]'),
      ];
      fieldset.querySelector("[data-wrapup-select-all]")?.addEventListener("click", () => {
        checkboxes().forEach((checkbox) => { checkbox.checked = true; });
      });
      fieldset.querySelector("[data-wrapup-clear-all]")?.addEventListener("click", () => {
        checkboxes().forEach((checkbox) => { checkbox.checked = false; });
      });
      fieldset.querySelector("[data-wrapup-select-suggested]")?.addEventListener("click", () => {
        checkboxes().forEach((checkbox) => {
          checkbox.checked = checkbox.dataset.suggested === "true";
        });
      });
    });
  };

  connect();
  document.addEventListener("admin:panel-updated", (event) => connect(event.detail?.panel || document));
})();
