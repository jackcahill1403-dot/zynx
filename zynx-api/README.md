# Zynx API

Small JSON backend that exposes Zynx's brain (OpenRouter Nemotron ladder + the
Zynx system prompt) over HTTP, so external clients — like the **Zynx Roblox
Studio plugin** — can chat with Zynx.

The live Streamlit app (`zynx-app`) serves HTML only and has no JSON API, so a
Roblox plugin can't parse its replies. This service fills that gap. It reuses
the exact model ids, system prompt, and OpenRouter 429 retry/backoff from
`ai_app.py`, so answers match the live site.

## Endpoints

| Method | Path      | Purpose |
|--------|-----------|---------|
| GET    | `/`       | banner |
| GET    | `/health` | `{ok, build, has_key}` |
| GET    | `/models` | the 3 Zynx models the plugin can pick |
| POST   | `/chat`   | chat — see below |
| GET    | `/docs`   | auto Swagger UI |

### POST `/chat`

```json
{
  "message": "write a Lua part spawner",
  "history": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "Hey!"}],
  "model": "everyday",
  "effort": "Medium"
}
```

`model` ∈ `supreme | everyday | lite` (default `everyday`).
`effort` ∈ `Low | Medium | High`.

Response:

```json
{ "reply": "...", "model": "everyday" }
```

If `ZYNX_API_KEY` is set on the server, send header `X-Zynx-Key: <that value>`.

## Env vars

| Var | Required | Meaning |
|-----|----------|---------|
| `OPENROUTER_API_KEY` | yes | your OpenRouter key (same one Zynx uses) |
| `ZYNX_API_KEY` | no | shared secret the plugin must send; leave unset for open access |

## Run locally

```bash
pip install -r requirements.txt
export OPENROUTER_API_KEY=sk-or-...      # Windows PS: $env:OPENROUTER_API_KEY="sk-or-..."
uvicorn main:app --reload
# -> http://127.0.0.1:8000/health
```

## Deploy to Render (free)

1. Push this `zynx-api` folder to a GitHub repo.
2. Render → New → Web Service → pick the repo.
3. Render reads `render.yaml` automatically (or set manually:
   Build `pip install -r requirements.txt`,
   Start `uvicorn main:app --host 0.0.0.0 --port $PORT`).
4. Add env var `OPENROUTER_API_KEY` (and optionally `ZYNX_API_KEY`).
5. Deploy → note the URL, e.g. `https://zynx-api.onrender.com`.
6. Put that URL in the Roblox plugin's ⚙ settings.

Railway / Fly / Heroku work too — the `Procfile` covers them.

> Free Render instances sleep after inactivity; the first request after a
> sleep takes ~30s to wake. Subsequent requests are fast.
