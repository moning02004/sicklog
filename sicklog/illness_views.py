"""아픔(감기·독감 등)과 병원 기록 화면."""
from datetime import datetime, time, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import dosing
from .models import (COMPLICATIONS, ILLNESS_TITLES, SYMPTOMS, HospitalVisit, Illness, IllnessLog, Medication,
                     Temperature, VisitPhoto, half_key, latest_first)
from .forms import MedicationForm, TemperatureForm
from .views import active_illness, baby_records, dose_rows, safe_next, sheet_data, chart_data, eul, get_baby, group_by_day, require_baby

MAX_PHOTOS = 6
MAX_PHOTO_BYTES = 8 * 1024 * 1024
PHOTO_TYPES = {b"\xff\xd8\xff": "image/jpeg", b"\x89PNG": "image/png", b"RIFF": "image/webp"}


class FormError(Exception):
    pass


def parse_time(value, earliest=None):
    """화면의 시간 휠 값(YYYY-MM-DDTHH:MM). 비어 있으면 지금."""
    now = timezone.now()
    if not value:
        return now
    try:
        moment = timezone.make_aware(datetime.strptime(value, "%Y-%m-%dT%H:%M"))
    except ValueError:
        raise FormError("시간을 다시 골라 주세요")
    if moment > now + timedelta(minutes=1):
        raise FormError("아직 오지 않은 시간이에요")
    if earliest and moment < earliest - timedelta(minutes=1):
        raise FormError("아픔이 시작되기 전 시간이에요")
    return moment


AM_HOUR, PM_HOUR = 9, 15


def parse_half(value):
    """화면의 날짜·오전/오후 휠 값('YYYY-MM-DD am|pm'). 비어 있으면 지금.

    오전은 9시, 오후는 15시로 저장한다. 오늘의 지금 반나절을 고르면 지금 시각으로 저장한다.
    """
    now = timezone.now()
    if not value:
        return now
    try:
        day_text, half = value.split()
        day = datetime.strptime(day_text, "%Y-%m-%d").date()
        if half not in ("am", "pm"):
            raise ValueError
    except ValueError:
        raise FormError("날짜를 다시 골라 주세요")
    local_now = timezone.localtime(now)
    if day == local_now.date() and (half == "pm") == (local_now.hour >= 12):
        return now
    moment = timezone.make_aware(datetime.combine(day, time(PM_HOUR if half == "pm" else AM_HOUR)))
    if moment > now:
        raise FormError("아직 오지 않은 때예요")
    return moment


def clean_symptoms(values):
    seen = []
    for value in values:
        value = value.strip()[:30]
        if value and value not in seen:
            seen.append(value)
    return seen[:20]


def get_illness(user, pk):
    illness = get_object_or_404(Illness.objects.select_related("baby"), pk=pk)
    get_baby(user, illness.baby_id)
    return illness


def get_visit(user, pk):
    visit = get_object_or_404(HospitalVisit.objects.select_related("baby", "illness"), pk=pk)
    get_baby(user, visit.baby_id)
    return visit


def form_context(**extra):
    return {"titles": ILLNESS_TITLES, "symptom_choices": SYMPTOMS, "complication_choices": COMPLICATIONS,
            "known_symptoms": SYMPTOMS + COMPLICATIONS, **extra}


# ---------------------------------------------------------------- 아픔

@require_baby
def illness_create(request, baby):
    if active_illness(baby):
        messages.error(request, "이미 기록 중인 아픔이 있어요")
        return redirect("home")
    data = {"title": "", "symptoms": []}
    if request.method == "POST":
        data = {"title": request.POST.get("title", "").strip()[:40],
                "symptoms": clean_symptoms(request.POST.getlist("symptoms"))}
        try:
            if not data["title"]:
                raise FormError("어떤 아픔인지 골라 주세요")
            started_at = parse_half(request.POST.get("started_at"))
            with transaction.atomic():
                illness = Illness.objects.create(baby=baby, title=data["title"], symptoms=data["symptoms"],
                                                 started_at=started_at, recorded_by=request.user)
                log = lambda **kw: IllnessLog.objects.create(illness=illness, recorded_at=illness.started_at,
                                                             half_day=True, recorded_by=request.user, **kw)
                log(kind=IllnessLog.Kind.START, detail=illness.title)
                for symptom in illness.symptoms:
                    log(kind=IllnessLog.Kind.ADD, symptom=symptom)
            messages.success(request, f"{eul(illness.title)} 기록하기 시작했어요")
            return redirect("home")
        except FormError as exc:
            messages.error(request, str(exc))
    return render(request, "sicklog/illness_form.html", form_context(baby=baby, data=data, creating=True))


