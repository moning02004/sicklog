import json
from datetime import timedelta
from decimal import Decimal
from itertools import groupby

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.core.cache import cache
from django.db import connection, transaction
from django.utils.http import url_has_allowed_host_and_scheme
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from . import dosing
from .forms import BabyForm, MedicationForm, NotificationForm, TemperatureForm, UserCreateForm, WeightForm
from .models import latest_first, Baby, Medication, PushSubscription, Temperature, User


def client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return forwarded.split(",")[0].strip() or request.META.get("REMOTE_ADDR", "")


class LoginView(auth_views.LoginView):
    """아이디·IP별로 여러 번 틀리면 잠시 로그인을 막는다 (비밀번호가 짧아서)."""

    template_name = "registration/login.html"
    redirect_authenticated_user = True

    def keys(self):
        username = self.request.POST.get("username", "").strip().lower()[:150]
        return f"login-fail:user:{username}", f"login-fail:ip:{client_ip(self.request)}"

    def locked(self):
        user_key, ip_key = self.keys()
        return (cache.get(user_key, 0) >= settings.LOGIN_MAX_FAILURES
                or cache.get(ip_key, 0) >= settings.LOGIN_MAX_FAILURES_PER_IP)

    def post(self, request, *args, **kwargs):
        if self.locked():
            form = self.get_form()
            form.errors.clear()
            minutes = settings.LOGIN_LOCK_SECONDS // 60
            return self.render_to_response(self.get_context_data(form=form, locked_minutes=minutes))
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        for key in self.keys():
            try:
                cache.incr(key)
            except ValueError:
                cache.set(key, 1, settings.LOGIN_LOCK_SECONDS)
        return super().form_invalid(form)

    def form_valid(self, form):
        cache.delete(self.keys()[0])
        return super().form_valid(form)


def safe_next(request, fallback="home"):
    """폼의 next 값은 우리 사이트 주소일 때만 따른다."""
    target = request.POST.get("next") or request.GET.get("next")
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()},
                                                   require_https=request.is_secure()):
        return target
    return fallback


# ---------------------------------------------------------------- helpers

def ro(name):
    """이름 받침에 맞춰 '로/으로'를 붙인다."""
    code = ord(name[-1]) - 0xAC00
    jong = code % 28 if 0 <= code < 11172 else 0
    return name + ("으로" if jong and jong != 8 else "로")


def eul(name):
    code = ord(name[-1]) - 0xAC00
    jong = code % 28 if 0 <= code < 11172 else 0
    return name + ("을" if jong else "를")


def get_baby(user, pk):
    baby = get_object_or_404(Baby, pk=pk)
    if not user.is_superuser and not baby.guardians.filter(pk=user.pk).exists():
        raise Http404
    return baby


def current_baby(user):
    babies = user.accessible_babies()
    if user.current_baby_id and babies.filter(pk=user.current_baby_id).exists():
        return user.current_baby
    baby = babies.first()
    if baby and user.current_baby_id != baby.pk:
        user.current_baby = baby
        user.save(update_fields=["current_baby"])
    return baby


def baby_records(baby):
    temps = list(baby.temperatures.order_by("recorded_at"))
    meds = list(baby.medications.order_by("recorded_at"))
    merged = sorted(temps + meds, key=lambda r: r.recorded_at)
    return temps, meds, merged


