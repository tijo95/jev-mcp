#!/usr/bin/env python3
"""
Jev MCP - Local stdio MCP server that wraps the TypeSafe Jev decision API.

Bypasses jevai.org (Cloudflare WAF issues) by calling api.typesafe.ai/v1/systemone directly.
Exposes the 6 jev_* tools as a local MCP server (stdio transport).

No external dependencies. Pure Python 3.10+.

Environment variables:
  TYPESAFE_API_KEY  (REQUIRED)  API key from https://console.typesafe.ai/settings/keys
  JEV_MODEL         (optional)  Model identifier, default "jev-latest"

Usage (MCP client config):
  {
    "mcpServers": {
      "jev": {
        "command": "python",
        "args": ["path/to/jev_mcp.py"],
        "env": {
          "TYPESAFE_API_KEY": "your-key-here"
        }
      }
    }
  }

Tools exposed:
  - jev_guard_tool_call   : Allow/confirm/review/deny before consequential actions
  - jev_route_model       : Choose best model among candidates
  - jev_route_task        : Route ambiguous tasks (proceed_fast/deep_review/split_task/block)
  - jev_check_research    : Verify evidence for a claim (accept/verify_more/reject)
  - jev_review_completion : Check if an objective is truly complete
  - jev_decide            : Custom state + questions (pass-through)
"""
import os
import sys
import json
import urllib.request
import urllib.error

PROTOCOL_VERSION = "2025-03-26"
SERVER_NAME = "jev-local"
SERVER_VERSION = "3.0.0"

API_URL = "https://api.typesafe.ai/v1/systemone"
API_KEY = os.environ.get("TYPESAFE_API_KEY", "").strip()
MODEL = os.environ.get("JEV_MODEL", "jev-latest")

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"


def log(msg):
    """Log to stderr (stdout is reserved for MCP protocol)."""
    try:
        sys.stderr.write("[jev-mcp] " + str(msg) + "\n")
        sys.stderr.flush()
    except Exception:
        pass


STR = "string"
ARR = "array"

# ---------------------------------------------------------------------------
# Tool definitions (input schemas match the official Jev MCP docs)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "jev_guard_tool_call",
        "description": "Immediately before a consequential tool call. Returns allow, confirm, review, or deny. Does not execute the tool.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tool": {"type": STR, "description": "Name of the tool about to be called"},
                "action": {"type": STR, "description": "What the action does"},
                "arguments_summary": {"type": ARR, "items": {"type": STR}},
                "side_effects": {"type": ARR, "items": {"type": STR}},
                "safeguards": {"type": ARR, "items": {"type": STR}},
                "policy": {"type": ARR, "items": {"type": STR}},
                "reversibility": {
                    "type": STR,
                    "enum": ["reversible", "partially_reversible", "irreversible", "unknown"],
                },
            },
            "required": ["tool", "action"],
        },
    },
    {
        "name": "jev_route_model",
        "description": "Choose among models the current environment can actually invoke based on task stakes, quality, cost, latency, context, and tool-use needs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": STR},
                "candidates": {
                    "type": ARR,
                    "items": {
                        "type": "object",
                        "required": ["id", "description"],
                        "properties": {
                            "id": {"type": STR},
                            "description": {"type": STR},
                            "cost": {"type": STR},
                            "latency": {"type": STR},
                        },
                    },
                },
                "priorities": {"type": ARR, "items": {"type": STR}},
                "constraints": {"type": ARR, "items": {"type": STR}},
                "stakes": {"type": STR},
            },
            "required": ["task", "candidates"],
        },
    },
    {
        "name": "jev_route_task",
        "description": "Choose proceed_fast, deep_review, split_task, or block for an ambiguous or risky task.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": STR},
                "evidence": {"type": ARR, "items": {"type": STR}},
                "constraints": {"type": ARR, "items": {"type": STR}},
            },
            "required": ["task"],
        },
    },
    {
        "name": "jev_check_research",
        "description": "Judge whether supplied evidence is enough to accept a precise claim, needs more verification, or should be rejected. Does not browse.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "claim": {"type": STR},
                "evidence": {"type": ARR, "items": {"type": STR}},
                "source_quality": {"type": STR},
                "stakes": {"type": STR},
            },
            "required": ["claim"],
        },
    },
    {
        "name": "jev_review_completion",
        "description": "Compare the objective, completed work, verification, and known gaps before reporting a task complete.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "objective": {"type": STR},
                "completed_work": {"type": ARR, "items": {"type": STR}},
                "verification": {"type": ARR, "items": {"type": STR}},
                "known_gaps": {"type": ARR, "items": {"type": STR}},
            },
            "required": ["objective"],
        },
    },
    {
        "name": "jev_decide",
        "description": "Send custom state and choice/noul/score questions when no preset fits. Pass-through to the TypeSafe API.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "state": {},
                "questions": {"type": "object"},
                "model": {"type": STR},
            },
            "required": ["state", "questions"],
        },
    },
]