@login_required
def illness_edit(request, pk):
    illness = get_illness(request.user, pk)
    data = {"title": illness.title, "symptoms": list(illness.symptoms)}
    if request.method == "POST":
        data = {"title": request.POST.get("title", "").strip()[:40],
                "symptoms": clean_symptoms(request.POST.getlist("symptoms"))}
        try:
            if not data["title"]:
                raise FormError("어떤 아픔인지 골라 주세요")
            changed_at = parse_half(request.POST.get("changed_at"))
            if half_key(changed_at) < half_key(illness.started_at):
                raise FormError("아프기 시작한 때보다 앞서요")
            changed_at = max(changed_at, illness.started_at)  # 같은 반나절이면 시작보다 뒤로
            added = [s for s in data["symptoms"] if s not in illness.symptoms]
            removed = [s for s in illness.symptoms if s not in data["symptoms"]]
            with transaction.atomic():
                log = lambda **kw: IllnessLog.objects.create(illness=illness, recorded_at=changed_at, half_day=True,
                                                             recorded_by=request.user, **kw)
                if data["title"] != illness.title:
                    log(kind=IllnessLog.Kind.TITLE, detail=f"{illness.title} → {data['title']}")
                for symptom in added:
                    log(kind=IllnessLog.Kind.ADD, symptom=symptom)
                for symptom in removed:
                    log(kind=IllnessLog.Kind.REMOVE, symptom=symptom)
                illness.title, illness.symptoms = data["title"], data["symptoms"]
                illness.save(update_fields=["title", "symptoms"])
            messages.success(request, "증상을 바꿨어요" if added or removed else "저장했어요")
            return redirect("illness_detail", pk=illness.pk)
        except FormError as exc:
            messages.error(request, str(exc))
    return render(request, "sicklog/illness_form.html",
                  form_context(baby=illness.baby, data=data, illness=illness, creating=False))


@login_required
def illness_detail(request, pk):
    illness = get_illness(request.user, pk)
    temps = list(illness.temperatures.order_by("recorded_at"))
    meds = list(illness.medications.order_by("recorded_at"))
    end = min(illness.ended_at or timezone.now(), timezone.now())
    pad = timedelta(minutes=30)
    start = min([illness.started_at] + [r.recorded_at for r in temps + meds])
    filt = request.GET.get("f", "all")
    today = timezone.localdate()
    return render(request, "sicklog/illness_detail.html", {
        "baby": illness.baby,
        "illness": illness,
        "stats": dosing.summarize(temps, meds),
        "logs": list(illness.logs.all()),
        "visits": latest_first(illness.visits.prefetch_related("photos")),
        "chart": chart_data(temps, meds, start - pad, end + pad) if temps or meds else None,
        "groups": group_by_day(temps + meds, filt),
        "filter": filt,
        "today": today, "yesterday": today - timedelta(days=1),
    })


@require_POST
@login_required
def illness_cure(request, pk):
    illness = get_illness(request.user, pk)
    if not illness.is_active:
        return redirect("illness_detail", pk=illness.pk)
    try:
        cured_at = parse_half(request.POST.get("cured_at"))
        if half_key(cured_at) < half_key(illness.started_at):
            raise FormError("아프기 시작한 때보다 앞서요")
        cured_at = max(cured_at, illness.started_at)  # 같은 반나절에 나을 수도 있다
    except FormError as exc:
        messages.error(request, str(exc))
        return redirect(safe_next(request))
    with transaction.atomic():
        illness.cured_at = cured_at
        illness.save(update_fields=["cured_at"])
        IllnessLog.objects.create(illness=illness, kind=IllnessLog.Kind.CURE, recorded_at=cured_at, half_day=True,
                                  recorded_by=request.user)
    messages.success(request, f"{illness.title} 완치로 기록했어요. {illness.days}일간 고생했어요")
    return redirect("illness_detail", pk=illness.pk)


@require_POST
@login_required
def illness_reopen(request, pk):
    illness = get_illness(request.user, pk)
    if illness.is_active:
        return redirect("illness_detail", pk=illness.pk)
    if active_illness(illness.baby):
        messages.error(request, "지금 기록 중인 다른 아픔이 있어요")
        return redirect("illness_detail", pk=illness.pk)
    with transaction.atomic():
        illness.cured_at = None
        illness.save(update_fields=["cured_at"])
        IllnessLog.objects.create(illness=illness, kind=IllnessLog.Kind.REOPEN, recorded_by=request.user)
    messages.success(request, "완치를 취소했어요. 다시 기록할 수 있어요")
    return redirect("home")


