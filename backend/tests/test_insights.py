import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import SearchProfile
from app.services import insights, llm as llmmod
from app.services.llm import CVEducation, CVRole, LLMError, StructuredCV
from app.services.resume_parser import parse_structured
from .conftest import docx_bytes, gh_job, lever_job, make_profile, register, run_now, upload
from .test_ai import FakeLLM, enable_ai

# A deliberately messy, realistic CV: school, places, hobbies, spoken languages and personal data mixed into the skills area.
MESSY = """Max Muster
max.muster@example.com | +41 79 123 45 67 | 8156 Oberhasli, Zurich

Professional Profile Summary
Experienced QA Automation Engineer focused on API and UI test automation.

Technical skills
Testing Tools JIRA with Zephyr, SoapUI, Postman, Selenium
CI/CD Tools Jenkins. Gitlab
Programming Languages Java, SQL
Manual testing, Regression testing
University of Zurich, 2015
8156 Oberhasli
Hiking, Chess, Travelling
English (fluent), German B2
Swiss citizen, permit C

Professional Experience
Senior QA Automation Engineer, UBS
Jan 2020 - Present
- Built Selenium and Java test automation for 40 regression suites
- Coordinated with stakeholders and led a team of 3 testers
- Executed API testing with Postman and SoapUI, tracked defects in Jira

Test Engineer, Infosys
Jun 2015 - Dec 2019
- Performed manual testing and regression testing
- Wrote SQL queries to validate data
- Mentored two junior testers

Education
B.Sc. Computer Science, ZHAW, 2015

Hobbies
Hiking, Chess
"""

CONSULTANT = """Priya Sharma

Technical skills
Selenium, Postman, Jira, Java, SQL
Education
Diploma in Computer Applications, 2012

Project Details
Company Acme Technologies
Project Payment platform migration
Period March 2019 – Present
Role: Test Automation Engineer
- Built Selenium framework in Java for payment APIs
- Led a team of 3 testers

Project Details
Company Globex Systems
Project Banking portal
Period June 2015 – February 2019
- Performed regression testing with Selenium and SoapUI
- Wrote SQL to validate data
"""

NO_HEADINGS = """Jan Beispiel

Selenium, Java, SQL

Acme AG
QA Engineer
03/2018 - 12/2021
- Automated UI tests with Selenium and Java
- Led the test team

Globex SA
Test Analyst
06/2013 - 02/2018
- Wrote SQL for data validation
"""


def up(client, auth, text, name="cv.docx"):
    r = upload(client, auth, docx_bytes(text), name)
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ---------------- parsing layouts ----------------
def test_parser_keeps_school_places_hobbies_languages_out_of_skills():
    p = parse_structured(MESSY)
    junk = {"University of Zurich, 2015", "8156 Oberhasli", "Hiking", "Chess", "Travelling", "English (fluent)", "German B2", "Swiss citizen", "permit C", "Zurich"}
    assert not junk & set(p["skills"])
    assert {"Selenium", "SoapUI", "Postman", "Java", "SQL", "Manual testing", "Regression testing", "Jenkins", "Gitlab"} <= set(p["skills"])
    assert [(e["title"], e["company"]) for e in p["experience"]] == [("Senior QA Automation Engineer", "UBS"), ("Test Engineer", "Infosys")]


def test_parser_reads_consultant_style_project_blocks_without_an_experience_heading():
    p = parse_structured(CONSULTANT)
    assert [(e["company"], e["start"], e["end"]) for e in p["experience"]] == [("Acme Technologies", "2019-03", "present"), ("Globex Systems", "2015-06", "2019-02")]
    assert p["experience"][0]["title"] == "Test Automation Engineer" and any("Selenium" in b for b in p["experience"][0]["bullets"])
    assert not any("Globex" in b for b in p["experience"][0]["bullets"])      # next block's header does not leak back
    assert "Diploma in Computer Applications, 2012" not in p["skills"]


def test_parser_builds_entries_from_date_ranges_when_no_headings_exist():
    p = parse_structured(NO_HEADINGS)
    assert len(p["experience"]) == 2 and p["experience"][0]["start"] == "2018-03" and p["experience"][1]["end"] == "2018-02"
    assert any("Selenium" in b for b in p["experience"][0]["bullets"])


