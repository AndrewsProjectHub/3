"""
MD-102 Daily Study Email Webhook
================================
A FastAPI webhook that queries 5 Notion databases and returns formatted
email content for Zapier to send.

Deploy to: Render, Railway, Fly.io, or any ASGI-compatible host.
"""

import os
import re
import httpx
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


# ==============================================================================
# CONFIGURATION
# ==============================================================================

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
AUTH_TOKEN = os.environ.get("AUTH_TOKEN", "")

# Database IDs from environment
PLAN_DB_ID = os.environ.get("PLAN_DB_ID", "")
OBJECTIVES_DB_ID = os.environ.get("OBJECTIVES_DB_ID", "")
RESOURCES_DB_ID = os.environ.get("RESOURCES_DB_ID", "")
PRACTICE_DB_ID = os.environ.get("PRACTICE_DB_ID", "")
MISTAKES_DB_ID = os.environ.get("MISTAKES_DB_ID", "")

NOTION_API_VERSION = "2022-06-28"
NOTION_BASE_URL = "https://api.notion.com/v1"


# ==============================================================================
# PYDANTIC MODELS
# ==============================================================================

class WebhookRequest(BaseModel):
    run_date: str = Field(..., description="Date in YYYY-MM-DD format")
    timezone: str = Field(default="America/New_York")


class DebugInfo(BaseModel):
    date: str
    objectives_count: int = 0
    resources_count: int = 0
    practice_test_found: bool = False
    mistakes_found: int = 0


class WebhookResponse(BaseModel):
    should_send: bool
    subject: str = ""
    body: str = ""
    reason: str = "ok"
    debug: DebugInfo


# ==============================================================================
# NOTION PROPERTY EXTRACTORS (Plain Text Only)
# ==============================================================================

def extract_rich_text(prop: dict) -> str:
    """Extract plain text from rich_text or title arrays."""
    if not prop:
        return ""
    
    prop_type = prop.get("type", "")
    
    if prop_type == "rich_text":
        arr = prop.get("rich_text", [])
    elif prop_type == "title":
        arr = prop.get("title", [])
    else:
        arr = prop.get("rich_text", []) or prop.get("title", [])
    
    if not arr:
        return ""
    
    return "".join(item.get("plain_text", "") for item in arr).strip()


def extract_select(prop: dict) -> str:
    """Extract name from select property."""
    if not prop:
        return ""
    select_obj = prop.get("select")
    if select_obj:
        return select_obj.get("name", "")
    return ""


def extract_checkbox(prop: dict) -> bool:
    """Extract boolean from checkbox property."""
    if not prop:
        return False
    return prop.get("checkbox", False)


def extract_date(prop: dict) -> str:
    """Extract start date from date property."""
    if not prop:
        return ""
    date_obj = prop.get("date")
    if date_obj:
        return date_obj.get("start", "") or ""
    return ""


def extract_url(prop: dict) -> str:
    """Extract URL from url property (or fallback to rich_text)."""
    if not prop:
        return ""
    
    prop_type = prop.get("type", "")
    
    if prop_type == "url":
        return prop.get("url", "") or ""
    elif prop_type == "rich_text":
        return extract_rich_text(prop)
    return ""


def get_prop(page: dict, name: str) -> dict:
    """Safely get a property from a Notion page."""
    return page.get("properties", {}).get(name, {})


# ==============================================================================
# ID PARSING UTILITIES
# ==============================================================================

