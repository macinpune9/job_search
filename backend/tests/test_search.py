from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Job, JobMatch, JobSourceListing, SearchRun
from app.services import matching
from app.services.textutil import norm_url
from .conftest import gh_job, lever_job, make_profile, register, run_now, upload


def jobs(client, auth, **params):
    return client.get("/api/jobs", headers=auth, params={"qualified": "", **params} if False else params).json()


def count(model):
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(model))


def test_first_run_applies_30_day_window(client, auth, web):
    upload(client, auth)
    web.greenhouse["acme"] = [gh_job(1, "Software Engineer", days_ago=5), gh_job(2, "Software Engineer II", days_ago=45)]
    p = make_profile(client, auth)
    run = run_now(p["id"])
    assert run.status == "completed"
    items = client.get("/api/jobs", headers=auth).json()["items"]
    assert [i["title"] for i in items] == ["Software Engineer"]
    old = client.get("/api/jobs", headers=auth, params={"qualified": False}).json()["items"]
    assert old[0]["exclusion_reasons"][0]["code"] == "posted_outside_window"
    # window is adjustable
    client.patch(f"/api/search-profiles/{p['id']}", headers=auth, json={"date_lookback_days": 60})
    run_now(p["id"])
    assert len(client.get("/api/jobs", headers=auth).json()["items"]) == 2


def test_repeat_runs_do_not_duplicate_and_new_jobs_are_reported_once(client, auth, web):
    upload(client, auth)
    web.greenhouse["acme"] = [gh_job(1, "Software Engineer")]
    pid = make_profile(client, auth)["id"]
    run_now(pid)
    run_now(pid)
    assert count(Job) == 1 and count(JobSourceListing) == 1
    web.greenhouse["acme"].append(gh_job(2, "Backend Software Engineer", days_ago=1))
    run3 = run_now(pid)
    assert count(Job) == 2 and run3.stats["new_jobs"] == 1
    reports = client.get("/api/reports/daily", headers=auth).json()
    assert [r["new_unique_jobs"] for r in reports] == [1, 0, 1]  # newest first (run3, run2, run1); old jobs never re-reported as new
    assert reports[1]["no_new_jobs"] and "No new qualifying jobs" in reports[1]["summary"]


def test_late_indexed_older_listing_is_discovered(client, auth, web):
    upload(client, auth)
    web.greenhouse["acme"] = [gh_job(1, "Software Engineer", days_ago=1)]
    pid = make_profile(client, auth)["id"]
    run_now(pid)
    web.greenhouse["acme"].append(gh_job(2, "Software Engineer Platform", days_ago=20))  # published 20d ago, indexed today
    run = run_now(pid)
    assert run.stats["new_jobs"] == 1 and run.stats["qualified_new"] == 1


def test_missing_and_unreliable_dates(client, auth, web):
    upload(client, auth)
    web.greenhouse["acme"] = [gh_job(1, "Software Engineer", first_published=False)]  # only updated_at (modified) is known
    pid = make_profile(client, auth)["id"]
    run_now(pid)
    it = client.get("/api/jobs", headers=auth).json()["items"][0]
    assert it["posted_at"] is None and it["posted_at_reliable"] is False  # modified date NOT promoted to posted date
    detail = client.get(f"/api/jobs/{it['id']}/match", headers=auth).json()
    assert any(f["name"] == "posted_date" for f in detail["factors"])
    client.patch(f"/api/search-profiles/{pid}", headers=auth, json={"unknown_date_policy": "exclude"})
    run_now(pid)
    assert client.get("/api/jobs", headers=auth).json()["total"] == 0
    reasons = client.get("/api/jobs", headers=auth, params={"qualified": False}).json()["items"][0]["exclusion_reasons"]
    assert reasons[0]["code"] == "posted_date_unknown"


