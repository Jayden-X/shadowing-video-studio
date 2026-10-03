from fastapi import FastAPI
from fastapi.testclient import TestClient

from shadowing_video_studio.frontend_serving import configure_frontend


def test_built_frontend_serves_only_public_assets(tmp_path):
    (tmp_path / "index.html").write_text("<h1>Shadowing Video Studio</h1>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log('ready')")
    (tmp_path / "private.txt").write_text("not a public asset")
    app = FastAPI()
    configure_frontend(app, str(tmp_path))
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/").status_code == 200
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/private.txt").status_code == 404
        assert client.get("/api/not-an-api").status_code == 404


def test_missing_frontend_configuration_is_actionable():
    app = FastAPI()
    configure_frontend(app, "")
    with TestClient(app) as client:
        assert client.get("/").status_code == 503
