#!/usr/bin/env python3
"""Small local Gateway fixture for Android emulator UI and SSE smoke tests."""

from __future__ import annotations

import argparse
import json
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


TASK_RUN_THREAD_ID = "fixture-task-thread-1"
AGENT_RUN_THREAD_ID = "fixture-agent-run-thread-1"
THREADS: dict[str, dict] = {
    TASK_RUN_THREAD_ID: {
        "title": "Morning research brief",
        "updated_at": "2026-07-19T09:01:12+08:00",
        "messages": [
            {
                "type": "human",
                "id": "fixture-task-prompt",
                "content": "Summarize the latest workspace research.",
            },
            {
                "type": "ai",
                "id": "fixture-task-result",
                "content": "The scheduled brief completed with the latest workspace research summary.",
            },
        ],
        "todos": [],
        "artifacts": [],
    },
    AGENT_RUN_THREAD_ID: {
        "title": "Research source review",
        "updated_at": "2026-07-20T11:14:20+08:00",
        "messages": [
            {
                "type": "human",
                "id": "fixture-agent-run-prompt",
                "content": "Review the evidence for the release plan.",
            },
            {
                "type": "ai",
                "id": "fixture-agent-run-result",
                "content": "The evidence is consistent and the release plan is ready for review.",
            },
        ],
        "todos": [],
        "artifacts": [],
    },
}
RUNS: dict[str, dict] = {}
STREAM_DELAY = 1.5
AGENT_RUNS = [
    {
        "run_id": "fixture-research-run-success",
        "thread_id": AGENT_RUN_THREAD_ID,
        "thread_title": "Research source review",
        "assistant_id": "researcher",
        "status": "success",
        "model_name": "deerflow-pro",
        "created_at": "2026-07-20T11:12:00+08:00",
        "updated_at": "2026-07-20T11:14:20+08:00",
        "duration_seconds": 140.0,
        "total_tokens": 2840,
        "message_count": 6,
        "cost": None,
        "error": None,
    },
    {
        "run_id": "fixture-creator-run-error",
        "thread_id": TASK_RUN_THREAD_ID,
        "thread_title": "Morning research brief",
        "assistant_id": "creator",
        "status": "error",
        "model_name": "deerflow-fast",
        "created_at": "2026-07-19T09:00:00+08:00",
        "updated_at": "2026-07-19T09:00:04+08:00",
        "duration_seconds": 4.0,
        "total_tokens": 120,
        "message_count": 2,
        "cost": None,
        "error": "The configured model was unavailable.",
    },
]
TASKS: dict[str, dict] = {
    "morning-brief": {
        "id": "morning-brief",
        "title": "Morning research brief",
        "prompt": "Summarize the latest workspace research.",
        "schedule_type": "cron",
        "schedule_spec": {"cron": "0 9 * * 1-5"},
        "timezone": "Asia/Shanghai",
        "status": "active",
        "next_run_at": "2026-07-22T09:00:00+08:00",
        "last_error": None,
        "run_count": 12,
    },
    "one-time-release": {
        "id": "one-time-release",
        "title": "Release review",
        "prompt": "Review the final release before launch.",
        "schedule_type": "once",
        "schedule_spec": {"run_at": "2026-12-31T09:30:00+08:00"},
        "timezone": "Asia/Shanghai",
        "status": "active",
        "next_run_at": "2026-12-31T09:30:00+08:00",
        "last_error": None,
        "run_count": 0,
    },
}


