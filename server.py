"""Basecamp Classic MCP Server"""

import json
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Optional

import httpx
from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
from mcp.types import ToolAnnotations

READ_ONLY = ToolAnnotations(readOnlyHint=True)

BASECAMP_URL = os.environ.get("BASECAMP_URL", "").strip().rstrip("/")
BASECAMP_USERNAME = os.environ.get("BASECAMP_USERNAME", "").strip()
BASECAMP_PASSWORD = os.environ.get("BASECAMP_PASSWORD", "").strip()
MCP_AUTH_TOKEN = os.environ.get("MCP_AUTH_TOKEN", "").strip()


def _build_auth() -> Optional[StaticTokenVerifier]:
    """Require a shared bearer token for remote (HTTP) clients."""
    if not MCP_AUTH_TOKEN:
        return None
    return StaticTokenVerifier(
        tokens={
            MCP_AUTH_TOKEN: {
                "client_id": "basecamp-bot",
                "scopes": ["basecamp"],
            }
        },
        required_scopes=["basecamp"],
    )


mcp = FastMCP("Basecamp Classic", auth=_build_auth())


def _client() -> httpx.Client:
    if not BASECAMP_URL:
        raise ValueError("BASECAMP_URL environment variable is required")
    if not BASECAMP_USERNAME:
        raise ValueError("BASECAMP_USERNAME environment variable is required")
    if not BASECAMP_PASSWORD:
        raise ValueError("BASECAMP_PASSWORD environment variable is required")
    return httpx.Client(
        base_url=BASECAMP_URL,
        auth=(BASECAMP_USERNAME, BASECAMP_PASSWORD),
        headers={"Accept": "application/xml", "Content-Type": "application/xml"},
    )


def _get(path: str) -> ET.Element:
    root, _headers = _fetch(path)
    return root


def _fetch(path: str) -> tuple[ET.Element, dict[str, str]]:
    with _client() as client:
        response = client.get(path)
        response.raise_for_status()
        headers = {key.lower(): value for key, value in response.headers.items()}
        if response.text.strip():
            return ET.fromstring(response.text), headers
        return ET.Element("ok"), headers


# Basecamp pages time entries 50 at a time. Stop well past any real project
# so a missing X-Pages header cannot loop forever.
_MAX_PAGES = 200


def _paged(path: str, item_tag: str) -> tuple[list[ET.Element], bool]:
    """Follow Basecamp's page query param and X-Pages header."""
    items: list[ET.Element] = []
    seen: set[str] = set()
    page = 1
    while page <= _MAX_PAGES:
        separator = "&" if "?" in path else "?"
        root, headers = _fetch(f"{path}{separator}page={page}")
        batch = root.findall(item_tag)
        if not batch:
            return items, False
        added = 0
        for element in batch:
            item_id = _elem_text(element, "id")
            if item_id and item_id in seen:
                continue
            if item_id:
                seen.add(item_id)
            items.append(element)
            added += 1
        # A repeated page means this endpoint ignores the page parameter.
        if added == 0:
            return items, False
        total_pages = int(headers.get("x-pages") or "0")
        if total_pages:
            if page >= total_pages:
                return items, False
        elif len(batch) < 50:
            return items, False
        page += 1
    return items, True


def _parse_date(value: str) -> datetime:
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    raise ValueError(f"Date must be YYYY-MM-DD, got {value!r}")


def _date_windows(start: datetime, end: datetime):
    """Split a range into chunks the report endpoint will accept (max 6 months)."""
    cursor = start
    while cursor <= end:
        window_end = min(end, cursor + timedelta(days=180))
        yield cursor, window_end
        cursor = window_end + timedelta(days=1)


def _post(path: str, body: str) -> ET.Element:
    with _client() as client:
        response = client.post(path, content=body.encode())
        response.raise_for_status()
        if response.text.strip():
            return ET.fromstring(response.text)
        return ET.Element("ok")


def _put(path: str, body: str = "") -> ET.Element:
    with _client() as client:
        response = client.put(path, content=body.encode())
        response.raise_for_status()
        if response.text.strip():
            return ET.fromstring(response.text)
        return ET.Element("ok")


def _elem_text(el: Optional[ET.Element], tag: str, default: str = "") -> str:
    if el is None:
        return default
    child = el.find(tag)
    if child is None or child.text is None:
        return default
    return child.text.strip()


