from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from fever import views

urlpatterns = [
    path("", views.home, name="home"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("history/", views.history, name="history"),
    path("guide/", views.guide, name="guide"),
    path("records/temperature/", views.temperature_create, name="temperature_create"),
    path("records/medication/", views.medication_create, name="medication_create"),
    path("babies/", views.baby_list, name="baby_list"),
    path("babies/new/", views.baby_create, name="baby_create"),
    path("babies/<int:pk>/", views.baby_detail, name="baby_detail"),
    path("babies/<int:pk>/select/", views.baby_select, name="baby_select"),
    path("babies/<int:pk>/weight/", views.baby_weight, name="baby_weight"),
    path("babies/<int:pk>/guardians/add/", views.guardian_add, name="guardian_add"),
    path("babies/<int:pk>/guardians/<int:user_id>/remove/", views.guardian_remove, name="guardian_remove"),
    path("settings/", views.settings_view, name="settings"),
    path("settings/notifications/", views.update_notifications, name="update_notifications"),
    path("settings/theme/", views.update_theme, name="update_theme"),
    path("settings/users/add/", views.user_add, name="user_add"),
    path("settings/users/<int:pk>/delete/", views.user_delete, name="user_delete"),
    path("api/users/lookup/", views.user_lookup, name="user_lookup"),
    path("push/subscribe/", views.push_subscribe, name="push_subscribe"),
    path("push/unsubscribe/", views.push_unsubscribe, name="push_unsubscribe"),
    path("manifest.webmanifest", views.manifest, name="manifest"),
    path("sw.js", views.service_worker, name="service_worker"),
    path("offline/", views.offline, name="offline"),
    path("healthz", views.healthz, name="healthz"),
    path("django-admin/", admin.site.urls),
]