def fresh_memory() -> dict:
    return {
        "version": "1.0",
        "lastUpdated": "2026-07-20T09:00:00+08:00",
        "user": {
            "workContext": {
                "summary": "Building and validating the DeerFlow Android client.",
                "updatedAt": "2026-07-20T08:30:00+08:00",
            },
            "personalContext": {
                "summary": "Prefers concise progress reports backed by current test evidence.",
                "updatedAt": "2026-07-20T08:30:00+08:00",
            },
            "topOfMind": {
                "summary": "Finish the native Memory workspace and offline cache.",
                "updatedAt": "2026-07-20T09:00:00+08:00",
            },
        },
        "history": {
            "recentMonths": {
                "summary": "Migrated Android preferences to DataStore and added Room metadata snapshots.",
                "updatedAt": "2026-07-20T08:45:00+08:00",
            },
            "earlierContext": {"summary": "", "updatedAt": ""},
            "longTermBackground": {
                "summary": "Uses Kotlin, Compose, and JDK 17 for Android development.",
                "updatedAt": "2026-07-20T08:30:00+08:00",
            },
        },
        "facts": [
            {
                "id": "fixture-jdk17",
                "content": "Use JDK 17 for DeerFlow Android builds.",
                "category": "preference",
                "confidence": 0.98,
                "createdAt": "2026-07-20T08:30:00+08:00",
                "source": "fixture",
            },
            {
                "id": "fixture-room",
                "content": "Workspace metadata remains available from Room while offline.",
                "category": "workflow",
                "confidence": 0.92,
                "createdAt": "2026-07-20T08:45:00+08:00",
                "source": "fixture",
            },
        ],
    }


MEMORY = fresh_memory()

SKILLS = [
    ("deep-research", "Search multiple sources, compare evidence, and produce a cited research brief.", "Research"),
    ("writing-studio", "Draft, rewrite, and polish articles, reports, emails, and social content.", "Writing"),
    ("web-collector", "Collect structured facts from public web pages and organize the findings.", "Research"),
    ("learning-coach", "Explain a topic step by step, create exercises, and check understanding.", "Learning"),
    ("frontend-design", "Design and build polished responsive web experiences from a concrete brief.", "Creation"),
    ("image-generation", "Turn an idea into a visual direction and generate supporting image assets.", "Creation"),
    ("data-analysis", "Inspect tabular data, find meaningful patterns, and summarize decisions.", "Analysis"),
    ("minutes-generator", "Convert meeting notes into decisions, owners, risks, and follow-up actions.", "Productivity"),
    ("document-review", "Review long documents for gaps, contradictions, and actionable improvements.", "Analysis"),
    ("presentation-maker", "Structure a clear narrative and produce an audience-ready presentation outline.", "Creation"),
]
SKILL_STATES = {name: True for name, _description, _category in SKILLS}
MCP_SERVERS = {
    "research-tools": {
        "enabled": True,
        "type": "http",
        "url": "https://mcp.example.test/research",
        "headers": {"Authorization": "***"},
        "description": "Search and summarize verified research sources.",
        "tools": {"search_sources": {"enabled": True}},
        "routing": {"keywords": ["research"]},
    },
    "local-files": {
        "enabled": False,
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@example/files"],
        "description": "Read and organize approved workspace files.",
        "tools": {},
    },
}
MCP_TOOLS = [
    {
        "server_name": "research-tools",
        "name": "search_sources",
        "description": "Search verified research sources and return citations.",
    },
    {
        "server_name": "research-tools",
        "name": "summarize_sources",
        "description": "Summarize selected research sources into a brief.",
    },
]
SSO_PROVIDERS = [
    {
        "id": "fixture-oidc",
        "display_name": "Fixture SSO",
        "type": "oidc",
    },
]
CHANNEL_PROVIDERS = [
    {
        "provider": "telegram",
        "display_name": "Telegram",
        "enabled": True,
        "configured": False,
        "connectable": False,
        "unavailable_reason": "Runtime credentials are required.",
        "auth_mode": "deep_link",
        "connection_status": "not_connected",
        "credential_fields": [
            {"name": "bot_token", "label": "Bot token", "type": "password", "required": True},
            {"name": "bot_username", "label": "Bot username", "type": "text", "required": True},
        ],
        "credential_values": {},
    },
    {
        "provider": "slack",
        "display_name": "Slack",
        "enabled": True,
        "configured": True,
        "connectable": True,
        "unavailable_reason": None,
        "auth_mode": "binding_code",
        "connection_status": "not_connected",
        "credential_fields": [
            {"name": "bot_token", "label": "Bot token", "type": "password", "required": True},
            {"name": "app_token", "label": "App token", "type": "password", "required": True},
        ],
        "credential_values": {"bot_token": "********", "app_token": "********"},
    },
    {
        "provider": "discord",
        "display_name": "Discord",
        "enabled": False,
        "configured": False,
        "connectable": False,
        "unavailable_reason": "Channel provider is disabled.",
        "auth_mode": "binding_code",
        "connection_status": "not_connected",
        "credential_fields": [
            {"name": "bot_token", "label": "Bot token", "type": "password", "required": True},
        ],
        "credential_values": {},
    },
]


