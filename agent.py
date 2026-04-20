"""
agent.py
Simplified LiveKit Voice Agent.

"""

import os
import asyncio
import json
import re
from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, cli
from livekit.agents import stt as agent_stt
from livekit import rtc
from livekit.plugins import deepgram, elevenlabs, silero
from orchestrator import OrchestratorAgent
from llm import GeminiClient
from config import settings
from redis import asyncio as aioredis
from livekit.agents import BackgroundAudioPlayer, AudioConfig, BuiltinAudioClip
from logger import get_logger

LOGGER = get_logger(__name__)

# ============================================
# VAD (loaded once at module level)
# ============================================
vad = silero.VAD.load(
    min_speech_duration=0.12,
    min_silence_duration=0.75,
    activation_threshold=0.62,
    prefix_padding_duration=0.2,
)


# ============================================
# GLOBAL SINGLETONS
# ============================================
_orchestrator: OrchestratorAgent | None = None
_redis_client = None


async def init_backend() -> OrchestratorAgent:
    """Initialise Redis + LLM + Orchestrator once per worker process."""
    global _orchestrator, _redis_client

    if _orchestrator is not None:
        return _orchestrator

    LOGGER.info("Initializing backend services")

    _redis_client = await aioredis.from_url(settings.redis_url)
    LOGGER.info("Redis connected")

    # NOTE: MongoDB connection is now lazy-initialised inside tools/db_connection.py
    # No MongoRepo import needed here.

    llm_client = GeminiClient(settings)
    LOGGER.info("Gemini LLM initialized")

    _orchestrator = OrchestratorAgent(
        llm=llm_client,
        redis_client=_redis_client,
        settings=settings,
    )
    LOGGER.info("LangGraph orchestrator ready")

    return _orchestrator


# ============================================
# LIVEKIT ENTRYPOINT
# ============================================
async def entrypoint(ctx: JobContext):
    orchestrator = await init_backend()

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    LOGGER.info("Connected to room: %s", ctx.room.name)

    participant = await ctx.wait_for_participant()
    session_id = participant.identity or ctx.room.name
    LOGGER.info("Participant joined: %s", session_id)

    deepgram_stt = deepgram.STT(
        model="nova-3",
        language=settings.deepgram_language,
        interim_results=False,
        endpointing_ms=0,
        vad_events=False,
        punctuate=True,
        smart_format=True,
        filler_words=False,
    )

    stt = agent_stt.StreamAdapter(stt=deepgram_stt, vad=vad)

    tts = elevenlabs.TTS(
        api_key=os.getenv("ELEVENLABS_API_KEY"),
        voice_id="EXAVITQu4vr4xnSDxMaL",  # Bella
    )

    assistant = VoiceAssistant(
        orchestrator=orchestrator,
        session_id=session_id,
        stt=stt,
        tts=tts,
        vad=vad,
    )
    assistant.start(ctx.room)

    await assistant.say(
        "Hello! Ami Neha, bolun how can I assist you today?"
    )
    LOGGER.info("Voice agent ready and listening")


