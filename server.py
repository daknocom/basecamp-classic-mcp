"""Basecamp Classic MCP Server"""

import json
import os
import xml.etree.ElementTree as ET
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
    with _client() as client:
        response = client.get(path)
        response.raise_for_status()
        return ET.fromstring(response.text)


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


def _elem_to_dict(el: ET.Element) -> dict:
    """Convert an XML element's direct children to a dict."""
    result = {}
    for child in el:
        tag = child.tag.replace("-", "_")
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


@mcp.tool(annotations=READ_ONLY)
def list_time_entries(project_id: int) -> list[dict]:
    """List all time entries for a project.

    Args:
        project_id: The numeric project ID.
    """
    root = _get(f"/projects/{project_id}/time_entries.xml")
    entries = []
    for entry in root.findall("time-entry"):
        entries.append({
            "id": _elem_text(entry, "id"),
            "person_name": _elem_text(entry, "person-name"),
            "date": _elem_text(entry, "date"),
            "hours": _elem_text(entry, "hours"),
            "description": _elem_text(entry, "description"),
            "todo_item_id": _elem_text(entry, "todo-item-id"),
        })
    return entries


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
