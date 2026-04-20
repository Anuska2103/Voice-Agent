"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { LiveKitRoom, RoomAudioRenderer, useRoomContext } from "@livekit/components-react";
import { RoomEvent } from "livekit-client";
import "@livekit/components-styles";

import { fetchLivekitToken } from "@/lib/api";

function makeId(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`;
}

type ChatRole = "user" | "agent";
type LanguageCode = "english" | "bengali";

type ChatMessage = {
  id: string;
  role: ChatRole;
  text: string;
};

// ─── Typing sound hook ────────────────────────────────────────────────────────
function useTypingSound(src: string = "/sounds/type.wav", volume = 0.6) {
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const start = () => {
    // Already playing — don't restart
    if (audioRef.current && !audioRef.current.paused) return;

    const audio = new Audio(src);
    audio.loop = true;
    audio.volume = volume;
    audio.play().catch(() => {
      // Browser may block autoplay before first user gesture — safe to ignore,
      // the button click that connects the room satisfies the gesture requirement.
    });
    audioRef.current = audio;
  };

  const stop = () => {
    if (!audioRef.current) return;
    audioRef.current.pause();
    audioRef.current.currentTime = 0;
    audioRef.current = null;
  };

  // Clean up on unmount
  useEffect(() => () => stop(), []);

  return { start, stop };
}

// ─── Chat + typing bridge ─────────────────────────────────────────────────────
type ChatDataBridgeProps = {
  onMessage: (message: ChatMessage) => void;
};

function ChatDataBridge({ onMessage }: ChatDataBridgeProps) {
  const room = useRoomContext();
  const { start: startTyping, stop: stopTyping } = useTypingSound();

  useEffect(() => {
    const onDataReceived = (payload: Uint8Array) => {
      try {
        const raw = new TextDecoder().decode(payload);
        const parsed = JSON.parse(raw) as {
          type?: string;
          role?: string;
          text?: string;
        };

        if (parsed.type !== "chat.message") return;
        if (parsed.role !== "user" && parsed.role !== "agent") return;
        if (!parsed.text || !parsed.text.trim()) return;

        if (parsed.role === "user") {
          // User spoke → agent is now thinking → start typing sound
          startTyping();
        } else {
          // Agent responded → stop typing sound
          stopTyping();
        }

        onMessage({
          id: makeId("msg"),
          role: parsed.role,
          text: parsed.text.trim(),
        });
      } catch {
        // Ignore non-chat data packets.
      }
    };

    room.on(RoomEvent.DataReceived, onDataReceived);
    return () => {
      room.off(RoomEvent.DataReceived, onDataReceived);
      stopTyping(); // clean up if room unmounts mid-thinking
    };
  }, [room, onMessage, startTyping, stopTyping]);

  return null;
}

type LanguageSyncBridgeProps = {
  language: LanguageCode;
};

function LanguageSyncBridge({ language }: LanguageSyncBridgeProps) {
  const room = useRoomContext();

  useEffect(() => {
    async function pushLanguageSetting() {
      const payload = {
        type: "agent.settings",
        language,
      };

      try {
        await room.localParticipant.publishData(new TextEncoder().encode(JSON.stringify(payload)), {
          reliable: true,
          topic: "agent.settings",
        });
      } catch {
        // Ignore transient data channel issues; language will re-sync on next change.
      }
    }

    void pushLanguageSetting();
  }, [room, language]);

  return null;
}

// ─── Main panel ───────────────────────────────────────────────────────────────
export function VoiceAgentPanel() {
  const [room, setRoom] = useState<string | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [serverUrl, setServerUrl] = useState<string | null>(null);
  const [isJoining, setIsJoining] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [language, setLanguage] = useState<LanguageCode>("english");
  const autoAccessKey = process.env.NEXT_PUBLIC_JOIN_ACCESS_KEY?.trim();

  const livekitUrl =
    serverUrl ?? process.env.NEXT_PUBLIC_LIVEKIT_URL?.replace(/\/$/, "") ?? "ws://localhost:7880";

  const status = useMemo(() => {
    if (error) return `Error: ${error}`;
    if (isConnected) return "Connected. You can start speaking now.";
    if (isJoining) return "Joining room...";
    return "Tap the button to connect with the agent.";
  }, [error, isConnected, isJoining]);

  async function handleConnectClick() {
    if (token || isConnected) {
      handleLeave();
      return;
    }

    setError(null);
    setIsJoining(true);

    try {
      const generatedIdentity = makeId("guest");
      const generatedRoom = makeId("room");

      const response = await fetchLivekitToken({
        identity: generatedIdentity,
        name: generatedIdentity,
        room: generatedRoom,
        access_key: autoAccessKey || undefined,
      });

      setRoom(response.room);
      setToken(response.token);
      setServerUrl(response.ws_url?.replace(/\/$/, "") || null);
    } catch (joinError) {
      const message = joinError instanceof Error ? joinError.message : "Unknown join error";
      setError(message);
      setToken(null);
      setServerUrl(null);
    } finally {
      setIsJoining(false);
    }
  }

  function handleLeave() {
    setToken(null);
    setServerUrl(null);
    setIsConnected(false);
    setError(null);
    setMessages([]);
  }

  function handleMessage(message: ChatMessage) {
    setMessages((previous) => [...previous, message]);
  }

  return (
    <section className="panel">
      <div className="joinForm">
        <div className="fieldRow">
          <label htmlFor="language-select">Language</label>
          <select
            id="language-select"
            value={language}
            onChange={(event) => setLanguage(event.target.value as LanguageCode)}
          >
            <option value="english">English</option>
            <option value="bengali">Bengali</option>
          </select>
        </div>
        <div className="actions">
          <button type="button" onClick={handleConnectClick} disabled={isJoining}>
            {isJoining
              ? "Connecting..."
              : token || isConnected
                ? "Disconnect"
                : "Click here to connect with the agent"}
          </button>
        </div>
      </div>

      <p className="status">{status}</p>

      <div className="roomShell">
        {token ? (
          <LiveKitRoom
            token={token}
            serverUrl={livekitUrl}
            connect
            audio
            video={false}
            onConnected={() => {
              setIsConnected(true);
              setError(null);
              setMessages([]);
            }}
            onDisconnected={() => {
              setIsConnected(false);
            }}
            onError={(eventError) => {
              setError(eventError.message);
              setIsConnected(false);
            }}
            className="lkContainer"
          >
            <LanguageSyncBridge language={language} />
            <ChatDataBridge onMessage={handleMessage} />
            <RoomAudioRenderer />
            <div className="hint">
              Mic is enabled while connected. Your backend LiveKit worker should be running for replies.
            </div>
            <div className="chatTimeline" aria-live="polite" aria-label="Conversation">
              {messages.length === 0 ? (
                <p className="chatEmpty">Conversation will appear here.</p>
              ) : (
                messages.map((message) => (
                  <div
                    key={message.id}
                    className={`chatBubble ${message.role === "user" ? "chatBubbleUser" : "chatBubbleAgent"}`}
                  >
                    {message.text}
                  </div>
                ))
              )}
            </div>
          </LiveKitRoom>
        ) : null}
      </div>
    </section>
  );
}