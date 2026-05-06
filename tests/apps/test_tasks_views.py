"""Smoke tests for the tasks app views.

The tests are pure-Django (no Neo4j needed). The auth-protected routes
should redirect anonymous users to the login page.
"""

from __future__ import annotations

import pytest
from django.test import Client


@pytest.mark.django_db
def test_landingRendersForAnonymous():
    client = Client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"CUTIEE" in resp.content
    assert b"/accounts/login/" in resp.content


@pytest.mark.django_db
def test_tasksRedirectsAnonymousToLogin():
    client = Client()
    resp = client.get("/tasks/")
    assert resp.status_code in (302, 301)
    assert "/accounts/login/" in resp.url


@pytest.mark.django_db
def test_dashboardRedirectsAnonymousToLogin():
    client = Client()
    resp = client.get("/tasks/dashboard/")
    assert resp.status_code in (302, 301)


@pytest.mark.django_db
def test_vlmHealthEndpointRespondsJson():
    client = Client()
    resp = client.get("/api/vlm-health/")
    assert resp.status_code == 200
    body = resp.json()
    assert "status" in body
    assert "env" in body


def test_runtimeContextDerivesNovncUrlFromWorkerUrl(monkeypatch: pytest.MonkeyPatch):
    from cutiee_site.context_processors import runtime

    monkeypatch.delenv("CUTIEE_NOVNC_URL", raising=False)
    monkeypatch.setenv("CUTIEE_WORKER_EXTERNAL_URL", "https://cutiee-worker-demo.onrender.com/")

    assert runtime(None)["NOVNC_URL"] == "https://cutiee-worker-demo.onrender.com/vnc.html"


def test_runtimeContextPrefersExplicitNovncUrl(monkeypatch: pytest.MonkeyPatch):
    from cutiee_site.context_processors import runtime

    monkeypatch.setenv("CUTIEE_NOVNC_URL", "https://worker.example.com/vnc.html")
    monkeypatch.setenv("CUTIEE_WORKER_EXTERNAL_URL", "https://cutiee-worker-demo.onrender.com")

    assert runtime(None)["NOVNC_URL"] == "https://worker.example.com/vnc.html"


@pytest.mark.django_db
def test_livenessEndpointReturnsOk():
    # Render's healthCheckPath targets /health/ and a deploy is marked
    # failed when this path does not return 2xx in the grace window.
    client = Client()
    resp = client.get("/health/")
    assert resp.status_code == 200
    assert resp.content == b"ok"


