import json
from datetime import timedelta
from decimal import Decimal
from itertools import groupby

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import connection, transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from . import dosing
from .forms import BabyForm, MedicationForm, NotificationForm, TemperatureForm, UserCreateForm, WeightForm
from .models import Baby, Medication, PushSubscription, Temperature, User


class LoginView(auth_views.LoginView):
    template_name = "registration/login.html"
    redirect_authenticated_user = True


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
            nd["sub"] = (f"다른 계열 복용 후 2시간 · {wait}" if nd["reason"] == "cross"
                         else f"같은 계열 {int(nd['klass'].gap.total_seconds() // 3600)}시간 간격 · {wait}")
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

@require_baby
def home(request, baby):
    now = timezone.now()
    temps, meds, merged = baby_records(baby)
    last_temp = temps[-1] if temps else None
    last = merged[-1] if merged else None
    recovered = dosing.is_recovered(last.recorded_at if last else None, now)
    episode = dosing.split_episodes(merged)[-1] if merged else None

    chart_end = last.recorded_at + timedelta(minutes=30) if recovered else now
    chart_start = chart_end - timedelta(hours=24)
    chart = {
        "start": chart_start.isoformat(),
        "end": chart_end.isoformat(),
        "temps": [[t.recorded_at.isoformat(), float(t.value)] for t in temps if chart_start <= t.recorded_at <= chart_end],
        "meds": [[m.recorded_at.isoformat(), dosing.DRUGS[m.drug].initial, dosing.DRUGS[m.drug].cls]
                 for m in meds if chart_start <= m.recorded_at <= chart_end],
    }

    rows = dose_rows(meds, now)
    filt = request.GET.get("f", "all")
    recent = [r for r in reversed(merged) if filt == "all" or r.kind == filt][:5]

    sheet_data = {
        "weight": float(baby.weight_kg),
        "lastTemp": float(last_temp.value) if last_temp else None,
        "drugs": {
            key: {
                "name": d.name, "cls": d.cls, "conc": d.mg_per_ml,
                "suggested": float(dosing.suggested_ml(baby.weight_kg, key)),
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
    default_drug = next((k for k, d in dosing.DRUGS.items()
                         if next(r for r in rows if r["cls"] == d.cls)["ready"]), "tylenol")

    return render(request, "fever/home.html", {
        "baby": baby,
        "last_temp": last_temp,
        "last_temp_ago": dosing.humanize_ago(now - last_temp.recorded_at) if last_temp else "",
        "recovered": recovered,
        "episode": episode,
        "since_last_days": (now - last.recorded_at).days if last else 0,
        "dose_rows": rows,
        "any_ready": any(r["ready"] and not r["full"] for r in rows),
        "chart": chart,
        "recent": recent,
        "filter": filt,
        "sheet_data": sheet_data,
        "default_drug": default_drug,
        "methods": Temperature.Method.choices,
        "drugs": dosing.DRUGS,
        "default_temp": last_temp.value if last_temp else Decimal("37.5"),
    })


@require_baby
def history(request, baby):
    _, _, merged = baby_records(baby)
    filt = request.GET.get("f", "all")
    episodes = dosing.split_episodes(merged)
    recovered = bool(merged) and dosing.is_recovered(merged[-1].recorded_at)
    current = episodes[-1] if merged and not recovered else None
    past = list(reversed(episodes if recovered else episodes[:-1]))

    shown = [r for r in reversed(merged) if filt == "all" or r.kind == filt]
    groups = [(day, list(items)) for day, items in
              groupby(shown, key=lambda r: timezone.localtime(r.recorded_at).date())]
    today = timezone.localdate()
    return render(request, "fever/history.html", {
        "baby": baby, "groups": groups, "filter": filt, "current": current, "past": past,
        "today": today, "yesterday": today - timedelta(days=1),
    })


@require_baby
def guide(request, baby):
    cards = []
    for key, drug in dosing.DRUGS.items():
        cards.append({"drug": drug, "klass": dosing.CLASSES[drug.cls], "range": dosing.dose_range(baby.weight_kg, key),
                      "gap_hours": int(dosing.CLASSES[drug.cls].gap.total_seconds() // 3600)})
    return render(request, "fever/guide.html", {"baby": baby, "cards": cards})


# ---------------------------------------------------------------- records

@require_POST
@require_baby
def temperature_create(request, baby):
    form = TemperatureForm(request.POST)
    if form.is_valid():
        record = form.save(commit=False)
        record.baby, record.recorded_by = baby, request.user
        record.save()
        messages.success(request, f"{record.value}℃ 기록했어요")
    else:
        messages.error(request, next(iter(form.errors.values()))[0])
    return redirect("home")


@require_POST
@require_baby
def medication_create(request, baby):
    form = MedicationForm(request.POST)
    if form.is_valid():
        record = form.save(commit=False)
        record.baby, record.recorded_by = baby, request.user
        record.save()
        messages.success(request, f"{record.get_drug_display()} {record.amount_ml}mL 기록했어요")
    else:
        messages.error(request, next(iter(form.errors.values()))[0])
    return redirect("home")


# ---------------------------------------------------------------- babies

@login_required
def baby_list(request):
    return render(request, "fever/baby_list.html", {
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
    return render(request, "fever/baby_form.html", {"form": form, "guardians": guardians})


@login_required
def baby_detail(request, pk):
    baby = get_baby(request.user, pk)
    guardians = baby.guardians.order_by("date_joined")
    back = reverse("settings") if request.GET.get("from") == "settings" else reverse("home")
    return render(request, "fever/baby_detail.html", {"baby": baby, "guardians": guardians, "back_url": back})


@require_POST
@login_required
def baby_select(request, pk):
    baby = get_baby(request.user, pk)
    request.user.current_baby = baby
    request.user.save(update_fields=["current_baby"])
    messages.success(request, f"{ro(baby.name)} 바꿨어요")
    return redirect(request.POST.get("next") or "home")


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
            u.record_count = u.temperatures.count() + u.medications.count()
        ctx["users"] = users
    return render(request, "fever/settings.html", ctx)


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
            count = user.temperatures.all().delete()[0] + user.medications.all().delete()[0]
        name = user.display_name
        user.delete()  # 남긴 기록은 recorded_by만 비워지고 그대로 남는다
    messages.success(request, f"{name} 님과 기록 {count}건을 삭제했어요" if delete_records and count
                     else f"{name} 님을 삭제했어요. 기록은 그대로예요")
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
        "name": "열체크",
        "short_name": "열체크",
        "description": "아기가 아플 때 함께 보는 체온·해열제 기록",
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
