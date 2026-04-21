# rfnry/chat react examples

Single Vite + Tailwind app that runs all three Python examples from a black-background UI with a top nav switcher.

```
src/
  main.tsx                    root + example switcher
  styles.css                  tailwind entry
  ui.tsx                      shared <EventFeed>, input/button classes
  examples/
    stock-tool/               → http://localhost:8100
    customer-support/         → http://localhost:8000
    organization-workspace/   → http://localhost:8001 (legal) + 8002 (medical)
```

## Run

```bash
# One terminal per Python backend (pick what you want to test):
cd ../python/stock-tool         && uv run uvicorn src.main:asgi --port 8100
cd ../python/customer-support   && uv run uvicorn src.main:asgi --port 8000
cd ../python/organization-workspace && WORKSPACE=legal  PORT=8001 uv run uvicorn src.main:asgi --port 8001
cd ../python/organization-workspace && WORKSPACE=medical PORT=8002 uv run uvicorn src.main:asgi --port 8002

# React dev server:
cd examples/react
npm install
npm run dev   # http://localhost:5173
```

Each example constructs `<ChatProvider url={...} identity={...}>` — when `identity` is set and no `authenticate` callback is given, the client encodes the identity into the `x-rfnry-identity` header (base64url) and the socket `auth` payload, and the server parses it back into the caller's `Identity`. No tokens, no DB, no auth plumbing — minimum setup to exercise the full chat API.