# Fields the Basecamp API returns that must never reach an MCP client.
SENSITIVE_FIELDS = {"token", "password", "api_token"}


def _elem_to_dict(el: ET.Element) -> dict:
    """Convert an XML element's direct children to a dict, dropping secrets."""
    result = {}
    for child in el:
        tag = child.tag.replace("-", "_")
        if tag in SENSITIVE_FIELDS:
            continue
        result[tag] = child.text.strip() if child.text else ""
    return result


# ─── Projects ────────────────────────────────────────────────────────────────


@mcp.tool(annotations=READ_ONLY)
def list_projects() -> list[dict]:
    """List all active Basecamp Classic projects."""
    root = _get("/projects.xml")
    projects = []
    for proj in root.findall("project"):
        projects.append({
            "id": _elem_text(proj, "id"),
            "name": _elem_text(proj, "name"),
            "status": _elem_text(proj, "status"),
            "created_on": _elem_text(proj, "created-on"),
            "last_changed_on": _elem_text(proj, "last-changed-on"),
            "description": _elem_text(proj, "description"),
        })
    return projects


@mcp.tool(annotations=READ_ONLY)
def get_project(project_id: int) -> dict:
    """Get details for a specific Basecamp Classic project.

    Args:
        project_id: The numeric project ID.
    """
    root = _get(f"/projects/{project_id}.xml")
    return _elem_to_dict(root)


# ─── To-do Lists ─────────────────────────────────────────────────────────────


@mcp.tool(annotations=READ_ONLY)
def list_todo_lists(project_id: int) -> list[dict]:
    """List all to-do lists for a project.

    Args:
        project_id: The numeric project ID.
    """
    root = _get(f"/projects/{project_id}/todo_lists.xml")
    lists = []
    for tl in root.findall("todo-list"):
        lists.append({
            "id": _elem_text(tl, "id"),
            "name": _elem_text(tl, "name"),
            "description": _elem_text(tl, "description"),
            "complete": _elem_text(tl, "complete"),
            "completed_count": _elem_text(tl, "completed-count"),
            "uncompleted_count": _elem_text(tl, "uncompleted-count"),
        })
    return lists


@mcp.tool(annotations=READ_ONLY)
def get_todo_list(todo_list_id: int) -> dict:
    """Get a specific to-do list with its items.

    Args:
        todo_list_id: The numeric to-do list ID.
    """
    root = _get(f"/todo_lists/{todo_list_id}.xml")
    result = _elem_to_dict(root)
    # Include todo items if present
    items_el = root.find("todo-items")
    if items_el is not None:
        items = []
        for item in items_el.findall("todo-item"):
            items.append({
                "id": _elem_text(item, "id"),
                "content": _elem_text(item, "content"),
                "completed": _elem_text(item, "completed"),
                "due_at": _elem_text(item, "due-at"),
                "assignee": _elem_text(item, "responsible-party-name"),
            })
        result["todo_items"] = items
    return result


# ─── To-do Items ─────────────────────────────────────────────────────────────


@mcp.tool(annotations=READ_ONLY)
def list_todo_items(todo_list_id: int) -> list[dict]:
    """List all to-do items in a to-do list.

    Args:
        todo_list_id: The numeric to-do list ID.
    """
    root = _get(f"/todo_lists/{todo_list_id}/todo_items.xml")
    items = []
    for item in root.findall("todo-item"):
        items.append({
            "id": _elem_text(item, "id"),
            "content": _elem_text(item, "content"),
            "completed": _elem_text(item, "completed"),
            "due_at": _elem_text(item, "due-at"),
            "created_on": _elem_text(item, "created-on"),
            "assignee": _elem_text(item, "responsible-party-name"),
            "creator": _elem_text(item, "creator-name"),
        })
    return items


