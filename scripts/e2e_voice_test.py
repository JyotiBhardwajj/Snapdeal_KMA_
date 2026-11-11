#!/usr/bin/env python3
"""End-to-end voice test: talks to the running app exactly like a browser would.

1. Synthesises the seller's lines as speech (using the Gemini Live model as a TTS).
2. Streams that audio, at real-time pace, into the app's /ws/call WebSocket as
   16 kHz PCM, with continuous background silence like a real microphone.
3. Waits for Disha to finish each turn, then answers with the next line.
4. Prints the transcript, tool calls and the final case file, and exits non-zero
   if the core workflow (diagnosis -> plan -> summary) didn't happen.

Usage:
    python scripts/e2e_voice_test.py --url ws://localhost:8080/ws/call
    python scripts/e2e_voice_test.py --url wss://<cloud-run-host>/ws/call --save-audio /tmp/call.wav
"""

from __future__ import annotations

import argparse
import array
import asyncio
import contextlib
import hashlib
import json
import os
import sys
import time
import wave
from pathlib import Path

import websockets
from google import genai
from google.genai import types

SELLER_LINES = [
    "Hi Disha. My sales have dropped a lot this month and I really don't understand why. Can you help me?",
    "Yes, my main supplier in Delhi delayed my stock by almost three weeks because of the festive rush.",
    "I update my stock on Snapdeal manually, maybe once a week. So some orders came for items I didn't have, "
    "and I had to cancel them.",
    "Okay, that makes sense. Please go ahead and set up the low stock alerts, and send me the restock list on "
    "WhatsApp.",
    "Yes, a follow-up call next week is good.",
    "No, that's all for now. Thank you, Disha!",
]

SELLER_LINES_HI = [
    "नमस्ते दिशा। इस महीने मेरी सेल्स बहुत गिर गई है, समझ नहीं आ रहा क्यों। क्या आप मेरी मदद कर सकती हैं?",
    "हाँ, मेरे दिल्ली वाले सप्लायर ने फेस्टिव रश की वजह से स्टॉक लगभग तीन हफ्ते लेट भेजा।",
    "मैं Snapdeal पर स्टॉक मैनुअली अपडेट करता हूँ, हफ्ते में एक बार। इसलिए कुछ ऑर्डर ऐसे आइटम्स के आए जो मेरे पास "
    "थे ही नहीं, और मुझे कैंसिल करने पड़े।",
    "ठीक है, समझ गया। प्लीज़ लो स्टॉक अलर्ट्स लगा दीजिए और रीस्टॉक लिस्ट WhatsApp पर भेज दीजिए।",
    "हाँ, अगले हफ्ते फॉलो-अप कॉल ठीक है।",
    "नहीं, बस इतना ही। धन्यवाद दिशा!",
]

IN_RATE = 16_000
CHUNK_SAMPLES = 512  # 32 ms, same as the browser worklet
CACHE_DIR = Path(os.getenv("E2E_CACHE_DIR", "/tmp/vkam-e2e-cache"))


# ----------------------------------------------------------------------------- speech synthesis


def resample_24k_to_16k(pcm24: bytes) -> bytes:
    src = array.array("h")
    src.frombytes(pcm24[: len(pcm24) - len(pcm24) % 2])
    n_out = int(len(src) * 2 / 3)
    out = array.array("h", bytes(2 * n_out))
    for j in range(n_out):
        pos = j * 1.5
        i = int(pos)
        frac = pos - i
        a = src[i]
        b = src[i + 1] if i + 1 < len(src) else a
        out[j] = int(a + (b - a) * frac)
    return out.tobytes()