def parse_id_list(raw: str) -> list[str]:
    """
    Parse comma-separated IDs, handling ranges like P-ENTRA-01..04.
    Returns deduplicated list of IDs.
    """
    if not raw:
        return []
    
    ids = set()
    tokens = [t.strip() for t in raw.split(",") if t.strip()]
    
    for token in tokens:
        # Check for range pattern like P-ENTRA-01..04 or P-ENTRA-01..P-ENTRA-04
        range_match = re.match(r"^(.+?)(\d+)\.\.(\d+)$", token)
        if range_match:
            prefix = range_match.group(1)
            start_num = int(range_match.group(2))
            end_num = int(range_match.group(3))
            width = len(range_match.group(2))  # preserve leading zeros
            for i in range(start_num, end_num + 1):
                ids.add(f"{prefix}{str(i).zfill(width)}")
        else:
            # Also handle P-PREFIX-01..P-PREFIX-04 style
            range_match2 = re.match(r"^(.+?)(\d+)\.\.(.+?)(\d+)$", token)
            if range_match2 and range_match2.group(1) == range_match2.group(3):
                prefix = range_match2.group(1)
                start_num = int(range_match2.group(2))
                end_num = int(range_match2.group(4))
                width = len(range_match2.group(2))
                for i in range(start_num, end_num + 1):
                    ids.add(f"{prefix}{str(i).zfill(width)}")
            else:
                ids.add(token)
    
    return sorted(list(ids))


# ==============================================================================
# NOTION API CLIENT
# ==============================================================================

class NotionClient:
    def __init__(self, token: str):
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_API_VERSION,
            "Content-Type": "application/json"
        }
    
    async def query_database(
        self, 
        database_id: str, 
        filter_obj: Optional[dict] = None,
        sorts: Optional[list] = None
    ) -> list[dict]:
        """Query a Notion database with optional filter and sorts."""
        url = f"{NOTION_BASE_URL}/databases/{database_id}/query"
        
        body = {}
        if filter_obj:
            body["filter"] = filter_obj
        if sorts:
            body["sorts"] = sorts
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=self.headers, json=body)
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=502,
                    detail=f"Notion API error: {response.status_code} - {response.text}"
                )
            
            data = response.json()
            return data.get("results", [])
    
    async def query_by_date(self, database_id: str, date_property: str, date_value: str) -> list[dict]:
        """Query database where a date property equals a specific date."""
        filter_obj = {
            "property": date_property,
            "date": {"equals": date_value}
        }
        return await self.query_database(database_id, filter_obj)
    
    async def query_by_text_equals(self, database_id: str, property_name: str, value: str) -> list[dict]:
        """Query database where a rich_text/title property equals a value."""
        # Try rich_text first, then title
        filter_obj = {
            "or": [
                {"property": property_name, "rich_text": {"equals": value}},
                {"property": property_name, "title": {"equals": value}}
            ]
        }
        return await self.query_database(database_id, filter_obj)
    
    async def query_unresolved_mistakes(self, database_id: str) -> list[dict]:
        """Query Mistake Bank where Resolved = false."""
        filter_obj = {
            "property": "Resolved",
            "checkbox": {"equals": False}
        }
        # Sort by created_time descending (newest first)
        sorts = [{"timestamp": "created_time", "direction": "descending"}]
        return await self.query_database(database_id, filter_obj, sorts)


# ==============================================================================
# FASTAPI APPLICATION
# ==============================================================================

app = FastAPI(
    title="MD-102 Study Email Webhook",
    description="Webhook for generating daily MD-102 study emails from Notion databases",
    version="1.0.0"
)


@app.get("/")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "md102-study-webhook"}


@app.get("/health")
async def health():
    """Alternative health check for some hosting platforms."""
    return {"status": "ok"}