@pytest.mark.django_db
def test_vlmHealthHtmxEscapesModelValue(monkeypatch: pytest.MonkeyPatch):
    # The banner interpolates CUTIEE_CU_MODEL into the HTML attribute.
    # Render's operator controls env but defense-in-depth escaping must
    # block an HTML-breaking value from leaking into the attribute.
    monkeypatch.setenv("CUTIEE_ENV", "production")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("CUTIEE_CU_MODEL", 'model"><script>alert(1)</script>')
    client = Client()
    resp = client.get("/api/vlm-health/", HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    body = resp.content.decode("utf-8")
    assert "<script>" not in body
    assert "&lt;script&gt;" in body or "&quot;" in body


@pytest.mark.django_db
def test_safeIntCoercesMalformedQueryParam():
    # Malformed query ints must not crash the endpoint; login_required
    # should redirect anonymous callers before the parser ever runs.
    client = Client()
    resp = client.get("/tasks/api/cost-timeseries/?days=abc")
    assert resp.status_code in (302, 301)


@pytest.mark.django_db
def test_deleteTaskRejectsRequestsWithoutCsrfToken():
    # Destructive POSTs must require a CSRF token even for logged-in
    # users; otherwise a cross-site form could delete a task on their
    # behalf.
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.create_user(username="alice", password="pw")
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    resp = client.post("/tasks/any-task-id/delete/")
    assert resp.status_code == 403


@pytest.mark.django_db
def test_previewPendingUrlResolves():
    # Regression guard: detail.html references tasks:preview_pending via
    # {% url %}. A NoReverseMatch here was the 500 on every detail page.
    from django.urls import reverse

    url = reverse("tasks:preview_pending", kwargs={"execution_id": "abc-123"})
    assert url.endswith("/tasks/api/preview/abc-123/")


@pytest.mark.django_db
def test_previewDecideUrlResolves():
    from django.urls import reverse

    url = reverse(
        "tasks:preview_decide",
        kwargs={"execution_id": "abc-123", "decision": "approve"},
    )
    assert url.endswith("/tasks/api/preview/abc-123/approve/")


@pytest.mark.django_db
def test_baseTemplateInjectsHtmxCsrfHeader():
    # HTMX POSTs from dynamically-rendered modals (approval, preview)
    # must include X-CSRFToken. The body-level hx-headers is the single
    # source of truth; losing it would silently 403 approve/cancel clicks
    # in production.
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.create_user(username="bob", password="pw")
    client = Client()
    client.force_login(user)
    resp = client.get("/tasks/dashboard/")
    assert resp.status_code == 200
    body = resp.content.decode("utf-8")
    assert "X-CSRFToken" in body
    assert "hx-headers" in body


@pytest.mark.django_db
def testRunTaskRejectsAnyActiveExecutionForUser(monkeypatch: pytest.MonkeyPatch):
    from django.contrib.auth import get_user_model
    from apps.tasks import api as tasksApi

    user = get_user_model().objects.create_user(username="drew", password="pw")
    client = Client()
    client.force_login(user)
    didCreateExecution = False

    def fakeCreateExecution(**_kwargs):
        nonlocal didCreateExecution
        didCreateExecution = True

    monkeypatch.setattr(
        tasksApi.tasksRepo,
        "getTask",
        lambda _userId, taskId: {"id": taskId, "description": "new task", "initial_url": ""},
    )
    monkeypatch.setattr(
        tasksApi.tasksRepo,
        "createExecutionForIdleUser",
        lambda **_kwargs: (
            None,
            {"id": "exec-active", "task_id": "task-active", "status": "running"},
        ),
    )
    monkeypatch.setattr(tasksApi.tasksRepo, "createExecution", fakeCreateExecution)

    resp = client.post("/tasks/task-new/run/")

    assert resp.status_code == 409
    assert resp.json() == {
        "status": "already_running",
        "task_id": "task-active",
        "execution_id": "exec-active",
    }
    assert didCreateExecution is False


@pytest.mark.django_db
def testRunTaskIgnoresMockOverrideInProduction(
    monkeypatch: pytest.MonkeyPatch,
    settings,
):
    from django.contrib.auth import get_user_model
    from apps.tasks import api as tasksApi

    settings.CUTIEE_ENV = "production"
    user = get_user_model().objects.create_user(username="prod-user", password="pw")
    client = Client()
    client.force_login(user)
    capturedThreadKwargs = {}

    class FakeThread:
        def __init__(self, *, target, kwargs, daemon):
            del target, daemon
            capturedThreadKwargs.update(kwargs)

        def start(self):
            return None

    monkeypatch.setattr(
        tasksApi.tasksRepo,
        "getTask",
        lambda _userId, taskId: {"id": taskId, "description": "new task", "initial_url": ""},
    )
    monkeypatch.setattr(
        tasksApi.tasksRepo,
        "createExecutionForIdleUser",
        lambda **kwargs: ({"id": kwargs["executionId"], "status": "running"}, None),
    )
    monkeypatch.setattr(tasksApi.threading, "Thread", FakeThread)

    resp = client.post("/tasks/task-prod/run/?use_mock=true")

    assert resp.status_code == 200
    assert capturedThreadKwargs["useMockAgent"] is None


def testBackgroundFailureFinalizesRunningExecution(monkeypatch: pytest.MonkeyPatch):
    from apps.tasks import api as tasksApi

    finalized = {}
    updated = {}

    def fakeRunTaskForUser(**_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(tasksApi, "runTaskForUser", fakeRunTaskForUser)
    monkeypatch.setattr(
        tasksApi.tasksRepo,
        "getExecution",
        lambda _userId, _executionId: {"id": "exec-failed", "status": "running"},
    )
    monkeypatch.setattr(
        tasksApi.tasksRepo,
        "finalizeExecution",
        lambda **kwargs: finalized.update(kwargs),
    )
    monkeypatch.setattr(
        tasksApi.tasksRepo,
        "updateTaskStatus",
        lambda **kwargs: updated.update(kwargs),
    )

    tasksApi._runInBackground(
        userId="user-1",
        taskId="task-1",
        description="task",
        initialUrl="",
        useMockAgent=None,
        executionId="exec-failed",
    )

    assert finalized["status"] == "failed"
    assert finalized["completionReason"] == "background_exception:RuntimeError"
    assert updated["status"] == "failed"
    assert updated["lastExecutionId"] == "exec-failed"


@pytest.mark.django_db
def test_previewDecideRejectsUnknownExecution():
    # Authorization boundary: if the execution does not exist under
    # the caller's User node, the endpoint must return 404 without
    # writing to Neo4j. Guards against execution-id enumeration.
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.create_user(username="carol", password="pw")
    client = Client()
    client.force_login(user)
    resp = client.post("/tasks/api/preview/missing-exec-id/approve/")
    assert resp.status_code == 404