async def synthesize(client: genai.Client, model: str, text: str, voice: str) -> bytes:
    key = hashlib.sha1(f"{model}|{voice}|{text}".encode()).hexdigest()[:16]
    cached = CACHE_DIR / f"{key}.pcm"
    if cached.exists() and cached.stat().st_size > IN_RATE:  # ignore empty/near-empty cached takes
        return cached.read_bytes()
    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        system_instruction=(
            "You are a voice actor playing an Indian small-business owner. Read the user's text aloud exactly, "
            "word for word, naturally, then stop. Never add anything."
        ),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))
        ),
    )
    # Expect roughly 2.5 words per second of speech; reject empty or truncated takes and retry.
    min_seconds = max(1.0, len(text.split()) / 4)
    for attempt in range(4):
        audio = bytearray()
        async with client.aio.live.connect(model=model, config=config) as session:
            await session.send_client_content(
                turns=types.Content(role="user", parts=[types.Part(text=f"Read this aloud: {text}")]),
                turn_complete=True,
            )
            async for msg in session.receive():
                sc = msg.server_content
                if sc and sc.model_turn:
                    for part in sc.model_turn.parts or []:
                        if part.inline_data and part.inline_data.data:
                            audio.extend(part.inline_data.data)
        pcm16 = resample_24k_to_16k(bytes(audio))
        if len(pcm16) / 2 / IN_RATE >= min_seconds:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(pcm16)
            return pcm16
        print(f"  (synthesis attempt {attempt + 1} too short for: {text[:40]}...; retrying)", flush=True)
    raise RuntimeError(f"Could not synthesise seller speech for: {text!r}")


# ----------------------------------------------------------------------------- the call


class Call:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self.transcript: list[list[str]] = []  # [role, text]
        self.tool_calls: list[str] = []
        self.case: dict | None = None
        self.last_audio_at = 0.0
        self.last_turn_complete_at = 0.0
        self.play_until = 0.0  # when Disha's audio would finish playing on a real speaker
        self.awaiting_reply_since: float | None = None
        self.latencies: list[float] = []
        self.hangup = False
        self.closed = False
        self.audio_out = bytearray()

    def add_text(self, role: str, text: str) -> None:
        if self.transcript and self.transcript[-1][0] == role:
            self.transcript[-1][1] += text
        else:
            self.transcript.append([role, text])


async def mic(ws, queue: asyncio.Queue, call: Call) -> None:
    """Streams queued speech, otherwise silence, at real-time pace (like an open microphone)."""
    silence = bytes(CHUNK_SAMPLES * 2)
    chunk_s = CHUNK_SAMPLES / IN_RATE
    next_at = time.monotonic()
    pending = b""
    done_event: asyncio.Event | None = None
    while not call.closed:
        if not pending and not queue.empty():
            pending, done_event = queue.get_nowait()
        if pending:
            chunk, pending = pending[: CHUNK_SAMPLES * 2], pending[CHUNK_SAMPLES * 2 :]
            chunk = chunk.ljust(CHUNK_SAMPLES * 2, b"\0")
            if not pending and done_event is not None:
                done_event.set()
                done_event = None
        else:
            chunk = silence
        try:
            await ws.send(chunk)
        except websockets.ConnectionClosed:
            return
        next_at += chunk_s
        await asyncio.sleep(max(0, next_at - time.monotonic()))


async def receiver(ws, call: Call, verbose: bool) -> None:
    try:
        async for message in ws:
            if isinstance(message, bytes):
                now = time.monotonic()
                if call.awaiting_reply_since is not None:
                    call.latencies.append(now - call.awaiting_reply_since)
                    call.awaiting_reply_since = None
                call.last_audio_at = now
                call.play_until = max(call.play_until, now) + len(message) / 48_000  # 24 kHz PCM16
                call.audio_out.extend(message)
                continue
            event = json.loads(message)
            call.events.append(event)
            kind = event.get("type")
            if kind == "transcript":
                call.add_text(event["role"], event["text"])
            elif kind == "tool_started":
                call.tool_calls.append(event["name"])
                if verbose:
                    print(f"    [tool] {event['name']}  ({event.get('label')})", flush=True)
            elif kind in ("case", "ready"):
                call.case = event.get("case")
            elif kind == "turn_complete":
                call.last_turn_complete_at = time.monotonic()
            elif kind == "hangup":
                call.hangup = True
            elif kind in ("error", "call_ended", "interrupted") and verbose:
                print(f"    [{kind}] {event if kind != 'interrupted' else ''}", flush=True)
    except websockets.ConnectionClosed:
        pass
    finally:
        call.closed = True


