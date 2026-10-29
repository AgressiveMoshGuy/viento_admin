/* Вкладки в форме товара.
 *
 * Без скрипта все разделы показываются подряд, поэтому форма работает и так.
 * Со скриптом показываем по одному разделу. Вкладку с ошибкой сервер открывает сам.
 * Если браузер отказывается отправлять форму из-за незаполненного поля на скрытой вкладке,
 * открываем эту вкладку, чтобы поле было видно.
 */
(function () {
  const form = document.querySelector("[data-tabbed-form]");
  if (!form) return;

  const tabs = Array.from(form.querySelectorAll("[data-tab]"));
  const panels = Array.from(form.querySelectorAll("[data-panel]"));
  if (!tabs.length || !panels.length) return;

  form.classList.add("catalog-tabbed");

  function show(id, focusTab) {
    tabs.forEach((tab) => {
      const on = tab.dataset.tab === id;
      tab.setAttribute("aria-selected", on ? "true" : "false");
      tab.tabIndex = on ? 0 : -1;
      if (on && focusTab) tab.focus();
    });
    panels.forEach((panel) => {
      if (panel.dataset.panel === id) panel.removeAttribute("data-inactive");
      else panel.setAttribute("data-inactive", "");
    });
  }

  const initial = tabs.find((tab) => tab.getAttribute("aria-selected") === "true") || tabs[0];
  show(initial.dataset.tab, false);

  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => show(tab.dataset.tab, false));
    tab.addEventListener("keydown", (event) => {
      let next = null;
      if (event.key === "ArrowRight") next = tabs[(index + 1) % tabs.length];
      if (event.key === "ArrowLeft") next = tabs[(index - 1 + tabs.length) % tabs.length];
      if (next) {
        event.preventDefault();
        show(next.dataset.tab, true);
      }
    });
  });

  // Поле с ошибкой проверки браузера лежит на скрытой вкладке: показываем её.
  form.addEventListener(
    "invalid",
    (event) => {
      const panel = event.target.closest && event.target.closest("[data-panel]");
      if (panel && panel.hasAttribute("data-inactive")) show(panel.dataset.panel, false);
    },
    true
  );
})();