# ---------------- career snapshot (rules) ----------------
def test_snapshot_is_short_ranked_and_evidence_based(client, auth):
    rid = up(client, auth, MESSY)
    s = client.get(f"/api/resumes/{rid}/insights", headers=auth).json()
    assert s["source"] == "rules" and 1 <= len(s["roles"]) <= 3
    assert len(s["technical_skills"]) <= 5 and len(s["tools"]) <= 5 and 2 <= len(s["behavioural_skills"]) <= 3
    names = {x["name"] for x in s["technical_skills"] + s["tools"] + s["behavioural_skills"]}
    assert not {"Zurich", "Hiking", "Chess", "University of Zurich", "German B2", "permit C"} & names
    tools = {t["name"]: t for t in s["tools"]}
    assert {"Selenium", "Postman", "Jira", "SoapUI"} <= set(tools)
    assert all(t["proficiency"] in ("Beginner", "Intermediate", "Advanced", "Expert") and t["evidence"] for t in s["tools"] + s["technical_skills"])
    assert s["roles"][0]["title"] == "Senior QA Automation Engineer" and s["seniority"] == "senior"
    assert any(r["title"] in ("QA Automation Engineer", "SDET", "Test Automation Engineer") for r in s["roles"])   # equivalent titles
    assert {b["name"] for b in s["behavioural_skills"]} >= {"Leadership"} and s["total_years"] > 8
    assert s["extras"] and set(s["extras"]) == {"technical", "tools", "behavioural"}


def test_proficiency_reflects_years_recency_and_number_of_mentions():
    s = parse_structured(MESSY)
    r = insights.compute(s)
    tools = {t["name"]: t for t in r["tools"]}
    assert tools["Selenium"]["years"] >= 6 and tools["Selenium"]["proficiency"] in ("Advanced", "Expert")
    one_mention = insights.compute({"skills": [], "summary": "", "certifications": [], "achievements": [], "experience": [
        {"title": "Dev", "company": "X", "start": "2010-01", "end": "2022-01", "bullets": ["Used Docker once"]}]})
    assert one_mention["tools"][0]["proficiency"] in ("Beginner", "Intermediate")        # a single mention is not 'Expert'
    old = insights.compute({"skills": [], "summary": "", "certifications": [], "achievements": [], "experience": [
        {"title": "Dev", "company": "X", "start": "2005-01", "end": "2009-01", "bullets": ["Used Jenkins daily", "Maintained Jenkins pipelines", "Jenkins admin"]}]})
    assert old["tools"][0]["proficiency"] != "Expert" and "last used" in old["tools"][0]["evidence"]


def test_roles_fall_back_to_summary_titles_then_to_skill_clusters():
    no_titles = {"summary": "QA Test Automation Engineer with API focus", "skills": ["Selenium"], "certifications": [], "achievements": [],
                 "experience": [{"title": "", "company": "Acme", "start": "2019-01", "end": "2022-01", "bullets": ["Wrote Selenium tests"]}]}
    r = insights.compute(no_titles)["roles"]
    assert r[0]["title"] == "QA Test Automation Engineer" and "summary" in r[0]["reason"]
    none_at_all = {"summary": "", "skills": [], "certifications": [], "achievements": [],
                   "experience": [{"title": "", "company": "Acme", "start": "2019-01", "end": "2022-01", "bullets": ["Wrote Selenium and Postman tests", "Regression testing"]}]}
    r2 = insights.compute(none_at_all)["roles"]
    assert r2[0]["title"] == "Test Automation Engineer" and "Inferred" in r2[0]["reason"]