def public_tool(t):
    return {
        "name": t["name"],
        "description": t["description"],
        "inputSchema": t["inputSchema"],
    }


# ---------------------------------------------------------------------------
# TypeSafe API call
# ---------------------------------------------------------------------------

def typesafe_call(state, questions, model=None):
    """Call the TypeSafe evaluation endpoint directly."""
    use_model = model or MODEL
    payload = {
        "state": state,
        "model": use_model,
        "questions": questions,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(API_URL, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", USER_AGENT)
    if API_KEY:
        req.add_header("Authorization", "Bearer " + API_KEY)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, body
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        return e.code, body
    except urllib.error.URLError as e:
        return None, "URL error: " + str(getattr(e, "reason", e))
    except Exception as e:
        return None, "Unexpected error: " + str(e)


# ---------------------------------------------------------------------------
# Tool call translation: jev_* tools -> TypeSafe state + questions
# ---------------------------------------------------------------------------

def make_text_result(text, is_error=False):
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def build_state_and_questions(tool_name, args):
    """Translate the 6 jev_* tools into TypeSafe state + questions format."""

    if tool_name == "jev_decide":
        # Pass-through: user sends state + questions directly
        state = args.get("state", "")
        questions = args.get("questions", {})
        model = args.get("model")
        return state, questions, model

    if tool_name == "jev_check_research":
        state = {
            "claim": args.get("claim", ""),
            "evidence": args.get("evidence", []),
            "source_quality": args.get("source_quality", "unknown"),
            "stakes": args.get("stakes", "medium"),
        }
        questions = {
            "verdict": {
                "type": "choice",
                "instructions": "Based on the claim and evidence provided, is the evidence sufficient to accept the claim, does it need more verification, or should it be rejected?",
                "criteria": {
                    "accept": "The evidence is strong and sufficient to accept the claim as true.",
                    "verify_more": "The evidence is insufficient or weak; more verification is needed before accepting.",
                    "reject": "The evidence contradicts the claim or is too weak; the claim should be rejected.",
                },
            },
        }
        return state, questions, None

    if tool_name == "jev_guard_tool_call":
        state = {
            "tool": args.get("tool", ""),
            "action": args.get("action", ""),
            "arguments_summary": args.get("arguments_summary", []),
            "side_effects": args.get("side_effects", []),
            "safeguards": args.get("safeguards", []),
            "policy": args.get("policy", []),
            "reversibility": args.get("reversibility", "unknown"),
        }
        questions = {
            "decision": {
                "type": "choice",
                "instructions": "Given the tool, action, side effects, safeguards, and policy, should this tool call be allowed, require confirmation, require human review, or be denied?",
                "criteria": {
                    "allow": "The action is safe, within policy, and can proceed without further checks.",
                    "confirm": "The action is reasonable but requires user confirmation before proceeding.",
                    "review": "The action is risky or outside normal policy; it requires human review before proceeding.",
                    "deny": "The action violates policy, is too dangerous, or should not be performed.",
                },
            },
        }
        return state, questions, None

    if tool_name == "jev_route_model":
        state = {
            "task": args.get("task", ""),
            "candidates": args.get("candidates", []),
            "priorities": args.get("priorities", []),
            "constraints": args.get("constraints", []),
            "stakes": args.get("stakes", "medium"),
        }
        criteria = {}
        for c in args.get("candidates", []):
            cid = c.get("id", "unknown")
            desc = c.get("description", "")
            cost = c.get("cost", "")
            lat = c.get("latency", "")
            criteria[cid] = desc + (f" (cost: {cost})" if cost else "") + (f" (latency: {lat})" if lat else "")
        questions = {
            "best_model": {
                "type": "choice",
                "instructions": "Given the task, candidates, priorities, and constraints, which model is the best fit?",
                "criteria": criteria,
            },
        }
        return state, questions, None

    if tool_name == "jev_route_task":
        state = {
            "task": args.get("task", ""),
            "evidence": args.get("evidence", []),
            "constraints": args.get("constraints", []),
        }
        questions = {
            "route": {
                "type": "choice",
                "instructions": "Given the task, evidence, and constraints, what is the best next path?",
                "criteria": {
                    "proceed_fast": "The task is clear and low-risk; proceed quickly without extra checks.",
                    "deep_review": "The task is ambiguous or risky; perform a thorough review before proceeding.",
                    "split_task": "The task is too large or complex; it should be broken into smaller sub-tasks.",
                    "block": "The task cannot proceed safely; it should be blocked and escalated.",
                },
            },
        }
        return state, questions, None

    if tool_name == "jev_review_completion":
        state = {
            "objective": args.get("objective", ""),
            "completed_work": args.get("completed_work", []),
            "verification": args.get("verification", []),
            "known_gaps": args.get("known_gaps", []),
        }
        questions = {
            "status": {
                "type": "choice",
                "instructions": "Given the objective, completed work, verification performed, and known gaps, is the objective truly complete?",
                "criteria": {
                    "complete": "The objective is fully met; all work is done and verified.",
                    "verify_more": "The work is mostly done but verification is incomplete; more checks are needed.",
                    "incomplete": "The objective is not met; significant work remains.",
                },
            },
        }
        return state, questions, None

    return None, None, None


# ---------------------------------------------------------------------------
# MCP protocol handler
# ---------------------------------------------------------------------------

def handle_tools_call(params):
    name = params.get("name")
    arguments = params.get("arguments", {})
    if not isinstance(arguments, dict):
        arguments = {}

    known = [t["name"] for t in TOOLS]
    if name not in known:
        return make_text_result(json.dumps({"error": "Unknown tool: " + str(name)}), True)

    state, questions, model = build_state_and_questions(name, arguments)
    if state is None:
        return make_text_result(json.dumps({"error": "Cannot translate tool: " + str(name)}), True)

    status, body = typesafe_call(state, questions, model)
    if status is None:
        return make_text_result(body, True)

    try:
        parsed = json.loads(body)
    except Exception:
        parsed = None

    if status >= 400:
        text = body if parsed is None else json.dumps(parsed)
        return make_text_result(text, True)

    if parsed is None:
        return make_text_result(body, False)

    result = {
        "content": [{"type": "text", "text": json.dumps(parsed, indent=2, ensure_ascii=False)}],
        "isError": False,
        "structuredContent": parsed,
    }
    return result


def handle(req):
    method = req.get("method")
    rid = req.get("id")
    params = req.get("params", {}) or {}
    is_notification = rid is None

    if method == "initialize":
        requested = params.get("protocolVersion")
        result = {
            "protocolVersion": requested or PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }
    elif method == "notifications/initialized":
        return None
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [public_tool(t) for t in TOOLS]}
    elif method == "tools/call":
        result = handle_tools_call(params)
    else:
        if is_notification:
            return None
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "error": {"code": -32601, "message": "Method not found: " + str(method)},
        }

    if is_notification:
        return None
    return {"jsonrpc": "2.0", "id": rid, "result": result}


# ---------------------------------------------------------------------------
# Main loop (stdio transport)
# ---------------------------------------------------------------------------

def main():
    log(
        "start jev-mcp v" + SERVER_VERSION
        + " | api=" + API_URL
        + " | model=" + MODEL
        + " | key_set=" + ("yes" if API_KEY else "NO (set TYPESAFE_API_KEY)")
    )
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception as e:
            log("invalid json: " + str(e))
            continue
        try:
            resp = handle(req)
        except Exception as e:
            log("handler error: " + str(e))
            resp = {
                "jsonrpc": "2.0",
                "id": req.get("id"),
                "error": {"code": -32603, "message": str(e)},
            }
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
