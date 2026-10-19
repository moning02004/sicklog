"""아픔(감기·독감 등)과 병원 기록 화면."""
import io
import re
from datetime import date, datetime, time, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import dosing
from .models import (COMPLICATIONS, ILLNESS_TITLES, SYMPTOMS, ConditionCheck, HospitalVisit, Illness, IllnessLog, Medication,
                     SLOTS, MedicineDose, Prescription, Temperature, VisitPhoto, half_key, latest_first)
from .forms import MedicationForm, TemperatureForm
from .push import notify_family, who
from .templatetags.sick_tags import eun
from .views import dose_lines, recent_prescriptions, active_illness, baby_records, dose_rows, safe_next, sheet_data, chart_data, eul, get_baby, group_by_day, require_baby

MAX_PHOTOS = 6
MAX_PHOTO_BYTES = 15 * 1024 * 1024
PHOTO_MAX_SIDE = 1600
PHOTO_TYPES = {b"\xff\xd8\xff": "image/jpeg", b"\x89PNG": "image/png", b"RIFF": "image/webp"}
HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1"}


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
        "logs": illness.logs.all(),
        "checks": list(illness.checks.all()),
        "visits": latest_first(illness.visits.prefetch_related("photos")),
        "chart": chart_data(temps, meds, start - pad, end + pad) if temps or meds else None,
        "groups": group_by_day(temps + meds, filt),
        "filter": filt,
        "today": today, "yesterday": today - timedelta(days=1),
    })


