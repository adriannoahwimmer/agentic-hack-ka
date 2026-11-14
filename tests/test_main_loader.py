"""Tests des Feature-Loaders und des Spiel-Mounts in main.py.

Feature-Module sind Registrierungspunkte (Design.md, "Vertrag"): fehlende werden
übersprungen, kaputte Importe brechen ab, register/router/startup/shutdown greifen.
"""

import sys
import textwrap

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import main
from hub import Hub

OK_MODULE = """
from fastapi import APIRouter

registered = []
started = []
router = APIRouter()


@router.get("/feat-ok")
def ping():
    return {"ok": True}


def register(hub):
    registered.append(hub)


async def startup():
    started.append("up")


async def shutdown():
    started.append("down")
"""


@pytest.fixture
def feature_dir(tmp_path, monkeypatch):
    """Legt Test-Featuremodule in tmp_path an und räumt sys.modules danach auf."""
    (tmp_path / "fk_feat_ok.py").write_text(
        textwrap.dedent(OK_MODULE), encoding="utf-8"
    )
    (tmp_path / "fk_feat_broken.py").write_text(
        "import fk_dependency_that_does_not_exist\n", encoding="utf-8"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    yield tmp_path
    for name in ("fk_feat_ok", "fk_feat_broken"):
        sys.modules.pop(name, None)


def _app() -> FastAPI:
    app = FastAPI(lifespan=main.lifespan)
    app.state.feature_hooks = {"startup": [], "shutdown": []}
    return app


def test_loader_registers_router_and_hooks(feature_dir, fresh_hub):
    app = _app()
    hub = Hub()
    loaded = main.load_features(app, hub, ("fk_feat_missing", "fk_feat_ok"))
    assert loaded == ["fk_feat_ok"]

    module = sys.modules["fk_feat_ok"]
    assert module.registered == [hub]
    with TestClient(app) as client:
        assert client.get("/feat-ok").json() == {"ok": True}
        assert module.started == ["up"]
    assert module.started == ["up", "down"]


def test_loader_raises_on_broken_import(feature_dir):
    with pytest.raises(ModuleNotFoundError, match="fk_dependency_that_does_not_exist"):
        main.load_features(_app(), Hub(), ("fk_feat_broken",))


def test_real_feature_list_loads_without_error():
    # Fehlende Feature-Module sind erlaubt; vorhandene dürfen nicht crashen.
    assert set(main.load_features(_app(), Hub())) <= set(main.FEATURE_MODULES)


def test_static_mount_only_with_build(tmp_path):
    app = _app()
    assert main.mount_static(app, tmp_path) is False

    (tmp_path / "index.html").write_text("<title>Fächerstadt</title>", encoding="utf-8")
    assert main.mount_static(app, tmp_path) is True
    r = TestClient(app).get("/play/")
    assert r.status_code == 200
    assert "Fächerstadt" in r.text