def dose_rows(meds, now):
    rows = []
    for cls in ("acet", "ibu"):
        nd = dosing.next_dose(meds, cls, now)
        if nd["full"]:
            nd["status"], nd["status_color"] = "하루 최대 횟수", "hot"
            nd["sub"] = f"24시간 동안 {nd['count']}/{nd['klass'].max_per_day}회 먹였어요"
        elif nd["ready"]:
            nd["status"], nd["status_color"] = "지금 가능", "ok"
            last = nd["last_same"]
            nd["sub"] = (f"마지막 {dosing.DRUGS[last.drug].name} {timezone.localtime(last.recorded_at):%H:%M}"
                         if last else "먹인 기록이 없어요")
        else:
            nd["status"], nd["status_color"] = f"{timezone.localtime(nd['available_at']):%H:%M}부터", ""
            wait = dosing.humanize_wait(nd["wait"])
            # 무엇 때문에 기다리는지 그 약과 시각을 함께 보여준다
            cause = nd["last_other"] if nd["reason"] == "cross" else nd["last_same"]
            gap_hours = 2 if nd["reason"] == "cross" else int(nd["klass"].gap.total_seconds() // 3600)
            nd["sub"] = (f"{dosing.DRUGS[cause.drug].name} {timezone.localtime(cause.recorded_at):%H:%M}에 먹음 · "
                         f"{gap_hours}시간 뒤 · {wait}")
        rows.append(nd)
    return rows


def require_baby(view):
    def wrapper(request, *args, **kwargs):
        baby = current_baby(request.user)
        if baby is None:
            return redirect("baby_list")
        return view(request, baby, *args, **kwargs)

    wrapper.__name__ = view.__name__
    return login_required(wrapper)


# ---------------------------------------------------------------- pages

def active_illness(baby):
    return baby.illnesses.filter(cured_at__isnull=True).first()


def chart_data(temps, meds, start, end):
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "temps": [[t.recorded_at.isoformat(), float(t.value)] for t in temps if start <= t.recorded_at <= end],
        "meds": [[m.recorded_at.isoformat(), dosing.DRUGS[m.drug].initial, dosing.DRUGS[m.drug].cls]
                 for m in meds if start <= m.recorded_at <= end],
    }


def group_by_day(records, filt="all"):
    shown = [r for r in sorted(records, key=lambda r: r.recorded_at, reverse=True) if filt == "all" or r.kind == filt]
    return [(day, list(items)) for day, items in
            groupby(shown, key=lambda r: timezone.localtime(r.recorded_at).date())]