# ---------------------------------------------------------------- 병원 기록

def read_photos(request):
    photos = []
    for upload in request.FILES.getlist("photos"):
        if upload.size > MAX_PHOTO_BYTES:
            raise FormError("사진 한 장은 8MB까지 올릴 수 있어요")
        data = upload.read()
        content_type = next((t for magic, t in PHOTO_TYPES.items() if data.startswith(magic)), None)
        if not content_type:
            raise FormError("사진 파일(JPG, PNG, WEBP)만 올릴 수 있어요")
        photos.append((content_type, data))
    return photos


def save_visit(request, visit):
    visit.name = request.POST.get("name", "").strip()[:60]
    visit.location = request.POST.get("location", "").strip()[:100]
    visit.got_medicine = request.POST.get("got_medicine") == "on"
    visit.medicine_note = request.POST.get("medicine_note", "").strip()[:200] if visit.got_medicine else ""
    visit.memo = request.POST.get("memo", "").strip()[:300]
    if not visit.name:
        raise FormError("병원 이름을 입력해 주세요")
    visit.visited_at = parse_half(request.POST.get("visited_at"))
    photos = read_photos(request) if visit.got_medicine else []
    remove_ids = [int(i) for i in request.POST.getlist("remove_photos") if i.isdigit()]
    kept = visit.photos.exclude(pk__in=remove_ids).count() if visit.pk else 0
    if kept + len(photos) > MAX_PHOTOS:
        raise FormError(f"사진은 {MAX_PHOTOS}장까지 올릴 수 있어요")
    with transaction.atomic():
        visit.save()
        if remove_ids:
            visit.photos.filter(pk__in=remove_ids).delete()
        for content_type, data in photos:
            VisitPhoto.objects.create(visit=visit, content_type=content_type, data=data)
    return visit


def visit_form_context(baby, visit, **extra):
    recent = (HospitalVisit.objects.filter(baby__in=[baby]).values_list("name", "location").order_by("-visited_at", "-id"))
    seen, suggestions = set(), []
    for name, location in recent:
        if name not in seen:
            seen.add(name)
            suggestions.append({"name": name, "location": location})
    return {"baby": baby, "visit": visit, "photos": list(visit.photos.all()) if visit.pk else [],
            "suggestions": suggestions[:5], "max_photos": MAX_PHOTOS, **extra}


@require_baby
def visit_create(request, baby):
    illness = active_illness(baby)
    visit = HospitalVisit(baby=baby, illness=illness, recorded_by=request.user)
    if request.method == "POST":
        try:
            save_visit(request, visit)
            messages.success(request, f"{visit.name} 방문을 기록했어요")
            return redirect("visit_detail", pk=visit.pk)
        except FormError as exc:
            messages.error(request, str(exc))
    return render(request, "sicklog/visit_form.html", visit_form_context(baby, visit, creating=True))


@login_required
def visit_edit(request, pk):
    visit = get_visit(request.user, pk)
    if request.method == "POST":
        try:
            save_visit(request, visit)
            messages.success(request, "병원 기록을 고쳤어요")
            return redirect("visit_detail", pk=visit.pk)
        except FormError as exc:
            messages.error(request, str(exc))
    return render(request, "sicklog/visit_form.html", visit_form_context(visit.baby, visit, creating=False))


@login_required
def visit_detail(request, pk):
    visit = get_visit(request.user, pk)
    return render(request, "sicklog/visit_detail.html", {"baby": visit.baby, "visit": visit,
                                                         "photos": visit.photos.all()})


@require_POST
@login_required
def visit_delete(request, pk):
    visit = get_visit(request.user, pk)
    name = visit.name
    visit.delete()
    messages.success(request, f"{name} 방문 기록을 지웠어요")
    return redirect(f"{reverse('history')}?tab=visits")


@login_required
def visit_photo(request, pk):
    photo = get_object_or_404(VisitPhoto.objects.select_related("visit"), pk=pk)
    get_baby(request.user, photo.visit.baby_id)
    response = HttpResponse(bytes(photo.data), content_type=photo.content_type)
    response["Cache-Control"] = "private, max-age=86400"
    return response


# ---------------------------------------------------------------- 체온·해열제 기록 고치기

RECORD_KINDS = {"temp": (Temperature, TemperatureForm), "med": (Medication, MedicationForm)}


def get_record(user, kind, pk):
    if kind not in RECORD_KINDS:
        raise Http404
    model, form_class = RECORD_KINDS[kind]
    record = get_object_or_404(model.objects.select_related("baby"), pk=pk)
    get_baby(user, record.baby_id)
    return record, form_class