@mcp.tool
def create_todo_item(
    todo_list_id: int,
    content: str,
    responsible_party_id: Optional[int] = None,
    due_at: Optional[str] = None,
    notify: bool = False,
) -> dict:
    """Create a new to-do item in a to-do list.

    Args:
        todo_list_id: The numeric to-do list ID.
        content: The text of the to-do item.
        responsible_party_id: Optional person ID to assign the item to.
        due_at: Optional due date in YYYY-MM-DD format.
        notify: Whether to notify the assigned person.
    """
    parts = [f"<content>{content}</content>"]
    if responsible_party_id is not None:
        parts.append(f"<responsible-party-id>{responsible_party_id}</responsible-party-id>")
    if due_at:
        parts.append(f"<due-at>{due_at}</due-at>")
    if notify:
        parts.append("<notify>true</notify>")
    body = f"<todo-item>{''.join(parts)}</todo-item>"
    root = _post(f"/todo_lists/{todo_list_id}/todo_items.xml", body)
    return _elem_to_dict(root)


@mcp.tool
def update_todo_item(
    todo_item_id: int,
    content: Optional[str] = None,
    responsible_party_id: Optional[int] = None,
    due_at: Optional[str] = None,
    notify: bool = False,
) -> dict:
    """Update an existing to-do item.

    Args:
        todo_item_id: The numeric to-do item ID.
        content: New text for the item.
        responsible_party_id: Person ID to assign the item to (use 0 to unassign).
        due_at: Due date in YYYY-MM-DD format.
        notify: Whether to notify the assigned person.
    """
    parts = []
    if content is not None:
        parts.append(f"<content>{content}</content>")
    if responsible_party_id is not None:
        parts.append(f"<responsible-party-id>{responsible_party_id}</responsible-party-id>")
    if due_at is not None:
        parts.append(f"<due-at>{due_at}</due-at>")
    if notify:
        parts.append("<notify>true</notify>")
    body = f"<todo-item>{''.join(parts)}</todo-item>"
    root = _put(f"/todo_items/{todo_item_id}.xml", body)
    return _elem_to_dict(root)


@mcp.tool
def complete_todo_item(todo_item_id: int) -> str:
    """Mark a to-do item as complete.

    Args:
        todo_item_id: The numeric to-do item ID.
    """
    _put(f"/todo_items/{todo_item_id}/complete")
    return f"Todo item {todo_item_id} marked complete"


@mcp.tool
def uncomplete_todo_item(todo_item_id: int) -> str:
    """Mark a to-do item as incomplete.

    Args:
        todo_item_id: The numeric to-do item ID.
    """
    _put(f"/todo_items/{todo_item_id}/uncomplete")
    return f"Todo item {todo_item_id} marked incomplete"


# ─── Messages ────────────────────────────────────────────────────────────────


@mcp.tool(annotations=READ_ONLY)
def list_messages(project_id: int) -> list[dict]:
    """List recent messages/posts for a project.

    Args:
        project_id: The numeric project ID.
    """
    root = _get(f"/projects/{project_id}/posts.xml")
    messages = []
    for post in root.findall("post"):
        messages.append({
            "id": _elem_text(post, "id"),
            "title": _elem_text(post, "title"),
            "author": _elem_text(post, "author-name"),
            "posted_on": _elem_text(post, "posted-on"),
            "category": _elem_text(post, "category-name"),
            "comments_count": _elem_text(post, "comments-count"),
        })
    return messages


@mcp.tool(annotations=READ_ONLY)
def get_message(message_id: int) -> dict:
    """Get a specific message/post with its body.

    Args:
        message_id: The numeric message ID.
    """
    root = _get(f"/posts/{message_id}.xml")
    return _elem_to_dict(root)


@mcp.tool
def create_message(
    project_id: int,
    title: str,
    body: str,
    category_id: Optional[int] = None,
    private: bool = False,
) -> dict:
    """Create a new message/post in a project.

    Args:
        project_id: The numeric project ID.
        title: The message title.
        body: The message body (HTML allowed).
        category_id: Optional category ID for the message.
        private: Whether the message is private.
    """
    parts = [f"<title>{title}</title>", f"<body>{body}</body>"]
    if category_id is not None:
        parts.append(f"<category-id>{category_id}</category-id>")
    if private:
        parts.append("<private>true</private>")
    xml_body = f"<request>{''.join(parts)}</request>"
    root = _post(f"/projects/{project_id}/posts.xml", xml_body)
    return _elem_to_dict(root)


# ─── Comments ────────────────────────────────────────────────────────────────