async def wait_for_disha(call: Call, since: float, pause_s: float = 0.8, timeout: float = 90) -> None:
    """Wait like a polite human: Disha spoke, finished her turn, her audio finished playing, then a short pause."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not call.closed and not call.hangup:
        now = time.monotonic()
        spoke = call.last_audio_at > since
        finished = call.last_turn_complete_at >= call.last_audio_at
        if spoke and finished and now > call.play_until + pause_s:
            return
        await asyncio.sleep(0.1)


async def say(queue: asyncio.Queue, pcm: bytes, call: Call) -> float:
    """Queue a line on the open mic and return when it has been fully streamed."""
    done = asyncio.Event()
    await queue.put((pcm, done))
    await done.wait()
    finished = time.monotonic()
    call.awaiting_reply_since = finished  # latency = end of seller speech -> first audio back
    return finished


def print_new_lines(call: Call, printed: int) -> int:
    for role, text in call.transcript[printed:]:
        who = "SELLER" if role == "seller" else "DISHA "
        print(f"  {who}: {text.strip()}", flush=True)
    return len(call.transcript)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://localhost:8080/ws/call")
    parser.add_argument("--mode", default="inbound", choices=["inbound", "outbound"])
    parser.add_argument("--lang", default="en", choices=["en", "hi"], help="UI language and seller script")
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT"))
    parser.add_argument("--location", default=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"))
    parser.add_argument("--tts-model", default=os.getenv("LIVE_MODEL", "gemini-live-2.5-flash-native-audio"))
    parser.add_argument("--seller-voice", default="Puck")
    parser.add_argument("--save-audio", help="Write Disha's audio (24 kHz WAV) to this path")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    client = genai.Client(vertexai=True, project=args.project, location=args.location)
    print("Synthesising seller lines...", flush=True)
    script = SELLER_LINES_HI if args.lang == "hi" else SELLER_LINES
    lines_audio = [await synthesize(client, args.tts_model, line, args.seller_voice) for line in script]

    url = f"{args.url}?mode={args.mode}&lang={args.lang}"
    call = Call()
    queue: asyncio.Queue = asyncio.Queue()
    printed = 0
    started = time.monotonic()
    async with websockets.connect(url, max_size=None) as ws:
        recv_task = asyncio.create_task(receiver(ws, call, not args.quiet))
        mic_task = asyncio.create_task(mic(ws, queue, call))
        await wait_for_disha(call, since=started)  # greeting
        printed = print_new_lines(call, printed)
        for pcm in lines_audio:
            if call.closed or call.hangup:
                break
            finished_speaking = await say(queue, pcm, call)
            await wait_for_disha(call, since=finished_speaking)
            printed = print_new_lines(call, printed)
        # Allow time for the goodbye / hangup.
        deadline = time.monotonic() + 20
        while not call.hangup and not call.closed and time.monotonic() < deadline:
            await asyncio.sleep(0.2)
        printed = print_new_lines(call, printed)
        call.closed = True
        with contextlib.suppress(websockets.ConnectionClosed):
            await ws.send(json.dumps({"type": "end"}))
        mic_task.cancel()
        recv_task.cancel()

    if args.save_audio:
        with wave.open(args.save_audio, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24_000)
            wav.writeframes(bytes(call.audio_out))

    case = call.case or {}
    print("\n=== Tool calls:", ", ".join(call.tool_calls) or "none")
    print("=== Insights:", json.dumps(case.get("insights"), indent=1, ensure_ascii=False))
    print("=== Action plan:", json.dumps(case.get("action_plan"), indent=1, ensure_ascii=False))
    print("=== KPI targets:", case.get("kpi_targets"))
    print("=== Actions taken:", json.dumps(case.get("actions_taken"), indent=1, ensure_ascii=False))
    print("=== Follow-up:", case.get("follow_up"))
    print("=== Summary:", json.dumps(case.get("summary"), indent=1, ensure_ascii=False))
    print(
        f"=== Hangup: {call.hangup}   Duration: {time.monotonic() - started:.0f}s   "
        f"Disha audio: {len(call.audio_out) / 48000:.0f}s"
    )
    if call.latencies:
        lat = sorted(call.latencies)
        print(
            f"=== Response latency (end of seller speech -> first audio): "
            f"median {lat[len(lat) // 2]:.2f}s, min {lat[0]:.2f}s, max {lat[-1]:.2f}s, n={len(lat)}"
        )
    interruptions = sum(1 for e in call.events if e.get("type") == "interrupted")
    print(f"=== Interruptions: {interruptions}")

    checks = {
        "diagnosis_run": "analyze_sales_drop" in call.tool_calls,
        "action_plan_saved": bool(case.get("action_plan")),
        "summary_saved": bool(case.get("summary")),
    }
    print("=== Checks:", checks)
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