def test_cross_source_duplicates_merge_but_keep_all_links(client, auth, web):
    upload(client, auth)
    desc = "Python and SQL required for this role."
    web.greenhouse["acme"] = [gh_job(1, "Software Engineer", content=f"<p>{desc}</p>", location="Remote", company="Acme Inc")]
    web.lever["acme-lever"] = [lever_job("L1", "Software Engineer", desc=desc, location="Remote")]
    # the lever connector labels company by board name; align to test the merge path
    web.lever["acme-lever"][0]["text"] = "Software Engineer"
    p = make_profile(client, auth, sources=[{"source": "greenhouse", "board": "acme"}, {"source": "lever", "board": "acme-lever"}])
    run_now(p["id"])
    # company names differ ("Acme Inc" vs "acme-lever") so these must NOT merge
    assert count(Job) == 2
    web.lever["acme-lever"] = []
    from app.connectors.base import RawListing
    from app.services.ingest import upsert_listing
    with SessionLocal() as db:
        a = RawListing("greenhouse", "x", "100", "Software Engineer", "Initech Corp", desc, "Berlin", source_url="https://x/1?utm_source=a")
        b = RawListing("lever", "y", "abc", "Software  Engineer (m/f/d)", "INITECH", desc, "Berlin", source_url="https://y/2")
        r1, r2 = upsert_listing(db, a), upsert_listing(db, b)
        db.commit()
        assert r1.job.id == r2.job.id and r2.created_listing and not r2.created_job
        assert len(r1.job.listings) == 2


def test_same_title_different_description_flagged_not_merged():
    from app.connectors.base import RawListing
    from app.services.ingest import upsert_listing
    with SessionLocal() as db:
        a = upsert_listing(db, RawListing("greenhouse", "x", "1", "Engineer", "Initech", "Build billing systems", "Berlin", source_url="https://x/1"))
        b = upsert_listing(db, RawListing("greenhouse", "x", "2", "Engineer", "Initech", "Operate ML platform", "Berlin", source_url="https://x/2"))
        db.commit()
        assert a.job.id != b.job.id and b.job.needs_dedup_review and b.job.possible_duplicate_of == a.job.id


def test_same_source_listing_matched_by_url_and_id():
    from app.connectors.base import RawListing
    from app.services.ingest import upsert_listing
    with SessionLocal() as db:
        a = upsert_listing(db, RawListing("greenhouse", "x", "1", "Engineer", "Initech", "d", "Berlin", source_url="https://x.com/jobs/1/?gh_src=q"))
        b = upsert_listing(db, RawListing("greenhouse", "x", "1", "Engineer", "Initech", "d", "Berlin", source_url="https://x.com/jobs/1"))
        c = upsert_listing(db, RawListing("other", "z", "99", "Engineer", "Initech", "d2", "Berlin", source_url="https://X.com/jobs/1"))  # url match
        db.commit()
        assert a.job.id == b.job.id == c.job.id and not c.created_job
    assert norm_url("https://X.com/a/?utm_x=1&b=2#f") == "https://x.com/a?b=2"


def test_closed_listing_detected_and_reopened(client, auth, web):
    upload(client, auth)
    web.greenhouse["acme"] = [gh_job(1, "Software Engineer"), gh_job(2, "Software Engineer Two")]
    pid = make_profile(client, auth)["id"]
    run_now(pid)
    web.greenhouse["acme"] = [gh_job(1, "Software Engineer")]
    run = run_now(pid)
    assert run.stats["closed"] == 1
    with SessionLocal() as db:
        assert {j.status for j in db.scalars(select(Job)).all()} == {"open", "closed"}
    web.greenhouse["acme"] = [gh_job(1, "Software Engineer"), gh_job(2, "Software Engineer Two")]
    run_now(pid)
    with SessionLocal() as db:
        assert {j.status for j in db.scalars(select(Job)).all()} == {"open"} and db.scalar(select(func.count()).select_from(Job)) == 2


def test_failed_source_does_not_block_others_and_is_reported(client, auth, web):
    upload(client, auth)
    web.greenhouse["acme"] = [gh_job(1, "Software Engineer")]
    web.lever["globex"] = [lever_job("L1", "Software Engineer")]
    web.fail.add("lever:globex")
    p = make_profile(client, auth, sources=[{"source": "lever", "board": "globex"}, {"source": "greenhouse", "board": "acme"},
                                           {"source": "greenhouse", "board": "missing-board"}])
    run = run_now(p["id"])
    assert run.status == "partial"
    assert run.source_statistics["greenhouse:acme"]["status"] == "ok"
    assert run.source_statistics["lever:globex"]["status"] == "failed" and run.source_statistics["lever:globex"]["transient"]
    assert "404" in run.source_statistics["greenhouse:missing-board"]["error"]
    assert count(Job) == 1
    rep = client.get("/api/reports/daily", headers=auth).json()[0]
    assert "lever:globex" in rep["sources_failed"] and rep["sources_searched"] == ["greenhouse:acme"]
    src = {s["name"]: s for s in client.get("/api/sources", headers=auth).json()}
    assert src["lever"]["status"] == "unavailable" and src["greenhouse"]["status"] == "ok"
    notes = client.get("/api/notifications", headers=auth).json()
    assert any(n["notification_type"] == "needs_attention" for n in notes)