def test_linkedin_text_adds_evidence_and_is_flagged_as_used(client, auth):
    rid = up(client, auth, MESSY)
    assert client.get(f"/api/resumes/{rid}/insights", headers=auth).json()["linkedin_missing"] is True
    li = "Max Muster\n\nSkills\nTosca, Cucumber, Appium\n\nExperience\nTest Lead, Swisscom\nJan 2012 - Dec 2014\n- Led a team of 5 testers using Tosca"
    client.post("/api/profiles/linkedin/import", headers=auth, json={"pasted_text": li})
    s = client.get(f"/api/resumes/{rid}/insights", headers=auth).json()
    assert s["used_linkedin"] is True and s["linkedin_missing"] is False
    allnames = {x["name"] for k in ("tools", "technical_skills") for x in s[k]} | {x["name"] for x in sum(s["extras"].values(), [])}
    assert "Tosca" in allnames


# ---------------- AI snapshot: every item needs a real quote ----------------
@pytest.fixture()
def fake(monkeypatch):
    f = FakeLLM()
    llmmod.set_llm_factory(lambda: f)
    yield f
    llmmod.set_llm_factory(None)


def test_ai_snapshot_drops_items_without_a_quote_and_tops_up_from_rules(client, auth, fake):
    rid = up(client, auth, "Jane Doe\n\nSkills\nPython, SQL, PostgreSQL, Docker\n\nExperience\nSenior Software Engineer, Initech\nJan 2020 - Present\n"
                           "- Built Python services handling 2 million requests per day\n- Maintained PostgreSQL databases and wrote SQL reports\n"
                           "- Mentored three junior engineers\n- Wrote Docker images for deployment\n")
    enable_ai(client, auth)
    s = client.get(f"/api/resumes/{rid}/insights?ai=true", headers=auth).json()
    assert s["source"] == "ai" and s["ai_dropped"] == 2
    tech, tools = [x["name"] for x in s["technical_skills"]], [x["name"] for x in s["tools"]]
    assert "Python" in tech and "Kubernetes" not in tech and "Terraform" not in tools
    assert {"PostgreSQL", "Docker"} <= set(tools) and "Mentoring" in [b["name"] for b in s["behavioural_skills"]]
    py = [x for x in s["technical_skills"] if x["name"] == "Python"][0]
    assert py["proficiency"] == "Advanced" and "Built Python services" in py["evidence"]
    assert s["roles"][0]["title"] == "Backend Software Engineer" and len(s["roles"]) <= 3
    # cached: no second model call; refresh forces one; failures degrade to rules with a message
    client.get(f"/api/resumes/{rid}/insights?ai=true", headers=auth)
    assert fake.insights_calls == 1
    client.get(f"/api/resumes/{rid}/insights?ai=true&refresh=true", headers=auth)
    assert fake.insights_calls == 2
    fake.insights_error = LLMError("overloaded")
    fb = client.get(f"/api/resumes/{rid}/insights?ai=true&refresh=true", headers=auth).json()
    assert fb["source"] == "rules" and "overloaded" in fb["ai_error"]


def test_ai_snapshot_requires_opt_in_and_sends_no_personal_data(client, auth, fake):
    rid = up(client, auth, MESSY)
    assert client.get(f"/api/resumes/{rid}/insights?ai=true", headers=auth).status_code == 422
    enable_ai(client, auth)
    client.get(f"/api/resumes/{rid}/insights?ai=true", headers=auth)
    sent = str(fake.facts_seen[-1])
    assert "max.muster@example.com" not in sent and "Max Muster" not in sent and "41 79" not in sent and "Selenium" in sent


