from django import template

from fever import dosing
from fever.models import relation_color

register = template.Library()


@register.filter
def level(value):
    return dosing.level(value)


@register.filter
def level_text(value):
    return dosing.LEVEL_TEXT[dosing.level(value)]


@register.filter
def relcolor(relation):
    return relation_color(relation)


@register.filter
def drug_cls(drug_key):
    return dosing.DRUGS[drug_key].cls


@register.filter
def drug_mg(record):
    return round(record.amount_ml * dosing.DRUGS[record.drug].mg_per_ml)


@register.filter
def f1(value):
    return "" if value is None else f"{float(value):.1f}"


@register.inclusion_tag("partials/icon.html")
def icon(name, size=20, stroke=2):
    return {"name": name, "size": size, "stroke": stroke}


@register.inclusion_tag("partials/who.html")
def who(relation):
    return {"relation": relation, "color": relation_color(relation)}


@register.filter
def eun(name):
    """이름 받침에 맞춰 '은/는'을 붙인다."""
    code = ord(name[-1]) - 0xAC00
    return name + ("은" if 0 <= code < 11172 and code % 28 else "는")
