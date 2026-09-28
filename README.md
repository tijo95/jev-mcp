# Jev MCP 

A lightweight, zero-dependency **local stdio MCP server** that wraps the [TypeSafe Jev](https://docs.typesafe.ai/) decision API. It exposes the 6 `jev_*` judgment tools to any MCP client (VS Code, Cursor, Claude Desktop, etc.).

## Why?

The official remote MCP server at `jevai.org/api/mcp` can be blocked by Cloudflare WAF (Error 1010) depending on the client's user-agent. This local server **bypasses that issue** by calling `api.typesafe.ai/v1/systemone` directly with a browser-like user-agent.

## Features

- ✅ **Zero dependencies** — pure Python 3.10+, stdlib only
- ✅ **6 tools** — `jev_guard_tool_call`, `jev_route_model`, `jev_route_task`, `jev_check_research`, `jev_review_completion`, `jev_decide`
- ✅ **MCP protocol 2025-03-26** — `initialize`, `ping`, `tools/list`, `tools/call`
- ✅ **Browser user-agent** — avoids Cloudflare 1010 blocks
- ✅ **Environment-based auth** — no key in source code

## Installation

No `pip install` needed. Just Python 3.10+.

```bash
# Clone
git clone https://github.com/tijo95/jev-mcp.git
cd jev-mcp
```

## Configuration

### 1. Get your API key

Create a key at [https://console.typesafe.ai/settings/keys](https://console.typesafe.ai/settings/keys).

### 2. MCP client config

**VS Code / Cursor** (`mcp.json`):
```json
{
  "mcpServers": {
    "jev": {
      "command": "python",
      "args": ["path/to/jev_mcp.py"],
      "env": {
        "TYPESAFE_API_KEY": "your-api-key-here"
      }
    }
  }
}
```

**Claude Desktop** (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "jev": {
      "command": "python",
      "args": ["/absolute/path/to/jev_mcp.py"],
      "env": {
        "TYPESAFE_API_KEY": "your-api-key-here"
      }
    }
  }
}
```

### Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TYPESAFE_API_KEY` | **Yes** | — | API key from console.typesafe.ai |
| `JEV_MODEL` | No | `jev-latest` | Model identifier |

## The 6 Tools

| Tool | Purpose | Key params |
|------|---------|------------|
| `jev_guard_tool_call` | Allow/confirm/review/deny before consequential actions | `tool`, `action` |
| `jev_route_model` | Choose best model among candidates | `task`, `candidates` |
| `jev_route_task` | Route ambiguous tasks (fast/review/split/block) | `task` |
| `jev_check_research` | Verify evidence for a claim | `claim`, `evidence` |
| `jev_review_completion` | Check if an objective is truly complete | `objective` |
| `jev_decide` | Custom state + questions (pass-through) | `state`, `questions` |

## Example: Classify support tickets

```python
# Using jev_decide with custom questions
{
    "state": {
        "ticket": "Server down, ERR_CONN_REFUSED, 14h outage"
    },
    "questions": {
        "severity": {
            "type": "choice",
            "instructions": "Classify the severity",
            "criteria": {
                "low": "No major disruption",
                "medium": "Limited disruption",
                "critical": "Major outage or security issue"
            }
        }
    }
}
```

## Project structure

```
jev-mcp/
├── jev_mcp.py      # The MCP server (single file, no deps)
├── README.md
└── .gitignore
```

## License

MIT
