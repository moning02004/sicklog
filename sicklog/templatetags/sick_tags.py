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


def _local(moment):
    """날짜는 그대로, 시각은 현지 시각으로 바꾼다."""
    if hasattr(moment, "hour") and timezone.is_aware(moment):
        return timezone.localtime(moment)
    return moment


@register.filter
def day(moment):
    """글로 읽는 날짜: 올해면 '10월 19일', 다른 해면 '2025년 12월 30일'."""
    if not moment:
        return ""
    d = _local(moment)
    text = f"{d.month}월 {d.day}일"
    return text if d.year == timezone.localdate().year else f"{d.year}년 {text}"


@register.filter
def md(moment):
    """좁은 칸에 쓰는 날짜: 올해면 '10.19', 다른 해면 '2025.12.30'."""
    if not moment:
        return ""
    d = _local(moment)
    return f"{d.month}.{d.day}" if d.year == timezone.localdate().year else f"{d.year}.{d.month}.{d.day}"


@register.filter
def period(start, end):
    """'10.19 ~ 10.21'. 한쪽이라도 올해가 아니면 둘 다 연도를 붙인다."""
    a, b = _local(start), _local(end)
    if a == b:  # 하루짜리는 한 번만
        return md(a)
    this = timezone.localdate().year
    if a.year == b.year == this:
        return f"{md(a)} ~ {md(b)}"
    return f"{a.year}.{a.month}.{a.day} ~ {b.year}.{b.month}.{b.day}"


@register.filter
def dt(moment):
    """날짜와 시각: '10월 19일 14:32'."""
    if not moment:
        return ""
    return f"{day(moment)} {_local(moment):%H:%M}"


@register.filter
def half(moment):
    """'10월 19일 오후'. 다른 해면 연도를 붙인다."""
    if not moment:
        return ""
    local = timezone.localtime(moment)
    return f"{day(local)} {'오후' if local.hour >= 12 else '오전'}"


@register.filter
def when(moment):
    """'오늘 14:32', '어제 21:05', '10.16 09:10'."""
    if not moment:
        return ""
    local, today = timezone.localtime(moment), timezone.localdate()
    days = (today - local.date()).days
    label = "오늘" if days == 0 else "어제" if days == 1 else md(local)
    return f"{label} {local:%H:%M}"


@register.filter
def dow(moment):
    """한 글자 요일: '수'. 날짜에도 시각에도 쓴다."""
    if not moment:
        return ""
    return "월화수목금토일"[_local(moment).weekday()]
