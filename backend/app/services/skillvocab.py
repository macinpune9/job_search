"""Vocabulary and plausibility rules used to pick the BEST skills from a CV (and to keep school, places, hobbies and
spoken languages out of the skill list)."""
from __future__ import annotations

import re

from .textutil import fold

# canonical display name -> aliases (lowercase). Named products/platforms the candidate would list as "tools".
TOOLS: dict[str, list[str]] = {
    "Jira": ["jira", "jira with zephyr"], "Confluence": ["confluence"], "Zephyr": ["zephyr"], "TestRail": ["testrail"], "Xray": ["xray"],
    "Selenium": ["selenium", "java selenium", "selenium webdriver"], "Cypress": ["cypress"], "Playwright": ["playwright"],
    "Appium": ["appium"], "Postman": ["postman"], "SoapUI": ["soapui", "soap ui"], "Tosca": ["tosca", "tricentis tosca"],
    "UFT": ["uft", "qtp", "micro focus uft"], "JMeter": ["jmeter"], "Cucumber": ["cucumber", "gherkin"], "Robot Framework": ["robot framework"],
    "JUnit": ["junit"], "TestNG": ["testng"], "pytest": ["pytest"], "Jenkins": ["jenkins"], "TeamCity": ["teamcity"], "Bamboo": ["bamboo"],
    "GitHub Actions": ["github actions"], "GitLab CI": ["gitlab ci", "gitlab"], "Git": ["git"], "GitHub": ["github"], "Bitbucket": ["bitbucket"],
    "Docker": ["docker"], "Kubernetes": ["kubernetes", "k8s"], "Terraform": ["terraform"], "Ansible": ["ansible"], "AWS": ["aws", "amazon web services"],
    "Azure": ["azure", "microsoft azure"], "Google Cloud": ["gcp", "google cloud"], "Linux": ["linux", "unix"], "Excel": ["excel", "ms excel"],
    "Power BI": ["power bi", "powerbi"], "Tableau": ["tableau"], "Looker": ["looker"], "SAP": ["sap"], "Salesforce": ["salesforce"],
    "ServiceNow": ["servicenow"], "Oracle DB": ["oracle", "oracle database", "database oracle"], "MySQL": ["mysql"],
    "PostgreSQL": ["postgresql", "postgres"], "MS SQL Server": ["ms sql server", "sql server", "mssql"], "MongoDB": ["mongodb"], "Redis": ["redis"],
    "Elasticsearch": ["elasticsearch"], "Kafka": ["kafka"], "RabbitMQ": ["rabbitmq"], "Airflow": ["airflow"], "Spark": ["spark", "apache spark"],
    "Snowflake": ["snowflake"], "Figma": ["figma"], "Sketch": ["sketch"], "Photoshop": ["photoshop"], "SharePoint": ["sharepoint"],
    "Visual Studio": ["visual studio"], "IntelliJ": ["intellij"], "Eclipse": ["eclipse"], "Maven": ["maven"], "Gradle": ["gradle"], "Splunk": ["splunk"],
    "Grafana": ["grafana"], "Prometheus": ["prometheus"], "Datadog": ["datadog"], "SonarQube": ["sonarqube"], "Burp Suite": ["burp suite", "burp"],
    "Wireshark": ["wireshark"], "Trello": ["trello"], "Asana": ["asana"], "Miro": ["miro"], "HubSpot": ["hubspot"], "Zendesk": ["zendesk"],
    "UiPath": ["uipath"], "Power Automate": ["power automate"], "MATLAB": ["matlab"], "AutoCAD": ["autocad"], "TFS / Azure DevOps": ["azure devops", "tfs"],
}
TECHNICAL: dict[str, list[str]] = {
    "Python": ["python"], "Java": ["java"], "JavaScript": ["javascript", "js"], "TypeScript": ["typescript"], "C#": ["c#"], "C++": ["c++"], "Go": ["golang"],
    "Rust": ["rust"], "Ruby": ["ruby"], "PHP": ["php"], "Kotlin": ["kotlin"], "Swift": ["swift"], "Scala": ["scala"], "SQL": ["sql"], "PL/SQL": ["pl/sql", "plsql"],
    "T-SQL": ["t-sql", "tsql"], "Bash": ["bash", "shell scripting"], "PowerShell": ["powershell"], "HTML/CSS": ["html", "css"], "React": ["react", "reactjs"],
    "Angular": ["angular"], "Vue": ["vue", "vue.js"], "Node.js": ["node.js", "nodejs"], "Spring": ["spring", "spring boot"], "Django": ["django"],
    "Flask": ["flask"], "FastAPI": ["fastapi"], ".NET": [".net", "dotnet"], "REST APIs": ["rest", "rest api", "restful", "api testing"], "SOAP": ["soap"],
    "GraphQL": ["graphql"], "Test automation": ["test automation", "automated testing", "automation testing", "test automation framework"],
    "Manual testing": ["manual testing"], "Regression testing": ["regression testing", "functional and regression testing"],
    "Smoke testing": ["smoke testing"], "Functional testing": ["functional testing"], "Performance testing": ["performance testing", "load testing"],
    "Security testing": ["security testing", "penetration testing"], "Unit testing": ["unit testing"], "Integration testing": ["integration testing"],
    "UAT": ["uat", "user acceptance testing"], "Test design": ["test case design", "test design", "test cases", "test planning", "test suites"],
    "Test management": ["test management", "test strategy"], "Defect management": ["defect triage", "defect management", "bug tracking"],
    "BDD / TDD": ["bdd", "tdd"], "CI/CD": ["ci/cd", "continuous integration"], "DevOps": ["devops"], "Agile / Scrum": ["agile", "scrum", "kanban"],
    "Microservices": ["microservices"], "Data validation": ["data validation", "data integrity"], "Data modeling": ["data modeling", "data modelling"],
    "ETL": ["etl"], "Data analysis": ["data analysis", "data analytics"], "Machine learning": ["machine learning"], "Deep learning": ["deep learning"],
    "NLP": ["nlp", "natural language processing"], "Data engineering": ["data engineering"], "Cloud computing": ["cloud computing"],
    "Networking": ["networking"], "Cybersecurity": ["cybersecurity", "information security"], "Embedded systems": ["embedded systems", "embedded"],
    "Project management": ["project management"], "Product management": ["product management"], "Business analysis": ["business analysis", "requirements analysis"],
    "Requirements engineering": ["requirements engineering"], "Financial analysis": ["financial analysis", "financial reporting"], "Budgeting": ["budgeting", "forecasting"],
    "Accounting": ["accounting", "bookkeeping"], "Auditing": ["auditing"], "Compliance": ["compliance"], "Risk management": ["risk management"],
    "Supply chain": ["supply chain"], "Logistics": ["logistics"], "Recruiting": ["recruiting", "talent acquisition"], "Customer service": ["customer service"],
    "Sales": ["sales"], "SEO": ["seo"], "Content marketing": ["content marketing"], "Quality assurance": ["quality assurance", "qa"],
}
# behavioural / soft skills: canonical -> (aliases, verbs in CV bullets that evidence them)
BEHAVIOURAL: dict[str, tuple[list[str], list[str]]] = {
    "Communication": (["communication", "communication skills"], ["communicated", "documented", "reported", "wrote", "explained"]),
    "Teamwork": (["teamwork", "team player", "team work"], ["collaborated", "partnered", "cross-functional", "worked closely", "team of"]),
    "Leadership": (["leadership"], ["led", "managed", "supervised", "headed", "directed", "lead "]),
    "Mentoring": (["mentoring", "coaching"], ["mentored", "coached", "trained", "onboarded", "guided"]),
    "Problem solving": (["problem solving", "problem-solving"], ["resolved", "troubleshot", "debugged", "diagnosed", "fixed", "solved"]),
    "Analytical thinking": (["analytical", "analytical thinking", "critical thinking"], ["analyzed", "analysed", "investigated", "evaluated", "root cause"]),
    "Stakeholder management": (["stakeholder management"], ["coordinated", "liaised", "aligned", "stakeholders", "negotiated with"]),
    "Planning & organisation": (["time management", "organisation", "organization", "prioritization", "planning"], ["planned", "prioritized", "prioritised", "scheduled", "organised", "organized"]),
    "Presentation": (["presentation skills", "presentation"], ["presented", "demonstrated", "demoed"]),
    "Attention to detail": (["attention to detail", "detail-oriented", "detail oriented"], ["verified", "reviewed", "validated", "audited"]),
    "Adaptability": (["adaptability", "flexibility", "quick learner"], ["adapted", "learned"]),
    "Ownership": (["ownership", "initiative", "self-motivated", "proactive"], ["owned", "initiated", "drove", "spearheaded"]),
    "Customer focus": (["customer orientation", "customer focus", "customer-oriented"], ["supported customers", "client-facing", "customer"]),
    "Negotiation": (["negotiation"], ["negotiated"]),
}

