import pytest
from sqlalchemy import select

from app import connectors
from app.config import get_settings
from app.db import SessionLocal
from app.models import Job
from .conftest import iso, make_profile, register, run_now, upload

SPEC = "Python and SQL required. Zurich based."


def profile_for(client, auth, source, board, **kw):
    return make_profile(client, auth, sources=[{"source": source, "board": board}], min_match_score=0, **kw)


def job_rows(client, auth, **params):
    return client.get("/api/jobs", headers=auth, params={"qualified": "all", **params}).json()["items"]


# ---------------- Personio ----------------
def personio_xml(with_text=True, created="2026-09-20T10:00:00+00:00"):
    desc = (f"<jobDescriptions><jobDescription><name>Your role</name><value><![CDATA[<p>{SPEC}</p><script>x()</script>]]></value></jobDescription>"
            "</jobDescriptions>") if with_text else "<jobDescriptions></jobDescriptions>"
    return (f"<workzag-jobs><position><id>501</id><subcompany>Muster AG</subcompany><office>Zürich</office>"
            f"<additionalOffices><office>Bern</office></additionalOffices><department>IT</department><name>Python Engineer</name>{desc}"
            f"<employmentType>permanent</employmentType><schedule>full-time</schedule><createdAt>{created}</createdAt></position></workzag-jobs>").encode()


def test_personio_feed_parsing_language_fallback_and_tld_fallback(client, auth, web):
    upload(client, auth)
    web.personio["muster"] = {"tld": "com", "feeds": {None: personio_xml(with_text=False), "en": personio_xml(), "de": personio_xml()}}
    run = run_now(profile_for(client, auth, "personio", "muster")["id"])
    assert run.status == "completed", run.source_statistics
    j = job_rows(client, auth)[0]
    assert (j["title"], j["company"], j["location"], j["employment_type"]) == ("Python Engineer", "Muster AG", "Zürich, Bern", "permanent")
    assert j["posted_at"] and j["posted_at_reliable"]
    detail = client.get(f"/api/jobs/{j['id']}", headers=auth).json()
    assert SPEC in detail["description"] and "x()" not in detail["description"]
    assert detail["listings"][0]["source_url"] == "https://muster.jobs.personio.com/job/501"
    langs = [r.url.params.get("language") for r in web.requests if "personio" in r.url.host]
    assert None in langs and "en" in langs   # default feed was empty, so English was requested


def test_personio_rejects_malicious_xml_and_unknown_board(client, auth, web):
    upload(client, auth)
    bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]><workzag-jobs>&b;</workzag-jobs>'
    web.personio["evil"] = {"tld": "de", "feeds": {None: bomb}}
    run = run_now(make_profile(client, auth, sources=[{"source": "personio", "board": "evil"}, {"source": "personio", "board": "nope"}])["id"])
    assert run.source_statistics["personio:evil"]["status"] == "failed" and "invalid feed XML" in run.source_statistics["personio:evil"]["error"]
    assert "404" in run.source_statistics["personio:nope"]["error"]


# ---------------- SmartRecruiters ----------------
def sr_item(i, name="Backend Developer", remote=False):
    return {"id": str(i), "name": name, "company": {"name": "Beispiel SA"}, "releasedDate": iso(3),
            "location": {"city": "Geneva", "country": "ch", "remote": remote, "hybrid": False, "fullLocation": "Geneva, Switzerland"},
            "typeOfEmployment": {"label": "Full-time"}, "department": {"label": "IT"}, "experienceLevel": {"label": "Mid"}}


def sr_detail(i):
    return {"id": str(i), "postingUrl": f"https://jobs.smartrecruiters.com/beispiel/{i}", "applyUrl": f"https://jobs.smartrecruiters.com/beispiel/{i}?oga=true",
            "jobAd": {"sections": {"jobDescription": {"title": "Job Description", "text": f"<p>{SPEC}</p>"},
                                   "qualifications": {"title": "Qualifications", "text": "<ul><li>Five years</li></ul>"}}}}