def test_no_sources_configured_is_an_explicit_failure(client, auth):
    p = make_profile(client, auth, sources=[])
    run = run_now(p["id"])
    assert run.status == "failed" and "No job sources" in run.error_summary


def test_lever_pagination(client, auth, web):
    web.lever["globex"] = [lever_job(f"L{i}", "Software Engineer " + str(i)) for i in range(130)]
    p = make_profile(client, auth, sources=[{"source": "lever", "board": "globex"}], keywords=[], role_preferences={})
    assert run_now(p["id"]).stats["retrieved"] == 130


def test_user_isolation_of_jobs(client, auth, web):
    upload(client, auth)
    web.greenhouse["acme"] = [gh_job(1, "Software Engineer")]
    run_now(make_profile(client, auth)["id"])
    other = register(client, "b@example.com")
    assert client.get("/api/jobs", headers=other).json()["total"] == 0
    jid = client.get("/api/jobs", headers=auth).json()["items"][0]["id"]
    assert client.get(f"/api/jobs/{jid}", headers=other).status_code == 404


# ---------------- pure matching rules ----------------
def _job(**kw):
    d = dict(title="Software Engineer", company_name="Acme", description="Python SQL", location="Berlin, Germany", remote_status="onsite",
             employment_type="permanent", salary_information=None, posted_at=None, posted_at_reliable=False)
    d.update(kw)
    return Job(**d)


def _sp(**kw):
    from app.models import SearchProfile
    d = dict(user_id=1, profile_name="x", keywords=[], match_mode="weighted", exclusions={}, employment_types=[], role_preferences={},
             salary_preferences={}, location_preferences={}, remote_preferences=[], date_lookback_days=30, unknown_date_policy="include",
             min_match_score=0)
    d.update(kw)
    return SearchProfile(**d)


def test_hard_vs_soft_filters_and_reasons():
    j = _job()
    r = matching.evaluate(j, _sp(exclusions={"companies": ["acme"]}))
    assert not r.qualified and r.exclusions[0]["code"] == "excluded_company"
    r = matching.evaluate(j, _sp(keywords=[{"term": "Kubernetes", "required": True}]))
    assert r.exclusions[0]["code"] == "missing_required_keyword"
    r = matching.evaluate(j, _sp(keywords=[{"term": "Kubernetes"}]))  # optional keyword is only a soft signal
    assert not r.exclusions or r.exclusions[0]["code"] != "missing_required_keyword"
    r = matching.evaluate(j, _sp(keywords=[{"term": "Java", "excluded": True}]))
    assert r.qualified  # 'Java' must not match 'JavaScript'-style substrings
    assert not matching.evaluate(_job(description="We use JavaScript"), _sp(keywords=[{"term": "Python", "required": True}])).qualified
    assert matching.evaluate(_job(description="we use java"), _sp(keywords=[{"term": "Java", "excluded": True}])).exclusions[0]["code"] == "excluded_keyword"
    assert matching.evaluate(_job(description="we use javascript"), _sp(keywords=[{"term": "Java", "excluded": True}])).qualified


def test_employment_and_remote_filters():
    assert not matching.evaluate(_job(employment_type="freelance"), _sp(employment_types=["permanent"])).qualified
    assert matching.evaluate(_job(employment_type=None), _sp(employment_types=["permanent"])).qualified  # unknown != excluded
    assert not matching.evaluate(_job(remote_status="onsite"), _sp(remote_preferences=["remote"])).qualified
    assert matching.evaluate(_job(remote_status="remote"), _sp(remote_preferences=["remote", "hybrid"])).qualified
    assert matching.evaluate(_job(remote_status="unknown"), _sp(remote_preferences=["remote"])).qualified


def test_salary_only_compared_when_comparable():
    pref = {"min": 100000, "currency": "EUR", "period": "year", "basis": "gross", "strict": True}
    hi = {"min": 110000, "max": 130000, "currency": "EUR", "period": "year", "basis": "gross"}
    lo = {"min": 50000, "max": 60000, "currency": "EUR", "period": "year", "basis": "gross"}
    usd = {"min": 50000, "max": 60000, "currency": "USD", "period": "year", "basis": "gross"}
    monthly = {"min": 9000, "max": 9500, "currency": "EUR", "period": "month", "basis": "gross"}
    net = {"min": 50000, "max": 60000, "currency": "EUR", "period": "year", "basis": "net"}
    q = lambda s: matching.evaluate(_job(salary_information=s), _sp(salary_preferences=pref)).qualified  # noqa: E731
    assert q(hi) and not q(lo)
    assert q(usd) and q(net)      # not comparable -> never excluded on salary
    assert not q({**monthly, "max": 8000, "min": 7000})  # 96k/yr < 100k after period normalisation
    assert q(monthly)             # 114k/yr
    assert matching.compare_salary(usd, pref)["status"] == "not_comparable"


