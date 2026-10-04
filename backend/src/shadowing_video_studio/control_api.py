"""Local human review UI, deliberately separate from AI tool capabilities."""

from html import escape
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from shadowing_video_studio.control import ApplicationControl, ControlError
from shadowing_video_studio.speech_api import get_speech_service, verify_local_request
from shadowing_video_studio.video_api import get_video_service

router = APIRouter(prefix="/control", dependencies=[Depends(verify_local_request)])


def get_control(request: Request) -> ApplicationControl:
    if not hasattr(request.app.state, "control"):
        request.app.state.control = ApplicationControl(
            get_speech_service(request), get_video_service(request)
        )
    return request.app.state.control


def page(content: str) -> HTMLResponse:
    return HTMLResponse(
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Review AI requests — Shadowing Video Studio</title>"
        "<body><main><h1>Review AI requests</h1>" + content + "</main></body></html>",
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; media-src 'self'; img-src 'self'; "
            "form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
        },
    )


@router.get("", response_class=HTMLResponse, include_in_schema=False)
def reviews(request: Request) -> HTMLResponse:
    rows = get_control(request).list_reviews()
    links = "".join(
        f'<li><a href="/control/{escape(item["requestId"])}">'
        f"{escape(item['operation'])} — {escape(item['requestId'])}</a> "
        f"({escape(item['state'])})</li>"
        for item in rows
    )
    return page(
        "<p>Requests last for this service session only. Approval does not start work; "
        "the AI must execute the approved request.</p><ul>" + links + "</ul>"
    )


@router.get("/{request_id}", response_class=HTMLResponse, include_in_schema=False)
def review(request_id: str, request: Request) -> HTMLResponse:
    try:
        item = get_control(request).review(request_id)
    except ControlError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    payload = item.payload
    rows = []
    for sentence in payload.sentences:
        audio_id = getattr(sentence, "assetId", None)
        audio = (
            f'<audio controls preload="none" src="/api/speech/assets/{audio_id}"></audio>'
            if audio_id
            else ""
        )
        illustration = getattr(sentence, "illustrationAssetId", None)
        rows.append(
            f"<li><p>{escape(sentence.id)}: {escape(sentence.text)}</p>"
            + audio
            + (
                f"<p>Illustration: {escape(illustration)}</p>"
                f'<img src="/api/visuals/assets/{illustration}" alt="Illustration" width="240">'
                if illustration
                else ""
            )
            + "</li>"
        )
    background = getattr(payload, "backgroundAssetId", None)
    background_preview = (
        f'<p>Background preview:</p><img src="/api/visuals/assets/{background}" '
        'alt="Video background" width="480">'
        if background
        else ""
    )
    details = (
        f"<p>Operation: {escape(item.operation)}. State: {escape(item.state)}.</p>"
        f"<p>Voice: {escape(payload.voice)}. Configuration: "
        f"{escape(payload.configurationFingerprint or '')}</p>"
        f"<p>Regenerate: {getattr(payload, 'force', False)}. Background: "
        f"{escape(getattr(payload, 'backgroundAssetId', None) or 'default')}</p>"
        + background_preview
        + "<ol>"
        + "".join(rows)
        + "</ol>"
    )
    if item.state == "needs_review":
        instruction = (
            "Read every sentence before approving speech."
            if item.operation == "speech"
            else "Listen to every audio segment and review all sentences and image previews "
            "before approving video."
        )
        details += (
            f"<p>{instruction} Approval applies only to these frozen inputs for 30 minutes "
            "after the request was created.</p>"
            f'<form method="post" action="/control/{item.id}/decision">'
            f'<input type="hidden" name="nonce" value="{item.nonce}">'
            '<button name="decision" value="approve">I reviewed these inputs — approve</button> '
            '<button name="decision" value="reject">Reject</button></form>'
        )
    return page(details + '<p><a href="/control">All requests</a></p>')


@router.post("/{request_id}/decision", include_in_schema=False)
async def decide(request_id: str, request: Request) -> RedirectResponse:
    if request.headers.get("content-type", "").split(";")[0] != "application/x-www-form-urlencoded":
        raise HTTPException(status_code=415, detail="Use the local review form.")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 1024:
            raise HTTPException(status_code=413, detail="Invalid review form.")
    try:
        form = parse_qs(body.decode("ascii"), strict_parsing=True, max_num_fields=2)
        if set(form) != {"nonce", "decision"} or any(len(value) != 1 for value in form.values()):
            raise ValueError
        get_control(request).decide(request_id, form["nonce"][0], form["decision"][0])
    except (ValueError, UnicodeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid review form.") from exc
    except ControlError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return RedirectResponse(f"/control/{request_id}", status_code=303)