@mcp.tool(annotations=READ_ONLY)
def list_comments(message_id: int) -> list[dict]:
    """List comments on a message/post.

    Args:
        message_id: The numeric message ID.
    """
    root = _get(f"/posts/{message_id}/comments.xml")
    comments = []
    for comment in root.findall("comment"):
        comments.append({
            "id": _elem_text(comment, "id"),
            "body": _elem_text(comment, "body"),
            "author": _elem_text(comment, "author-name"),
            "created_at": _elem_text(comment, "created-at"),
        })
    return comments


@mcp.tool
def create_comment(message_id: int, body: str) -> dict:
    """Add a comment to a message/post.

    Args:
        message_id: The numeric message ID.
        body: The comment body (HTML allowed).
    """
    xml_body = f"<comment><body>{body}</body></comment>"
    root = _post(f"/posts/{message_id}/comments.xml", xml_body)
    return _elem_to_dict(root)


# ─── People ──────────────────────────────────────────────────────────────────


@mcp.tool(annotations=READ_ONLY)
def list_people() -> list[dict]:
    """List all people in the Basecamp Classic account."""
    root = _get("/people.xml")
    people = []
    for person in root.findall("person"):
        people.append({
            "id": _elem_text(person, "id"),
            "name": _elem_text(person, "name"),
            "email_address": _elem_text(person, "email-address"),
            "user_name": _elem_text(person, "user-name"),
            "title": _elem_text(person, "title"),
        })
    return people


@mcp.tool(annotations=READ_ONLY)
def get_person(person_id: int) -> dict:
    """Get details for a specific person.

    Args:
        person_id: The numeric person ID.
    """
    root = _get(f"/people/{person_id}.xml")
    return _elem_to_dict(root)


@mcp.tool(annotations=READ_ONLY)
def get_current_person() -> dict:
    """Get the currently authenticated person's details."""
    root = _get("/me.xml")
    return _elem_to_dict(root)


# ─── Milestones ───────────────────────────────────────────────────────────────


@mcp.tool(annotations=READ_ONLY)
def list_milestones(project_id: int) -> list[dict]:
    """List all milestones for a project.

    Args:
        project_id: The numeric project ID.
    """
    root = _get(f"/projects/{project_id}/milestones/list")
    milestones = []
    for ms in root.findall("milestone"):
        milestones.append({
            "id": _elem_text(ms, "id"),
            "title": _elem_text(ms, "title"),
            "deadline": _elem_text(ms, "deadline"),
            "completed": _elem_text(ms, "completed"),
            "created_on": _elem_text(ms, "created-on"),
            "responsible_party_name": _elem_text(ms, "responsible-party-name"),
        })
    return milestones


@mcp.tool
def complete_milestone(milestone_id: int) -> str:
    """Mark a milestone as complete.

    Args:
        milestone_id: The numeric milestone ID.
    """
    _put(f"/milestones/complete/{milestone_id}")
    return f"Milestone {milestone_id} marked complete"


@mcp.tool
def uncomplete_milestone(milestone_id: int) -> str:
    """Mark a milestone as incomplete.

    Args:
        milestone_id: The numeric milestone ID.
    """
    _put(f"/milestones/uncomplete/{milestone_id}")
    return f"Milestone {milestone_id} marked incomplete"


# ─── Time Entries ─────────────────────────────────────────────────────────────


def _time_entry_dict(entry: ET.Element) -> dict:
    return {
        "id": _elem_text(entry, "id"),
        "person_id": _elem_text(entry, "person-id"),
        "person_name": _elem_text(entry, "person-name"),
        "date": _elem_text(entry, "date"),
        "hours": _elem_text(entry, "hours"),
        "description": _elem_text(entry, "description"),
        "todo_item_id": _elem_text(entry, "todo-item-id"),
    }