# ============================================
# VOICE ASSISTANT
# ============================================
class VoiceAssistant:
    def __init__(self, orchestrator, session_id, stt, tts, vad):
        self.orchestrator = orchestrator
        self.session_id = session_id
        self.stt = stt
        self.tts = tts
        self.vad = vad
        self.room: rtc.Room | None = None
        self.is_speaking = False
        self.is_processing = False
        self._bg: BackgroundAudioPlayer = BackgroundAudioPlayer()
        self._typing_handle = None
        self.selected_language = "english"

    def start(self, room: rtc.Room):
        self.room = room
        asyncio.create_task(self._bg.start(room=room), name="bg-audio-start")

        @room.on("data_received")
        def on_data_received(packet: rtc.DataPacket):
            asyncio.create_task(self._handle_data_packet(packet))

        @room.on("track_subscribed")
        def on_track_subscribed(
            track: rtc.Track,
            publication: rtc.TrackPublication,
            participant: rtc.RemoteParticipant,
        ):
            if track.kind == rtc.TrackKind.KIND_AUDIO:
                LOGGER.info("Audio track subscribed from participant: %s", participant.identity)
                asyncio.create_task(self._process_audio_track(track, participant))

    async def _handle_data_packet(self, packet: rtc.DataPacket) -> None:
        try:
            if getattr(packet, "topic", "") != "agent.settings":
                return

            raw = packet.data.decode("utf-8", errors="ignore")
            payload = json.loads(raw)
            if payload.get("type") != "agent.settings":
                return

            language = str(payload.get("language", "")).strip().lower()
            if language not in {"english", "bengali", "en", "bn", "bangla"}:
                return

            normalized = await self.orchestrator.set_session_language(
                self.session_id,
                language,
            )
            self.selected_language = normalized
            LOGGER.info("Language switched to: %s", normalized)
        except Exception as exc:
            LOGGER.warning("Language settings packet error: %s", exc)

    async def _process_audio_track(
        self, track: rtc.AudioTrack, participant: rtc.RemoteParticipant
    ):
        audio_stream = rtc.AudioStream(track)
        stt_stream = self.stt.stream()

        async def forward_audio():
            async for event in audio_stream:
                if not self.is_processing and not self.is_speaking:
                    stt_stream.push_frame(event.frame)
            await stt_stream.aclose()

        asyncio.create_task(forward_audio())

        from livekit.agents.stt import SpeechEventType

        async for event in stt_stream:
            if self.is_processing or self.is_speaking:
                continue

            if event.type == SpeechEventType.FINAL_TRANSCRIPT:
                if event.alternatives:
                    final_text = event.alternatives[0].text.strip()
                    if final_text:
                        LOGGER.info("Final utterance received: %s", final_text)
                        asyncio.create_task(self._handle_user_message(final_text))

    def _start_typing(self) -> None:
        """Start looping keyboard sound on the already-started background player."""
        if self._typing_handle and not self._typing_handle.done():
            return  # already playing
        self._typing_handle = self._bg.play(
            [
                AudioConfig(BuiltinAudioClip.KEYBOARD_TYPING, volume=1.0),
                
            ],
            loop=True,
        )
        LOGGER.debug("Typing sound started")

    def _stop_typing(self) -> None:
        """Stop the looping keyboard sound."""
        if self._typing_handle is not None:
            try:
                self._typing_handle.stop()
            except Exception:
                pass
            self._typing_handle = None
        LOGGER.debug("Typing sound stopped")

    async def _invoke_with_busy_typing(self, invoke_coro):
        self._start_typing()
        fetch_task = asyncio.create_task(invoke_coro, name="orchestrator-fetch")
        try:
            return await fetch_task
        finally:
            self._stop_typing()

    async def _publish_chat_event(self, role: str, text: str) -> None:
        if not self.room or not text.strip():
            return

        payload = json.dumps(
            {
                "type": "chat.message",
                "role": role,
                "text": text.strip(),
            }
        )
        try:
            await self.room.local_participant.publish_data(payload, topic="chat.message")
        except Exception:
            pass

    async def _handle_user_message(self, user_text: str):
        if self.is_processing:
            LOGGER.warning("Already processing a previous request, skipping current utterance")
            return

        self.is_processing = True
        try:
            self._start_typing()
            LOGGER.info("User message: %s", user_text)
            await self._publish_chat_event("user", user_text)

            intent = await asyncio.wait_for(
                self.orchestrator.classify_intent(user_text),
                timeout=6.0,
            )

            if intent in {"search", "query"}:
                await self.say("Umm... Please wait until i come back")
                self._start_typing()

            result = await self._invoke_with_busy_typing(
                self.orchestrator.invoke(
                    session_id=self.session_id,
                    user_input=user_text,
                    preclassified_intent=intent,
                    preferred_language=self.selected_language,
                )
            )
            response = result.get("final_response", "I'm sorry, I couldn't process that.")
            LOGGER.info("Assistant response prepared")
            await self.say(response)

        except asyncio.TimeoutError:
            await self.say("sorry umm i am really sorry, i couldn't finish that, can you please try once more?")
        except Exception as exc:
            LOGGER.exception("Error while handling user message (%s): %s", type(exc).__name__, exc)
            await self.say("I hit a small snag. Could you repeat that?")
        finally:
            self._stop_typing()
            self.is_processing = False
            LOGGER.info("Ready for next input")

    async def say(self, text: str):
        if not self.room or not text:
            return
        self._stop_typing()
        self.is_speaking = True
        spoken_text = self._clean_tts_text(text)
        if not spoken_text:
            spoken_text = "umm so sorry, can you say that again?"

        await self._publish_chat_event("agent", spoken_text)
        LOGGER.info("Speaking response")
        try:
            audio_stream = self.tts.synthesize(spoken_text)
            source: rtc.AudioSource | None = None
            track: rtc.LocalAudioTrack | None = None

            async for chunk in audio_stream:
                if source is None:
                    source = rtc.AudioSource(
                        sample_rate=chunk.frame.sample_rate,
                        num_channels=chunk.frame.num_channels,
                    )
                    track = rtc.LocalAudioTrack.create_audio_track("neha-voice", source)
                    options = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
                    await self.room.local_participant.publish_track(track, options)
                await source.capture_frame(chunk.frame)

            if source:
                await source.wait_for_playout()
            if track:
                await self.room.local_participant.unpublish_track(track.sid)

            LOGGER.info("Finished speaking")
        except Exception as exc:
            LOGGER.exception("TTS error (%s): %s", type(exc).__name__, exc)
        finally:
            self.is_speaking = False

    def _clean_tts_text(self, text: str) -> str:
        cleaned = (text or "").strip()
        if not cleaned:
            return ""

        # Remove bracketed and XML-style emotion tags so they are not spoken.
        cleaned = re.sub(r"\[[^\]]*\]", " ", cleaned)
        cleaned = re.sub(r"<emotion\b[^>]*\/?>", " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"</?emotion\b[^>]*>", " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned


# ============================================
# RUN
# ============================================
if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name="real-estate-agent",
        )
    )