@app.post("/webhook")
async def generate_study_email(
    request: WebhookRequest,
    x_auth_token: Optional[str] = Header(None, alias="X-AUTH-TOKEN")
):
    """
    Main webhook endpoint.
    
    Expects:
    - Header: X-AUTH-TOKEN with shared secret
    - Body: {"run_date": "YYYY-MM-DD", "timezone": "America/New_York"}
    
    Returns:
    - JSON with should_send, subject, body, reason, debug
    """
    
    # -------------------------------------------------------------------------
    # 1. AUTH CHECK
    # -------------------------------------------------------------------------
    if not AUTH_TOKEN:
        return JSONResponse(
            status_code=500,
            content={"error": "Server misconfigured: AUTH_TOKEN not set"}
        )
    
    if not x_auth_token or x_auth_token != AUTH_TOKEN:
        return JSONResponse(
            status_code=401,
            content={"error": "Unauthorized: Invalid or missing X-AUTH-TOKEN"}
        )
    
    # -------------------------------------------------------------------------
    # 2. VALIDATE CONFIG
    # -------------------------------------------------------------------------
    if not NOTION_TOKEN:
        return JSONResponse(
            status_code=500,
            content={"error": "Server misconfigured: NOTION_TOKEN not set"}
        )
    
    missing_dbs = []
    if not PLAN_DB_ID: missing_dbs.append("PLAN_DB_ID")
    if not OBJECTIVES_DB_ID: missing_dbs.append("OBJECTIVES_DB_ID")
    if not RESOURCES_DB_ID: missing_dbs.append("RESOURCES_DB_ID")
    if not PRACTICE_DB_ID: missing_dbs.append("PRACTICE_DB_ID")
    if not MISTAKES_DB_ID: missing_dbs.append("MISTAKES_DB_ID")
    
    if missing_dbs:
        return JSONResponse(
            status_code=500,
            content={"error": f"Missing database IDs: {', '.join(missing_dbs)}"}
        )
    
    # Initialize response debug
    debug = DebugInfo(date=request.run_date)
    
    # -------------------------------------------------------------------------
    # 3. QUERY PLAN DATABASE FOR TODAY
    # -------------------------------------------------------------------------
    notion = NotionClient(NOTION_TOKEN)
    
    try:
        plan_results = await notion.query_by_date(PLAN_DB_ID, "Date", request.run_date)
    except HTTPException as e:
        return JSONResponse(status_code=e.status_code, content={"error": e.detail})
    
    if not plan_results:
        return WebhookResponse(
            should_send=False,
            reason="no_plan",
            debug=debug
        ).model_dump()
    
    plan = plan_results[0]
    
    # -------------------------------------------------------------------------
    # 4. CHECK IF ALREADY COMPLETED
    # -------------------------------------------------------------------------
    session1_done = extract_checkbox(get_prop(plan, "Session 1 Done"))
    session2_done = extract_checkbox(get_prop(plan, "Session 2 Done"))
    
    if session1_done and session2_done:
        return WebhookResponse(
            should_send=False,
            reason="completed",
            debug=debug
        ).model_dump()
    
    # -------------------------------------------------------------------------
    # 5. EXTRACT PLAN DETAILS
    # -------------------------------------------------------------------------
    phase = extract_rich_text(get_prop(plan, "Phase"))
    focus_priority = extract_select(get_prop(plan, "Focus Priority")) or extract_rich_text(get_prop(plan, "Focus Priority"))
    
    session1_text = extract_rich_text(get_prop(plan, "Session 1 (1 hr) – Learn"))
    session1_resources_raw = extract_rich_text(get_prop(plan, "Session 1 Resources (IDs/URLs)"))
    
    session2_text = extract_rich_text(get_prop(plan, "Session 2 (1 hr) – Lab/Practice"))
    session2_resources_raw = extract_rich_text(get_prop(plan, "Session 2 Resources (IDs/URLs)"))
    
    focus_objectives_raw = extract_rich_text(get_prop(plan, "Focus objectives (IDs)"))
    
    # -------------------------------------------------------------------------
    # 6. PARSE OBJECTIVE IDs
    # -------------------------------------------------------------------------
    objective_ids = parse_id_list(focus_objectives_raw)
    debug.objectives_count = len(objective_ids)
    
    # -------------------------------------------------------------------------
    # 7. FETCH OBJECTIVES
    # -------------------------------------------------------------------------
    objectives = []
    for obj_id in objective_ids:
        try:
            results = await notion.query_by_text_equals(OBJECTIVES_DB_ID, "Objective ID", obj_id)
            if results:
                obj_page = results[0]
                objectives.append({
                    "id": obj_id,
                    "objective": extract_rich_text(get_prop(obj_page, "Objective")),
                    "exam_area": extract_select(get_prop(obj_page, "Exam Area")) or extract_rich_text(get_prop(obj_page, "Exam Area")),
                    "skill_group": extract_select(get_prop(obj_page, "Skill Group")) or extract_rich_text(get_prop(obj_page, "Skill Group")),
                    "priority": extract_select(get_prop(obj_page, "Priority")) or extract_rich_text(get_prop(obj_page, "Priority")),
                    "primary_resources": extract_rich_text(get_prop(obj_page, "Primary Resources (IDs)"))
                })
        except Exception:
            # If an objective query fails, continue with others
            pass
    
    # -------------------------------------------------------------------------
    # 8. BUILD RESOURCE ID SET
    # -------------------------------------------------------------------------
    resource_ids_raw = session1_resources_raw + ", " + session2_resources_raw
    for obj in objectives:
        if obj.get("primary_resources"):
            resource_ids_raw += ", " + obj["primary_resources"]
    
    resource_ids = parse_id_list(resource_ids_raw)
    debug.resources_count = len(resource_ids)
    
    # -------------------------------------------------------------------------
    # 9. FETCH RESOURCES
    # -------------------------------------------------------------------------
    resources = []
    for res_id in resource_ids:
        try:
            results = await notion.query_by_text_equals(RESOURCES_DB_ID, "Resource ID", res_id)
            if results:
                res_page = results[0]
                resources.append({
                    "id": res_id,
                    "name": extract_rich_text(get_prop(res_page, "Name")),
                    "type": extract_select(get_prop(res_page, "Type")) or extract_rich_text(get_prop(res_page, "Type")),
                    "url": extract_url(get_prop(res_page, "URL")),
                    "why": extract_rich_text(get_prop(res_page, "Why it matters"))
                })
        except Exception:
            pass
    
    # -------------------------------------------------------------------------
    # 10. FETCH PRACTICE TEST FOR TODAY
    # -------------------------------------------------------------------------
    practice_test = None
    try:
        practice_results = await notion.query_by_date(PRACTICE_DB_ID, "Date", request.run_date)
        if practice_results:
            pt = practice_results[0]
            practice_test = {
                "provider": extract_select(get_prop(pt, "Provider")) or extract_rich_text(get_prop(pt, "Provider")),
                "test": extract_rich_text(get_prop(pt, "Test")),
                "focus": extract_rich_text(get_prop(pt, "Primary Focus")),
                "notes": extract_rich_text(get_prop(pt, "Notes"))
            }
            debug.practice_test_found = True
    except Exception:
        pass
    
    # -------------------------------------------------------------------------
    # 11. FETCH UNRESOLVED MISTAKES FOR TODAY'S OBJECTIVES
    # -------------------------------------------------------------------------
    mistakes = []
    try:
        all_mistakes = await notion.query_unresolved_mistakes(MISTAKES_DB_ID)
        
        # Filter to those matching today's objective IDs
        objective_id_set = set(objective_ids)
        for m in all_mistakes:
            mistake_obj_id = extract_rich_text(get_prop(m, "Objective ID"))
            if mistake_obj_id in objective_id_set:
                mistakes.append({
                    "objective_id": mistake_obj_id,
                    "summary": extract_rich_text(get_prop(m, "Mistake Summary")),
                    "rule": extract_rich_text(get_prop(m, "Correct Rule")),
                    "tip": extract_rich_text(get_prop(m, "Recognition Tip"))
                })
        
        # Limit to 3 newest
        mistakes = mistakes[:3]
        debug.mistakes_found = len(mistakes)
    except Exception:
        pass
    
    # -------------------------------------------------------------------------
    # 12. BUILD EMAIL BODY
    # -------------------------------------------------------------------------
    body_lines = [
        "MD-102 DAILY STUDY BRIEF",
        f"Date: {request.run_date}",
        f"Phase: {phase}",
        f"Priority: {focus_priority}",
        "",
        "================================",
        "TODAY'S STUDY SESSIONS",
        "================================",
        "SESSION 1 — LEARN (1 hour)",
        session1_text or "(No details)",
        "Resources (IDs/URLs):",
        session1_resources_raw or "(None)",
        "",
        "SESSION 2 — LAB / PRACTICE (1 hour)",
        session2_text or "(No details)",
        "Resources (IDs/URLs):",
        session2_resources_raw or "(None)",
        "",
        "================================",
        "TODAY'S OBJECTIVES",
        "================================",
    ]
    
    if objectives:
        for obj in objectives:
            obj_line = f"- {obj['id']} — {obj['objective']}"
            details = []
            if obj['exam_area']:
                details.append(f"Exam Area: {obj['exam_area']}")
            if obj['skill_group']:
                details.append(f"Skill: {obj['skill_group']}")
            if obj['priority']:
                details.append(f"Priority: {obj['priority']}")
            if details:
                obj_line += f" ({' | '.join(details)})"
            body_lines.append(obj_line)
    else:
        body_lines.append("(No objectives found)")
    
    body_lines.extend([
        "",
        "================================",
        "KEY RESOURCES",
        "================================",
    ])
    
    if resources:
        for res in resources:
            body_lines.append(f"- {res['id']} — {res['name']} ({res['type']})")
            if res['url']:
                body_lines.append(f"  URL: {res['url']}")
            if res['why']:
                body_lines.append(f"  Why: {res['why']}")
    else:
        body_lines.append("(No resources found)")
    
    body_lines.extend([
        "",
        "================================",
        "PRACTICE TEST (IF ANY)",
        "================================",
    ])
    
    if practice_test:
        body_lines.append(f"{practice_test['provider']} — {practice_test['test']}")
        if practice_test['focus']:
            body_lines.append(f"Focus: {practice_test['focus']}")
        if practice_test['notes']:
            body_lines.append(f"Notes: {practice_test['notes']}")
    else:
        body_lines.append("(No practice test scheduled for today)")
    
    body_lines.extend([
        "",
        "================================",
        "OPEN MISTAKES (IF ANY)",
        "================================",
    ])
    
    if mistakes:
        for m in mistakes:
            body_lines.append(f"- Mistake: {m['summary']}")
            if m['rule']:
                body_lines.append(f"  Rule: {m['rule']}")
            if m['tip']:
                body_lines.append(f"  Tip: {m['tip']}")
    else:
        body_lines.append("(No open mistakes for today's objectives)")
    
    body_lines.extend([
        "",
        "================================",
        "COMPLETION CHECKLIST",
        "================================",
        "[ ] Session 1 Done",
        "[ ] Session 2 Done",
    ])
    
    body = "\n".join(body_lines)
    
    # -------------------------------------------------------------------------
    # 13. BUILD SUBJECT
    # -------------------------------------------------------------------------
    subject = f"MD-102 — Daily Study Brief ({focus_priority})" if focus_priority else "MD-102 — Daily Study Brief"
    
    # -------------------------------------------------------------------------
    # 14. RETURN RESPONSE
    # -------------------------------------------------------------------------
    return WebhookResponse(
        should_send=True,
        subject=subject,
        body=body,
        reason="ok",
        debug=debug
    ).model_dump()


# ==============================================================================
# ERROR HANDLERS
# ==============================================================================

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "should_send": False,
            "subject": "",
            "body": "",
            "reason": "error",
            "error": str(exc),
            "debug": {"date": "", "objectives_count": 0, "resources_count": 0, "practice_test_found": False, "mistakes_found": 0}
        }
    )


# ==============================================================================
# LOCAL DEVELOPMENT
# ==============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
