from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from shadowing_video_studio.speech_api import create_speech_service
from shadowing_video_studio.speech_api import router as speech_router
from shadowing_video_studio.text_api import router as text_router


@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.speech = create_speech_service()
    try:
        yield
    finally:
        await application.state.speech.close()


app = FastAPI(
    title="Shadowing Video Studio",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(text_router)
app.include_router(speech_router)


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, _error: RequestValidationError) -> JSONResponse:
    # Pydantic's default validation response echoes submitted values, including private source.
    detail = (
        "Invalid speech request."
        if request.url.path.startswith("/api/speech/")
        else "Invalid text preparation request."
    )
    return JSONResponse(status_code=422, content={"detail": detail})


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
