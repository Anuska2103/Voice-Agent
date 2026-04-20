# NewVoice Real Estate Assistant

Voice-first real estate assistant for Kolkata using LiveKit + LangGraph + Gemini + MongoDB + Redis.

This README explains the full workflow in simple terms: where user speech goes, how prompts are processed, which code runs at each step, and how the response comes back as audio.

## 1) What This Project Does

The assistant listens to a user in a LiveKit room, converts speech to text, classifies intent, calls tools (property search, amenities, weather), synthesizes a final answer with Gemini, and speaks the response back.

Main intents currently handled:
- `search`: property search from MongoDB
- `amenity`: nearby schools/hospitals/banks/metro/college
- `weather`: current + short forecast using OpenWeatherMap
- `general`: normal conversation

## 2) Project Structure and Responsibility

- `run.py`
  - Process start file.
  - Launches LiveKit worker with `entrypoint` from `agent.py`.

- `agent.py`
  - Thin voice layer.
  - Initializes backend services once (Redis, Mongo, Gemini, Orchestrator).
  - Connects to LiveKit room.
  - Receives audio, performs STT, sends text to orchestrator.
  - Converts final text response to TTS and streams back.

- `orchestrator.py`
  - Core LangGraph decision and workflow engine.
  - Steps: classify intent -> route to node -> run tool node -> synthesize final response.
  - Maintains chat history in Redis per session.

- `llm.py`
  - Gemini wrapper (`GeminiClient`) with async text generation.

- `mongo.py`
  - MongoDB repository.
  - Property retrieval (`search_properties`) and interaction save helper.

- `config.py`
  - Loads and validates environment variables.

- `tools/geocoding.py`
  - Nominatim geocoding (sync + async).

- `tools/weather_tool.py`
  - Geocode location -> check Redis cache -> call OpenWeatherMap -> aggregate forecast -> return formatted weather text.

- `tools/amenities_tool.py`
  - Extract amenity type and location from user text.
  - Geocode location.
  - Query Overpass API for nearby amenities.
  - Return ranked nearby places + voice-friendly formatting.

## 3) End-to-End Runtime Flow (Prompt Path)

### High-level flow

1. User speaks in LiveKit room.
2. `agent.py` receives audio track.
3. Deepgram STT converts speech chunks to text.
4. On end of speech, complete transcript is built.
5. Transcript is sent to `OrchestratorAgent.invoke(...)`.
6. `orchestrator.py` loads conversation history from Redis.
7. LangGraph runs:
   - `classify_intent`
   - one tool node (`search_properties` / `find_amenities` / `get_weather` / `general_chat`)
   - `synthesize`
8. Final response is saved to Redis history.
9. `agent.py` receives `final_response` and sends it to ElevenLabs TTS.
10. Audio is streamed back to the room.

### Mermaid diagram

```mermaid
flowchart TD
    A[User speaks] --> B[LiveKit room audio]
    B --> C[agent.py VoiceAssistant]
    C --> D[Deepgram STT stream]
    D --> E[Final transcript]
    E --> F[orchestrator.invoke(session_id, user_input)]
    F --> G[Load history from Redis]
    G --> H[classify_intent via Gemini]
    H --> I{Intent route}
    I -->|search| J[Mongo search_properties]
    I -->|amenity| K[tools/amenities_tool]
    I -->|weather| L[tools/weather_tool]
    I -->|general| M[general_chat context]
    J --> N[synthesize response via Gemini]
    K --> N
    L --> N
    M --> N
    N --> O[Save history to Redis]
    O --> P[Return final_response]
    P --> Q[ElevenLabs TTS]
    Q --> R[Assistant audio reply]
```

## 4) Prompt Journey (Exactly where prompt goes)

There are two important prompts in orchestrator:

- Intent classification prompt
  - Created in `orchestrator.py` inside `_classify_intent`.
  - Input: user transcript text.
  - Output: one label (`search`, `amenity`, `weather`, `general`).

- Final response synthesis prompt
  - Created in `orchestrator.py` inside `_synthesize`.
  - Input:
    - recent chat history
    - current user message
    - selected intent
    - tool output JSON (`tool_context`)
  - Output: natural conversational answer for voice.

Additionally in weather flow:
- Location extraction prompt
  - Created in `_get_weather`.
  - Extracts place name from user message (fallback Kolkata).

## 5) How Routing Works in LangGraph

Graph entry point: `classify_intent`

Conditional route function: `_route_intent`
- `search` -> `_search_properties`
- `amenity` -> `_find_amenities`
- `weather` -> `_get_weather`
- fallback -> `_general_chat`

All nodes then go to `_synthesize` and terminate.

## 6) Caching and Session Memory

- Redis in orchestrator:
  - key: `chat:{session_id}`
  - stores last ~20 messages
  - TTL: 24 hours

- Redis in weather tool:
  - key pattern: `owm_weather:{lat}:{lon}`
  - caches weather report
  - TTL: 15 minutes

