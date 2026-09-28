# Basecamp Classic MCP Server

An MCP server for the [Basecamp Classic API](https://github.com/basecamp/basecamp-classic-api), built with [FastMCP](https://github.com/jlowin/fastmcp).

This fork is set up for team use from ChatGPT:

- Streamable HTTP transport for remote connectors
- Shared bearer-token gate (`MCP_AUTH_TOKEN`)
- Runs as a single Basecamp bot user
- Destructive delete tools removed

Forked from [Boian/basecamp-classic-mcp](https://github.com/Boian/basecamp-classic-mcp).

## Basecamp bot user

1. In Basecamp Classic, add a person such as **MCP Bot** / `mcp-bot@yourcompany.com`.
2. Give that person access to the projects the team should reach through ChatGPT.
3. Sign in as the bot (or have an admin open its **My info** page) and copy its **API token**.
4. Use the token as `BASECAMP_USERNAME` and set `BASECAMP_PASSWORD` to `X`.

Every ChatGPT action (messages, todos, time entries) will be attributed to this bot.

## Configuration

| Variable | Description |
|---|---|
| `BASECAMP_URL` | Your Basecamp account URL, e.g. `https://yourcompany.basecamphq.com` |
| `BASECAMP_USERNAME` | Bot API token (preferred) or username |
| `BASECAMP_PASSWORD` | `X` when using an API token |
| `MCP_AUTH_TOKEN` | Shared secret ChatGPT clients send as a bearer token (required for HTTP) |
| `MCP_TRANSPORT` | `stdio` (default) or `http` |
| `PORT` | HTTP listen port (Render sets this automatically) |

## Local setup

```bash
uv sync
```

### stdio (Claude Desktop / Cursor)

```bash
uv run python server.py
```

### HTTP (ChatGPT / remote clients)

```bash
export MCP_TRANSPORT=http
export MCP_AUTH_TOKEN="$(openssl rand -hex 32)"
export BASECAMP_URL=https://yourcompany.basecamphq.com
export BASECAMP_USERNAME=your-bot-api-token
export BASECAMP_PASSWORD=X
uv run python server.py
```

The MCP endpoint is `http://localhost:8000/mcp`.

## Deploy on Render

This repo is meant to run as a Render **Web Service**:

- **Runtime:** Python
- **Build command:** `pip install uv && uv sync --frozen`
- **Start command:** `uv run python server.py`
- **Env vars:** `MCP_TRANSPORT=http`, plus `BASECAMP_*` and `MCP_AUTH_TOKEN`
- **Plan:** Starter (or higher). Free instances sleep and drop MCP connections.

After deploy, the connector URL is:

```text
https://<your-service>.onrender.com/mcp
```

## Connect from ChatGPT

Each teammate (or a workspace admin) needs a paid ChatGPT plan with connectors enabled.

1. Open **Settings → Apps & Connectors → Advanced** and turn on **Developer mode**.
2. Create a new connector:
   - **Name:** Basecamp Classic
   - **MCP Server URL:** `https://<your-service>.onrender.com/mcp`
   - **Authentication:** Token
   - **Token:** the value of `MCP_AUTH_TOKEN`
3. Trust the connector and confirm the tools load.
4. In a chat, enable the connector and ask something like “list our active Basecamp projects”.

## Claude Desktop (local stdio)

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "basecamp-classic": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/basecamp-classic-mcp", "python", "server.py"],
      "env": {
        "BASECAMP_URL": "https://yourcompany.basecamphq.com",
        "BASECAMP_USERNAME": "your-bot-api-token",
        "BASECAMP_PASSWORD": "X"
      }
    }
  }
}
```

## Available tools

### Projects
- `list_projects` — List all active projects
- `get_project(project_id)` — Get project details

### To-do lists
- `list_todo_lists(project_id)` — List to-do lists in a project
- `get_todo_list(todo_list_id)` — Get a to-do list with its items

### To-do items
- `list_todo_items(todo_list_id)` — List items in a to-do list
- `create_todo_item(todo_list_id, content, ...)` — Create a new to-do item
- `update_todo_item(todo_item_id, ...)` — Update an existing to-do item
- `complete_todo_item(todo_item_id)` — Mark an item complete
- `uncomplete_todo_item(todo_item_id)` — Mark an item incomplete

### Messages
- `list_messages(project_id)` — List recent messages in a project
- `get_message(message_id)` — Get a message with its body
- `create_message(project_id, title, body, ...)` — Post a new message

### Comments
- `list_comments(message_id)` — List comments on a message
- `create_comment(message_id, body)` — Add a comment to a message

### People
- `list_people` — List all people in the account
- `get_person(person_id)` — Get a person's details
- `get_current_person` — Get the authenticated user's details

### Milestones
- `list_milestones(project_id)` — List milestones in a project
- `complete_milestone(milestone_id)` — Mark a milestone complete
- `uncomplete_milestone(milestone_id)` — Mark a milestone incomplete

### Time entries
- `list_time_entries(project_id, from_date, to_date)` — List time entries for a project, following every page. Pass both dates (YYYY-MM-DD) for a range such as a month. The result includes `count`, `total_hours`, and `truncated`.
- `create_time_entry(project_id, date, hours, description, ...)` — Log time on a project

Deleted intentionally: `delete_todo_item`.
