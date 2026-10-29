/* Состояния ожидания в разделе каталога.
 *
 * Страницы строятся на сервере и могут грузиться секунды (список собирает данные из Go API).
 * Пока браузер ждёт ответ, он показывает старую страницу, и кажется, что клик не сработал.
 * Поэтому после клика по ссылке или отправки поиска мы через 150 мс заменяем рабочую область
 * на «скелет» (серые блоки по форме будущего экрана).
 * В формах создания и правки скелета нет: там блокируем кнопку, чтобы не отправить дважды.
 */
(function () {
  const page = document.querySelector(".catalog-page");
  if (!page) return;

  const DELAY_MS = 150; // быстрые ответы не мигают скелетом
  let timer = null;
  let state = null; // { skeleton, hidden: [элементы] }
  const locked = []; // заблокированные кнопки отправки

  function bar(width, modifier) {
    const node = document.createElement("span");
    node.className = "catalog-sk" + (modifier ? " catalog-sk--" + modifier : "");
    if (width) node.style.width = width;
    return node;
  }

  function stack(children) {
    const node = document.createElement("div");
    node.className = "catalog-skeleton__stack";
    children.forEach((child) => node.appendChild(child));
    return node;
  }

  function panel(children) {
    const node = document.createElement("div");
    node.className = "catalog-panel";
    node.appendChild(stack(children));
    return node;
  }

  function wrapper(modifier) {
    const node = document.createElement("div");
    node.className = "catalog-skeleton catalog-skeleton--" + modifier;
    node.setAttribute("role", "status");
    node.setAttribute("aria-live", "polite");
    const label = document.createElement("span");
    label.className = "catalog-visually-hidden";
    label.textContent = "Загрузка…";
    node.appendChild(label);
    return node;
  }

  function listSkeleton() {
    const root = wrapper("list");
    const grid = document.createElement("div");
    grid.className = "catalog-skeleton__grid";

    const tree = panel([bar("60%", "title"), bar("90%"), bar("75%"), bar("85%"), bar("55%"), bar("80%")]);

    const rows = [];
    rows.push(bar("40%", "title"));
    for (let i = 0; i < 8; i += 1) {
      const row = document.createElement("div");
      row.className = "catalog-skeleton__row";
      ["40%", "80%", "95%", "55%", "65%"].forEach((w) => row.appendChild(bar(w)));
      rows.push(row);
    }
    const table = panel(rows);

    const filters = panel([bar("55%", "title"), bar("85%"), bar("70%"), bar("90%"), bar("60%"), bar("80%"), bar("65%")]);

    grid.append(tree, table, filters);
    root.appendChild(grid);
    return root;
  }

  function panelSkeleton() {
    const root = wrapper("panel");
    root.appendChild(
      panel([bar("35%", "title"), bar("90%"), bar("75%"), bar("85%"), bar("50%", "field"), bar("100%", "field"), bar("100%", "field"), bar("70%", "field")])
    );
    return root;
  }

  // kind: "list" для списка товаров, "panel" для остальных экранов. Вид выбираем по тому,
  // куда идёт переход, а не по текущей странице.
  function show(kind) {
    if (state) return;
    const layout = page.querySelector(".catalog-layout");
    const target = layout || page.querySelector(".catalog-panel");
    if (!target) return;
    const skeleton = kind === "list" ? listSkeleton() : panelSkeleton();
    target.before(skeleton);
    const hidden = [target];
    const meta = page.querySelector(".catalog-meta");
    if (layout && meta) hidden.push(meta);
    hidden.forEach((node) => {
      node.hidden = true;
    });
    page.setAttribute("aria-busy", "true");
    state = { skeleton, hidden };
  }

  function kindFor(pathname) {
    return pathname === "/catalog/" ? "list" : "panel";
  }

  function schedule(kind) {
    if (timer || state) return;
    timer = setTimeout(() => {
      timer = null;
      show(kind);
    }, DELAY_MS);
  }

  function lockSubmit(form) {
    const button = form.querySelector('button[type="submit"]');
    if (!button || button.disabled) return;
    // Блокируем после отправки, иначе браузер может не передать форму.
    setTimeout(() => {
      locked.push({ button, label: button.textContent });
      button.disabled = true;
      button.textContent = "Сохраняем…";
    }, 0);
  }

  function reset() {
    clearTimeout(timer);
    timer = null;
    if (state) {
      state.skeleton.remove();
      state.hidden.forEach((node) => {
        node.hidden = false;
      });
      page.removeAttribute("aria-busy");
      state = null;
    }
    while (locked.length) {
      const item = locked.pop();
      item.button.disabled = false;
      item.button.textContent = item.label;
    }
  }

  document.addEventListener("click", (event) => {
    const link = event.target.closest && event.target.closest("a[href]");
    if (!link || !page.contains(link)) return;
    if (event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if (link.target && link.target !== "_self") return;
    if (link.hasAttribute("download")) return;
    const url = new URL(link.href, window.location.href);
    if (url.origin !== window.location.origin) return;
    // Переход по якорю внутри этой же страницы ничего не грузит.
    if (url.hash && url.pathname === window.location.pathname && url.search === window.location.search) return;
    schedule(kindFor(url.pathname));
  });

  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || !page.contains(form)) return;
    if (event.defaultPrevented) return;
    if (form.matches(".catalog-entity-form")) {
      lockSubmit(form);
      return;
    }
    schedule(kindFor(new URL(form.action || window.location.href, window.location.href).pathname));
  });

  // Возврат кнопкой «Назад»: страница берётся из кэша вместе со скелетом, его нужно убрать.
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) reset();
  });
})();
