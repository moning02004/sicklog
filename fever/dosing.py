"""해열제 용량, 교차복용 시간, 아픈 기간 계산.

용량은 흔히 쓰는 제품 라벨 기준이며 참고용이다. 화면에는 항상 제품 라벨을 확인하라고 안내한다.
"""
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

FEVER = Decimal("38.0")
MILD_FEVER = Decimal("37.5")
CROSS_GAP = timedelta(hours=2)
RECOVERY_GAP = timedelta(hours=72)


@dataclass(frozen=True)
class Drug:
    key: str
    name: str
    ingredient: str
    cls: str
    mg_per_ml: int
    mg_per_kg_min: int
    mg_per_kg_max: int
    product: str

    @property
    def initial(self):
        return self.name[:1]


@dataclass(frozen=True)
class DrugClass:
    key: str
    label: str
    drugs: str
    gap: timedelta
    max_per_day: int


DRUGS = {
    "tylenol": Drug("tylenol", "타이레놀", "아세트아미노펜", "acet", 32, 10, 15, "어린이타이레놀 현탁액 32mg/mL"),
    "maxibupen": Drug("maxibupen", "맥시부펜", "덱시부프로펜", "ibu", 12, 5, 7, "맥시부펜 시럽 12mg/mL"),
    "ibuprofen": Drug("ibuprofen", "이부프로펜", "이부프로펜", "ibu", 20, 5, 10, "부루펜 시럽 20mg/mL 기준"),
}

CLASSES = {
    "acet": DrugClass("acet", "아세트아미노펜 계열", "타이레놀", timedelta(hours=4), 5),
    "ibu": DrugClass("ibu", "이부프로펜 계열", "맥시부펜 · 이부프로펜", timedelta(hours=6), 4),
}


def level(value):
    if value is None:
        return "ok"
    value = Decimal(value)
    if value >= FEVER:
        return "hot"
    if value >= MILD_FEVER:
        return "warn"
    return "ok"


LEVEL_TEXT = {"hot": "열이 있어요", "warn": "미열이에요", "ok": "정상 체온이에요"}


def dose_range(weight_kg, drug_key):
    drug = DRUGS[drug_key]
    weight = Decimal(weight_kg)
    mg_min = weight * drug.mg_per_kg_min
    mg_max = weight * drug.mg_per_kg_max
    return {
        "mg_min": round(mg_min),
        "mg_max": round(mg_max),
        "ml_min": (mg_min / drug.mg_per_ml).quantize(Decimal("0.1")),
        "ml_max": (mg_max / drug.mg_per_ml).quantize(Decimal("0.1")),
    }


def suggested_ml(weight_kg, drug_key):
    """권장 범위 가운데 값을 0.5mL 단위로."""
    r = dose_range(weight_kg, drug_key)
    middle = (r["ml_min"] + r["ml_max"]) / 2
    return (middle * 2).quantize(Decimal("1")) / 2


def next_dose(medications, cls, now=None):
    """medications: 시간 오름차순 Medication 목록."""
    now = now or timezone.now()
    klass = CLASSES[cls]
    same = [m for m in medications if DRUGS[m.drug].cls == cls]
    other = [m for m in medications if DRUGS[m.drug].cls != cls]
    last_same = same[-1] if same else None
    last_other = other[-1] if other else None
    by_same = last_same.recorded_at + klass.gap if last_same else None
    by_cross = last_other.recorded_at + CROSS_GAP if last_other else None
    candidates = [t for t in (by_same, by_cross) if t]
    available_at = max(candidates) if candidates else None
    reason = "same" if available_at and available_at == by_same else "cross"
    count = sum(1 for m in same if now - m.recorded_at < timedelta(hours=24))
    ready = available_at is None or available_at <= now
    if ready or available_at is None:
        progress = 100
    else:
        progress = max(4, round(100 - (available_at - now) / klass.gap * 100))
    return {
        "cls": cls,
        "klass": klass,
        "available_at": available_at,
        "ready": ready,
        "reason": reason,
        "last_same": last_same,
        "count": count,
        "full": count >= klass.max_per_day,
        "progress": progress,
        "wait": (available_at - now) if available_at and not ready else None,
    }


def humanize_wait(delta):
    minutes = max(1, int(-(-delta.total_seconds() // 60)))
    if minutes < 60:
        return f"{minutes}분 후"
    hours, rest = divmod(minutes, 60)
    return f"{hours}시간 {rest}분 후" if rest else f"{hours}시간 후"


def humanize_ago(delta):
    minutes = int(delta.total_seconds() // 60)
    if minutes < 1:
        return "방금"
    if minutes < 60:
        return f"{minutes}분 전"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}시간 전"
    return f"{hours // 24}일 전"


def split_episodes(records):
    """시간 오름차순 기록을 72시간 이상 빈 구간으로 나눠 '아팠던 기간' 목록을 만든다."""
    episodes = []
    for record in records:
        if episodes and record.recorded_at - episodes[-1][-1].recorded_at < RECOVERY_GAP:
            episodes[-1].append(record)
        else:
            episodes.append([record])
    return [summarize(ep) for ep in episodes]


def summarize(records):
    first, last = records[0].recorded_at, records[-1].recorded_at
    first_day, last_day = timezone.localtime(first).date(), timezone.localtime(last).date()
    temps = [r.value for r in records if r.kind == "temp"]
    return {
        "key": int(first.timestamp()),
        "records": records,
        "start": first,
        "end": last,
        "days": (last_day - first_day).days + 1,
        "max_temp": max(temps) if temps else None,
        "med_count": sum(1 for r in records if r.kind == "med"),
        "count": len(records),
    }


def is_recovered(last_record_at, now=None):
    now = now or timezone.now()
    return last_record_at is not None and now - last_record_at >= RECOVERY_GAP
