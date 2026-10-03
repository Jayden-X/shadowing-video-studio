from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from shadowing_video_studio.text_api import router as text_router

app = FastAPI(
    title="Shadowing Video Studio",
    version="0.1.0",
)
app.include_router(text_router)


@app.exception_handler(RequestValidationError)
async def invalid_request(_request: Request, _error: RequestValidationError) -> JSONResponse:
    # Pydantic's default validation response echoes submitted values, including private source.
    return JSONResponse(status_code=422, content={"detail": "Invalid text preparation request."})


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
