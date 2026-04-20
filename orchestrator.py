"""
orchestrator.py
LangGraph Orchestrator — LLM-first, tools are dumb executors.

Flow per turn:
  STT text
    → classify_intent  (LLM)
    → route to tool node
        search_properties : LLM extracts MongoDB query → db_tool executes it
        find_amenities    : amenities_tool handles location internally
        get_weather       : LLM extracts location → weather_tool fetches
        general_chat      : no tool
    → synthesize (LLM) → TTS-ready reply
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import TypedDict, Literal
from logger import get_logger

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from llm import GeminiClient
from prompts import (
    build_intent_prompt,
    build_amenity_location_resolution_prompt,
    build_location_extraction_prompt,
    build_query_extraction_prompt,
    build_synthesis_prompt,
)
from tools.weather_tool import fetch_weather_report, format_weather_for_voice
from tools.amenities_tool import handle_user_query
from tools.db_tool import search_properties as db_search_properties

LOGGER = get_logger(__name__)


# ============================================
# STATE
# ============================================
class AgentState(TypedDict):
    session_id: str
    user_input: str
    messages: list[dict]
    intent: str
    preferred_language: str
    tool_context: dict
    final_response: str


# ============================================
# ORCHESTRATOR
# ============================================
class OrchestratorAgent:

    def __init__(self, llm: GeminiClient, redis_client, settings):
        self._llm = llm
        self._redis = redis_client
        self._settings = settings
        self._graph = self._build_graph()

    @staticmethod
    def _normalize_language(language: str | None) -> str:
        code = (language or "").strip().lower()
        if code in {"bn", "bengali", "bangla"}:
            return "bengali"
        return "english"

    async def set_session_language(self, session_id: str, language: str | None) -> str:
        normalized = self._normalize_language(language)
        key = f"lang:{session_id}"
        try:
            await self._redis.setex(key, 60 * 60 * 24, normalized)
        except Exception as exc:
            LOGGER.warning("Redis language write error: %s", exc)
        return normalized

    async def get_session_language(self, session_id: str) -> str:
        key = f"lang:{session_id}"
        try:
            value = await self._redis.get(key)
            if value:
                return self._normalize_language(str(value))
        except Exception as exc:
            LOGGER.warning("Redis language read error: %s", exc)
        return "english"

    # ──────────────────────────────────────────
    # GRAPH
    # ──────────────────────────────────────────

    def _build_graph(self):
        g = StateGraph(AgentState)
        g.add_node("classify_intent",   self._classify_intent)
        g.add_node("search_properties", self._search_properties)
        g.add_node("find_amenities",    self._find_amenities)
        g.add_node("get_weather",       self._get_weather)
        g.add_node("general_chat",      self._general_chat)
        g.add_node("synthesize",        self._synthesize)

        g.set_entry_point("classify_intent")
        g.add_conditional_edges(
            "classify_intent",
            self._route_intent,
            {
                "search":  "search_properties",
                "amenity": "find_amenities",
                "weather": "get_weather",
                "general": "general_chat",
            },
        )
        for node in ("search_properties", "find_amenities", "get_weather", "general_chat"):
            g.add_edge(node, "synthesize")
        g.add_edge("synthesize", END)
        return g.compile(checkpointer=MemorySaver())

    # ──────────────────────────────────────────
    # ROUTING
    # ──────────────────────────────────────────

    def _route_intent(self, state: AgentState) -> Literal["search","amenity","weather","general"]:
        intent = state.get("intent", "general").lower().strip()
        return intent if intent in ("search", "amenity", "weather", "general") else "general"

    # ──────────────────────────────────────────
    # NODE: CLASSIFY INTENT
    # ──────────────────────────────────────────

    async def classify_intent(self, user_input: str) -> str:
        if self._is_contact_request(user_input):
            return "search"

        prompt = build_intent_prompt(user_input)
        try:
            raw = await self._llm.generate_text(prompt)
            intent = raw.strip().lower()
            if intent not in ("search", "amenity", "weather", "general"):
                intent = "general"
            return intent
        except Exception as exc:
            LOGGER.exception("Intent classification error: %s", exc)
            return "general"

    async def _classify_intent(self, state: AgentState) -> dict:
        existing_intent = state.get("intent", "").lower().strip()
        if existing_intent in ("search", "amenity", "weather", "general"):
            LOGGER.info("Intent (preclassified): %s", existing_intent)
            return {"intent": existing_intent}

        intent = await self.classify_intent(state["user_input"])
        LOGGER.info("Intent classified: %s", intent)
        return {"intent": intent}

    # ──────────────────────────────────────────
    # NODE: SEARCH PROPERTIES
    # LLM extracts the MongoDB query → tool executes it
    # ──────────────────────────────────────────

    @staticmethod
    def _is_contact_request(user_input: str) -> bool:
        text = (user_input or "").strip().lower()
        if not text:
            return False
        return bool(
            re.search(
                r"\b(contact|phone|number|mobile|call|agent number|owner number|contact details?)\b",
                text,
                flags=re.IGNORECASE,
            )
        )

    async def _search_properties(self, state: AgentState) -> dict:
        user_input = state["user_input"]
        LOGGER.info("Search node input received")
        contact_requested = self._is_contact_request(user_input)

        # Step 1: LLM builds the MongoDB query dict from natural language
        query_dict: dict = {}
        try:
            extraction_prompt = build_query_extraction_prompt(user_input)
            raw_json = await self._llm.generate_text(extraction_prompt)

            # Handle occasional fenced or prefixed output and parse first JSON object.
            clean = raw_json.strip()
            if clean.startswith("```"):
                clean = clean.strip("`").strip()
                if clean.lower().startswith("json"):
                    clean = clean[4:].strip()

            start = clean.find("{")
            end = clean.rfind("}")
            if start != -1 and end != -1 and end >= start:
                clean = clean[start:end + 1]

            query_dict = json.loads(clean)
            LOGGER.info("LLM extracted DB query: %s", query_dict)

        except Exception as exc:
            LOGGER.warning("Query extraction failed (%s), using empty filter", exc)
            query_dict = {}

        # Step 2: Dumb tool executes the query — no parsing logic inside
        try:
            result = await db_search_properties(
                query_dict=query_dict,
                uri=self._settings.mongo_uri,
                db_name=self._settings.mongo_db_name,
                collection_name=self._settings.mongo_property_collection,
                limit=5,
            )
            result["contact_requested"] = contact_requested
            top_property = (result.get("properties") or [None])[0]
            if contact_requested and isinstance(top_property, dict):
                contact = top_property.get("contact") or {}
                result["primary_contact"] = {
                    "name": contact.get("name", "N/A"),
                    "phone": contact.get("phone", "N/A"),
                }
            return {"tool_context": result}

        except Exception as exc:
            LOGGER.exception("DB tool call failed: %s", exc)
            return {
                "tool_context": {
                    "properties": [],
                    "count": 0,
                    "error": str(exc),
                    "contact_requested": contact_requested,
                }
            }

    # ──────────────────────────────────────────
    # NODE: FIND AMENITIES
    # ──────────────────────────────────────────

    async def _find_amenities(self, state: AgentState) -> dict:
        user_input = state["user_input"]
        LOGGER.info("Amenity node input received")
        location = "Kolkata"
        context_location = None

        try:
            resolution_prompt = build_amenity_location_resolution_prompt(
                user_input=user_input,
                messages=state.get("messages", []),
            )
            resolved = (await self._llm.generate_text(resolution_prompt)).strip().strip("\"'")
            if resolved and resolved.lower() not in {"none", "null", "unknown", "n/a"}:
                context_location = resolved
                LOGGER.info("Amenity context location resolved: %s", context_location)
        except Exception as exc:
            LOGGER.warning("Amenity context resolution failed: %s", exc)

        try:
            payload = await asyncio.to_thread(
                handle_user_query,
                user_input,
                context_location,
            )
            location = payload.get("location", "Kolkata")
            LOGGER.info("Amenity lookup completed near: %s", location)
            fallback_text = (
                "sorry umm i couldn't find what you asked for, "
                "umm i am really sorry, anything else i can help with?"
            )
            return {
                "tool_context": {
                    "amenities": payload.get("formatted", fallback_text),
                    "amenities_data": payload,
                    "location": location,
                    "status": "success" if not payload.get("error") else "error",
                    "amenity_error": payload.get("error"),
                }
            }
        except Exception as exc:
            LOGGER.exception("Amenity tool error: %s", exc)
            return {
                "tool_context": {
                    "amenity_error": str(exc),
                    "location": location,
                    "amenities": (
                        "sorry umm i couldn't find what you asked for, "
                        "umm i am really sorry, anything else i can help with?"
                    ),
                    "status": "error",
                }
            }

    # ──────────────────────────────────────────
    # NODE: GET WEATHER
    # LLM extracts location → tool fetches weather
    # ──────────────────────────────────────────

    async def _get_weather(self, state: AgentState) -> dict:
        user_input = state["user_input"]
        LOGGER.info("Weather node input received")

        try:
            loc_raw = await self._llm.generate_text(
                build_location_extraction_prompt(user_input)
            )
            location = loc_raw.strip().strip("\"'") or "Kolkata"
        except Exception as exc:
            LOGGER.warning("Weather location extraction failed: %s", exc)
            location = "Kolkata"

        LOGGER.info("Weather location resolved: %s", location)

        api_key = getattr(self._settings, "openweather_api_key", "")
        if not api_key:
            return {"tool_context": {"weather_error": "Weather API key not configured.", "status": "error"}}

        try:
            report = await fetch_weather_report(
                redis_client=self._redis,
                api_key=api_key,
                location_query=location,
            )
            LOGGER.info("Weather fetched for %s", report.city_name)
            return {
                "tool_context": {
                    "weather": format_weather_for_voice(report),
                    "weather_data": report.to_dict(),
                    "location": report.city_name,
                    "status": "success",
                }
            }
        except Exception as exc:
            LOGGER.exception("Weather node error: %s", exc)
            return {"tool_context": {"weather_error": str(exc), "location": location, "status": "error"}}

    # ──────────────────────────────────────────
    # NODE: GENERAL CHAT
    # ──────────────────────────────────────────

    async def _general_chat(self, state: AgentState) -> dict:
        LOGGER.info("General chat node")
        return {"tool_context": {"type": "general"}}

    # ──────────────────────────────────────────
    # NODE: SYNTHESIZE
    # ──────────────────────────────────────────

    async def _synthesize(self, state: AgentState) -> dict:
        tool_context = state.get("tool_context", {})
        preferred_language = self._normalize_language(
            state.get("preferred_language") or tool_context.get("preferred_language")
        )
        is_bengali = preferred_language == "bengali"
        if state.get("intent") == "search" and tool_context.get("contact_requested"):
            contact = tool_context.get("primary_contact") or {}
            name = str(contact.get("name", "N/A")).strip() or "N/A"
            phone = str(contact.get("phone", "N/A")).strip() or "N/A"

            if phone != "N/A":
                if is_bengali:
                    response = f"umm so ei top listing er contact holo {name}, phone number {phone}."
                else:
                    response = f"umm so the top listing contact is {name}, phone number {phone}."
            elif (tool_context.get("count") or 0) > 0:
                if is_bengali:
                    response = "umm so ami listing peyechi, kintu ei record e contact number nei."
                else:
                    response = "umm so i found listings, but i could not find the contact number in this record."
            else:
                if is_bengali:
                    response = "umm so contact details share korar jonno matching property khuje pelam na."
                else:
                    response = "umm so i could not find a matching property to share contact details."

            LOGGER.info("Response generated in contact flow")
            return {"final_response": response}

        prompt = build_synthesis_prompt(
            user_input=state["user_input"],
            intent=state.get("intent", "general"),
            tool_context=tool_context,
            messages=state.get("messages", []),
            preferred_language=preferred_language,
        )
        try:
            response = (await self._llm.generate_text(prompt)).strip()
            if not response:
                response = "I'm sorry, I didn't catch that — could you rephrase?"
            LOGGER.info("Synthesis response generated")
        except Exception as exc:
            LOGGER.exception("Synthesis error: %s", exc)
            response = "I apologise, something went wrong — please try again."
        return {"final_response": response}

    # ──────────────────────────────────────────
    # ENTRY POINT
    # ──────────────────────────────────────────

    async def invoke(
        self,
        session_id: str,
        user_input: str,
        *,
        preclassified_intent: str | None = None,
        preferred_language: str | None = None,
    ) -> dict:
        async def _run() -> dict:
            history_key = f"chat:{session_id}"
            try:
                raw = await self._redis.get(history_key)
                history: list[dict] = json.loads(raw) if raw else []
            except Exception as exc:
                LOGGER.warning("Redis history read error: %s", exc)
                history = []

            effective_language = (
                self._normalize_language(preferred_language)
                if preferred_language
                else await self.get_session_language(session_id)
            )

            state: AgentState = {
                "session_id": session_id,
                "user_input": user_input,
                "messages": history,
                "intent": (preclassified_intent or ""),
                "tool_context": {},
                "final_response": "",
                "preferred_language": effective_language,
            }

            LOGGER.info("Session start: %s", session_id)
            LOGGER.debug("User input: %s", user_input)

            result = await self._graph.ainvoke(
                state,
                config={"configurable": {"thread_id": session_id}},
            )

            try:
                history.append({"role": "user",      "content": user_input})
                history.append({"role": "assistant",  "content": result.get("final_response", "")})
                await self._redis.setex(
                    history_key,
                    60 * 60 * 24,
                    json.dumps(history[-20:]),
                )
            except Exception as exc:
                LOGGER.warning("Redis history write error: %s", exc)

            return result

        try:
            return await asyncio.wait_for(_run(), timeout=25.0)
        except asyncio.TimeoutError:
            LOGGER.error("Orchestrator timeout")
            return {"final_response": "sorry umm i am really sorry, i couldn't finish that right now, anything else i can help with?"}