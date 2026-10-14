import json

from django import forms


class JSONTextareaField(forms.CharField):
    def to_python(self, value):
        raw = super().to_python(value)
        if raw in ("", None):
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError(f"Невалидный JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise forms.ValidationError("Ожидается JSON-объект (словарь).")
        return parsed


class ItemSearchForm(forms.Form):
    q = forms.CharField(label="Поиск", required=False)
    category_id = forms.IntegerField(label="Категория ID", required=False, min_value=1)
    filter_key = forms.CharField(label="Ключ фильтра", required=False)
    filter_value = forms.CharField(label="Значение фильтра", required=False)
    filter_min = forms.FloatField(label="Минимум фильтра", required=False)
    filter_max = forms.FloatField(label="Максимум фильтра", required=False)
    filters_json = forms.CharField(label="Выбранные фильтры", required=False)
    sort = forms.ChoiceField(
        label="Сортировка",
        required=False,
        choices=[
            ("name_asc", "Название ↑"),
            ("name_desc", "Название ↓"),
            ("price_asc", "Цена ↑"),
            ("price_desc", "Цена ↓"),
        ],
        initial="name_asc",
    )
    page = forms.IntegerField(label="Страница", min_value=1, initial=1)
    limit = forms.IntegerField(label="Лимит", min_value=1, max_value=100, initial=100)


class AddItemForm(forms.Form):
    name = forms.CharField(label="Название", max_length=255)
    sku = forms.CharField(label="SKU", max_length=128, required=False)
    category_id = forms.IntegerField(
        label="ID категории",
        min_value=1,
        help_text="Числовой ID из дерева категорий (не slug).",
    )
    description = forms.CharField(label="Описание", required=False, widget=forms.Textarea)
    filters = JSONTextareaField(
        label="Свойства (JSON)",
        required=False,
        widget=forms.Textarea(attrs={"rows": 6, "placeholder": '{"diameter": 100, "airflow": 130}'}),
        help_text='Объект JSON, например {"diameter": 100}. Пусто = без свойств.',
    )
    color = forms.CharField(label="Цвет", required=False)
    material = forms.CharField(label="Материал", required=False)
    weight = forms.FloatField(label="Вес", required=False)
    height = forms.IntegerField(label="Высота", required=False)
    width = forms.IntegerField(label="Ширина", required=False)
    length = forms.IntegerField(label="Длина", required=False)
    price = forms.IntegerField(label="Цена (копейки)", min_value=0)


class EditItemForm(forms.Form):
    item_id = forms.IntegerField(
        label="ID товара",
        min_value=1,
        help_text="Числовой id из списка товаров. Можно открыть форму ссылкой ?item_id=…",
    )
    name = forms.CharField(label="Название", max_length=255, required=False)
    sku = forms.CharField(label="SKU", max_length=128, required=False)
    category_slug = forms.CharField(label="Slug категории", required=False)
    description = forms.CharField(label="Описание", required=False, widget=forms.Textarea)
    filters = JSONTextareaField(
        label="Свойства (JSON)",
        required=False,
        widget=forms.Textarea(attrs={"rows": 6}),
    )
    color = forms.CharField(label="Цвет", required=False)
    material = forms.CharField(label="Материал", required=False)
    weight = forms.FloatField(label="Вес", required=False)
    height = forms.IntegerField(label="Высота", required=False)
    width = forms.IntegerField(label="Ширина", required=False)
    length = forms.IntegerField(label="Длина", required=False)
    price = forms.IntegerField(label="Цена (копейки)", min_value=0, required=False)


class SuggestFilterForm(forms.Form):
    category_slug = forms.CharField(
        label="Slug категории",
        help_text="Например: axial_fans",
    )
    filter_key = forms.CharField(
        label="Ключ фильтра",
        help_text="Латиница/snake_case, например airflow_noise",
    )
    filter_type = forms.ChoiceField(
        label="Тип",
        choices=[
            ("number", "number"),
            ("string", "string"),
            ("boolean", "boolean"),
            ("enum", "enum"),
        ],
    )
    filter_label = forms.CharField(label="Название фильтра")
    suggested_values = forms.CharField(
        label="Предложенные значения (JSON массив)",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4, "placeholder": '["100", "125", "150"]'}),
        help_text="Для enum — JSON-массив значений. Можно оставить пустым.",
    )

    def clean_suggested_values(self):
        raw = self.cleaned_data["suggested_values"]
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError(f"Невалидный JSON: {exc}") from exc
        if not isinstance(parsed, list):
            raise forms.ValidationError("Ожидается JSON-массив.")
        return parsed