# ---------------- AI CV structuring ----------------
def test_ai_structuring_rescues_unreadable_layouts_and_rejects_invented_content(client, auth, fake):
    enable_ai(client, auth)
    cv = ("Zoe Example\nzoe@example.com +41 79 000 11 22\nwww.linkedin.com/in/zoe\n\nWORK\nQA Lead at Acme since 2018\n"
          "Introduced contract testing across payment services\nMentored five testers\n")
    fake.structure_result = StructuredCV(
        summary="", skills=["Contract testing", "Kubernetes", "Hiking"],
        experience=[CVRole(title="QA Lead", company="Acme", start="2018", end="Present",
                           bullets=["Introduced contract testing across payment services", "Cut release time by 80% with Kubernetes"]),
                    CVRole(title="CTO", company="Totally Invented Ltd", start="2010", end="2012", bullets=["Ran everything"])],
        education=[CVEducation(text="PhD in Astrophysics, MIT")], certifications=[])
    r = upload(client, auth, docx_bytes(cv), "odd.docx")
    p = r.json()["structured_profile"]            # heuristics found no dated entry here, so AI structuring ran at upload
    assert fake.structure_texts and p["parsed_by"] == "ai"
    sent = fake.structure_texts[0]
    assert "zoe@example.com" not in sent and "+41 79 000 11 22" not in sent and "linkedin.com" not in sent and "Zoe Example" not in sent
    assert [(e["title"], e["company"]) for e in p["experience"]] == [("QA Lead", "Acme")]               # invented employer dropped
    assert p["experience"][0]["bullets"] == ["Introduced contract testing across payment services"]    # unsupported bullet dropped
    assert "Contract testing" in p["skills"] and "Kubernetes" not in p["skills"] and "Hiking" not in p["skills"]
    assert not p["education"] or "Astrophysics" not in str(p["education"])
    assert p["name"] == "Zoe Example" and p["email"] == "zoe@example.com"                               # identity from rules, not the model


def test_reparse_with_ai_needs_opt_in_and_reports_provider_errors(client, auth, fake):
    rid = up(client, auth, MESSY)
    assert client.post(f"/api/resumes/{rid}/reparse?ai=true", headers=auth).status_code == 422
    enable_ai(client, auth)
    fake.structure_error = LLMError("overloaded")
    r = client.post(f"/api/resumes/{rid}/reparse?ai=true", headers=auth)
    assert r.status_code == 502 and "overloaded" in r.text
    assert client.post(f"/api/resumes/{rid}/reparse", headers=auth).json()["structured_profile"]["parsed_by"] == "rules"


# ---------------- apply snapshot to the search ----------------
def test_apply_creates_a_flexible_profile_with_a_short_optional_keyword_list(client, auth):
    rid = up(client, auth, MESSY)
    body = {"resume_id": rid, "roles": ["Senior QA Automation Engineer", "QA Automation Engineer"], "technical": ["Test automation", "Java"],
            "behavioural": ["Leadership"], "tools": [{"name": "Selenium", "proficiency": "Expert"}, {"name": "Postman", "proficiency": "Beginner"}]}
    r = client.post("/api/insights/apply", headers=auth, json=body).json()
    p = r["profile"]
    assert r["created"] and p["strictness"] == "flexible" and p["min_match_score"] == 40 and p["resume_id"] == rid
    assert p["role_preferences"]["target_titles"] == ["Senior QA Automation Engineer", "QA Automation Engineer"]
    kws = {k["term"]: k for k in p["keywords"]}
    assert len(kws) == 7 and all(not k["required"] and not k["excluded"] for k in kws.values())
    assert kws["Selenium"]["weight"] > kws["Postman"]["weight"] and kws["Leadership"]["kind"] == "behavioural" and kws["Leadership"]["weight"] < 1
    assert "automated testing" in kws["Test automation"]["synonyms"]                                       # synonyms widen matching
    assert client.post("/api/insights/apply", headers=auth, json={**body, "roles": []}).status_code == 422
    # applying again updates the same profile (keeps sources and other settings), replacing only keywords/titles
    client.patch(f"/api/search-profiles/{p['id']}", headers=auth, json={"sources": [{"source": "greenhouse", "board": "acme"}], "date_lookback_days": 14})
    r2 = client.post("/api/insights/apply", headers=auth, json={**body, "technical": ["Java"], "tools": []}).json()
    assert not r2["created"] and r2["replaced_keywords"] == 7 and len(r2["profile"]["keywords"]) == 4
    assert r2["profile"]["sources"] == [{"source": "greenhouse", "board": "acme"}] and r2["profile"]["date_lookback_days"] == 14
    with SessionLocal() as db:
        assert len(db.scalars(select(SearchProfile)).all()) == 1


def test_apply_is_private_to_the_user(client, auth):
    rid = up(client, auth, MESSY)
    other = register(client, "b@example.com")
    assert client.get(f"/api/resumes/{rid}/insights", headers=other).status_code == 404
    assert client.post("/api/insights/apply", headers=other, json={"resume_id": rid, "roles": ["QA"]}).status_code == 404
    pid = make_profile(client, auth)["id"]
    assert client.post("/api/insights/apply", headers=other, json={"search_profile_id": pid, "roles": ["QA"]}).status_code == 404