@mcp.tool(annotations=READ_ONLY)
def list_time_entries(
    project_id: int,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> dict:
    """List time entries for a project, following every result page.

    Basecamp returns 50 entries per page. This walks all pages. Pass both
    from_date and to_date (YYYY-MM-DD) for a bounded report such as a month.
    Ranges longer than six months are requested in chunks, which is the
    report endpoint's limit.

    Args:
        project_id: The numeric project ID.
        from_date: Optional start date, inclusive, YYYY-MM-DD.
        to_date: Optional end date, inclusive, YYYY-MM-DD.
    """
    if (from_date is None) != (to_date is None):
        raise ValueError("Pass both from_date and to_date, or neither")

    elements: list[ET.Element] = []
    truncated = False
    if from_date and to_date:
        start = _parse_date(from_date)
        end = _parse_date(to_date)
        if end < start:
            raise ValueError("to_date must be on or after from_date")
        for window_start, window_end in _date_windows(start, end):
            path = (
                "/time_entries/report.xml"
                f"?from={window_start:%Y%m%d}&to={window_end:%Y%m%d}"
                f"&filter_project_id={project_id}"
            )
            batch, hit_cap = _paged(path, "time-entry")
            elements.extend(batch)
            truncated = truncated or hit_cap
    else:
        elements, truncated = _paged(
            f"/projects/{project_id}/time_entries.xml", "time-entry"
        )

    entries = [_time_entry_dict(entry) for entry in elements]
    total_hours = round(sum(float(entry["hours"] or 0) for entry in entries), 2)
    return {
        "project_id": project_id,
        "from_date": from_date,
        "to_date": to_date,
        "count": len(entries),
        "total_hours": total_hours,
        "truncated": truncated,
        "entries": entries,
    }


@mcp.tool
def create_time_entry(
    project_id: int,
    date: str,
    hours: float,
    description: str,
    person_id: Optional[int] = None,
    todo_item_id: Optional[int] = None,
) -> dict:
    """Log a time entry on a project.

    Args:
        project_id: The numeric project ID.
        date: Date of the time entry in YYYY-MM-DD format.
        hours: Number of hours to log (e.g. 1.5).
        description: Description of work done.
        person_id: Optional person ID (defaults to current user).
        todo_item_id: Optional to-do item ID to associate the entry with.
    """
    parts = [
        f"<date>{date}</date>",
        f"<hours>{hours}</hours>",
        f"<description>{description}</description>",
    ]
    if person_id is not None:
        parts.append(f"<person-id>{person_id}</person-id>")
    if todo_item_id is not None:
        parts.append(f"<todo-item-id>{todo_item_id}</todo-item-id>")
    xml_body = f"<time-entry>{''.join(parts)}</time-entry>"
    root = _post(f"/projects/{project_id}/time_entries.xml", xml_body)
    return _elem_to_dict(root)


# ─── Resources ───────────────────────────────────────────────────────────────


@mcp.resource("basecamp://projects", mime_type="application/json")
def resource_list_projects() -> str:
    """All active Basecamp Classic projects."""
    return json.dumps(list_projects())


@mcp.resource("basecamp://projects/{project_id}", mime_type="application/json")
def resource_get_project(project_id: int) -> str:
    """A single Basecamp Classic project."""
    return json.dumps(get_project(project_id))


@mcp.resource("basecamp://projects/{project_id}/todo_lists", mime_type="application/json")
def resource_list_todo_lists(project_id: int) -> str:
    """All to-do lists for a project."""
    return json.dumps(list_todo_lists(project_id))


@mcp.resource("basecamp://todo_lists/{todo_list_id}", mime_type="application/json")
def resource_get_todo_list(todo_list_id: int) -> str:
    """A to-do list with all its items."""
    return json.dumps(get_todo_list(todo_list_id))


@mcp.resource("basecamp://projects/{project_id}/messages", mime_type="application/json")
def resource_list_messages(project_id: int) -> str:
    """All messages/posts for a project."""
    return json.dumps(list_messages(project_id))


@mcp.resource("basecamp://messages/{message_id}", mime_type="application/json")
def resource_get_message(message_id: int) -> str:
    """A single message/post with its full body."""
    return json.dumps(get_message(message_id))


@mcp.resource("basecamp://people", mime_type="application/json")
def resource_list_people() -> str:
    """All people in the Basecamp Classic account."""
    return json.dumps(list_people())


if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "stdio").strip().lower()
    if transport in {"http", "streamable-http"}:
        if not MCP_AUTH_TOKEN:
            raise SystemExit(
                "MCP_AUTH_TOKEN is required when MCP_TRANSPORT=http "
                "(set a shared secret for ChatGPT / remote clients)"
            )
        port = int(os.environ.get("PORT", "8000"))
        mcp.run(transport="http", host="0.0.0.0", port=port, path="/mcp")
    else:
        mcp.run()
