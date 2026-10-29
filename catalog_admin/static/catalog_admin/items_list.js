(function () {
  const queryInput = document.getElementById("id_q");
  // Курсор сразу в поиске: сканер штрихкодов «печатает» цифры и нажимает Enter, мышь не нужна.
  // Текст выделяется, чтобы следующий скан заменил предыдущий.
  if (queryInput) {
    queryInput.focus({ preventScroll: true });
    queryInput.select();
  }
  const filterKeyInput = document.getElementById("id_filter_key_select");
  const filterValueInput = document.getElementById("id_filter_value_select");
  const filterMinInput = document.getElementById("id_filter_min");
  const filterMaxInput = document.getElementById("id_filter_max");
  const filtersJsonInput = document.getElementById("id_filters_json");
  const categoryInput = document.getElementById("id_category_id_select");
  const pageInput = document.getElementById("id_page_hidden");
  const applyBtn = document.getElementById("apply_filters_btn");
  const filterValuesByKeyNode = document.getElementById("filter-values-by-key");
  let filterValuesByKey = {};

  if (filterValuesByKeyNode) {
    try {
      filterValuesByKey = JSON.parse(filterValuesByKeyNode.textContent);
    } catch (_err) {
      filterValuesByKey = {};
    }
  }

  function readSelectedFilters() {
    if (!filtersJsonInput || !filtersJsonInput.value) return [];
    try {
      const parsed = JSON.parse(filtersJsonInput.value);
      return Array.isArray(parsed) ? parsed.filter((entry) => entry && entry.key) : [];
    } catch (_err) {
      return [];
    }
  }

  function writeSelectedFilters(filters) {
    if (filtersJsonInput) {
      filtersJsonInput.value = JSON.stringify(filters);
    }
    if (filterKeyInput) filterKeyInput.value = "";
    if (filterValueInput) filterValueInput.value = "";
    clearRangeInputs();
  }

  function sameValueFilter(filter, key, value) {
    return filter.key === key && Object.prototype.hasOwnProperty.call(filter, "value") && String(filter.value) === String(value);
  }

  function toggleValueFilter(key, value) {
    const filters = readSelectedFilters();
    const exists = filters.some((filter) => sameValueFilter(filter, key, value));
    const nextFilters = exists
      ? filters.filter((filter) => !sameValueFilter(filter, key, value))
      : filters.filter((filter) => filter.key !== key).concat([{ key, value }]);
    writeSelectedFilters(nextFilters);
  }

  function setRangeFilter(key, minValue, maxValue) {
    const filters = readSelectedFilters().filter((filter) => filter.key !== key);
    filters.push({ key, min: minValue, max: maxValue });
    writeSelectedFilters(filters);
  }

  const scrollStorageKey = `catalog-admin-scroll:${window.location.pathname}`;

  function restoreScrollPosition() {
    const rawPosition = sessionStorage.getItem(scrollStorageKey);
    if (!rawPosition) return;

    sessionStorage.removeItem(scrollStorageKey);
    try {
      const position = JSON.parse(rawPosition);
      if (typeof position.x === "number" && typeof position.y === "number") {
        requestAnimationFrame(() => {
          window.scrollTo(position.x, position.y);
        });
      }
    } catch (_err) {
      // Ignore broken storage data and keep the browser default scroll.
    }
  }

  function rememberScrollPosition() {
    sessionStorage.setItem(
      scrollStorageKey,
      JSON.stringify({
        x: window.scrollX,
        y: window.scrollY,
      })
    );
  }

  function refillFilterValues(key, selected) {
    if (!filterValueInput) return;
    if (filterValueInput.type === "hidden") {
      filterValueInput.value = selected || "";
      return;
    }

    const values = filterValuesByKey[key] || [];
    filterValueInput.innerHTML = "";
    const emptyOption = document.createElement("option");
    emptyOption.value = "";
    emptyOption.textContent = "-- любое --";
    filterValueInput.appendChild(emptyOption);
    values.forEach((val) => {
      const opt = document.createElement("option");
      opt.value = val;
      opt.textContent = val;
      filterValueInput.appendChild(opt);
    });
    filterValueInput.value = selected || "";
    if (filterValueInput.value !== (selected || "")) {
      filterValueInput.value = "";
    }
  }

  function clearRangeInputs() {
    if (filterMinInput) filterMinInput.value = "";
    if (filterMaxInput) filterMaxInput.value = "";
  }

  function submitSearchForm() {
    rememberScrollPosition();
    const form = applyBtn ? applyBtn.form : null;
    if (form && typeof form.requestSubmit === "function") {
      form.requestSubmit();
      return;
    }
    if (applyBtn) applyBtn.click();
  }

  if (filterKeyInput) {
    filterKeyInput.addEventListener("change", () => {
      clearRangeInputs();
      refillFilterValues(filterKeyInput.value, "");
    });
  }

  if (filterValueInput) {
    filterValueInput.addEventListener("change", clearRangeInputs);
  }

  document.querySelectorAll(".js-filter-value").forEach((el) => {
    el.addEventListener("click", () => {
      const filterKey = el.dataset.filterKey || "";
      const targetValue = el.dataset.filterValue || "";
      toggleValueFilter(filterKey, targetValue);
      if (pageInput) pageInput.value = "1";
      submitSearchForm();
    });
  });

  if (filterKeyInput && filterValueInput) {
    refillFilterValues(filterKeyInput.value, filterValueInput.value);
  }

  const appliedRanges = new Map();

  function formatRangeValue(value) {
    const numberValue = Number(value);
    if (!Number.isFinite(numberValue)) return value;
    return Number.isInteger(numberValue) ? String(numberValue) : String(numberValue);
  }

  function getRangeParts(target) {
    const slider = target.closest(".js-filter-range-min, .js-filter-range-max");
    if (!slider) return null;

    const container = slider.closest(".js-filter-range");
    if (!container) return null;

    const minSlider = container.querySelector(".js-filter-range-min");
    const maxSlider = container.querySelector(".js-filter-range-max");
    const minLabel = container.querySelector(".js-filter-range-min-label");
    const maxLabel = container.querySelector(".js-filter-range-max-label");
    if (!minSlider || !maxSlider) return null;

    return { container, slider, minSlider, maxSlider, minLabel, maxLabel };
  }

  function syncRangeLabels(target) {
    const parts = getRangeParts(target);
    if (!parts) return;

    let minValue = Number(parts.minSlider.value);
    let maxValue = Number(parts.maxSlider.value);

    if (minValue > maxValue) {
      if (parts.slider === parts.minSlider) {
        maxValue = minValue;
        parts.maxSlider.value = String(maxValue);
      } else {
        minValue = maxValue;
        parts.minSlider.value = String(minValue);
      }
    }

    if (parts.minLabel) parts.minLabel.textContent = formatRangeValue(parts.minSlider.value);
    if (parts.maxLabel) parts.maxLabel.textContent = formatRangeValue(parts.maxSlider.value);
  }

  function applyRangeFilter(target) {
    const parts = getRangeParts(target);
    if (!parts) return;

    syncRangeLabels(target);

    const filterKey = parts.container.dataset.filterKey || "";
    const currentRange = `${parts.minSlider.value}:${parts.maxSlider.value}`;
    if (appliedRanges.get(filterKey) === currentRange) return;
    appliedRanges.set(filterKey, currentRange);

    setRangeFilter(filterKey, parts.minSlider.value, parts.maxSlider.value);
    if (pageInput) pageInput.value = "1";
    submitSearchForm();
  }

  document.addEventListener("input", (evt) => {
    syncRangeLabels(evt.target);
  });

  document.addEventListener("change", (evt) => {
    applyRangeFilter(evt.target);
  });

  document.addEventListener("mouseup", (evt) => {
    applyRangeFilter(evt.target);
  });

  document.addEventListener("touchend", (evt) => {
    applyRangeFilter(evt.target);
  });

  document.querySelectorAll(".js-filter-range-min, .js-filter-range-max").forEach((slider) => {
    syncRangeLabels(slider);
  });

  restoreScrollPosition();

  document.querySelectorAll(".js-category-node").forEach((el) => {
    el.addEventListener("click", () => {
      if (!categoryInput) return;
      // При смене категории сбрасываем предыдущие фильтры текущей выборки.
      if (queryInput) queryInput.value = "";
      if (filterKeyInput) {
        filterKeyInput.value = "";
      }
      writeSelectedFilters([]);
      if (filterValueInput) {
        refillFilterValues("", "");
        filterValueInput.value = "";
      }
      const categoryId = el.dataset.categoryId || "";
      categoryInput.value = categoryId;
      if (pageInput) pageInput.value = "1";
      submitSearchForm();
    });
  });

  document.querySelectorAll(".js-category-toggle").forEach((toggleBtn) => {
    toggleBtn.addEventListener("click", (evt) => {
      evt.stopPropagation();
      const container = toggleBtn.closest("li");
      if (!container) return;
      const children = container.querySelector(":scope > ul.category-children");
      if (!children) return;
      const nextOpen = children.hasAttribute("hidden");
      if (nextOpen) {
        children.removeAttribute("hidden");
        toggleBtn.setAttribute("aria-expanded", "true");
        toggleBtn.textContent = "▾";
      } else {
        children.setAttribute("hidden", "hidden");
        toggleBtn.setAttribute("aria-expanded", "false");
        toggleBtn.textContent = "▸";
      }
    });
  });

  function expandCategoryPathById(categoryId) {
    if (!categoryId) return;
    const node = document.querySelector(`.js-category-node[data-category-id="${categoryId}"]`);
    if (!node) return;

    let li = node.closest("li");
    while (li) {
      const toggle = li.querySelector(":scope > div .js-category-toggle");
      const children = li.querySelector(":scope > ul.category-children");
      if (toggle && children) {
        children.removeAttribute("hidden");
        toggle.setAttribute("aria-expanded", "true");
        toggle.textContent = "▾";
      }
      const parentChildren = li.parentElement;
      if (!parentChildren || !parentChildren.classList.contains("category-children")) {
        break;
      }
      li = parentChildren.closest("li");
    }
  }

  if (categoryInput && categoryInput.value) {
    expandCategoryPathById(categoryInput.value);
  }

  // Настройки таблицы (какие колонки скрыты, сжата ли она) запоминаются в браузере:
  // каждый клик по фильтру перезагружает страницу, и раньше они сбрасывались.
  const TABLE_PREFS_KEY = "catalog_admin_table_prefs";

  function readTablePrefs() {
    try {
      const value = JSON.parse(localStorage.getItem(TABLE_PREFS_KEY) || "{}");
      return value && typeof value === "object" ? value : {};
    } catch (_err) {
      return {};
    }
  }

  // Колонки-характеристики нумеруются по позиции, а позиция меняется от выдачи к выдаче,
  // поэтому для них ключом служит подпись.
  function columnKey(checkbox) {
    const colId = checkbox.dataset.colId || "";
    if (!colId.startsWith("filter_")) return colId;
    const label = checkbox.closest("label");
    return "label:" + (label ? label.textContent.trim() : colId);
  }

  function saveTablePrefs() {
    const table = document.querySelector(".catalog-items-table");
    const photoCheckbox = document.querySelector('.js-col-visibility[data-col-id="photo"]');
    const hidden = Array.from(document.querySelectorAll(".js-col-visibility"))
      .filter((checkbox) => !checkbox.checked)
      .map(columnKey);
    try {
      localStorage.setItem(
        TABLE_PREFS_KEY,
        JSON.stringify({
          hidden,
          // Колонка «Фото» по умолчанию скрыта: пока фото нет, там одни заглушки.
          photo: photoCheckbox ? photoCheckbox.checked : false,
          expanded: table ? table.classList.contains("catalog-items-table--expanded") : true,
        })
      );
    } catch (_err) {
      /* без хранилища всё работает как раньше */
    }
  }

  const savedTablePrefs = readTablePrefs();

  const tableExpandBtn = document.getElementById("toggle_table_expand_btn");
  const itemsTable = document.querySelector(".catalog-items-table");
  if (tableExpandBtn && itemsTable) {
    const syncExpandButtonText = () => {
      const expanded = itemsTable.classList.contains("catalog-items-table--expanded");
      tableExpandBtn.textContent = expanded ? "Сжать колонки" : "Расширить колонки";
    };
    if (typeof savedTablePrefs.expanded === "boolean") {
      itemsTable.classList.toggle("catalog-items-table--expanded", savedTablePrefs.expanded);
    }
    syncExpandButtonText();
    tableExpandBtn.addEventListener("click", () => {
      const expanded = itemsTable.classList.toggle("catalog-items-table--expanded");
      tableExpandBtn.textContent = expanded ? "Сжать колонки" : "Расширить колонки";
      saveTablePrefs();
    });
  }

  const columnPickerBtn = document.getElementById("toggle_column_picker_btn");
  const columnPickerPanel = document.getElementById("column_picker_panel");
  if (columnPickerBtn && columnPickerPanel) {
    columnPickerBtn.addEventListener("click", () => {
      const optionalCheckboxes = Array.from(
        document.querySelectorAll('.js-col-visibility[data-col-id^="filter_"], .js-col-visibility[data-col-id="description"]')
      );
      const allOptionalVisible = optionalCheckboxes.every((checkbox) => checkbox.checked);
      const nextVisible = !allOptionalVisible;

      optionalCheckboxes.forEach((checkbox) => {
        checkbox.checked = nextVisible;
        const colId = checkbox.dataset.colId || "";
        setColumnVisibility(itemsTable, colId, nextVisible);
      });

      columnPickerPanel.removeAttribute("hidden");
      columnPickerBtn.textContent = nextVisible ? "Скрыть колонки" : "Показать колонки";
      saveTablePrefs();
    });
  }

  function setColumnVisibility(table, colId, visible) {
    if (!table || !colId) return;
    const selector = `[data-col-id="${colId}"]`;
    table.querySelectorAll(selector).forEach((cell) => {
      cell.classList.toggle("catalog-col-hidden", !visible);
    });
  }

  if (itemsTable) {
    document.querySelectorAll(".js-col-visibility").forEach((checkbox) => {
      const colId = checkbox.dataset.colId || "";
      if (colId === "photo") {
        checkbox.checked = savedTablePrefs.photo === true;
      } else if (Array.isArray(savedTablePrefs.hidden)) {
        checkbox.checked = !savedTablePrefs.hidden.includes(columnKey(checkbox));
      }
      setColumnVisibility(itemsTable, colId, checkbox.checked);
      checkbox.addEventListener("change", () => {
        setColumnVisibility(itemsTable, colId, checkbox.checked);
        saveTablePrefs();
      });
    });
    if (columnPickerBtn) {
      const optional = Array.from(
        document.querySelectorAll('.js-col-visibility[data-col-id^="filter_"], .js-col-visibility[data-col-id="description"]')
      );
      if (optional.length && !optional.some((checkbox) => checkbox.checked)) {
        columnPickerBtn.textContent = "Показать колонки";
      }
    }
  }

  function initColumnResize(table) {
    if (!table) return;
    const minWidth = 120;
    const resizers = table.querySelectorAll(".js-col-resizer");
    resizers.forEach((resizer) => {
      resizer.addEventListener("mousedown", (evt) => {
        evt.preventDefault();
        evt.stopPropagation();
        const header = resizer.closest("th");
        if (!header) return;
        const colIndex = header.cellIndex;
        const startX = evt.clientX;
        const startWidth = header.getBoundingClientRect().width;
        const startTableWidth = table.getBoundingClientRect().width;

        const onMove = (moveEvt) => {
          const deltaX = moveEvt.clientX - startX;
          const nextWidth = Math.max(minWidth, startWidth + deltaX);
          table.querySelectorAll("tr").forEach((row) => {
            const cell = row.children[colIndex];
            if (cell) {
              cell.style.width = `${nextWidth}px`;
              cell.style.minWidth = `${nextWidth}px`;
            }
          });

          // Расширяем таблицу вправо от левого края, не сжимая соседние колонки.
          const nextTableWidth = Math.max(startTableWidth, startTableWidth + deltaX);
          table.style.width = `${nextTableWidth}px`;
          table.style.minWidth = `${nextTableWidth}px`;
        };

        const onUp = () => {
          document.removeEventListener("mousemove", onMove);
          document.removeEventListener("mouseup", onUp);
        };

        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
      });
    });
  }

  initColumnResize(itemsTable);
})();