def test_smartrecruiters_list_detail_and_cap(client, auth, web, monkeypatch):
    monkeypatch.setattr(connectors.REGISTRY["smartrecruiters"], "DETAIL_CAP", 2)
    upload(client, auth)
    items = [sr_item(i, name=f"Backend Developer {i}", remote=(i == 1)) for i in range(1, 5)]   # distinct titles: identical postings would be merged
    web.smartrecruiters["beispiel"] = {"list": items, "detail": {str(i): sr_detail(i) for i in range(1, 5)}}
    run = run_now(profile_for(client, auth, "smartrecruiters", "beispiel")["id"])
    assert run.stats["retrieved"] == 4 and run.status == "completed"
    rows = {r["id"]: r for r in job_rows(client, auth)}
    assert len(rows) == 4
    detailed = [client.get(f"/api/jobs/{i}", headers=auth).json() for i in rows]
    with_desc = [d for d in detailed if SPEC in d["description"]]
    assert len(with_desc) == 2                                   # detail requests are capped
    assert "Qualifications" in with_desc[0]["description"] and with_desc[0]["listings"][0]["application_url"].endswith("oga=true")
    assert any(r["remote_status"] == "remote" for r in rows.values())
    assert [d for d in detailed if d["listings"][0]["source_metadata"].get("description_truncated")]


# ---------------- Workable / Recruitee ----------------
def test_workable_and_recruitee_parsing(client, auth, web):
    upload(client, auth)
    web.workable["acme-ch"] = {"name": "Acme Schweiz", "jobs": [
        {"title": "Data Engineer", "shortcode": "AB12", "employment_type": "Full-time", "telecommuting": True, "published_on": "2026-09-25",
         "url": "https://apply.workable.com/j/AB12", "application_url": "https://apply.workable.com/j/AB12/apply", "city": "Zürich",
         "country": "Switzerland", "description": f"<p>{SPEC}</p>"},
        {"title": "No code", "description": "x"}]}
    web.recruitee["beta"] = {"offers": [
        {"id": 9, "title": "Platform Engineer", "status": "published", "published_at": "2026-09-30 08:35:08 UTC", "location": "Basel, Switzerland",
         "employment_type_code": "parttime_permanent", "hybrid": True, "remote": False, "on_site": False, "description": f"<p>{SPEC}</p>",
         "requirements": "<p>Kubernetes</p>", "careers_url": "https://beta.recruitee.com/o/platform", "careers_apply_url": "https://beta.recruitee.com/o/platform/c/new",
         "salary": {"min": 90000, "max": 110000, "currency": "CHF", "period": "year"}},
        {"id": 10, "title": "Draft job", "status": "draft", "description": "x"}]}
    pid = make_profile(client, auth, min_match_score=0, sources=[{"source": "workable", "board": "acme-ch"}, {"source": "recruitee", "board": "beta"}])["id"]
    run = run_now(pid)
    assert run.status == "completed" and run.stats["retrieved"] == 2
    rows = {r["title"]: r for r in job_rows(client, auth)}
    w, r = rows["Data Engineer"], rows["Platform Engineer"]
    assert (w["company"], w["remote_status"], w["employment_type"], w["location"]) == ("Acme Schweiz", "remote", "permanent", "Zürich, Switzerland")
    assert (r["remote_status"], r["employment_type"], r["salary"]["currency"]) == ("hybrid", "part_time", "CHF")
    assert "Kubernetes" in client.get(f"/api/jobs/{r['id']}", headers=auth).json()["description"]
    assert w["posted_at"] and r["posted_at"]


# ---------------- Adzuna (needs credentials) ----------------
def adz(i, title="Software Engineer", **kw):
    return {"id": str(i), "title": f"<strong>{title}</strong>", "company": {"display_name": "Swiss Corp"}, "location": {"display_name": "Zürich"},
            "created": iso(2), "description": "Snippet about python", "redirect_url": f"https://www.adzuna.ch/land/ad/{i}",
            "salary_min": 100000, "salary_max": 120000, "salary_is_predicted": "0", "contract_time": "full_time", "contract_type": "permanent", **kw}


def test_adzuna_without_credentials_is_reported_as_needing_configuration(client, auth, web, monkeypatch):
    monkeypatch.setattr(get_settings(), "adzuna_app_id", "")
    run = run_now(profile_for(client, auth, "adzuna", "python|Zürich")["id"])
    assert run.status == "failed" and run.source_statistics["adzuna:python|Zürich"]["status"] == "unavailable"
    assert "ADZUNA_APP_ID" in run.source_statistics["adzuna:python|Zürich"]["error"]
    ad = {s["name"]: s for s in client.get("/api/sources", headers=auth).json()}["adzuna"]
    assert ad["requires_credentials"] and ad["configured"] is False and ad["status"] == "needs_configuration" and "ADZUNA_APP_KEY" in ad["credentials_help"]
    assert web.adzuna_requests == []                             # never called without a key