@login_required
def illness_records(request, pk):
    """한 아픔의 체온·해열제 기록 전체 (홈의 최근 기록 → 전체 보기)."""
    illness = get_illness(request.user, pk)
    filt = request.GET.get("f", "all")
    today = timezone.localdate()
    return render(request, "sicklog/illness_records.html", {
        "baby": illness.baby,
        "illness": illness,
        "groups": group_by_day(list(illness.temperatures.all()) + list(illness.medications.all()), filt),
        "filter": filt,
        "empty_text": {"temp": "체온 기록이 없어요", "med": "해열제 기록이 없어요"}.get(filt, "기록이 없어요"),
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
def illness_check(request, pk):
    """컨디션을 지금 시각으로 새로 남긴다. 모르는 질문은 비워도 되고, 메모만 남겨도 된다."""
    illness = get_illness(request.user, pk)
    back = safe_next(request, fallback=reverse("home"))
    if not illness.is_active:
        return redirect(back)
    answers = {f: request.POST.get(f, "") for f, _ in ConditionCheck.ANSWERS}
    answers = {f: v if v in ConditionCheck.choices_for(f) else "" for f, v in answers.items()}
    memo = request.POST.get("memo", "").strip()[:200]
    if not memo and not any(answers.values()):
        messages.error(request, "하나라도 고르거나 메모를 남겨 주세요")
        return redirect(back)
    check = ConditionCheck.objects.create(illness=illness, memo=memo, recorded_by=request.user, **answers)
    messages.success(request, "컨디션을 남겼어요")
    notify_family(illness.baby, request.user, f"{illness.baby.name} 컨디션",
                  f"{who(request.user)} 남겼어요: {check.line}")
    return redirect(back)


@require_POST
@login_required
def check_delete(request, pk):
    check = get_object_or_404(ConditionCheck.objects.select_related("illness"), pk=pk)
    get_baby(request.user, check.illness.baby_id)
    check.delete()
    messages.success(request, "컨디션 기록을 지웠어요")
    return redirect(safe_next(request, fallback=reverse("home")))


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

def is_heif(data):
    """아이폰·갤럭시 사진(HEIC/HEIF): 'ftyp' 상자의 브랜드로 알아본다."""
    return data[4:8] == b"ftyp" and data[8:12] in HEIF_BRANDS


def to_jpeg(data):
    """HEIC 등을 브라우저가 보여 줄 수 있는 JPEG로 바꾸고, 사진 방향을 바로잡고 줄인다."""
    from PIL import Image, ImageOps
    from pi_heif import register_heif_opener  # 읽기 전용(인코더 없음)

    register_heif_opener()
    try:
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
        image = image.convert("RGB")
        image.thumbnail((PHOTO_MAX_SIDE, PHOTO_MAX_SIDE))
        out = io.BytesIO()
        image.save(out, "JPEG", quality=82, optimize=True)
        return out.getvalue()
    except Exception:  # 깨진 파일 등
        raise FormError("사진을 읽지 못했어요. 다른 사진으로 올려 주세요")


def read_photos(request):
    photos = []
    for upload in request.FILES.getlist("photos"):
        if upload.size > MAX_PHOTO_BYTES:
            raise FormError("사진 한 장은 15MB까지 올릴 수 있어요")
        data = upload.read()
        if is_heif(data):
            photos.append(("image/jpeg", to_jpeg(data)))
            continue
        content_type = next((t for magic, t in PHOTO_TYPES.items() if data.startswith(magic)), None)
        if not content_type:
            raise FormError("사진 파일(JPG, PNG, WEBP, HEIC)만 올릴 수 있어요")
        photos.append((content_type, data))
    return photos


def save_visit(request, visit):
    visit.name = request.POST.get("name", "").strip()[:60]
    visit.location = request.POST.get("location", "").strip()[:100]
    visit.got_medicine = request.POST.get("got_medicine") == "on"
    if "medicine_note" in request.POST:  # 화면에서는 뺐지만 예전에 적어 둔 메모는 그대로 둔다
        visit.medicine_note = request.POST["medicine_note"].strip()[:200]
    if not visit.got_medicine:
        visit.medicine_note = ""
    rows = read_prescriptions(request) if visit.got_medicine else []
    # 현재 복용중인 약 중 토글을 끈 약은 그만 먹인다
    keep = set(request.POST.getlist("keep_rx"))
    stop_ids = [int(i) for i in request.POST.getlist("shown_rx") if i.isdigit() and i not in keep]
    visit.memo = request.POST.get("memo", "").strip()[:300]
    if not visit.name:
        raise FormError("병원 이름을 입력해 주세요")
    visit.visited_at = parse_half(request.POST.get("visited_at"))
    if visit.illness:  # 아픔에 딸린 병원 기록은 아프기 시작한 뒤여야 한다
        if half_key(visit.visited_at) < half_key(visit.illness.started_at):
            raise FormError("아프기 시작한 때보다 앞서요")
        visit.visited_at = max(visit.visited_at, visit.illness.started_at)
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
        save_prescriptions(visit, rows)
        # 새 약으로 바꾸면 고른 예전 약은 이 방문한 날부터 그만 먹인다
        for rx in Prescription.objects.filter(pk__in=stop_ids, visit__baby=visit.baby).exclude(visit=visit):
            rx.stop(visit.visited_on)
    return visit


def read_prescriptions(request):
    """폼의 약 줄(rx-0-name, rx-0-days, rx-0-slots …)을 읽는다. 이름을 비운 줄은 건너뛴다 (며칠분은 기본 3이 들어 있다)."""
    indexes = sorted({int(m.group(1)) for k in request.POST if (m := re.fullmatch(r"rx-(\d+)-name", k))})
    rows = []
    for i in indexes:
        name = request.POST.get(f"rx-{i}-name", "").strip()[:40]
        days = request.POST.get(f"rx-{i}-days", "").strip()
        if not name:
            continue
        if not (days.isdigit() and 1 <= int(days) <= Prescription.MAX_DAYS):
            raise FormError(f"{name}: 며칠분인지 1~{Prescription.MAX_DAYS} 사이로 입력해 주세요")
        picked = request.POST.getlist(f"rx-{i}-slots")
        pk = request.POST.get(f"rx-{i}-id", "")
        rows.append({"pk": int(pk) if pk.isdigit() else None, "name": name, "days": int(days),
                     "slots": [key for key, _ in SLOTS if key in picked]})
    return rows


def save_prescriptions(visit, rows):
    """폼에 남은 약은 고치고, 새 줄은 만들고, 폼에서 뺀 약은 지운다 (먹인 기록도 함께)."""
    existing = {rx.pk: rx for rx in visit.prescriptions.all()}
    kept = set()
    for row in rows:
        rx = existing.get(row["pk"]) or Prescription(visit=visit)
        rx.name, rx.days, rx.slots = row["name"], row["days"], row["slots"]
        rx.save()
        kept.add(rx.pk)
    visit.prescriptions.exclude(pk__in=kept).delete()


def taking_now(baby, exclude_visit=None):
    """지금(오늘) 먹이고 있는 약. 새 병원 기록에서 '그만 먹여요'를 고를 수 있게 보여 준다."""
    today = timezone.localdate()
    rxs = Prescription.objects.filter(visit__baby=baby, stopped_on__isnull=True).select_related("visit").prefetch_related("doses")
    if exclude_visit and exclude_visit.pk:
        rxs = rxs.exclude(visit=exclude_visit)
    # 병원별로 묶어 보여 주므로 최근 방문부터, 같은 방문 안에서는 넣은 순서대로
    return sorted((rx for rx in rxs if rx.day_no(today)), key=lambda rx: (-rx.visit.visited_at.timestamp(), rx.pk))


def visit_form_context(baby, visit, **extra):
    recent = (HospitalVisit.objects.filter(baby__in=[baby]).values_list("name", "location").order_by("-visited_at", "-id"))
    seen, suggestions = set(), []
    for name, location in recent:
        if name not in seen:
            seen.add(name)
            suggestions.append({"name": name, "location": location})
    return {"baby": baby, "visit": visit, "photos": list(visit.photos.all()) if visit.pk else [],
            "suggestions": suggestions[:5], "max_photos": MAX_PHOTOS,
            "prescriptions": list(visit.prescriptions.all()) if visit.pk else [],
            "slots": SLOTS, "max_days": Prescription.MAX_DAYS, "taking_now": taking_now(baby, visit), **extra}


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
            messages.success(request, "병원 기록을 수정했어요")
            return redirect("visit_detail", pk=visit.pk)
        except FormError as exc:
            messages.error(request, str(exc))
    return render(request, "sicklog/visit_form.html", visit_form_context(visit.baby, visit, creating=False))


@login_required
def illness_visits(request, pk):
    """한 아픔의 병원 방문과 방문마다 받은 약 (홈의 병원·약 → 전체 보기)."""
    illness = get_illness(request.user, pk)
    visits = latest_first(illness.visits.prefetch_related("prescriptions__doses"))
    return render(request, "sicklog/illness_visits.html", {
        "baby": illness.baby, "illness": illness, "visits": visits, "today": timezone.localdate(),
        "medicine_visits": sum(1 for v in visits if v.got_medicine),
    })


@login_required
def visit_detail(request, pk):
    visit = get_visit(request.user, pk)
    return render(request, "sicklog/visit_detail.html", {"baby": visit.baby, "visit": visit, "photos": visit.photos.all(),
                                                         "today": timezone.localdate()})


@login_required
def illness_doses(request, pk):
    """처방약 먹인 기록 전체, 날마다 (홈의 병원·약 → 지난 기록 보기). 여기서 지난 기록을 더하거나 지운다."""
    illness = get_illness(request.user, pk)
    doses = list(MedicineDose.objects.filter(prescription__visit__illness=illness).select_related("prescription"))
    by_day = {}
    for d in doses:
        by_day.setdefault(timezone.localtime(d.recorded_at).date(), []).append(d)
    today = timezone.localdate()
    visits = latest_first(illness.visits.prefetch_related("prescriptions__doses"))
    return render(request, "sicklog/illness_doses.html", {
        "baby": illness.baby, "illness": illness, "today": today, "yesterday": today - timedelta(days=1),
        "days": [(day, dose_lines(ds)) for day, ds in sorted(by_day.items(), reverse=True)],
        "choices": recent_prescriptions(visits, today),
    })


@require_POST
@login_required
def dose_create(request, pk):
    """기록 시트: 고른 약들을 같은 시간에 먹였다고 남긴다."""
    illness = get_illness(request.user, pk)
    back = safe_next(request)
    rxs = list(Prescription.objects.filter(visit__illness=illness, pk__in=[i for i in request.POST.getlist("rx") if i.isdigit()]))
    if not rxs:
        messages.error(request, "먹인 약을 골라 주세요")
        return redirect(back)
    try:
        given_at = parse_time(request.POST.get("given_at"))
    except FormError as exc:
        messages.error(request, str(exc))
        return redirect(back)
    day = timezone.localtime(given_at).date()
    first = timezone.localtime(illness.started_at).date()
    last = timezone.localtime(illness.cured_at).date() if illness.cured_at else timezone.localdate()
    if not (first <= day <= last):  # 아픈 기간 안에서만
        messages.error(request, f"아픈 기간({first:%Y.%m.%d}~{last:%Y.%m.%d}) 안의 시간을 골라 주세요")
        return redirect(back)
    for rx in rxs:  # 자기 전 약을 자정 넘어 먹일 수 있어서 끝난 다음 날까지는 받는다
        if not (rx.start_on <= day <= rx.end_on + timedelta(days=1)):
            messages.error(request, f"{eun(rx.name)} {day:%Y.%m.%d}에 먹는 약이 아니에요")
            return redirect(back)
    for rx in rxs:
        MedicineDose.objects.create(prescription=rx, recorded_at=given_at, recorded_by=request.user)
    names = ", ".join(rx.name for rx in rxs)
    messages.success(request, f"{timezone.localtime(given_at):%H:%M} {names} 복용을 기록했어요")
    if day == timezone.localdate():  # 지난 기록을 채워 넣는 것은 가족에게 알리지 않는다
        notify_family(illness.baby, request.user, f"{illness.baby.name} 처방약",
                      f"{who(request.user)} {timezone.localtime(given_at):%H:%M}에 {eul(names)} 먹였어요")
    return redirect(back)


@require_POST
@login_required
def dose_delete(request):
    """한 줄(같은 시간에 먹인 약들)을 지운다."""
    ids = [int(i) for i in request.POST.getlist("id") if i.isdigit()]
    doses = list(MedicineDose.objects.filter(pk__in=ids).select_related("prescription__visit"))
    if not doses:
        raise Http404
    for d in doses:
        get_visit(request.user, d.prescription.visit_id)  # 볼 수 있는 아이의 기록인지
    for d in doses:
        d.delete()
    messages.success(request, "복용 기록을 지웠어요")
    return redirect(safe_next(request))


@require_POST
@login_required
def prescription_stop(request, pk):
    """약을 오늘부터 그만 먹인다 (오늘 이미 먹였으면 내일부터). 그만 먹인 약이면 다시 먹인다."""
    rx = get_object_or_404(Prescription.objects.select_related("visit"), pk=pk)
    get_visit(request.user, rx.visit_id)
    if rx.stopped_on:
        rx.stopped_on = None
        rx.save(update_fields=["stopped_on"])
        messages.success(request, f"{eul(rx.name)} 다시 먹여요")
    else:
        rx.stop(timezone.localdate())
        messages.success(request, f"{eun(rx.name)} 이제 그만 먹여요")
    return redirect(safe_next(request))


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
            record = form.save(commit=False)  # 처음 기록한 사람은 그대로 두고, 고친 사람을 따로 남긴다
            record.mark_edited(request.user)
            record.save()
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
        "checks": list(illness.checks.all()),
        "daily": daily,
        "meds": list(reversed(meds)),
        "visits": latest_first(illness.visits.prefetch_related("photos")),
        "chart": chart_data(temps, meds, start - pad, min(end, now) + pad) if temps or meds else None,
    })
