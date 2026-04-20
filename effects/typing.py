from __future__ import annotations

from livekit.agents import AudioConfig, BackgroundAudioPlayer, BuiltinAudioClip


THINKING_SOUNDS: list[AudioConfig] = [
    AudioConfig(BuiltinAudioClip.KEYBOARD_TYPING, volume=0.8),
    AudioConfig(BuiltinAudioClip.KEYBOARD_TYPING2, volume=0.7),
]


def Create_effects() -> BackgroundAudioPlayer:
    return BackgroundAudioPlayer(thinking_sound=THINKING_SOUNDS)


def play_thinking_sound(background_audio: BackgroundAudioPlayer):
    return background_audio.play(THINKING_SOUNDS, loop=True)


def stop_thinking_sound(play_handle) -> None:
    if play_handle and not play_handle.done():
        play_handle.stop()

