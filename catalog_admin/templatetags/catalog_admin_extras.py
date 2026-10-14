import json

from django import template


register = template.Library()


@register.filter
def pretty_json(value):
    try:
        return json.dumps(value, ensure_ascii=False, indent=2)
    except TypeError:
        return value


@register.filter
def get_item(mapping, key):
    if isinstance(mapping, dict):
        return mapping.get(key, "")
    return ""