def test_adzuna_search_params_salary_and_no_closing(client, auth, web, monkeypatch):
    monkeypatch.setattr(get_settings(), "adzuna_app_id", "id1")
    monkeypatch.setattr(get_settings(), "adzuna_app_key", "key1")
    upload(client, auth)
    web.adzuna_pages = [[adz(1), adz(2, "Backend Engineer", salary_is_predicted="1")]]
    pid = make_profile(client, auth, min_match_score=0, date_lookback_days=14, sources=[{"source": "adzuna", "board": "python developer|Zürich"}])["id"]
    run = run_now(pid)
    assert run.status == "completed"
    req = web.adzuna_requests[0]
    assert req["path"].endswith("/jobs/ch/search/1") and req["what"] == "python developer" and req["where"] == "Zürich"
    assert req["max_days_old"] == "14" and req["app_id"] == "id1"            # the posted-age window is applied by Adzuna
    rows = {r["title"]: r for r in job_rows(client, auth)}
    assert set(rows) == {"Software Engineer", "Backend Engineer"}             # <strong> markup removed from titles
    assert rows["Software Engineer"]["salary"] == {"min": 100000, "max": 120000, "currency": "CHF", "period": "year", "basis": "gross"}
    assert rows["Backend Engineer"]["salary"] is None                         # predicted salaries are not treated as real
    assert rows["Software Engineer"]["posted_at_reliable"] is False
    d = client.get(f"/api/jobs/{rows['Software Engineer']['id']}", headers=auth).json()
    assert d["listings"][0]["source_metadata"]["description_truncated"] is True
    # a search is not a full listing, so results missing next time must NOT mark jobs closed
    web.adzuna_pages = [[adz(1)]]
    assert run_now(pid).stats.get("closed", 0) == 0
    with SessionLocal() as db:
        assert {j.status for j in db.scalars(select(Job)).all()} == {"open"}


def test_adzuna_pagination_stops_when_page_is_short(client, auth, web, monkeypatch):
    monkeypatch.setattr(get_settings(), "adzuna_app_id", "i")
    monkeypatch.setattr(get_settings(), "adzuna_app_key", "k")
    web.adzuna_pages = [[adz(i) for i in range(50)], [adz(100 + i) for i in range(10)]]
    run = run_now(make_profile(client, auth, sources=[{"source": "adzuna", "board": "engineer||de"}])["id"])
    assert run.stats["retrieved"] == 60 and len(web.adzuna_requests) == 2 and web.adzuna_requests[0]["path"].endswith("/jobs/de/search/1")


# ---------------- validation of source configuration ----------------
@pytest.mark.parametrize("source,board,ok", [
    ("personio", "muster", True), ("personio", "../etc", False), ("personio", "a b", False),
    ("recruitee", "bunq", True), ("smartrecruiters", "x/y", False), ("workable", "huggingface", True),
    ("adzuna", "software engineer|Zürich", True), ("adzuna", "a", False), ("adzuna", "<script>", False), ("greenhouse", "gitlab", True),
])
def test_board_validation_is_per_source(client, auth, source, board, ok):
    r = client.post("/api/search-profiles", headers=auth, json={"profile_name": "p", "sources": [{"source": source, "board": board}]})
    assert (r.status_code == 201) is ok, r.text


def test_registry_lists_all_sources_with_help(client, auth):
    src = {s["name"]: s for s in client.get("/api/sources", headers=auth).json()}
    assert {"greenhouse", "lever", "ashby", "personio", "smartrecruiters", "workable", "recruitee", "adzuna"} <= set(src)
    assert not {"linkedin", "indeed", "jobs.ch", "jobsch"} & set(src)     # deliberately absent: no permitted access method
    assert all(s["board_hint"] for s in src.values()) and src["personio"]["requires_credentials"] is False


# ---------------- manual import (LinkedIn / Indeed / jobs.ch ...) ----------------
IMPORT = {"site": "LinkedIn", "url": "https://www.linkedin.com/jobs/view/123456", "title": "Senior Python Developer", "company": "Zürcher Kantonalbank",
          "location": "Zürich", "description": "We need a senior Python developer with SQL experience. Remote friendly. " * 3}


