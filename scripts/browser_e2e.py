#!/usr/bin/env python3
"""Browser end-to-end test: drives the real UI in headless Chrome with a synthetic microphone.

Only getUserMedia is replaced (with a WebAudio stream this script controls); everything else
is the production code path: AudioWorklets, WebSocket, Gemini Live, playback, case file UI.

1. Opens the app, presses "Call Disha".
2. Speaks each seller line (synthesised speech, cached by e2e_voice_test.py) into the fake mic,
   waiting for Disha to finish speaking first, using the UI's own status like a person would.
3. Saves screenshots and fails if the case file didn't fill in.

Usage:
    python scripts/browser_e2e.py --url http://localhost:8080 --shots docs/img
Requires: pip install playwright (uses the system Chrome; no browser download needed).
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import os
import sys
import time
import wave
from pathlib import Path

from google import genai
from playwright.async_api import Page, async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from e2e_voice_test import SELLER_LINES, synthesize

FAKE_MIC = """
(() => {
  const ctx = new AudioContext({ sampleRate: 48000 });
  let dest = null;
  // Like a real microphone, every getUserMedia call gets a fresh stream (the app stops tracks on hang-up).
  navigator.mediaDevices.getUserMedia = async () => {
    await ctx.resume();
    dest = ctx.createMediaStreamDestination();
    return dest.stream;
  };
  window.__say = async (b64) => {
    const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    const buffer = await ctx.decodeAudioData(bytes.buffer);
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(dest);
    await new Promise((resolve) => { source.onended = resolve; source.start(); });
    return buffer.duration;
  };
})();
"""


FOLLOW_UP_LINES = [
    "Hi Disha, yes, good to hear from you. Go ahead.",
    "The spice rack supplier sent only half the order. The rest should come next week.",
    "Oh, I didn't notice the mugs. Yes, please add them to the restock list, "
    "and nominate the bestsellers for the sale.",
    "No, that's all. Thank you, Disha!",
]


def to_wav_b64(pcm16k: bytes) -> str:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16_000)
        wav.writeframes(pcm16k + bytes(16_000))  # + 0.5 s of trailing silence
    return base64.b64encode(buf.getvalue()).decode()


async def stage(page: Page) -> str:
    return await page.get_attribute("#stage", "data-state") or ""


async def call_active(page: Page) -> bool:
    return await page.is_visible("#end-btn")


async def transcript(page: Page) -> str:
    rows = await page.locator("#transcript-list li").all_text_contents()
    return "\n".join("  " + " ".join(r.split()) for r in rows)


async def wait_for_disha_turn(page: Page, timeout: float = 90) -> None:
    """Disha starts speaking, then the UI is back to 'listening' for 1.5 s (or the call ended)."""
    deadline = time.monotonic() + timeout
    spoke = False
    quiet_since = None
    while time.monotonic() < deadline:
        if not await call_active(page):
            return
        state = await stage(page)
        if state == "speaking":
            spoke, quiet_since = True, None
        elif spoke and state == "listening":
            quiet_since = quiet_since or time.monotonic()
            if time.monotonic() - quiet_since > 1.5:
                return
        await asyncio.sleep(0.15)
    raise TimeoutError(f"Disha did not finish her turn in time. Transcript so far:\n{await transcript(page)}")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8080")
    parser.add_argument("--mode", default="inbound", choices=["inbound", "outbound", "followup"])
    parser.add_argument("--shots", default=None, help="Directory for screenshots")
    parser.add_argument("--chrome", default=os.getenv("CHROME_PATH", "/usr/bin/google-chrome"))
    parser.add_argument("--tts-model", default=os.getenv("TTS_MODEL", "gemini-live-2.5-flash-native-audio"))
    parser.add_argument("--followup", action="store_true", help="Then fast-forward 7 days and take the follow-up call")
    parser.add_argument("--og-image", default=None, help="Also save a 1200x630 link-preview image here")
    args = parser.parse_args()

    client = genai.Client(
        vertexai=True,
        project=os.getenv("GOOGLE_CLOUD_PROJECT"),
        location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
    )
    lines = [to_wav_b64(await synthesize(client, args.tts_model, line, "Puck")) for line in SELLER_LINES]
    follow_lines = [to_wav_b64(await synthesize(client, args.tts_model, line, "Puck")) for line in FOLLOW_UP_LINES]
    shots = Path(args.shots) if args.shots else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            executable_path=args.chrome,
            args=["--autoplay-policy=no-user-gesture-required", "--use-fake-ui-for-media-stream"],
        )
        context = await browser.new_context(viewport={"width": 1440, "height": 1000}, device_scale_factor=2)
        await context.add_init_script(FAKE_MIC)
        page = await context.new_page()
        page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
        page.on(
            "console",
            lambda msg: errors.append(f"console.{msg.type}: {msg.text}") if msg.type == "error" else None,
        )

        await page.goto(args.url, wait_until="networkidle")
        await page.wait_for_selector("#metrics-table tbody tr")
        if shots:
            await page.screenshot(path=str(shots / "01-ready.jpg"), type="jpeg", quality=85)

        if args.mode != "inbound":
            await page.check(f'input[name="mode"][value="{args.mode}"]', force=True)
        if args.mode == "followup":
            lines, follow_lines, args.followup = follow_lines, [], False
        await page.click("#call-btn")
        await page.wait_for_selector("#end-btn", state="visible", timeout=15_000)
        await wait_for_disha_turn(page)
        print("greeting done", flush=True)

        for i, b64 in enumerate(lines):
            if not await call_active(page):
                break
            await page.evaluate("b64 => window.__say(b64)", b64)
            print(f"seller line {i + 1} spoken", flush=True)
            await wait_for_disha_turn(page)
            if shots and i == 3:
                await page.screenshot(path=str(shots / "02-mid-call.jpg"), type="jpeg", quality=85)
            if args.og_image and i == 3:
                await page.set_viewport_size({"width": 1200, "height": 630})
                await page.screenshot(path=args.og_image, type="jpeg", quality=80, scale="css")
                await page.set_viewport_size({"width": 1440, "height": 1000})

        deadline = time.monotonic() + 30
        while await call_active(page) and time.monotonic() < deadline:
            await asyncio.sleep(0.5)
        if await call_active(page):
            await page.click("#end-btn")
        await asyncio.sleep(1)
        if shots:
            await page.locator(".case-panel").screenshot(path=str(shots / "03-case-file.jpg"), type="jpeg", quality=85)
            await page.locator(".call-panel").screenshot(path=str(shots / "04-call-panel.jpg"), type="jpeg", quality=85)

        bubbles = await page.locator(".bubble-kam, .bubble-seller").count()
        final_transcript = await transcript(page)
        followup_checks = {}
        if args.followup:
            await page.wait_for_selector("#followup-btn", state="visible", timeout=10_000)
            await page.click("#followup-btn")
            await page.wait_for_selector("#end-btn", state="visible", timeout=15_000)
            await wait_for_disha_turn(page)
            print("follow-up greeting done", flush=True)
            for i, b64 in enumerate(follow_lines):
                if not await call_active(page):
                    break
                await page.evaluate("b64 => window.__say(b64)", b64)
                print(f"follow-up line {i + 1} spoken", flush=True)
                await wait_for_disha_turn(page)
            deadline = time.monotonic() + 30
            while await call_active(page) and time.monotonic() < deadline:
                await asyncio.sleep(0.5)
            if await call_active(page):
                await page.click("#end-btn")
            await asyncio.sleep(1)
            if shots:
                await page.locator(".case-panel").screenshot(
                    path=str(shots / "04-follow-up.jpg"), type="jpeg", quality=85
                )
            followup_checks = {
                "progress_card_filled": await page.locator("#card-progress.filled").count() == 1,
                "followup_summary_visible": await page.is_visible("#card-summary"),
            }
        checks = {
            "diagnosis_or_progress_filled": await page.locator("#card-diagnosis.filled, #card-progress.filled").count()
            == 1,
            "plan_card_filled": await page.locator("#card-plan.filled").count() == 1,
            "actions_card_filled": await page.locator("#card-actions.filled").count() == 1,
            "summary_visible": await page.is_visible("#card-summary"),
            "transcript_turns>=6": bubbles >= 6,
            "status": await page.text_content("#status-label"),
            **followup_checks,
        }
        await browser.close()

    print("Checks:", checks)
    print("Final transcript:\n" + final_transcript)
    if errors:
        print("Browser errors:", *errors, sep="\n  ")
    ok = all(v for k, v in checks.items() if k != "status") and not any("pageerror" in e for e in errors)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
