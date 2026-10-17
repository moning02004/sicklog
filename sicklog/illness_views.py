"""아픔(감기·독감 등)과 병원 기록 화면."""
from datetime import datetime, time, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import dosing
from .models import COMPLICATIONS, ILLNESS_TITLES, SYMPTOMS, HospitalVisit, Illness, IllnessLog, VisitPhoto
from .views import active_illness, chart_data, eul, get_baby, group_by_day, require_baby

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


def parse_day(value):
    """화면의 날짜 휠 값(YYYY-MM-DD). 비어 있으면 오늘."""
    today = timezone.localdate()
    if not value:
        return today
    try:
        day = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise FormError("날짜를 다시 골라 주세요")
    if day > today:
        raise FormError("아직 오지 않은 날이에요")
    return day


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
            started_on = parse_day(request.POST.get("started_on"))
            with transaction.atomic():
                illness = Illness.objects.create(baby=baby, title=data["title"], symptoms=data["symptoms"],
                                                 started_on=started_on, recorded_by=request.user)
                log = lambda **kw: IllnessLog.objects.create(illness=illness, recorded_at=illness.started_at,
                                                             all_day=True, recorded_by=request.user, **kw)
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
            changed_at = parse_time(request.POST.get("changed_at"), earliest=illness.started_at)
            added = [s for s in data["symptoms"] if s not in illness.symptoms]
            removed = [s for s in illness.symptoms if s not in data["symptoms"]]
            with transaction.atomic():
                log = lambda **kw: IllnessLog.objects.create(illness=illness, recorded_at=changed_at,
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
        "visits": list(illness.visits.prefetch_related("photos")),
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
        cured_on = parse_day(request.POST.get("cured_on"))
        if cured_on < illness.started_on:
            raise FormError("아프기 시작한 날보다 앞선 날이에요")
    except FormError as exc:
        messages.error(request, str(exc))
        return redirect(request.POST.get("next") or "home")
    # 오늘이면 지금, 지난 날이면 그날의 끝으로 남겨 그날의 다른 기록보다 뒤에 오게 한다
    logged_at = timezone.now() if cured_on == timezone.localdate() else timezone.make_aware(
        datetime.combine(cured_on, time(23, 59)))
    with transaction.atomic():
        illness.cured_on = cured_on
        illness.save(update_fields=["cured_on"])
        IllnessLog.objects.create(illness=illness, kind=IllnessLog.Kind.CURE, recorded_at=logged_at, all_day=True,
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
        illness.cured_on = None
        illness.save(update_fields=["cured_on"])
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
    visit.visited_on = parse_day(request.POST.get("visited_on"))
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
    recent = (HospitalVisit.objects.filter(baby__in=[baby]).values_list("name", "location").order_by("-visited_on", "-id"))
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
