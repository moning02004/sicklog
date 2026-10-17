from django.conf import settings


def app(request):
    match = getattr(request, "resolver_match", None)
    return {
        "url_name": match.url_name if match else "",
        "vapid_public_key": settings.VAPID_PUBLIC_KEY,
    }
