/* Редактор характеристик товара.
 *
 * Вместо ручного JSON менеджер видит ряды «название: поле нужного типа». Настоящим хранилищем
 * остаётся то же текстовое поле «Свойства» (оно спрятано под «Показать как JSON»): редактор
 * лишь читает и пишет его. Поэтому сервер ничего не знает о редакторе, а если скрипт не загрузится,
 * форма работает как раньше.
 *
 * Типы (число, да/нет, выбор из значений, текст) сервер определил по данным каталога.
 * Добавить можно только характеристики из описаний фильтров: другие Go всё равно отклонит.
 * Значения сложнее строки или числа (вложенные) показываем только для чтения и сохраняем как есть.
 */
(function () {
  const textarea = document.getElementById("id_filters");
  const schemaNode = document.getElementById("specs-schema");
  if (!textarea || !schemaNode) return;

  let schema;
  let itemsById = {};
  try {
    schema = JSON.parse(schemaNode.textContent);
    const itemsNode = document.getElementById("specs-items");
    if (itemsNode) itemsById = JSON.parse(itemsNode.textContent) || {};
  } catch (_err) {
    return; // нет данных для редактора: остаётся обычное поле
  }
  const specByKey = new Map(schema.map((spec) => [spec.key, spec]));

  const field = textarea.closest(".catalog-field");
  if (!field) return;

  // ---- каркас -------------------------------------------------------------
  const editor = document.createElement("div");
  editor.className = "catalog-specs";

  const rows = document.createElement("div");
  rows.className = "catalog-specs__rows";
  rows.setAttribute("role", "list");

  const addBar = document.createElement("div");
  addBar.className = "catalog-specs__add";
  const addSelect = document.createElement("select");
  addSelect.setAttribute("aria-label", "Какую характеристику добавить");
  const addButton = document.createElement("button");
  addButton.type = "button";
  addButton.textContent = "Добавить характеристику";
  addBar.append(addSelect, addButton);

  const status = document.createElement("p");
  status.className = "catalog-specs__status";
  status.setAttribute("role", "status");

  const details = document.createElement("details");
  details.className = "catalog-specs__json";
  const summary = document.createElement("summary");
  summary.textContent = "Показать как JSON";
  details.appendChild(summary);

  const help = field.querySelector(".catalog-help");
  if (help) details.appendChild(help); // подсказка про фигурные скобки нужна только здесь
  details.appendChild(textarea);

  editor.append(rows, addBar, status);
  const label = field.querySelector("label");
  if (label) label.after(editor, details);
  else field.prepend(editor, details);

  // ---- состояние ----------------------------------------------------------
  let entries = []; // [{ key, value }]
  let dirty = false;
  let counter = 0;

  function parseTextarea() {
    const raw = textarea.value.trim();
    if (!raw) return [];
    let parsed;
    try {
      parsed = JSON.parse(raw);
    } catch (_err) {
      return null;
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null;
    return Object.entries(parsed).map(([key, value]) => ({ key, value }));
  }

  function isEmpty(value) {
    return value === null || value === undefined || value === "";
  }

  function serialize() {
    const result = {};
    entries.forEach((entry) => {
      if (!isEmpty(entry.value)) result[entry.key] = entry.value;
    });
    return Object.keys(result).length ? JSON.stringify(result, null, 2) : "";
  }

  function commit() {
    dirty = true;
    textarea.value = serialize();
    status.textContent = "";
  }

  // Тип ряда: берём тип характеристики, но не навязываем его значению, которое ему не подходит.
  function effectiveType(entry) {
    const spec = specByKey.get(entry.key);
    const value = entry.value;
    if (value !== null && typeof value === "object") return "raw";
    const declared = spec ? spec.type : "text";
    if (declared === "raw") return "raw";
    if (isEmpty(value)) return declared;
    if (declared === "number" && typeof value !== "number") return "text";
    if (declared === "bool" && typeof value !== "boolean") return "text";
    if (declared === "enum" && typeof value !== "string") return "text";
    return declared;
  }

  function control(entry, id) {
    const spec = specByKey.get(entry.key);
    const type = effectiveType(entry);
    let input;

    if (type === "bool") {
      input = document.createElement("select");
      [["", "Не указано"], ["true", "Да"], ["false", "Нет"]].forEach(([value, text]) => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = text;
        input.appendChild(option);
      });
      input.value = typeof entry.value === "boolean" ? String(entry.value) : "";
      input.addEventListener("change", () => {
        entry.value = input.value === "" ? null : input.value === "true";
        commit();
      });
    } else if (type === "number") {
      input = document.createElement("input");
      input.type = "number";
      input.step = "any";
      input.inputMode = "decimal";
      input.value = isEmpty(entry.value) ? "" : String(entry.value);
      input.addEventListener("input", () => {
        entry.value = input.value === "" ? null : Number(input.value);
        commit();
      });
    } else if (type === "raw") {
      input = document.createElement("input");
      input.type = "text";
      input.readOnly = true;
      input.value = JSON.stringify(entry.value);
      input.title = "Сложное значение. Изменить его можно только в JSON ниже.";
    } else {
      input = document.createElement("input");
      input.type = "text";
      input.value = isEmpty(entry.value) ? "" : String(entry.value);
      if (type === "enum" && spec && Array.isArray(spec.options)) {
        const list = document.createElement("datalist");
        list.id = id + "-options";
        spec.options.forEach((optionValue) => {
          const option = document.createElement("option");
          option.value = optionValue;
          list.appendChild(option);
        });
        input.setAttribute("list", list.id);
        input.dataset.datalist = "1";
        input._datalist = list;
      }
      input.addEventListener("input", () => {
        entry.value = input.value;
        commit();
      });
    }
    input.id = id;
    return input;
  }

  function render() {
    rows.textContent = "";
    entries.forEach((entry) => {
      const spec = specByKey.get(entry.key);
      const id = "spec-" + counter++;

      const row = document.createElement("div");
      row.className = "catalog-spec-row";
      row.setAttribute("role", "listitem");

      const title = document.createElement("label");
      title.htmlFor = id;
      title.textContent = spec ? spec.label : entry.key;

      const input = control(entry, id);

      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "catalog-spec-row__remove";
      remove.textContent = "Убрать";
      remove.setAttribute("aria-label", "Убрать характеристику «" + title.textContent + "»");
      remove.addEventListener("click", () => {
        entries = entries.filter((other) => other !== entry);
        commit();
        render();
      });

      row.append(title, input, remove);
      if (input._datalist) row.appendChild(input._datalist);
      rows.appendChild(row);
    });

    if (!entries.length) {
      const empty = document.createElement("p");
      empty.className = "catalog-specs__empty";
      empty.textContent = "Характеристик пока нет. Добавьте их кнопкой ниже.";
      rows.appendChild(empty);
    }

    // Добавить можно только то, чего в карточке ещё нет.
    const used = new Set(entries.map((entry) => entry.key));
    addSelect.textContent = "";
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = "Выберите характеристику…";
    addSelect.appendChild(placeholder);
    schema
      .filter((spec) => !used.has(spec.key))
      .forEach((spec) => {
        const option = document.createElement("option");
        option.value = spec.key;
        option.textContent = spec.label;
        addSelect.appendChild(option);
      });
    addBar.hidden = addSelect.options.length <= 1;
  }

  function load(nextEntries) {
    entries = nextEntries;
    render();
  }

  addButton.addEventListener("click", () => {
    const key = addSelect.value;
    if (!key) {
      status.textContent = "Сначала выберите характеристику в списке.";
      return;
    }
    entries.push({ key, value: null });
    render();
    const rowsInputs = rows.querySelectorAll("input, select");
    const last = rowsInputs[rowsInputs.length - 1];
    if (last) last.focus();
  });

  // Ручная правка JSON обновляет ряды. Если JSON неверный, ряды не трогаем: сервер скажет, где ошибка.
  textarea.addEventListener("change", () => {
    const parsed = parseTextarea();
    if (parsed === null) {
      status.textContent = "JSON записан неверно, ряды выше не обновились.";
      return;
    }
    status.textContent = "";
    load(parsed);
  });

  // В форме правки: выбрали товар, подставляем его текущие характеристики.
  const idInput = document.getElementById("id_item_id");
  function fillFromItem() {
    if (!idInput) return;
    const known = itemsById[String(idInput.value).trim()];
    if (!known) return;
    if (dirty && !window.confirm("Заменить характеристики на те, что сейчас у этого товара?")) return;
    textarea.value = JSON.stringify(known, null, 2);
    dirty = false;
    load(parseTextarea() || []);
  }
  if (idInput) idInput.addEventListener("change", fillFromItem);

  const initial = parseTextarea();
  if (initial === null) {
    status.textContent = "Свойства записаны не как JSON. Исправьте их в поле ниже.";
    details.open = true;
  }
  load(initial || []);
})();
