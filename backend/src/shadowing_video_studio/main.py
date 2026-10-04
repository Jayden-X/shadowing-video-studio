import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from shadowing_video_studio.control import ApplicationControl
from shadowing_video_studio.control_api import router as control_router
from shadowing_video_studio.frontend_serving import configure_frontend
from shadowing_video_studio.mcp_control import LocalMcpAccess, McpSettings, create_mcp
from shadowing_video_studio.project_api import create_project_service
from shadowing_video_studio.project_api import router as project_router
from shadowing_video_studio.speech_api import create_speech_service
from shadowing_video_studio.speech_api import router as speech_router
from shadowing_video_studio.text_api import router as text_router
from shadowing_video_studio.video_api import create_video_service
from shadowing_video_studio.video_api import router as video_router
from shadowing_video_studio.visual_api import create_visual_service
from shadowing_video_studio.visual_api import router as visual_router


@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.mcp_settings = McpSettings.from_environment()
    application.state.mcp = create_mcp(application)
    application.state.mcp_http = application.state.mcp.streamable_http_app()
    application.state.projects = await asyncio.to_thread(create_project_service)
    application.state.speech = create_speech_service(application.state.projects.assets)
    application.state.visuals = create_visual_service()
    application.state.video = create_video_service(
        application.state.speech,
        visuals=application.state.visuals.library,
        project_store=application.state.projects.store,
    )
    application.state.control = ApplicationControl(
        application.state.speech, application.state.video
    )
    try:
        async with application.state.mcp.session_manager.run():
            yield
    finally:
        if hasattr(application.state, "control"):
            await application.state.control.close()
        await application.state.video.close()
        await application.state.speech.close()


app = FastAPI(
    title="Shadowing Video Studio",
    version="0.1.0",
    lifespan=lifespan,
)
app.mount("/mcp", LocalMcpAccess(None, app))
app.include_router(control_router)
app.include_router(text_router)
app.include_router(speech_router)
app.include_router(video_router)
app.include_router(visual_router)
app.include_router(project_router)
configure_frontend(app)


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, _error: RequestValidationError) -> JSONResponse:
    # Pydantic's default validation response echoes submitted values, including private source.
    detail = (
        "Invalid project request."
        if request.url.path.startswith("/api/projects")
        else (
            "Invalid visual request."
            if request.url.path.startswith("/api/visuals/")
            else (
                "Invalid video request."
                if request.url.path.startswith("/api/video/")
                else (
                    "Invalid speech request."
                    if request.url.path.startswith("/api/speech/")
                    else "Invalid text preparation request."
                )
            )
        )
    )
    return JSONResponse(status_code=422, content={"detail": detail})


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
