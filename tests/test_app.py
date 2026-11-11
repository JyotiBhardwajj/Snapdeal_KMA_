"""HTTP endpoints and the WebSocket <-> Live API bridge, using a fake Live session."""

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from google.genai import types
from starlette.websockets import WebSocketDisconnect

from app.config import Settings
from app.main import create_app


def make_settings(**overrides) -> Settings:
    base = dict(
        google_cloud_project="test-project",
        google_cloud_location="us-central1",
        gemini_api_key=None,
        live_model="fake-live-model",
        voice_name="Kore",
        temperature=None,
        vad_start_sensitivity=None,
        vad_end_sensitivity=None,
        vad_silence_ms=None,
        max_call_seconds=120,
        max_concurrent_calls=2,
        allowed_origins=(),
        log_level="WARNING",
    )
    base.update(overrides)
    return Settings(**base)


class FakeSession:
    """Mimics google.genai AsyncSession: receive() yields one model turn per call."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.client_content = []
        self.audio_chunks = 0
        self.stream_ends = 0
        self.tool_responses = []

    async def send_client_content(self, turns=None, turn_complete=True):
        self.client_content.append(turns)

    async def send_realtime_input(self, audio=None, audio_stream_end=None, **_):
        if audio is not None:
            self.audio_chunks += 1
        if audio_stream_end:
            self.stream_ends += 1

    async def send_tool_response(self, function_responses):
        self.tool_responses.extend(function_responses)

    async def receive(self):
        if self.turns:
            for message in self.turns.pop(0):
                yield message
        else:
            await asyncio.sleep(3600)  # like a quiet live session
            yield types.LiveServerMessage()


class FakeClient:
    def __init__(self, session):
        self.session = session
        self.connected_with = None

        @asynccontextmanager
        async def connect(model, config):
            self.connected_with = (model, config)
            yield session

        self.aio = SimpleNamespace(live=SimpleNamespace(connect=connect))


def audio_message(data=b"\x01\x00" * 100, text=None):
    return types.LiveServerMessage(
        server_content=types.LiveServerContent(
            model_turn=types.Content(
                parts=[types.Part(inline_data=types.Blob(data=data, mime_type="audio/pcm;rate=24000"))]
            ),
            output_transcription=types.Transcription(text=text) if text else None,
        )
    )


def tool_call_message(name, args=None, call_id="call-1"):
    return types.LiveServerMessage(
        tool_call=types.LiveServerToolCall(function_calls=[types.FunctionCall(id=call_id, name=name, args=args or {})])
    )


def turn_complete_message():
    return types.LiveServerMessage(server_content=types.LiveServerContent(turn_complete=True))


@pytest.fixture
def make_client():
    def _make(turns=(), **settings_overrides):
        session = FakeSession(turns)
        fake = FakeClient(session)
        app = create_app(settings=make_settings(**settings_overrides), genai_client=fake)
        return TestClient(app), session, fake, app

    return _make


def test_health_config_and_index(make_client):
    client, *_ = make_client()
    with client:
        assert client.get("/healthz").json()["status"] == "ok"
        config = client.get("/api/config").json()
        assert config["seller"]["business_name"] == "Gupta Home Essentials"
        assert config["metrics"][0]["this_month"] == 135_000
        index = client.get("/")
        assert index.status_code == 200 and "Disha" in index.text
        assert "default-src 'self'" in index.headers["content-security-policy"]
        assert index.headers["x-content-type-options"] == "nosniff"
        assert client.get("/static/js/app.js").status_code == 200


def test_cross_site_websocket_is_rejected(make_client):
    client, *_ = make_client()
    with (
        client,
        pytest.raises(WebSocketDisconnect) as exc,
        client.websocket_connect("/ws/call", headers={"origin": "https://evil.example"}) as ws,
    ):
        ws.receive_json()
    assert exc.value.code == 1008


def test_lines_busy_when_concurrency_cap_reached(make_client):
    client, _, _, app = make_client(max_concurrent_calls=1)
    app.state.active_calls = 1
    with client, client.websocket_connect("/ws/call") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error" and "busy" in msg["message"]


def test_full_call_turn_through_the_bridge(make_client):
    turns = [
        [audio_message(text="Namaste Rajesh"), tool_call_message("analyze_sales_drop")],
        [turn_complete_message()],
    ]
    client, session, fake, _ = make_client(turns)
    url = "/ws/call?mode=outbound&lang=hi"
    with client, client.websocket_connect(url, headers={"origin": "http://testserver"}) as ws:
        ready = ws.receive_json()
        assert ready["type"] == "ready" and ready["case"]["mode"] == "outbound"
        assert len(ws.receive_bytes()) == 200
        assert ws.receive_json() == {"type": "transcript", "role": "kam", "text": "Namaste Rajesh"}
        started = ws.receive_json()
        assert started == {"type": "tool_started", "name": "analyze_sales_drop", "label": "Analysing your sales data"}
        case = ws.receive_json()
        assert case["type"] == "case"
        assert case["case"]["diagnosis"]["drivers"][0]["verdict"] == "primary_driver"
        assert ws.receive_json()["type"] == "turn_complete"
        ws.send_bytes(b"\x00\x00" * 512)
        ws.send_text(json.dumps({"type": "mute", "muted": True}))
        ws.send_text(json.dumps({"type": "end"}))

    model, config = fake.connected_with
    assert model == "fake-live-model"
    assert config.response_modalities == [types.Modality.AUDIO]
    assert "HINDI" in config.system_instruction.parts[0].text
    assert "proactive outbound call" in session.client_content[0].parts[0].text
    assert session.tool_responses[0].name == "analyze_sales_drop"
    assert session.tool_responses[0].id == "call-1"
    assert session.audio_chunks == 1
    assert session.stream_ends == 1


def test_hangup_after_summary_and_goodbye(make_client):
    summary_args = {"key_issues": ["Stock-outs"], "recommendations": ["Restock"], "next_steps": ["Restock in 3 days"]}
    turns = [
        [tool_call_message("end_call_with_summary", summary_args)],
        [audio_message(text="Thank you, goodbye!"), turn_complete_message()],
    ]
    client, *_ = make_client(turns)
    with client, client.websocket_connect("/ws/call") as ws:
        seen = []
        while "hangup" not in seen:
            message = ws.receive()
            if message.get("text"):
                seen.append(json.loads(message["text"])["type"])
        assert seen.index("case") < seen.index("turn_complete") < seen.index("hangup")
        ws.send_text(json.dumps({"type": "end"}))


def test_follow_up_call_receives_previous_case(make_client):
    previous = {
        "case_id": "CASE-PREV01",
        "action_plan": [{"title": "Restock the water bottles"}],
        "kpi_targets": ["OOS <= 5"],
        "actions_taken": [{"action": "set_low_stock_alerts", "label": "Set low-stock alerts"}],
    }
    turns = [[tool_call_message("review_progress")], [turn_complete_message()]]
    client, session, fake, _ = make_client(turns)
    with client, client.websocket_connect("/ws/call?mode=followup") as ws:
        ws.send_text(json.dumps({"type": "start", "previous_case": previous}))
        ready = ws.receive_json()
        assert ready["case"]["mode"] == "followup" and ready["case"]["previous_case_id"] == "CASE-PREV01"
        assert ws.receive_json()["name"] == "review_progress"
        case = ws.receive_json()["case"]
        assert case["progress"]["kpis"][0]["status"] in {"met", "on_track", "behind", "off_track"}
        ws.send_text(json.dumps({"type": "end"}))

    _, config = fake.connected_with
    instruction = config.system_instruction.parts[0].text
    assert "Restock the water bottles" in instruction and "7-day follow-up" in instruction
    names = {d.name for d in config.tools[0].function_declarations}
    assert "review_progress" in names and "analyze_sales_drop" not in names
    assert "follow-up you booked" in session.client_content[0].parts[0].text


def test_follow_up_without_previous_case_uses_a_default(make_client):
    turns = [[turn_complete_message()]]
    client, _, fake, _ = make_client(turns)
    with client, client.websocket_connect("/ws/call?mode=followup") as ws:
        ws.send_text(json.dumps({"type": "start", "previous_case": None}))
        assert ws.receive_json()["type"] == "ready"
        ws.send_text(json.dumps({"type": "end"}))
    _, config = fake.connected_with
    assert "Restock the 4 out-of-stock bestsellers" in config.system_instruction.parts[0].text
