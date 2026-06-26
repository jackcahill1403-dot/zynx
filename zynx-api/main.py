"""
Zynx API — a small JSON backend that exposes Zynx's brain (OpenRouter Nemotron
ladder + the Zynx system prompt) over HTTP so external clients such as the Zynx
Roblox Studio plugin can chat with it.

This reuses the exact model ladder, system prompt, and OpenRouter retry/backoff
behaviour from the Streamlit app (ai_app.py) so replies match the live site.

Endpoints
---------
GET  /            -> service banner
GET  /health      -> {"ok": true, "build": ...}
GET  /models      -> the three Zynx models the plugin can pick from
POST /chat        -> {"reply": str, "model": str}

Auth
----
If the ZYNX_API_KEY env var is set, every /chat request must send a matching
`X-Zynx-Key` header. Leave it unset for an open (testing) deployment.

Env vars
--------
OPENROUTER_API_KEY  (required)  your OpenRouter key
ZYNX_API_KEY        (optional)  shared secret the plugin must send
"""

import json
import os
import time
import urllib.error
import urllib.request

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

API_BUILD = "2026-06-26-zynx-api-v1"

# ---------------------------------------------------------------------------
# Model ladder — mirrors MODELS in ai_app.py. Keys are what the plugin sends;
# values are the raw OpenRouter model slugs (the "openrouter/" prefix stripped,
# matching _openrouter_slug in the Streamlit app).
# ---------------------------------------------------------------------------
MODELS = {
    "supreme": {
        "label": "⚡ Zynx Supreme ⚡",
        "desc": "Our most powerful model — best for hard problems.",
        "model_id": "nvidia/nemotron-3-super-120b-a12b:free",
    },
    "everyday": {
        "label": "☀️ Zynx Everyday ☀️",
        "desc": "Fast, reliable all-rounder for daily use.",
        "model_id": "nvidia/nemotron-3-nano-30b-a3b:free",
    },
    "lite": {
        "label": "\U0001f4a1 Zynx Lite \U0001f4a1",
        "desc": "Light and quick for simple questions.",
        "model_id": "nvidia/nemotron-nano-9b-v2:free",
    },
}
DEFAULT_MODEL_KEY = "everyday"

EFFORT_PROMPTS = {
    "Low": "Use low effort. Keep it short and simple. This mode is not best for hard tasks.",
    "Medium": "Use medium effort. Give a normal balanced answer.",
    "High": "Use high effort. Think carefully, give more depth, and handle harder tasks better.",
}

AI_NAME = "Zynx"
COMPANY_NAME = "Zynx.AI"


def build_system_prompt(effort: str = "Medium") -> str:
    """Faithful port of build_system_prompt() from ai_app.py (no persona/custom)."""
    return f"""
You are {AI_NAME}, a general-purpose AI assistant made by {COMPANY_NAME}.

You can help with normal conversations, coding, Roblox Studio, Lua, school work, writing, ideas, tech help, game development, debugging, planning, and learning.

Do not act like a basic scripted bot.
Do not only talk about Roblox unless the user asks about Roblox.
If you do not know something, say so.
If the user asks for code, give full working code when possible.

Creator rule:
If asked who made you, who created you, who built you, who owns you, or who your creator is, answer:
"I was made by {COMPANY_NAME}."

Effort:
{EFFORT_PROMPTS.get(effort, EFFORT_PROMPTS['Medium'])}
"""


def _ratelimit_reset_hint(e) -> str:
    ra = e.headers.get("Retry-After") if e.headers else None
    if ra:
        try:
            return f"{int(float(ra))}s"
        except Exception:
            pass
    return "a little while"


def openrouter_generate(system_text: str, turns, model_id: str):
    """OpenRouter chat call with the same 429 retry/backoff as ai_app.py.

    `turns` is a list of (role, content). Returns (ok: bool, text: str).
    """
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        return False, "Server is missing OPENROUTER_API_KEY."

    messages = [{"role": "system", "content": system_text}]
    for role, content in turns:
        if content and content.strip():
            messages.append({
                "role": "assistant" if role == "assistant" else "user",
                "content": content,
            })

    payload = {"model": model_id, "messages": messages, "max_tokens": 4096}
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://zynx.ai",
        "X-Title": "Zynx",
    }
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    delay = 2.0
    for attempt in range(3):  # the free pool is often busy — retry 429s
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            text = (
                data.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
            ).strip()
            return True, text or "Zynx returned an empty response."
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="ignore")
            low = err.lower()
            if e.code == 429:
                if attempt < 2:
                    time.sleep(min(delay, 8))
                    delay *= 2
                    continue
                return False, (
                    "Zynx is busy right now (free models hit their usage limit). "
                    f"Try again in {_ratelimit_reset_hint(e)}."
                )
            if e.code in (401, 403):
                return False, "OpenRouter API key is invalid (server-side)."
            if "not found" in low or "no endpoints" in low:
                return False, "That Zynx model is unavailable right now."
            return False, "OpenRouter could not respond: " + err[:300]
        except Exception as e:
            return False, "OpenRouter error: " + str(e)[:300]

    return False, "Zynx could not respond."


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="Zynx API", version=API_BUILD)


class Turn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    history: list[Turn] = Field(default_factory=list)
    model: str = DEFAULT_MODEL_KEY
    effort: str = "Medium"


class ChatResponse(BaseModel):
    reply: str
    model: str


def _check_auth(x_zynx_key: str | None):
    required = os.getenv("ZYNX_API_KEY")
    if required and x_zynx_key != required:
        raise HTTPException(status_code=401, detail="Bad or missing X-Zynx-Key.")


@app.get("/")
def root():
    return {"service": "Zynx API", "build": API_BUILD, "docs": "/docs"}


@app.get("/health")
def health():
    return {"ok": True, "build": API_BUILD, "has_key": bool(os.getenv("OPENROUTER_API_KEY"))}


@app.get("/models")
def models():
    return {
        "default": DEFAULT_MODEL_KEY,
        "models": [
            {"key": k, "label": v["label"], "desc": v["desc"]} for k, v in MODELS.items()
        ],
    }


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, x_zynx_key: str | None = Header(default=None)):
    _check_auth(x_zynx_key)

    model_key = req.model if req.model in MODELS else DEFAULT_MODEL_KEY
    model_id = MODELS[model_key]["model_id"]
    effort = req.effort if req.effort in EFFORT_PROMPTS else "Medium"

    system_text = build_system_prompt(effort)
    turns = [(t.role, t.content) for t in req.history]
    turns.append(("user", req.message))

    ok, text = openrouter_generate(system_text, turns, model_id)
    if not ok:
        raise HTTPException(status_code=503, detail=text)
    return ChatResponse(reply=text, model=model_key)
