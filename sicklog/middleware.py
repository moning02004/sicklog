from django.contrib import messages
from django.http import JsonResponse


class AjaxFormMiddleware:
    """화면에서 fetch로 보낸 폼(X-Requested-With: fetch)의 결과를 JSON으로 바꾼다.

    뷰는 평소처럼 messages + redirect(성공) 또는 다시 그리기(실패)를 돌려주고,
    화면은 이 JSON을 받아 이전 화면으로 돌아가거나(history.back) 그 자리에서 새로 고친다.
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
        return JsonResponse({
            "ok": ok,
            "next": response.get("Location") if is_redirect else None,
            "message": next((text for tag, text in texts if tag != "error"), ""),
            "error": errors[0] if errors else ("" if ok else "저장하지 못했어요. 입력한 내용을 확인해 주세요"),
        }, status=200 if ok else 400)
