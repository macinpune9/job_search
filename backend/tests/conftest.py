import io
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

_tmp = tempfile.mkdtemp(prefix="jobpilot-test-")
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_tmp}/test.db", "STORAGE_DIR": f"{_tmp}/storage", "SECRET_KEY": "test-secret-key-0123456789",
    "RATE_LIMIT_AUTH_PER_MIN": "100000", "RATE_LIMIT_DEFAULT_PER_MIN": "100000", "SANDBOX_MODE": "true",
    "RETRY_BASE_SECONDS": "0",
})

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import connectors, ratelimit  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services import applications as appsvc  # noqa: E402

NOW = datetime.now(timezone.utc)


def iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")


def ms(days_ago: float) -> int:
    return int((NOW - timedelta(days=days_ago)).timestamp() * 1000)


class FakeWeb:
    """Mutable fake of the public job-board endpoints, served through httpx.MockTransport."""

    def __init__(self):
        self.greenhouse: dict[str, list] = {}
        self.lever: dict[str, list] = {}
        self.fail: set[str] = set()
        self.calls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        host, path = request.url.host, request.url.path
        if host == "boards-api.greenhouse.io":
            board = path.split("/")[3]
            if f"greenhouse:{board}" in self.fail:
                return httpx.Response(500)
            if board not in self.greenhouse:
                return httpx.Response(404)
            return httpx.Response(200, json={"jobs": self.greenhouse[board]})
        if host == "api.lever.co":
            board = path.split("/")[-1]
            if f"lever:{board}" in self.fail:
                return httpx.Response(500)
            if board not in self.lever:
                return httpx.Response(404)
            skip, limit = int(request.url.params.get("skip", 0)), int(request.url.params.get("limit", 100))
            return httpx.Response(200, json=self.lever[board][skip:skip + limit])
        return httpx.Response(404)


def gh_job(jid, title, days_ago=2, content="<p>Python and SQL required. Remote friendly.</p>", location="Remote", company="Acme", first_published=True):
    j = {"id": jid, "title": title, "updated_at": iso(0.1), "location": {"name": location}, "company_name": company,
         "absolute_url": f"https://boards.greenhouse.io/acme/jobs/{jid}?gh_src=abc", "content": content}
    if first_published:
        j["first_published"] = iso(days_ago)
    return j


def lever_job(jid, title, days_ago=2, desc="Python and SQL required.", location="Remote", commitment="Full-time"):
    return {"id": jid, "text": title, "createdAt": ms(days_ago), "categories": {"location": location, "commitment": commitment},
            "descriptionPlain": desc, "lists": [], "hostedUrl": f"https://jobs.lever.co/globex/{jid}", "applyUrl": f"https://jobs.lever.co/globex/{jid}/apply"}


@pytest.fixture()
def web():
    w = FakeWeb()
    connectors.set_factory(lambda name: connectors.REGISTRY[name](httpx.Client(transport=httpx.MockTransport(w.handler))))
    yield w
    connectors.set_factory(None)


@pytest.fixture(autouse=True)
def clean_db():
    import shutil
    shutil.rmtree(os.environ["STORAGE_DIR"], ignore_errors=True)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    ratelimit.reset()
    appsvc.reset_submitters()
    yield


@pytest.fixture()
def client():
    return TestClient(app)


PASSWORD = "correct-horse-9"


def register(client, email="a@example.com"):
    r = client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    t = client.post("/api/auth/login", json={"email": email, "password": PASSWORD}).json()["access_token"]
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture()
def auth(client):
    return register(client)


RESUME_TEXT = """Jane Doe
jane@example.com | +1 555 123 4567

Summary
Backend engineer who builds reliable data services.

Skills
Python, SQL, PostgreSQL, Docker

Experience
Senior Software Engineer, Initech
Jan 2020 - Present
- Built Python services handling 2 million requests per day
- Maintained PostgreSQL databases and wrote SQL reports
- Mentored three junior engineers

Software Developer at Hooli
Mar 2016 - Dec 2019
- Developed internal tools in Python
- Wrote Docker images for deployment

Education
B.Sc. Computer Science, State University, 2015

Certifications
AWS Certified Developer
"""


def docx_bytes(text: str = RESUME_TEXT) -> bytes:
    import docx
    d = docx.Document()
    for line in text.splitlines():
        d.add_paragraph(line)
    b = io.BytesIO()
    d.save(b)
    return b.getvalue()


def pdf_bytes(text: str = RESUME_TEXT) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    b = io.BytesIO()
    c = canvas.Canvas(b, pagesize=A4)
    y = 800
    for line in text.splitlines():
        c.drawString(40, y, line)
        y -= 14
    c.save()
    return b.getvalue()


def upload(client, auth, data=None, name="resume.docx"):
    data = data or docx_bytes()
    return client.post("/api/resumes", headers=auth, files={"file": (name, data, "application/octet-stream")})


def make_profile(client, auth, **over):
    body = {"profile_name": "Backend", "keywords": [{"term": "Python", "kind": "skill"}, {"term": "SQL", "kind": "skill"}],
            "role_preferences": {"target_titles": ["Software Engineer"]},
            "sources": [{"source": "greenhouse", "board": "acme"}], "min_match_score": 20}
    body.update(over)
    r = client.post("/api/search-profiles", headers=auth, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def run_now(profile_id):
    from app.services import engine
    with SessionLocal() as db:
        return engine.run_search(db, profile_id, "manual")