@login_required
def record_edit(request, kind, pk):
    record, form_class = get_record(request.user, kind, pk)
    if request.method == "POST":
        form = form_class(request.POST, instance=record)
        if form.is_valid():
            form.save()  # 처음 기록한 사람은 그대로 둔다
            messages.success(request, "기록을 고쳤어요")
            return redirect("illness_detail", pk=record.illness_id) if record.illness_id else redirect("home")
        messages.error(request, next(iter(form.errors.values()))[0])
    baby = record.baby
    ctx = {"baby": baby, "record": record, "kind": kind}
    if kind == "temp":
        ctx["methods"] = Temperature.Method.choices
    else:
        _, meds, _ = baby_records(baby)
        illness_meds = [m for m in meds if m.illness_id == record.illness_id]
        ctx["drugs"] = dosing.DRUGS
        ctx["sheet_data"] = sheet_data(baby, dose_rows(illness_meds, timezone.now()), None, meds)
    return render(request, "sicklog/record_form.html", ctx)


@require_POST
@login_required
def record_delete(request, kind, pk):
    record, _ = get_record(request.user, kind, pk)
    label = f"{record.value}℃" if kind == "temp" else f"{record.get_drug_display()} {record.amount_ml}mL"
    illness_id = record.illness_id
    record.delete()
    messages.success(request, f"{label} 기록을 지웠어요")
    return redirect("illness_detail", pk=illness_id) if illness_id else redirect("home")


# ---------------------------------------------------------------- 진료용 요약

def symptom_timeline(logs):
    """증상별로 언제 생기고 언제 나아졌는지. logs는 시간 오름차순."""
    spans = {}
    for log in logs:
        if log.kind == IllnessLog.Kind.ADD:
            span = spans.get(log.symptom)
            if span is None or span["end"] is not None:
                spans[log.symptom] = {"name": log.symptom, "start": log.recorded_at, "end": None}
        elif log.kind == IllnessLog.Kind.REMOVE and log.symptom in spans:
            spans[log.symptom]["end"] = log.recorded_at
    return sorted(spans.values(), key=lambda s: (s["end"] is not None, s["start"]))


@login_required
def illness_summary(request, pk):
    """진료 때 보여주기 좋게 한 아픔을 한 화면에 모은다."""
    illness = get_illness(request.user, pk)
    now = timezone.now()
    temps = list(illness.temperatures.order_by("recorded_at"))
    meds = list(illness.medications.order_by("recorded_at"))
    fever = [t for t in temps if t.value >= dosing.FEVER]
    peak = max(temps, key=lambda t: (t.value, t.recorded_at), default=None)

    by_drug = {}
    for m in meds:
        by_drug.setdefault(m.drug, {"drug": dosing.DRUGS[m.drug], "count": 0})["count"] += 1

    days = {}
    for r in temps + meds:
        day = timezone.localtime(r.recorded_at).date()
        row = days.setdefault(day, {"day": day, "max": None, "fever": 0, "meds": {}})
        if r.kind == "temp":
            row["max"] = r.value if row["max"] is None else max(row["max"], r.value)
            row["fever"] += r.value >= dosing.FEVER
        else:
            name = dosing.DRUGS[r.drug].name
            row["meds"][name] = row["meds"].get(name, 0) + 1
    daily = sorted(days.values(), key=lambda d: d["day"], reverse=True)

    end = illness.cured_at or now
    pad = timedelta(minutes=30)
    start = min([illness.started_at] + [r.recorded_at for r in temps + meds])
    last_med = meds[-1] if meds else None
    return render(request, "sicklog/illness_summary.html", {
        "baby": illness.baby,
        "illness": illness,
        "now": now,
        "last_temp": temps[-1] if temps else None,
        "peak": peak,
        "fever_count": len(fever),
        "last_fever": fever[-1] if fever else None,
        "temp_count": len(temps),
        "by_drug": sorted(by_drug.values(), key=lambda d: -d["count"]),
        "med_count": len(meds),
        "last_med": last_med,
        "last_med_ago": dosing.humanize_ago(now - last_med.recorded_at) if last_med and illness.is_active else "",
        "symptoms": symptom_timeline(illness.logs.order_by("recorded_at", "id")),
        "daily": daily,
        "meds": list(reversed(meds)),
        "visits": latest_first(illness.visits.prefetch_related("photos")),
        "chart": chart_data(temps, meds, start - pad, min(end, now) + pad) if temps or meds else None,
    })
