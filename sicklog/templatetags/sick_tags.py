from django import template
from django.utils import timezone

from sicklog import dosing
from sicklog.models import relation_color

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


@register.filter
def ga(name):
    """'이/가' 조사만 돌려준다."""
    code = ord(name[-1]) - 0xAC00
    return "이" if 0 <= code < 11172 and code % 28 else "가"


@register.filter
def is_complication(symptom):
    from sicklog.models import COMPLICATIONS

    return symptom in COMPLICATIONS


@register.filter
def half(moment):
    """'2026.05.12 오후' 형식."""
    if not moment:
        return ""
    local = timezone.localtime(moment)
    return f"{local:%Y.%m.%d} {'오후' if local.hour >= 12 else '오전'}"


@register.filter
def when(moment):
    """'오늘 14:32', '어제 21:05', '2026.10.16 09:10'."""
    if not moment:
        return ""
    local, today = timezone.localtime(moment), timezone.localdate()
    days = (today - local.date()).days
    day = "오늘" if days == 0 else "어제" if days == 1 else f"{local:%Y.%m.%d}"
    return f"{day} {local:%H:%M}"


@register.filter
def dow(moment):
    """한 글자 요일: '수'. 날짜에도 시각에도 쓴다."""
    if not moment:
        return ""
    if hasattr(moment, "hour") and timezone.is_aware(moment):
        moment = timezone.localtime(moment)
    return "월화수목금토일"[moment.weekday()]