def test_manual_import_creates_a_visible_matched_job_without_any_network_access(client, auth, web):
    upload(client, auth)
    make_profile(client, auth, min_match_score=95)          # strict: a fetched job like this would normally be filtered out
    calls_before = web.calls
    r = client.post("/api/jobs/import", headers=auth, json=IMPORT)
    assert r.status_code == 201, r.text
    assert web.calls == calls_before                        # the LinkedIn URL is never fetched
    jid = r.json()["job_id"]
    shown = client.get("/api/jobs", headers=auth).json()["items"]    # default view = qualified only
    assert [j["id"] for j in shown] == [jid] and shown[0]["sources"] == ["manual:linkedin"]
    d = client.get(f"/api/jobs/{jid}", headers=auth).json()
    assert d["listings"][0]["source_url"] == IMPORT["url"] and any(f["name"] == "manual_import" for f in d["match"]["matching_factors"])
    assert d["listings"][0]["source_metadata"]["imported_by_user"] is True
    # works with the rest of the flow
    prep = client.post(f"/api/jobs/{jid}/prepare-application", headers=auth, json={})
    assert prep.status_code == 200 and prep.json()["application"]["status"] in ("awaiting_user_approval", "manual_application_required")


def test_manual_import_is_deduplicated_sanitised_and_validated(client, auth):
    make_profile(client, auth)
    a = client.post("/api/jobs/import", headers=auth, json={**IMPORT, "description": "<p>Python role</p><script>steal()</script> " + "x" * 30}).json()
    b = client.post("/api/jobs/import", headers=auth, json=IMPORT).json()
    assert a["job_id"] == b["job_id"] and a["created"] is True and b["created"] is False        # same URL -> same job
    assert "steal()" not in client.get(f"/api/jobs/{a['job_id']}", headers=auth).json()["description"]
    for bad in ({"url": "javascript:alert(1)"}, {"title": "x"}, {"description": "too short"}, {"employment_type": "bogus"}, {"remote_status": "moon"}):
        assert client.post("/api/jobs/import", headers=auth, json={**IMPORT, **bad}).status_code == 422, bad
    with SessionLocal() as db:
        assert len(db.scalars(select(Job)).all()) == 1


def test_manual_import_needs_a_profile_and_is_private(client, auth):
    assert client.post("/api/jobs/import", headers=auth, json=IMPORT).status_code == 422
    make_profile(client, auth)
    jid = client.post("/api/jobs/import", headers=auth, json=IMPORT).json()["job_id"]
    other = register(client, "b@example.com")
    assert client.get(f"/api/jobs/{jid}", headers=other).status_code == 404
    pid = make_profile(client, auth, profile_name="second")["id"]
    assert client.post("/api/jobs/import", headers=other, json={**IMPORT, "search_profile_id": pid}).status_code == 422  # someone else's profile
    assert client.post("/api/jobs/import", headers={}, json=IMPORT).status_code == 401


def test_manual_import_keeps_hard_exclusion_reasons_visible(client, auth):
    make_profile(client, auth, exclusions={"companies": ["Zürcher Kantonalbank"]})
    r = client.post("/api/jobs/import", headers=auth, json=IMPORT).json()
    assert "excluded_company" in r["would_normally_be_excluded"]
    m = client.get(f"/api/jobs/{r['job_id']}/match", headers=auth).json()
    assert m["qualified"] is True and m["exclusions"][0]["code"] == "excluded_company"


def test_adzuna_accepts_country_names(client, auth, web, monkeypatch):
    monkeypatch.setattr(get_settings(), "adzuna_app_id", "i")
    monkeypatch.setattr(get_settings(), "adzuna_app_key", "k")
    web.adzuna_pages = [[adz(1)]]
    run = run_now(make_profile(client, auth, sources=[{"source": "adzuna", "board": "Software Test engineer|Zurich|Switzerland"}])["id"])
    assert run.status == "completed" and web.adzuna_requests[0]["path"].endswith("/jobs/ch/search/1")
    bad = run_now(make_profile(client, auth, profile_name="b", sources=[{"source": "adzuna", "board": "x y|Zurich|Narnia"}])["id"])
    assert "country" in bad.source_statistics["adzuna:x y|Zurich|Narnia"]["error"]