- In-memory session state in amenities tool:
  - remembers last resolved location (`session_memory` dict)
  - lets follow-up amenity queries reuse location when omitted

## 7) Data Sources and External APIs

- STT: Deepgram
- TTS: ElevenLabs
- LLM: Google Gemini (`langchain-google-genai`)
- Geocoding: OpenStreetMap Nominatim
- Amenities: Overpass API
- Weather: OpenWeatherMap
- Storage: MongoDB
- Cache/history: Redis
- Realtime voice transport: LiveKit

## 8) Environment Variables

Loaded in `config.py`:

- `GEMINI_API_KEY`
- `GEMINI_MODEL` (optional, default already set)
- `OPENWEATHER_API_KEY`
- `DEEPGRAM_API_KEY`
- `DEEPGRAM_LANGUAGE` (optional, default: `multi` for English + Bengali style mixed input)
- `ELEVENLABS_API_KEY`
- `MONGO_URI`
- `MONGO_DB_NAME`
- `MONGO_PROPERTY_COLLECTION`
- `REDIS_URL`
- `LIVEKIT_URL`
- `LIVEKIT_API_KEY`
- `LIVEKIT_API_SECRET`

## 9) How to Run

1. Create/activate virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Set environment variables (or `.env`).
4. Start agent:

```bash
python run.py dev
```

## 10) Typical Request Examples

- Search flow:
  - User: "I want a 2BHK flat in Salt Lake"
  - Route: `search`
  - Tool: Mongo query
  - Reply: concise list of matching properties

- Amenity flow:
  - User: "Any hospitals near New Town?"
  - Route: `amenity`
  - Tool: geocoding + Overpass
  - Reply: top nearby hospitals with distance

- Weather flow:
  - User: "How is the weather in Howrah today?"
  - Route: `weather`
  - Tool: geocoding + OpenWeatherMap
  - Reply: temp + condition + forecast summary

## 11) Notes

- `agent.py` is intentionally a thin layer. Most reasoning and orchestration happens in `orchestrator.py`.
- If any external API fails, the system returns a friendly fallback response instead of crashing.
- Current property search in `mongo.py` is a basic placeholder (`find({})`) and can be upgraded to full text/vector search later.

## 12) Custom Web UI (Next.js) + FastAPI Token API

This repo now includes a dedicated frontend in `frontend/` so you can use your own UI instead of LiveKit Playground.

### What was added

- `api.py`
  - FastAPI service with:
   - `GET /health`
   - `POST /api/v1/livekit/token` (returns LiveKit join token)
- `frontend/`
  - Next.js app (App Router, TypeScript)
  - Voice UI that calls FastAPI with `fetch` (no axios)
  - Connects browser mic/audio to your LiveKit room

### Backend API run command

From project root:

```bash
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

### Frontend run commands

From `frontend/`:

```bash
npm install
npm run dev
```

### Frontend environment variables

Create `frontend/.env.local`:

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
NEXT_PUBLIC_LIVEKIT_URL=ws://localhost:7880
```

### How to run everything together

1. Start LiveKit server (if not already running).
2. Start voice worker:
  - `python run.py dev`
3. Start FastAPI token API:
  - `uvicorn api:app --host 0.0.0.0 --port 8000 --reload`
4. Start Next.js frontend:
  - `cd frontend && npm run dev`
5. Open browser at `http://localhost:3000`, join room, allow microphone, and speak.

## 13) Render Cloud Deployment (Works from Any Machine)

This repository now includes a Render blueprint file at `render.yaml` that deploys:

- `newvoice-backend-api` (FastAPI)
- `newvoice-backend-worker` (LiveKit worker)
- `newvoice-frontend` (Next.js)

### Important for MongoDB and Redis

- Render does not provide managed MongoDB in the same way it provides Redis.
- Use MongoDB Atlas (recommended) and set `MONGO_URI` to your Atlas connection string.
- Use Render Redis and set `REDIS_URL` from your Render Redis service.

### LiveKit Cloud setup

- Set `LIVEKIT_URL` to your LiveKit Cloud WebSocket URL (must be `wss://...`).
- Set `LIVEKIT_API_KEY` and `LIVEKIT_API_SECRET` from LiveKit Cloud.
- Set frontend `NEXT_PUBLIC_LIVEKIT_URL` to the same `wss://...` URL.

### Frontend and CORS setup

- Set `NEXT_PUBLIC_API_BASE_URL` to your backend API public URL on Render.
  - Example: `https://newvoice-backend-api.onrender.com`
- Set backend `CORS_ORIGINS` to your frontend URL.
  - Example: `https://newvoice-frontend.onrender.com`

### Deploy steps

1. Push this repo to GitHub.
2. In Render, create Blueprint from repo.
3. Render will detect `render.yaml` and create 3 services.
4. Fill all `sync: false` environment variables.
5. Redeploy all services after setting variables.

Once deployed, users can open your frontend URL from any machine/browser and connect through LiveKit Cloud.
