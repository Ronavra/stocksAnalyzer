from types import SimpleNamespace

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

from app.main import app as api_app
from app.routers.retry_clock_skew import RetryClockSkewRoute


def test_retries_only_future_jwt_error(monkeypatch):
    delays = []

    async def record_sleep(seconds):
        delays.append(seconds)

    monkeypatch.setattr("app.routers.retry_clock_skew.sleep", record_sleep)
    router = APIRouter(route_class=RetryClockSkewRoute)
    calls = []

    @router.get("/test")
    def endpoint():
        calls.append(1)
        if len(calls) == 1:
            raise APIError({"code": "PGRST303", "message": "JWT issued at future"})
        return {"ok": True}

    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).get("/test")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert len(calls) == 2
    assert delays == [1]


def test_persistent_clock_skew_returns_503(monkeypatch):
    async def no_wait(_seconds):
        pass

    monkeypatch.setattr("app.routers.retry_clock_skew.sleep", no_wait)
    router = APIRouter(route_class=RetryClockSkewRoute)
    calls = []

    @router.get("/test")
    def endpoint():
        calls.append(1)
        raise APIError({"code": "PGRST303", "message": "JWT issued at future"})

    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).get("/test")
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"
    assert len(calls) == 4


def test_other_auth_errors_are_not_retried():
    router = APIRouter(route_class=RetryClockSkewRoute)
    calls = []

    @router.get("/test")
    def endpoint():
        calls.append(1)
        raise APIError({"code": "PGRST301", "message": "Invalid JWT"})

    app = FastAPI()
    app.include_router(router)
    response = TestClient(app, raise_server_exceptions=False).get("/test")
    assert response.status_code == 500
    assert len(calls) == 1


def test_scorecard_recovers_from_transient_postgrest_rejection(monkeypatch):
    calls = []

    class FakeQuery:
        def order(self, *_args, **_kwargs): return self
        def range(self, *_args): return self
        def eq(self, *_args): return self
        def limit(self, *_args): return self

        def select(self, _columns):
            return self

        def execute(self):
            calls.append(1)
            if len(calls) == 1:
                raise APIError({"code": "PGRST303", "message": "JWT issued at future"})
            return SimpleNamespace(data=[])

    class FakeDb:
        def table(self, _name):
            return FakeQuery()

    async def no_wait(_seconds):
        pass

    monkeypatch.setattr("app.routers.research.get_supabase", FakeDb)
    monkeypatch.setattr("app.routers.retry_clock_skew.sleep", no_wait)
    response = TestClient(api_app).get("/api/v1/research/scorecard")
    assert response.status_code == 200
    assert response.json()["overall"]["evaluated"] == 0
    assert len(calls) == 4 # prediction retry, then cohorts and benchmark lookup