def skill_payload(name: str, description: str, category: str) -> dict:
    return {
        "name": name,
        "description": description,
        "category": category,
        "enabled": SKILL_STATES[name],
    }


def channel_provider(provider: str) -> dict | None:
    return next((item for item in CHANNEL_PROVIDERS if item["provider"] == provider), None)


def thread_summary(thread_id: str, thread: dict) -> dict:
    return {
        "thread_id": thread_id,
        "status": "idle",
        "updated_at": thread["updated_at"],
        "values": {"title": thread["title"]},
    }


class GatewayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        print(f"[mock-gateway] {self.command} {self.path} - {format % args}", flush=True)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def write_json(self, payload: object, status: int = 200, headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def write_bytes(self, body: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/v1/auth/me":
            self.write_json({"id": "emulator-user", "email": "android@deerflow.local", "system_role": "admin", "needs_setup": False})
        elif path == "/api/v1/auth/providers":
            self.write_json({"providers": SSO_PROVIDERS})
        elif path == "/api/features":
            self.write_json({"agents_api": {"enabled": True}})
        elif path == "/api/models":
            self.write_json({"models": [
                {"name": "deerflow-fast", "display_name": "DeerFlow Fast", "description": "Quick everyday work", "supports_thinking": False, "supports_reasoning_effort": False},
                {"name": "deerflow-pro", "display_name": "DeerFlow Pro", "description": "Complex research and creation", "supports_thinking": True, "supports_reasoning_effort": True},
            ]})
        elif path == "/api/agents":
            self.write_json({"agents": [
                {"name": "lead_agent", "description": "General workspace agent", "model": "deerflow-pro", "skills": []},
                {"name": "researcher", "description": "Evidence-first research specialist", "model": "deerflow-pro", "skills": ["deep-research"]},
                {"name": "creator", "description": "Writing and visual creation specialist", "model": "deerflow-fast", "skills": ["writing-studio", "image-generation"]},
            ]})
        elif path == "/api/console/runs":
            assistant_id = parse_qs(parsed.query).get("assistant_id", [None])[0]
            runs = [run for run in AGENT_RUNS if assistant_id is None or run["assistant_id"] == assistant_id]
            self.write_json({"runs": runs, "has_more": False})
        elif path == "/api/skills":
            self.write_json({"skills": [
                skill_payload(name, description, category)
                for name, description, category in SKILLS
            ]})
        elif path == "/api/mcp/config":
            self.write_json({"mcp_servers": MCP_SERVERS})
        elif path == "/api/mcp/tools":
            self.write_json({
                "tools": [
                    tool for tool in MCP_TOOLS
                    if MCP_SERVERS.get(tool["server_name"], {}).get("enabled", False)
                ],
            })
        elif path == "/api/channels/providers":
            self.write_json({"enabled": True, "providers": CHANNEL_PROVIDERS})
        elif path.startswith("/api/scheduled-tasks/") and path.endswith("/runs"):
            task_id = path.split("/")[3]
            if task_id != "morning-brief":
                self.write_json([])
                return
            self.write_json([
                {
                    "id": "task-run-success-1",
                    "task_id": "morning-brief",
                    "thread_id": TASK_RUN_THREAD_ID,
                    "run_id": "gateway-run-success-1",
                    "scheduled_for": "2026-07-19T09:00:00+08:00",
                    "trigger": "scheduled",
                    "status": "success",
                    "error": None,
                    "started_at": "2026-07-19T09:00:03+08:00",
                    "finished_at": "2026-07-19T09:01:12+08:00",
                    "created_at": "2026-07-19T09:00:00+08:00",
                },
                {
                    "id": "task-run-failed-1",
                    "task_id": "morning-brief",
                    "thread_id": "fixture-task-thread-failed",
                    "run_id": "gateway-run-failed-1",
                    "scheduled_for": "2026-07-18T09:00:00+08:00",
                    "trigger": "manual",
                    "status": "failed",
                    "error": "The configured model was unavailable.",
                    "started_at": "2026-07-18T09:00:01+08:00",
                    "finished_at": "2026-07-18T09:00:04+08:00",
                    "created_at": "2026-07-18T09:00:00+08:00",
                },
            ])
        elif path == "/api/scheduled-tasks":
            self.write_json(list(TASKS.values()))
        elif path == "/api/memory":
            self.write_json(MEMORY)
        elif path.startswith("/api/threads/") and path.endswith("/state"):
            thread_id = path.split("/")[3]
            thread = THREADS.get(thread_id, {"title": "New conversation", "messages": [], "todos": [], "artifacts": []})
            self.write_json({"values": {"title": thread["title"], "messages": thread["messages"], "todos": thread.get("todos", []), "artifacts": thread.get("artifacts", [])}})
        elif path.startswith("/api/threads/") and path.endswith("/runs"):
            thread_id = path.split("/")[3]
            self.write_json([
                {"run_id": run_id, "thread_id": thread_id, "status": run.get("status", "success")}
                for run_id, run in RUNS.items()
                if run.get("thread_id") == thread_id
            ])
        elif path.startswith("/api/threads/") and path.endswith("/stream") and "/runs/" in path:
            parts = path.split("/")
            self.stream_existing_run(parts[3], parts[5])
        elif path.startswith("/api/threads/") and "/artifacts/" in path:
            artifact_path = path.split("/artifacts/", 1)[1]
            if artifact_path.endswith("report.md"):
                self.write_bytes(b"# Fixture report\n\nAndroid artifact preview works.\n", "text/markdown; charset=utf-8")
            else:
                self.write_json({"detail": "Artifact not found"}, status=404)
        else:
            self.write_json({"detail": "Not found"}, status=404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/v1/auth/login/local":
            length = int(self.headers.get("Content-Length", "0"))
            if length:
                self.rfile.read(length)
            self.write_json({}, headers={"Set-Cookie": "access_token=emulator; Path=/; HttpOnly"})
        elif path == "/api/v1/auth/logout":
            self.write_json({})
        elif path.startswith("/api/channels/") and path.endswith("/runtime-config"):
            provider_name = path.split("/")[3]
            provider = channel_provider(provider_name)
            if provider is None:
                self.read_json()
                self.write_json({"detail": "Unknown channel provider"}, status=404)
                return
            values = self.read_json().get("values", {})
            missing = [
                field["label"]
                for field in provider["credential_fields"]
                if field["required"] and not str(values.get(field["name"], "")).strip()
            ]
            if missing:
                self.write_json({"detail": f"Missing required channel configuration: {', '.join(missing)}"}, status=400)
                return
            provider["configured"] = True
            provider["connectable"] = True
            provider["unavailable_reason"] = None
            provider["credential_values"] = {
                field["name"]: "********" if field["type"] == "password" else str(values[field["name"]])
                for field in provider["credential_fields"]
                if field["name"] in values
            }
            self.write_json(provider)
        elif path.startswith("/api/channels/") and path.endswith("/connect"):
            provider_name = path.split("/")[3]
            provider = channel_provider(provider_name)
            if provider is None or not provider["connectable"]:
                self.read_json()
                self.write_json({"detail": "Channel provider is not configured"}, status=400)
                return
            self.read_json()
            code = f"bind-{provider_name}-fixture"
            self.write_json({
                "provider": provider_name,
                "mode": provider["auth_mode"],
                "url": f"https://channels.example.test/{provider_name}?code={code}" if provider["auth_mode"] == "deep_link" else None,
                "code": code,
                "instruction": f"Use code {code} to connect {provider['display_name']}.",
                "expires_in": 600,
            })
        elif path == "/api/threads/search":
            self.read_json()
            ordered = sorted(THREADS.items(), key=lambda item: item[1]["updated_at"], reverse=True)
            self.write_json([thread_summary(thread_id, thread) for thread_id, thread in ordered])
        elif path == "/api/threads":
            self.read_json()
            thread_id = str(uuid.uuid4())
            THREADS[thread_id] = {"title": "New conversation", "updated_at": "2026-07-19T10:00:00+08:00", "messages": [], "todos": [], "artifacts": []}
            self.write_json(thread_summary(thread_id, THREADS[thread_id]))
        elif path == "/api/scheduled-tasks":
            body = self.read_json()
            schedule_type = str(body.get("schedule_type", ""))
            schedule_spec = body.get("schedule_spec")
            if schedule_type not in {"cron", "once"} or not isinstance(schedule_spec, dict):
                self.write_json({"detail": "Unsupported task schedule"}, status=422)
                return
            task_id = f"fixture-task-{uuid.uuid4().hex[:8]}"
            task = {
                "id": task_id,
                "title": str(body.get("title", "Scheduled task")),
                "prompt": str(body.get("prompt", "")),
                "schedule_type": schedule_type,
                "schedule_spec": schedule_spec,
                "timezone": str(body.get("timezone", "UTC")),
                "status": "active",
                "next_run_at": schedule_spec.get("run_at") if schedule_type == "once" else None,
                "last_error": None,
                "run_count": 0,
            }
            TASKS[task_id] = task
            self.write_json(task, status=201)
        elif path.startswith("/api/scheduled-tasks/"):
            task_id = path.split("/")[3]
            task = TASKS.get(task_id)
            if task is None:
                self.read_json()
                self.write_json({"detail": "Scheduled task not found"}, status=404)
                return
            self.read_json()
            if path.endswith("/pause"):
                task["status"] = "paused"
            elif path.endswith("/resume"):
                task["status"] = "active"
            elif path.endswith("/trigger"):
                task["run_count"] += 1
            self.write_json(task)
        elif path == "/api/memory/facts":
            body = self.read_json()
            content = str(body.get("content", "")).strip()
            if not content:
                self.write_json({"detail": "Memory fact content cannot be empty."}, status=400)
                return
            fact = {
                "id": f"fixture-{uuid.uuid4()}",
                "content": content,
                "category": str(body.get("category", "context")),
                "confidence": float(body.get("confidence", 0.5)),
                "createdAt": "2026-07-20T09:05:00+08:00",
                "source": "manual",
            }
            MEMORY["facts"].append(fact)
            MEMORY["lastUpdated"] = "2026-07-20T09:05:00+08:00"
            self.write_json(MEMORY)
        elif path.endswith("/runs/regenerate/prepare") and "/api/threads/" in path:
            self.prepare_regenerate(path.split("/")[3], self.read_json())
        elif path.endswith("/branches") and "/api/threads/" in path:
            self.branch_thread(path.split("/")[3], self.read_json())
        elif path.endswith("/runs/stream") and "/api/threads/" in path:
            self.stream_run(path.split("/")[3], self.read_json())
        elif path.endswith("/state") and "/api/threads/" in path:
            thread_id = path.split("/")[3]
            body = self.read_json()
            if thread_id in THREADS:
                THREADS[thread_id]["title"] = body.get("values", {}).get("title", THREADS[thread_id]["title"])
            self.write_json({})
        else:
            self.read_json()
            self.write_json({})

    def do_PATCH(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/api/scheduled-tasks/"):
            task_id = path.split("/")[3]
            task = TASKS.get(task_id)
            if task is None:
                self.read_json()
                self.write_json({"detail": "Scheduled task not found"}, status=404)
                return
            body = self.read_json()
            for key in ("title", "prompt", "timezone"):
                if key in body:
                    task[key] = body[key]
            schedule_spec = body.get("schedule_spec")
            if isinstance(schedule_spec, dict):
                task["schedule_spec"] = schedule_spec
                task["next_run_at"] = schedule_spec.get("run_at") if task["schedule_type"] == "once" else None
            self.write_json(task)
        elif path.startswith("/api/memory/facts/"):
            fact_id = path.rsplit("/", 1)[1]
            fact = next((item for item in MEMORY["facts"] if item["id"] == fact_id), None)
            if fact is None:
                self.read_json()
                self.write_json({"detail": f"Memory fact '{fact_id}' not found."}, status=404)
                return
            body = self.read_json()
            content = str(body.get("content", fact["content"])).strip()
            if not content:
                self.write_json({"detail": "Memory fact content cannot be empty."}, status=400)
                return
            fact.update(
                content=content,
                category=str(body.get("category", fact["category"])),
                confidence=float(body.get("confidence", fact["confidence"])),
            )
            MEMORY["lastUpdated"] = "2026-07-20T09:10:00+08:00"
            self.write_json(MEMORY)
        else:
            self.read_json()
            self.write_json({})

    def do_PUT(self) -> None:
        global MCP_SERVERS
        path = urlparse(self.path).path
        if path.startswith("/api/skills/"):
            skill_name = path.rsplit("/", 1)[1]
            skill = next((item for item in SKILLS if item[0] == skill_name), None)
            if skill is None:
                self.read_json()
                self.write_json({"detail": f"Skill '{skill_name}' not found."}, status=404)
                return
            body = self.read_json()
            enabled = body.get("enabled")
            if not isinstance(enabled, bool):
                self.write_json({"detail": "enabled must be a boolean."}, status=400)
                return
            SKILL_STATES[skill_name] = enabled
            self.write_json(skill_payload(*skill))
        elif path == "/api/mcp/config":
            servers = self.read_json().get("mcp_servers")
            if not isinstance(servers, dict):
                self.write_json({"detail": "mcp_servers must be an object."}, status=400)
                return
            MCP_SERVERS = servers
            self.write_json({"mcp_servers": MCP_SERVERS})
        else:
            self.read_json()
            self.write_json({})

    def do_DELETE(self) -> None:
        global MEMORY
        path = urlparse(self.path).path
        if path == "/api/memory":
            MEMORY = fresh_memory()
            MEMORY["lastUpdated"] = ""
            MEMORY["user"] = {
                "workContext": {"summary": "", "updatedAt": ""},
                "personalContext": {"summary": "", "updatedAt": ""},
                "topOfMind": {"summary": "", "updatedAt": ""},
            }
            MEMORY["history"] = {
                "recentMonths": {"summary": "", "updatedAt": ""},
                "earlierContext": {"summary": "", "updatedAt": ""},
                "longTermBackground": {"summary": "", "updatedAt": ""},
            }
            MEMORY["facts"] = []
            self.write_json(MEMORY)
        elif path.startswith("/api/memory/facts/"):
            fact_id = path.rsplit("/", 1)[1]
            before = len(MEMORY["facts"])
            MEMORY["facts"] = [item for item in MEMORY["facts"] if item["id"] != fact_id]
            if len(MEMORY["facts"]) == before:
                self.write_json({"detail": f"Memory fact '{fact_id}' not found."}, status=404)
                return
            MEMORY["lastUpdated"] = "2026-07-20T09:15:00+08:00"
            self.write_json(MEMORY)
        elif path.startswith("/api/channels/") and path.endswith("/runtime-config"):
            provider = channel_provider(path.split("/")[3])
            if provider is None:
                self.write_json({"detail": "Unknown channel provider"}, status=404)
                return
            provider.update(
                configured=False,
                connectable=False,
                unavailable_reason="Runtime credentials are required.",
                connection_status="not_connected",
                credential_values={},
            )
            self.write_json(provider)
        elif path.startswith("/api/scheduled-tasks/"):
            task_id = path.split("/")[3]
            if TASKS.pop(task_id, None) is None:
                self.write_json({"detail": "Scheduled task not found"}, status=404)
                return
            self.write_json({})
        elif path.startswith("/api/threads/"):
            THREADS.pop(path.split("/")[3], None)
            self.write_json({})
        else:
            self.write_json({})

    def stream_run(self, thread_id: str, request: dict) -> None:
        thread = THREADS.setdefault(thread_id, {"title": "New conversation", "updated_at": "", "messages": [], "todos": [], "artifacts": []})
        input_messages = request.get("input", {}).get("messages", [])
        human = input_messages[-1] if input_messages else {"type": "human", "content": "Hello", "id": str(uuid.uuid4())}
        regenerate_target = request.get("metadata", {}).get("regenerate_from_message_id")
        if regenerate_target:
            target_index = next(
                (index for index, message in enumerate(thread["messages"]) if message.get("id") == regenerate_target),
                None,
            )
            if target_index is not None:
                human_index = next(
                    (
                        index
                        for index in range(target_index - 1, -1, -1)
                        if thread["messages"][index].get("type") in {"human", "user"}
                    ),
                    target_index,
                )
                thread["messages"] = thread["messages"][:human_index]
        thread["messages"].append(human)
        prompt = str(human.get("content", "")).strip()
        title = prompt[:32] or "New conversation"
        answer = "I mapped the request into a concise plan, checked the available workspace skills, and prepared the next concrete action."
        assistant = {"type": "ai", "content": answer, "id": str(uuid.uuid4())}
        tool_result = None
        if prompt == "Show tool presentation":
            tool_call_id = f"search-{uuid.uuid4()}"
            answer = ""
            assistant = {
                "type": "ai",
                "content": answer,
                "id": str(uuid.uuid4()),
                "tool_calls": [{
                    "id": tool_call_id,
                    "function": {"name": "web_search", "arguments": {"query": "Android DataStore"}},
                }],
            }
            tool_result = {
                "type": "tool",
                "id": f"result-{tool_call_id}",
                "tool_call_id": tool_call_id,
                "name": "web_search",
                "content": json.dumps({
                    "results": [{
                        "title": "Android Developers",
                        "url": "https://developer.android.com/topic/libraries/architecture/datastore",
                        "content": "Official guide to Jetpack DataStore.",
                    }],
                }),
            }
        run_id = str(uuid.uuid4())
        RUNS[run_id] = {"thread_id": thread_id, "status": "running"}
        thread.update(
            title=title,
            updated_at="2026-07-19T10:05:00+08:00",
            messages=thread["messages"] + [assistant] + ([tool_result] if tool_result else []),
            todos=[{"content": "Validate Android fixture", "status": "completed"}],
            artifacts=["mnt/user-data/outputs/report.md"],
        )

        answer_chunks = [
            "I mapped the request into a concise plan, ",
            "checked the available workspace skills, ",
            "and prepared the next concrete action.",
        ]
        events = [("metadata", {"run_id": run_id})]
        if tool_result:
            events.extend([
                ("messages-tuple", [assistant, {"langgraph_node": "lead_agent"}]),
                ("messages-tuple", [tool_result, {"langgraph_node": "tools"}]),
            ])
        else:
            events.extend(
                (
                    "messages-tuple",
                    [
                        {"type": "AIMessageChunk", "content": chunk, "id": assistant["id"]},
                        {"langgraph_node": "lead_agent"},
                    ],
                )
                for chunk in answer_chunks
            )
        events.extend([
            ("values", {"title": title, "messages": thread["messages"], "todos": thread["todos"], "artifacts": thread["artifacts"]}),
            ("end", {}),
        ])
        payloads = [
            f"id: {index}\nevent: {event}\ndata: {json.dumps(data)}\n\n".encode("utf-8")
            for index, (event, data) in enumerate(events, start=1)
        ]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(sum(map(len, payloads))))
        self.send_header("Connection", "close")
        self.send_header("Content-Location", f"/api/threads/{thread_id}/runs/{run_id}")
        self.end_headers()
        try:
            for payload in payloads:
                self.wfile.write(payload)
                self.wfile.flush()
                time.sleep(STREAM_DELAY)
        finally:
            RUNS[run_id]["status"] = "success"
        self.close_connection = True

    def stream_existing_run(self, thread_id: str, run_id: str) -> None:
        thread = THREADS.setdefault(thread_id, {"title": "Recovered conversation", "updated_at": "", "messages": [], "todos": [], "artifacts": []})
        if not thread["messages"]:
            thread["messages"] = [{"type": "ai", "content": "Recovered run completed after process restart.", "id": f"recovered-{run_id}"}]
        events = [
            ("metadata", {"run_id": run_id}),
            ("messages-tuple", [{"type": "AIMessageChunk", "content": "Recovered run completed after process restart.", "id": f"recovered-{run_id}"}, {"langgraph_node": "lead_agent"}]),
            ("values", {"title": thread["title"], "messages": thread["messages"], "todos": thread.get("todos", []), "artifacts": thread.get("artifacts", [])}),
            ("end", {}),
        ]
        payloads = [
            f"id: {index}\nevent: {event}\ndata: {json.dumps(data)}\n\n".encode("utf-8")
            for index, (event, data) in enumerate(events, start=1)
        ]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(sum(map(len, payloads))))
        self.send_header("Connection", "close")
        self.end_headers()
        for payload in payloads:
            self.wfile.write(payload)
            self.wfile.flush()
        RUNS.setdefault(run_id, {"thread_id": thread_id, "status": "success"})["status"] = "success"

    def prepare_regenerate(self, thread_id: str, request: dict) -> None:
        thread = THREADS.get(thread_id)
        message_id = str(request.get("message_id", ""))
        if not thread:
            self.write_json({"detail": "Thread not found"}, status=404)
            return
        target_index = next(
            (index for index, message in enumerate(thread["messages"]) if message.get("id") == message_id),
            None,
        )
        if target_index is None:
            self.write_json({"detail": "Message not found"}, status=404)
            return
        previous_human = next(
            (
                thread["messages"][index]
                for index in range(target_index - 1, -1, -1)
                if thread["messages"][index].get("type") in {"human", "user"}
            ),
            None,
        )
        if previous_human is None:
            self.write_json({"detail": "Could not find the user message"}, status=409)
            return
        run_id = f"fixture-run-{message_id}"
        self.write_json({
            "input": {"messages": [previous_human]},
            "checkpoint": {"thread_id": thread_id, "checkpoint_ns": "", "checkpoint_id": f"before-{previous_human['id']}"},
            "metadata": {
                "regenerate_from_message_id": message_id,
                "regenerate_from_run_id": run_id,
                "regenerate_checkpoint_id": f"before-{previous_human['id']}",
            },
            "target_run_id": run_id,
        })

    def branch_thread(self, thread_id: str, request: dict) -> None:
        source = THREADS.get(thread_id)
        message_id = str(request.get("message_id", ""))
        if not source:
            self.write_json({"detail": "Thread not found"}, status=404)
            return
        target_index = next(
            (index for index, message in enumerate(source["messages"]) if message.get("id") == message_id),
            None,
        )
        if target_index is None:
            self.write_json({"detail": "Message not found"}, status=404)
            return
        branch_id = str(uuid.uuid4())
        THREADS[branch_id] = {
            "title": source["title"],
            "updated_at": "2026-07-19T10:06:00+08:00",
            "messages": [dict(message) for message in source["messages"][: target_index + 1]],
            "todos": list(source.get("todos", [])),
            "artifacts": list(source.get("artifacts", [])),
        }
        self.write_json({
            "thread_id": branch_id,
            "parent_thread_id": thread_id,
            "parent_checkpoint_id": f"checkpoint-{message_id}",
            "branched_from_message_id": message_id,
            "workspace_clone_mode": "copied_latest_turn",
        })


def main() -> None:
    global STREAM_DELAY
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2027)
    parser.add_argument("--delay", type=float, default=1.5, help="Seconds between fixture SSE events")
    args = parser.parse_args()
    STREAM_DELAY = max(0.0, args.delay)
    server = ThreadingHTTPServer((args.host, args.port), GatewayHandler)
    print(f"Mock Gateway listening on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