def test_location_soft_by_default_hard_when_strict():
    j = _job(location="Berlin, Germany")
    assert matching.evaluate(j, _sp(location_preferences={"city": "Paris"})).qualified
    assert not matching.evaluate(j, _sp(location_preferences={"city": "Paris", "strict": True})).qualified
    assert matching.evaluate(j, _sp(location_preferences={"city": "Berlin", "strict": True})).qualified


def test_and_or_modes():
    j = _job(description="Python only")
    kws = [{"term": "Python"}, {"term": "Go"}]
    assert not matching.evaluate(j, _sp(keywords=kws, match_mode="and")).qualified
    assert matching.evaluate(j, _sp(keywords=kws, match_mode="or")).qualified
    assert not matching.evaluate(_job(description="nothing"), _sp(keywords=kws, match_mode="or")).qualified
    assert matching.evaluate(j, _sp(keywords=kws, match_mode="weighted", min_match_score=40)).qualified


def test_score_is_explained():
    r = matching.evaluate(_job(), _sp(keywords=[{"term": "Python"}, {"term": "SQL"}], role_preferences={"target_titles": ["Software Engineer"]}))
    names = {f["name"] for f in r.factors}
    assert {"title", "keywords"} <= names and r.score == 100
    assert all("detail" in f for f in r.factors)


# ---------------- "found jobs but none shown" diagnostics ----------------
def test_many_required_keywords_give_one_reason_per_job_and_a_clear_summary(client, auth, web):
    upload(client, auth)
    web.greenhouse["acme"] = [gh_job(1, "Software Engineer"), gh_job(2, "Backend Engineer", content="<p>Python only</p>")]
    kws = [{"term": t, "required": True} for t in ("Selenium", "Tosca", "Zephyr", "Postman")]
    run = run_now(make_profile(client, auth, keywords=kws)["id"])
    assert run.stats["new_jobs"] == 2 and run.stats.get("qualified_new", 0) == 0
    assert run.stats["skipped_reasons"]["missing_required_keyword"] == 2          # counts jobs, not keywords (was 8)
    r = client.get("/api/jobs", headers=auth).json()
    assert r["total"] == 0 and r["summary"]["matching"] == 0 and r["summary"]["excluded"] == 2
    assert r["summary"]["top_exclusions"][0] == ["missing_required_keyword", 2]
    ex = client.get("/api/jobs", headers=auth, params={"qualified": "false"}).json()["items"][0]["exclusion_reasons"]
    assert len(ex) == 1 and "4 of 4 required keywords missing: Selenium, Tosca, Zephyr, Postman" in ex[0]["detail"]
    # showing everything works too
    assert client.get("/api/jobs", headers=auth, params={"qualified": "all"}).json()["total"] == 2
    assert client.get("/api/jobs", headers=auth, params={"qualified": "bogus"}).status_code == 422


def test_skill_parsing_strips_category_labels_and_splits_sentences():
    from app.services.resume_parser import parse_structured
    text = ("Jane Doe\n\nSkills\nTesting Tools JIRA with Zephyr, SoapUI, Manual testing\nCI/CD Tools Jenkins. Gitlab. TeamCity\n"
            "Programming Languages Java\nDatabase Design, Node.js, Postman\n")
    assert parse_structured(text)["skills"] == ["JIRA with Zephyr", "SoapUI", "Manual testing", "Jenkins", "Gitlab", "TeamCity", "Java",
                                                "Database Design", "Node.js", "Postman"]


def test_reparse_endpoint_rebuilds_the_profile_from_the_stored_text(client, auth):
    rid = upload(client, auth).json()["id"]
    sp = client.get(f"/api/resumes/{rid}", headers=auth).json()["structured_profile"]
    sp["skills"] = ["Totally wrong"]
    client.patch(f"/api/resumes/{rid}", headers=auth, json={"structured_profile": sp})
    r = client.post(f"/api/resumes/{rid}/reparse", headers=auth).json()
    assert "Python" in r["structured_profile"]["skills"] and "Totally wrong" not in r["structured_profile"]["skills"]
    assert client.post(f"/api/resumes/{rid}/reparse", headers=register(client, "z@example.com")).status_code == 404
