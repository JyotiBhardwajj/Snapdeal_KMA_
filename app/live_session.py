"""Bridges one browser WebSocket <-> one Gemini Live API session.

Audio path (speech-to-speech, no separate STT/TTS hop):
    mic (browser, 16 kHz PCM16) --ws--> server --Live API--> Gemini native-audio model
    speaker (browser, 24 kHz PCM16) <--ws-- server <--Live API-- model audio

The server sits in the middle so that (a) credentials never reach the browser,
(b) function calls run server-side against the seller's data, and (c) every
step is mirrored to the UI as structured events (transcripts, tool calls, case
file updates).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections import Counter
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from google import genai
from google.genai import errors, types

from app.case_file import CaseFile
from app.config import Settings
from app.prompts import build_system_instruction, kickoff_prompt
from app.tools import ToolExecutor, tool_declarations

logger = logging.getLogger(__name__)

INPUT_AUDIO_MIME = "audio/pcm;rate=16000"
MAX_AUDIO_CHUNK_BYTES = 64_000  # ~2 s of 16 kHz PCM16; browser sends ~32 ms chunks
TIME_WARNING_SECONDS = 60

_SENSITIVITY = {
    "start": {
        "LOW": types.StartSensitivity.START_SENSITIVITY_LOW,
        "HIGH": types.StartSensitivity.START_SENSITIVITY_HIGH,
    },
    "end": {"LOW": types.EndSensitivity.END_SENSITIVITY_LOW, "HIGH": types.EndSensitivity.END_SENSITIVITY_HIGH},
}


def build_live_config(
    settings: Settings,
    language: str,
    mode: str = "inbound",
    previous_case: dict[str, Any] | None = None,
) -> types.LiveConnectConfig:
    vad = types.AutomaticActivityDetection(
        disabled=False,
        start_of_speech_sensitivity=_SENSITIVITY["start"].get(settings.vad_start_sensitivity or ""),
        end_of_speech_sensitivity=_SENSITIVITY["end"].get(settings.vad_end_sensitivity or ""),
        silence_duration_ms=settings.vad_silence_ms,
    )
    return types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        system_instruction=types.Content(
            parts=[types.Part(text=build_system_instruction(language, mode, previous_case))]
        ),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=settings.voice_name)
            )
        ),
        tools=[types.Tool(function_declarations=tool_declarations(mode))],
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        realtime_input_config=types.RealtimeInputConfig(automatic_activity_detection=vad),
        # Sliding-window compression lets a call run past the default context limit.
        context_window_compression=types.ContextWindowCompressionConfig(sliding_window=types.SlidingWindow()),
        temperature=settings.temperature,
    )


class CallBridge:
    """Runs one voice call. Create one per WebSocket connection."""

    def __init__(
        self,
        websocket: WebSocket,
        client: genai.Client,
        settings: Settings,
        *,
        mode: str,
        language: str,
        previous_case: dict[str, Any] | None = None,
    ) -> None:
        self.ws = websocket
        self.client = client
        self.settings = settings
        self.mode = mode
        self.language = language
        self.previous_case = previous_case
        self.case = CaseFile.open(
            mode=mode,
            language=language,
            previous_case_id=(previous_case or {}).get("case_id") or None,
        )
        self.tools = ToolExecutor(self.case, previous_case=previous_case)
        self.session: Any = None
        self._send_lock = asyncio.Lock()
        self._muted = False
        self._started = time.monotonic()
        self._end_reason = "unknown"
        self._tool_counts: Counter[str] = Counter()
        self._audio_after_summary = 0
        self._hangup_sent = False
        self._total_tokens: int | None = None

    # ------------------------------------------------------------------ lifecycle

    async def run(self) -> None:
        config = build_live_config(self.settings, self.language, self.mode, self.previous_case)
        try:
            async with self.client.aio.live.connect(model=self.settings.live_model, config=config) as session:
                self.session = session
                await self._send_json(
                    {
                        "type": "ready",
                        "case": self.case.to_dict(),
                        "max_call_seconds": self.settings.max_call_seconds,
                    }
                )
                await session.send_client_content(
                    turns=types.Content(role="user", parts=[types.Part(text=kickoff_prompt(self.mode))]),
                    turn_complete=True,
                )
                await self._run_pumps()
        except WebSocketDisconnect:
            self._end_reason = "client_disconnected"
        except errors.APIError as exc:
            if self._end_reason == "unknown":
                self._end_reason = f"live_api_error_{exc.code}"
            logger.warning("Live API error: %s", exc)
            await self._safe_send_json(
                {"type": "error", "message": "The voice AI service closed the connection. Please start a new call."}
            )
        except Exception:  # last-resort guard so one bad call never crashes the server
            self._end_reason = "server_error"
            logger.exception("Call failed")
            await self._safe_send_json({"type": "error", "message": "Something went wrong. Please try again."})
        finally:
            logger.info(
                "call_ended",
                extra={
                    "json_fields": {
                        "event": "call_ended",
                        "case_id": self.case.case_id,
                        "mode": self.mode,
                        "language": self.language,
                        "reason": self._end_reason,
                        "duration_s": round(time.monotonic() - self._started, 1),
                        "tools": dict(self._tool_counts),
                        "actions_taken": len(self.case.actions_taken),
                        "total_tokens": self._total_tokens,
                    }
                },
            )

    async def _run_pumps(self) -> None:
        tasks = {
            asyncio.create_task(self._browser_to_model(), name="browser_to_model"),
            asyncio.create_task(self._model_to_browser(), name="model_to_browser"),
            asyncio.create_task(self._watchdog(), name="watchdog"),
        }
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            exc = task.exception()
            if exc is not None:
                raise exc

    # ------------------------------------------------------------------ browser -> model

    async def _browser_to_model(self) -> None:
        while True:
            message = await self.ws.receive()
            if message["type"] == "websocket.disconnect":
                self._end_reason = "client_disconnected"
                return
            data = message.get("bytes")
            if data is not None:
                if self._muted or not data or len(data) > MAX_AUDIO_CHUNK_BYTES or len(data) % 2:
                    continue
                await self.session.send_realtime_input(audio=types.Blob(data=data, mime_type=INPUT_AUDIO_MIME))
                continue
            text = message.get("text")
            if text and not await self._handle_control(text):
                return

    async def _handle_control(self, raw: str) -> bool:
        """Handle a JSON control message. Returns False when the call should end."""
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            return True
        if not isinstance(event, dict):
            return True
        kind = event.get("type")
        if kind == "end":
            self._end_reason = "seller_hung_up" if not self.case.call_ending else "completed"
            return False
        if kind == "mute":
            self._muted = bool(event.get("muted"))
            if self._muted:
                # Tell the model the audio stream paused so it doesn't wait for more speech.
                await self.session.send_realtime_input(audio_stream_end=True)
        return True

    # ------------------------------------------------------------------ model -> browser

    async def _model_to_browser(self) -> None:
        while True:
            async for message in self.session.receive():
                await self._handle_server_message(message)

    async def _handle_server_message(self, message: types.LiveServerMessage) -> None:
        content = message.server_content
        if content is not None:
            if content.model_turn and content.model_turn.parts:
                for part in content.model_turn.parts:
                    if part.inline_data and part.inline_data.data:
                        if self.case.call_ending:
                            self._audio_after_summary += len(part.inline_data.data)
                        await self._send_bytes(part.inline_data.data)
            if content.input_transcription and content.input_transcription.text:
                if self._hangup_sent:
                    # The seller kept talking after the goodbye: keep the line open and
                    # hang up only after Disha's next closing turn.
                    self._hangup_sent = False
                    self._audio_after_summary = 0
                await self._send_json(
                    {"type": "transcript", "role": "seller", "text": content.input_transcription.text}
                )
            if content.output_transcription and content.output_transcription.text:
                await self._send_json({"type": "transcript", "role": "kam", "text": content.output_transcription.text})
            if content.interrupted:
                await self._send_json({"type": "interrupted"})
            if content.turn_complete:
                await self._send_json({"type": "turn_complete"})
                if self.case.call_ending and self._audio_after_summary and not self._hangup_sent:
                    # Disha has spoken her goodbye: the browser hangs up once playback finishes.
                    self._hangup_sent = True
                    self._end_reason = "completed"
                    await self._send_json({"type": "hangup"})

        if message.tool_call and message.tool_call.function_calls:
            await self._handle_tool_calls(message.tool_call.function_calls)

        if message.go_away is not None:
            logger.warning("Live API go_away received: %s", message.go_away.time_left)
        if message.usage_metadata is not None and message.usage_metadata.total_token_count:
            self._total_tokens = message.usage_metadata.total_token_count

    async def _handle_tool_calls(self, calls: list[types.FunctionCall]) -> None:
        responses: list[types.FunctionResponse] = []
        for call in calls:
            name = call.name or ""
            args = dict(call.args or {})
            self._tool_counts[name] += 1
            await self._send_json({"type": "tool_started", "name": name, "label": ToolExecutor.label(name, args)})
            result = self.tools.execute(name, args)
            responses.append(types.FunctionResponse(id=call.id, name=name, response=result))
            logger.info(
                "tool_call", extra={"json_fields": {"event": "tool_call", "tool": name, "ok": "error" not in result}}
            )
        # Latency-critical: unblock the model first, then update the UI.
        await self.session.send_tool_response(function_responses=responses)
        await self._send_json({"type": "case", "case": self.case.to_dict()})

    # ------------------------------------------------------------------ guard rails

    async def _watchdog(self) -> None:
        limit = self.settings.max_call_seconds
        warn_at = max(0, limit - TIME_WARNING_SECONDS)
        await asyncio.sleep(warn_at)
        await self._send_json({"type": "notice", "message": "About a minute left on this demo call."})
        await asyncio.sleep(limit - warn_at)
        self._end_reason = "time_limit"
        await self._send_json({"type": "call_ended", "reason": "time_limit"})

    # ------------------------------------------------------------------ transport helpers

    async def _send_json(self, payload: dict[str, Any]) -> None:
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        async with self._send_lock:
            await self.ws.send_text(text)

    async def _send_bytes(self, data: bytes) -> None:
        async with self._send_lock:
            await self.ws.send_bytes(data)

    async def _safe_send_json(self, payload: dict[str, Any]) -> None:
        with contextlib.suppress(Exception):  # the socket may already be gone
            await self._send_json(payload)
