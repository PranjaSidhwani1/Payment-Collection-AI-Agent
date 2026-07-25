"""Flask web UI for the payment collection agent.

This is a thin wrapper around the Agent class (agent.py) - all
conversation logic still lives there. This module only adds:
  - a chat UI (templates/index.html + static/)
  - per-browser-session Agent instances, keyed by a signed session cookie

Deployment note: session state is held in-memory (_SESSIONS), consistent
with the rest of the project (see DESIGN.md - no persistence layer by
design). That means this must run as a SINGLE worker process, otherwise
different requests from the same user could land on different workers
with no shared state. The included Procfile pins `--workers 1` for
exactly this reason.
"""
import os
import uuid

from dotenv import load_dotenv

load_dotenv()

from flask import Flask, jsonify, render_template, request, session  # noqa: E402

from agent import Agent  # noqa: E402

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-only-insecure-secret-change-me")

_SESSIONS = {}


def _new_session() -> str:
    session_id = str(uuid.uuid4())
    session["session_id"] = session_id
    _SESSIONS[session_id] = Agent()
    return session_id


def _get_agent() -> Agent:
    session_id = session.get("session_id")
    if not session_id or session_id not in _SESSIONS:
        session_id = _new_session()
    return _SESSIONS[session_id]


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/start", methods=["POST"])
def start():
    """Begins a brand new conversation and returns the greeting."""
    _new_session()
    agent = _get_agent()
    return jsonify(agent.next("Hi"))


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()
    if not user_message:
        return jsonify({"message": "Sorry, I didn't catch that - could you type your message?"}), 400
    agent = _get_agent()
    return jsonify(agent.next(user_message))


@app.route("/api/reset", methods=["POST"])
def reset():
    """Discards the current session's agent and starts a fresh one."""
    session_id = session.get("session_id")
    if session_id:
        _SESSIONS.pop(session_id, None)
    _new_session()
    agent = _get_agent()
    return jsonify(agent.next("Hi"))


@app.route("/healthz")
def healthz():
    return {"status": "ok"}, 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