def sheet_data(baby, rows, last_temp, meds):
    last_ml = {}
    for m in meds:  # 시간 순이라 마지막 값이 남는다
        last_ml[m.drug] = float(m.amount_ml)
    return {
        "weight": float(baby.weight_kg),
        "lastTemp": float(last_temp.value) if last_temp else None,
        "drugs": {
            key: {
                "name": d.name, "cls": d.cls, "conc": d.mg_per_ml,
                "suggested": float(dosing.suggested_ml(baby.weight_kg, key)),
                "lastMl": last_ml.get(key),
                "mlMin": float(dosing.dose_range(baby.weight_kg, key)["ml_min"]),
                "mlMax": float(dosing.dose_range(baby.weight_kg, key)["ml_max"]),
            }
            for key, d in dosing.DRUGS.items()
        },
        "classes": {
            r["cls"]: {
                "availableAt": r["available_at"].isoformat() if r["available_at"] else None,
                "reason": r["reason"],
                "gapHours": int(r["klass"].gap.total_seconds() // 3600),
            }
            for r in rows
        },
    }


@require_baby
def home(request, baby):
    """아픔이 있으면 그 아픔을 먼저 보여 주고, 없으면 새 아픔 기록을 권한다."""
    now = timezone.now()
    illness = active_illness(baby)
    if illness is None:
        last = baby.illnesses.first()
        return render(request, "sicklog/home_healthy.html", {
            "baby": baby, "last_illness": last,
            "last_stats": dosing.summarize(list(last.temperatures.all()), list(last.medications.all())) if last else None,
        })

    _, meds, merged = baby_records(baby)
    # 체온·차트·최근 기록은 이번 아픔 것만. 교차복용 시간은 실제 먹인 시간이 중요해 전체 해열제로 계산한다.
    illness_records = [r for r in merged if r.illness_id == illness.pk]
    temps = [r for r in illness_records if r.kind == "temp"]
    illness_meds = [r for r in illness_records if r.kind == "med"]
    last_temp = temps[-1] if temps else None
    rows = dose_rows(meds, now)
    filt = request.GET.get("f", "all")
    recent = [r for r in reversed(illness_records) if filt == "all" or r.kind == filt][:5]
    last_activity = max([r.recorded_at for r in illness_records] + [illness.created_at])
    default_drug = next((k for k, d in dosing.DRUGS.items()
                         if next(r for r in rows if r["cls"] == d.cls)["ready"]), "tylenol")
    return render(request, "sicklog/home.html", {
        "baby": baby,
        "illness": illness,
        "last_visit": next(iter(latest_first(illness.visits.all())), None),
        "quiet": dosing.quiet_for(last_activity, now),
        "last_temp": last_temp,
        "last_temp_ago": dosing.humanize_ago(now - last_temp.recorded_at) if last_temp else "",
        "dose_rows": rows,
        "dose_warnings": [
            {**w, "text": (f"{dosing.DRUGS[w['earlier'].drug].name} {timezone.localtime(w['earlier'].recorded_at):%H:%M} → "
                           f"{dosing.DRUGS[w['later'].drug].name} {timezone.localtime(w['later'].recorded_at):%H:%M}: "
                           f"{dosing.humanize_gap(w['gap'])} 간격 "
                           f"({'같은 계열' if w['same'] else '다른 계열'}은 {int(w['need'].total_seconds() // 3600)}시간)")}
            for w in dosing.interval_warnings(meds, now)
        ],
        "any_ready": any(r["ready"] and not r["full"] for r in rows),
        "chart": chart_data(temps, illness_meds, now - timedelta(hours=24), now),
        "recent": recent,
        "filter": filt,
        "sheet_data": sheet_data(baby, rows, last_temp, meds),
        "default_drug": default_drug,
        "methods": Temperature.Method.choices,
        "drugs": dosing.DRUGS,
        "default_temp": last_temp.value if last_temp else Decimal("37.0"),
    })


@require_baby
def history(request, baby):
    """기록 탭: 아픔 목록과 병원 기록 목록."""
    tab = request.GET.get("tab", "illness")
    illnesses = list(baby.illnesses.prefetch_related("temperatures", "medications", "visits"))
    for ill in illnesses:
        ill.stats = dosing.summarize(list(ill.temperatures.all()), list(ill.medications.all()))
    visits = latest_first(baby.visits.select_related("illness").prefetch_related("photos"))
    return render(request, "sicklog/history.html", {
        "baby": baby, "tab": tab,
        "current": next((i for i in illnesses if i.is_active), None),
        "past": [i for i in illnesses if not i.is_active],
        "visits": visits,
    })


@require_baby
def guide(request, baby):
    cards = []
    for key, drug in dosing.DRUGS.items():
        cards.append({"drug": drug, "klass": dosing.CLASSES[drug.cls], "range": dosing.dose_range(baby.weight_kg, key),
                      "gap_hours": int(dosing.CLASSES[drug.cls].gap.total_seconds() // 3600)})
    return render(request, "sicklog/guide.html", {"baby": baby, "cards": cards})


# ---------------------------------------------------------------- records

@require_POST
@require_baby
def temperature_create(request, baby):
    illness = active_illness(baby)
    if illness is None:
        messages.error(request, "먼저 아픔을 기록해 주세요")
        return redirect("home")
    form = TemperatureForm(request.POST)
    if form.is_valid():
        record = form.save(commit=False)
        record.baby, record.recorded_by, record.illness = baby, request.user, illness
        record.save()
        messages.success(request, f"{record.value}℃ 기록했어요")
    else:
        messages.error(request, next(iter(form.errors.values()))[0])
    return redirect("home")


@require_POST
@require_baby
def medication_create(request, baby):
    illness = active_illness(baby)
    if illness is None:
        messages.error(request, "먼저 아픔을 기록해 주세요")
        return redirect("home")
    form = MedicationForm(request.POST)
    if form.is_valid():
        record = form.save(commit=False)
        record.baby, record.recorded_by, record.illness = baby, request.user, illness
        record.save()
        messages.success(request, f"{record.get_drug_display()} {record.amount_ml}mL 기록했어요")
    else:
        messages.error(request, next(iter(form.errors.values()))[0])
    return redirect("home")


# ---------------------------------------------------------------- babies

@login_required
def baby_list(request):
    return render(request, "sicklog/baby_list.html", {
        "babies": request.user.accessible_babies().prefetch_related("guardians"),
        "current": current_baby(request.user),
    })


@login_required
def baby_create(request):
    form = BabyForm(request.POST or None)
    usernames = [u.strip().lower() for u in request.POST.getlist("guardians") if u.strip()]
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            baby = form.save()
            guardians = list(User.objects.filter(username__in=usernames)) + [request.user]
            baby.guardians.add(*guardians)
            request.user.current_baby = baby
            request.user.save(update_fields=["current_baby"])
        messages.success(request, f"{eul(baby.name)} 등록했어요")
        return redirect("home")
    guardians = list(User.objects.filter(username__in=usernames).exclude(pk=request.user.pk))
    return render(request, "sicklog/baby_form.html", {"form": form, "guardians": guardians})


@login_required
def baby_detail(request, pk):
    baby = get_baby(request.user, pk)
    guardians = baby.guardians.order_by("date_joined")
    back = {"settings": reverse("settings"), "babies": reverse("baby_list")}.get(request.GET.get("from"), reverse("home"))
    return render(request, "sicklog/baby_detail.html", {"baby": baby, "guardians": guardians, "back_url": back})


@require_POST
@login_required
def baby_select(request, pk):
    baby = get_baby(request.user, pk)
    request.user.current_baby = baby
    request.user.save(update_fields=["current_baby"])
    messages.success(request, f"{ro(baby.name)} 바꿨어요")
    return redirect(safe_next(request))


@require_POST
@login_required
def baby_weight(request, pk):
    baby = get_baby(request.user, pk)
    form = WeightForm(request.POST)
    if form.is_valid():
        baby.weight_kg = form.cleaned_data["weight_kg"]
        baby.weight_updated_at = timezone.now()
        baby.save(update_fields=["weight_kg", "weight_updated_at"])
        messages.success(request, f"{baby.name} 몸무게를 {baby.weight_kg}kg으로 바꿨어요")
    else:
        messages.error(request, "몸무게를 다시 확인해 주세요")
    return redirect("baby_detail", pk=baby.pk)


@require_POST
@login_required
def guardian_add(request, pk):
    baby = get_baby(request.user, pk)
    username = request.POST.get("username", "").strip().lower()
    user = User.objects.filter(username=username).first()
    if not user:
        messages.error(request, f"'{username}' 아이디를 찾을 수 없어요")
    elif baby.guardians.filter(pk=user.pk).exists():
        messages.error(request, "이미 추가된 보호자예요")
    else:
        baby.guardians.add(user)
        messages.success(request, f"{user.display_name}({user.relation_label}) 님을 추가했어요")
    return redirect("baby_detail", pk=baby.pk)


@require_POST
@login_required
def guardian_remove(request, pk, user_id):
    baby = get_baby(request.user, pk)
    if user_id == request.user.pk:
        messages.error(request, "나는 뺄 수 없어요")
    else:
        baby.guardians.remove(user_id)
        messages.success(request, "보호자에서 뺐어요")
    return redirect("baby_detail", pk=baby.pk)


@login_required
def user_lookup(request):
    username = request.GET.get("username", "").strip().lower()
    user = User.objects.filter(username=username).first()
    if not user:
        return JsonResponse({"ok": False, "error": f"'{username}' 아이디를 찾을 수 없어요. 철자를 확인해 주세요."})
    return JsonResponse({"ok": True, "username": user.username, "name": user.display_name,
                         "relation": user.relation_label, "color": user.color, "me": user.pk == request.user.pk})


# ---------------------------------------------------------------- settings

@login_required
def settings_view(request, add_form=None):
    user = request.user
    ctx = {
        "babies": user.accessible_babies(),
        "current": current_baby(user),
        "notif_form": NotificationForm(instance=user),
        "add_form": add_form or UserCreateForm(),
        "add_open": add_form is not None,
        "relations": UserCreateForm.base_fields["relation"].choices,
        "push_enabled": bool(settings.VAPID_PUBLIC_KEY),
        "theme_choices": User.Theme.choices,
    }
    if user.is_superuser:
        users = list(User.objects.order_by("-is_superuser", "date_joined"))
        for u in users:
            u.record_count = u.temperatures.count() + u.medications.count() + u.hospitalvisits.count()
        ctx["users"] = users
    return render(request, "sicklog/settings.html", ctx)


@require_POST
@login_required
def update_notifications(request):
    form = NotificationForm(request.POST, instance=request.user)
    if form.is_valid():
        form.save()
        return JsonResponse({"ok": True})
    return JsonResponse({"ok": False, "errors": form.errors}, status=400)


@require_POST
@login_required
def update_theme(request):
    theme = request.POST.get("theme")
    if theme in User.Theme.values:
        request.user.theme = theme
        request.user.save(update_fields=["theme"])
    return JsonResponse({"ok": True, "theme": request.user.theme})


def superuser_required(view):
    return login_required(user_passes_test(lambda u: u.is_superuser)(view))


@require_POST
@superuser_required
def user_add(request):
    form = UserCreateForm(request.POST)
    if not form.is_valid():
        return settings_view(request, add_form=form)
    data = form.cleaned_data
    User.objects.create_user(username=data["username"], password=settings.DEFAULT_USER_PASSWORD,
                             name=data["name"], relation=data["relation"])
    messages.success(request, f"{data['name']}({data['relation']}) 님을 추가했어요")
    return redirect("settings")


@require_POST
@superuser_required
def user_delete(request, pk):
    user = get_object_or_404(User, pk=pk)
    if user.is_superuser or user.pk == request.user.pk:
        messages.error(request, "관리자는 삭제할 수 없어요")
        return redirect("settings")
    delete_records = request.POST.get("records") == "delete"
    with transaction.atomic():
        count = 0
        if delete_records:
            count = (user.temperatures.all().delete()[0] + user.medications.all().delete()[0]
                     + user.hospitalvisits.all().delete()[0])
        name = user.display_name
        user.delete()  # 남긴 기록은 recorded_by만 비워지고 그대로 남는다
    messages.success(request, f"{name} 님과 기록 {count}건을 삭제했어요" if delete_records and count
                     else f"{name} 님을 삭제했어요. 기록은 그대로예요")
    return redirect("settings")


@login_required
def password_change(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    form.fields["old_password"].error_messages["required"] = "지금 비밀번호를 입력해 주세요."
    if request.method == "POST":
        new = request.POST.get("new_password1", "")
        if form.is_valid():
            if len(new) < 4:
                form.add_error("new_password1", "4자 이상으로 정해 주세요.")
            elif request.user.check_password(new):
                form.add_error("new_password1", "지금 비밀번호와 다르게 정해 주세요.")
            else:
                user = form.save()
                update_session_auth_hash(request, user)  # 바꾼 기기에서는 로그인 유지
                messages.success(request, "비밀번호를 바꿨어요")
                return redirect("settings")
    errors = {name: field_errors[0] for name, field_errors in form.errors.items()}
    if "old_password" in errors:
        errors["old_password"] = "지금 비밀번호가 맞지 않아요."
    if "new_password2" in errors:
        errors["new_password2"] = "새 비밀번호가 서로 달라요."
    return render(request, "sicklog/password_change.html", {"errors": errors})


@require_POST
@superuser_required
def user_reset_password(request, pk):
    user = get_object_or_404(User, pk=pk)
    if user.is_superuser:
        messages.error(request, "관리자 비밀번호는 여기서 바꿀 수 없어요")
    else:
        user.set_password(settings.DEFAULT_USER_PASSWORD)
        user.save(update_fields=["password"])
        messages.success(request, f"{user.display_name} 님 비밀번호를 {settings.DEFAULT_USER_PASSWORD}으로 바꿨어요")
    return redirect("settings")


# ---------------------------------------------------------------- push / PWA

@require_POST
@login_required
def push_subscribe(request):
    try:
        data = json.loads(request.body)
        endpoint, keys = data["endpoint"], data["keys"]
        PushSubscription.objects.update_or_create(
            endpoint=endpoint,
            defaults={"user": request.user, "p256dh": keys["p256dh"], "auth": keys["auth"],
                      "user_agent": request.headers.get("User-Agent", "")[:300]},
        )
    except (ValueError, KeyError):
        return JsonResponse({"ok": False}, status=400)
    return JsonResponse({"ok": True})


@require_POST
@login_required
def push_unsubscribe(request):
    try:
        endpoint = json.loads(request.body)["endpoint"]
    except (ValueError, KeyError):
        return JsonResponse({"ok": False}, status=400)
    PushSubscription.objects.filter(endpoint=endpoint, user=request.user).delete()
    return JsonResponse({"ok": True})


def manifest(request):
    data = {
        "name": "아파요",
        "short_name": "아파요",
        "description": "아기가 아플 때 함께 쓰는 증상·체온·해열제·병원 기록",
        "lang": "ko",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#EEF1F5",
        "theme_color": "#EEF1F5",
        "icons": [
            {"src": static("icons/icon-192.png"), "sizes": "192x192", "type": "image/png"},
            {"src": static("icons/icon-512.png"), "sizes": "512x512", "type": "image/png"},
            {"src": static("icons/icon-maskable-512.png"), "sizes": "512x512", "type": "image/png",
             "purpose": "maskable"},
        ],
    }
    return JsonResponse(data, content_type="application/manifest+json", json_dumps_params={"ensure_ascii": False})


@never_cache
def service_worker(request):
    path = settings.BASE_DIR / "static" / "js" / "sw.js"
    response = HttpResponse(path.read_text(encoding="utf-8"), content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/"
    return response


def offline(request):
    return render(request, "offline.html")


def healthz(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return HttpResponse("ok", content_type="text/plain")