# ---- things that are NOT skills ----
_EDU = re.compile(r"\b(university|universit[aä]t|college|school|gymnasium|bachelor|master|msc|bsc|b\.?sc|m\.?sc|phd|diploma|degree|certificate of|"
                  r"matura|apprenticeship|lehre|hochschule|eth|epfl|fh|zhaw|bfh|graduat\w+|class of|semester|thesis)\b", re.I)
_PLACE = re.compile(r"\b(zurich|zürich|bern|basel|geneva|gen[eè]ve|lausanne|lucerne|luzern|st\.? gallen|winterthur|lugano|zug|aargau|ticino|vaud|valais|"
                    r"switzerland|schweiz|suisse|svizzera|germany|deutschland|austria|france|italy|india|uk|usa|united (states|kingdom)|berlin|munich|vienna|london|"
                    r"strasse|straße|str\.|street|road|avenue|platz|weg|gasse|canton|kanton|postcode|zip)\b", re.I)
_HOBBY = re.compile(r"^(hiking|reading|travel(l)?ing|music|football|soccer|swimming|cooking|photography|chess|gaming|video games|cycling|running|yoga|movies|"
                    r"films|painting|drawing|dancing|skiing|snowboarding|tennis|gym|fitness|volunteering|gardening|climbing|fishing|sports?|walking|"
                    r"cinema|theatre|theater|knitting|baking|travel|hobbies|interests)$", re.I)