# ---------------- flexible matching: 40-50% of the criteria is enough ----------------
def _lever(jid, title, desc, commitment, mode, location="Berlin"):
    j = lever_job(jid, title, desc=desc, location=location, commitment=commitment)
    j["workplaceType"] = mode
    return j


def test_flexible_mode_shows_partial_matches_that_strict_mode_hides(client, auth, web):
    upload(client, auth)
    web.lever["globex"] = [
        _lever("A1", "Software Engineer", "Python role. Fully on-site, freelance contract.", "Freelance", "on-site"),   # title+skill ok, 2 preferences missed
        _lever("A2", "Accountant", "Bookkeeping and payroll", "Freelance", "on-site"),                                  # unrelated
    ]
    prefs = dict(role_preferences={"target_titles": ["Software Engineer"]}, keywords=[{"term": "Python", "kind": "skill"}, {"term": "Docker", "kind": "tool"}],
                 employment_types=["permanent"], remote_preferences=["remote"], min_match_score=40, sources=[{"source": "lever", "board": "globex"}])
    flex = make_profile(client, auth, strictness="flexible", **prefs)
    run_now(flex["id"])
    shown = client.get("/api/jobs", headers=auth).json()["items"]
    assert [j["title"] for j in shown] == ["Software Engineer"] and 40 <= shown[0]["match_score"] < 100
    m = client.get(f"/api/jobs/{shown[0]['id']}/match", headers=auth).json()
    names = {f["name"]: f for f in m["factors"]}
    assert "criteria_met" in names and "of your criteria are met" in names["criteria_met"]["detail"]
    assert names["employment"]["earned"] == 0 and names["work_mode"]["earned"] == 0 and names["title"]["earned"] > 0   # mismatches cost score only
    assert m["exclusions"] == []
    # the same preferences in strict mode exclude it outright
    client.patch(f"/api/search-profiles/{flex['id']}", headers=auth, json={"strictness": "strict"})
    run_now(flex["id"])
    assert client.get("/api/jobs", headers=auth).json()["total"] == 0
    reasons = {e["code"] for e in client.get("/api/jobs", headers=auth, params={"qualified": "false"}).json()["items"][0]["exclusion_reasons"]}
    assert {"employment_type", "work_mode"} <= reasons


def test_flexible_mode_does_not_penalise_details_a_job_does_not_state(client, auth, web):
    upload(client, auth)
    web.greenhouse["acme"] = [gh_job(1, "Software Engineer", content="<p>Python</p>", location="")]    # no employment type, no work mode stated
    p = make_profile(client, auth, role_preferences={"target_titles": ["Software Engineer"]}, keywords=[{"term": "Python"}],
                     employment_types=["permanent"], remote_preferences=["hybrid"], min_match_score=40)
    run_now(p["id"])
    j = client.get("/api/jobs", headers=auth).json()["items"][0]
    m = client.get(f"/api/jobs/{j['id']}/match", headers=auth).json()
    names = {f["name"] for f in m["factors"]}
    assert "employment" not in names and "work_mode" not in names          # unknown details are simply not counted
    assert j["match_score"] >= 85 and any("not stated" in f["detail"] for f in m["factors"] if f["name"] == "employment_type")

def test_dealbreakers_still_exclude_in_flexible_mode(client, auth, web):
    upload(client, auth)
    web.greenhouse["acme"] = [gh_job(1, "Software Engineer", content="<p>Python on-site</p>", location="Berlin")]
    p = make_profile(client, auth, role_preferences={"target_titles": ["Software Engineer"]}, keywords=[{"term": "Python"}],
                     exclusions={"companies": ["Acme"]}, min_match_score=0)
    run_now(p["id"])
    assert client.get("/api/jobs", headers=auth).json()["total"] == 0
    r = client.get("/api/jobs", headers=auth, params={"qualified": "false"}).json()["items"][0]["exclusion_reasons"]
    assert r[0]["code"] == "excluded_company"
