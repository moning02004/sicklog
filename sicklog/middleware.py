import copy
from urllib.parse import urlsplit

from django.contrib import messages
from django.http import JsonResponse, QueryDict
from django.urls import Resolver404, resolve


class AjaxFormMiddleware:
    """화면에서 fetch로 보낸 폼(X-Requested-With: fetch)의 결과를 JSON으로 바꾼다.

    뷰는 평소처럼 messages + redirect(성공) 또는 다시 그리기(실패)를 돌려주고,
    화면은 이 JSON을 받아 이전 화면으로 돌아가거나(history.back) 그 자리에서 새로 고친다.

    저장하고 지금 화면을 새로 그릴 때(X-Reload: 지금 주소)는 성공하면 그 화면을 바로 그려 돌려준다.
    휴대폰에서 '저장 → 화면 다시 받기'로 두 번 오가던 것을 한 번으로 줄인다.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.method != "POST" or request.headers.get("X-Requested-With") != "fetch":
            return response
        is_redirect = response.status_code in (301, 302, 303)
        is_page = response.status_code == 200 and response.get("Content-Type", "").startswith("text/html")
        if not (is_redirect or is_page):
            return response
        texts = [(m.level_tag, str(m)) for m in messages.get_messages(request)]  # 읽은 메시지는 저장되지 않는다
        errors = [text for tag, text in texts if tag == "error"]
        ok = is_redirect and not errors
        if ok and request.headers.get("X-Reload"):
            page = self.render_page(request, request.headers["X-Reload"])
            if page is not None:
                return page
        return JsonResponse({
            "ok": ok,
            "next": response.get("Location") if is_redirect else None,
            "message": next((text for tag, text in texts if tag != "error"), ""),
            "error": errors[0] if errors else ("" if ok else "저장하지 못했어요. 입력한 내용을 확인해 주세요"),
        }, status=200 if ok else 400)

    @staticmethod
    def render_page(request, url):
        """같은 사이트의 화면 하나를 GET으로 그린다. 바로 그릴 수 없으면(다른 곳으로 보내는 등) None.
        이번 요청의 메시지는 그 화면 안에 함께 그려져 알림으로 뜬다."""
        parts = urlsplit(url)
        try:
            match = resolve(parts.path)
        except Resolver404:
            return None
        page = copy.copy(request)
        page.method = "GET"
        page.META = {**request.META, "REQUEST_METHOD": "GET", "QUERY_STRING": parts.query}
        page.GET, page.POST = QueryDict(parts.query), QueryDict()
        page.path = page.path_info = parts.path
        page.resolver_match = match
        response = match.func(page, *match.args, **match.kwargs)
        if hasattr(response, "render"):
            response = response.render()
        if response.status_code != 200 or not response.get("Content-Type", "").startswith("text/html"):
            return None
        response["X-Page-Url"] = parts.path + (f"?{parts.query}" if parts.query else "")
        return response