_LANG = re.compile(r"\b(english|german|deutsch|french|fran[cç]ais|italian|italiano|spanish|hindi|marathi|urdu|portuguese|russian|dutch|arabic|chinese|japanese)\b"
                   r".*\b(a1|a2|b1|b2|c1|c2|native|fluent|mother tongue|basic|intermediate|advanced|proficient|beginner)\b|"
                   r"\b(a1|a2|b1|b2|c1|c2)\b", re.I)
_CONTACT = re.compile(r"(@|https?://|www\.|linkedin\.com|\+?\d[\d\s().-]{7,}|\b\d{4,5}\b|\b(born|nationality|marital|permit|visa|citizen\w*|resident|single|married|swiss|available|notice period)\b)", re.I)
_DATE = re.compile(r"\b(19|20)\d{2}\b|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", re.I)


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", fold(s or "").lower()).strip(" .,:;-–•")


def _alias_map(d) -> dict[str, str]:
    m = {}
    for canon, v in d.items():
        aliases = v[0] if isinstance(v, tuple) else v
        for a in [canon.lower(), *aliases]:
            m[norm(a)] = canon
    return m


TOOL_ALIAS, TECH_ALIAS, BEHAV_ALIAS = _alias_map(TOOLS), _alias_map(TECHNICAL), _alias_map(BEHAVIOURAL)


def classify(term: str) -> tuple[str | None, str | None]:
    """Return (kind, canonical) for a known skill, else (None, None). kind: tool | technical | behavioural."""
    n = norm(term)
    for kind, table in (("tool", TOOL_ALIAS), ("technical", TECH_ALIAS), ("behavioural", BEHAV_ALIAS)):
        if n in table:
            return kind, table[n]
    return None, None


def is_plausible_skill(term: str) -> bool:
    """False for school/degree lines, places and addresses, hobbies, spoken languages, contact details, dates and sentences."""
    t = (term or "").strip()
    n = norm(t)
    if not n or len(n) < 2 or len(n) > 40 or len(n.split()) > 4:
        return False
    if classify(t)[0]:
        return True                       # a known skill always passes
    if _CONTACT.search(t) or _DATE.search(t) or _EDU.search(t) or _PLACE.search(t) or _LANG.search(t) or _HOBBY.match(n):
        return False
    if sum(ch.isdigit() for ch in t) > 2 or t.count("(") != t.count(")"):
        return False
    return bool(re.search(r"[A-Za-z]", t))
