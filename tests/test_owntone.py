from __future__ import annotations

from collections import deque

import pytest
import requests

from needledrop.owntone import (
    OwnToneApiError,
    OwnToneClient,
    OwnToneConnectionError,
    OwnToneSpeakerNotFound,
)


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


class FakeSession:
    def __init__(self, get_responses):
        self.get_responses = deque(get_responses)
        self.get_calls = []
        self.put_calls = []

    def get(self, url, json=None, timeout=None):
        self.get_calls.append((url, json, timeout))
        if not self.get_responses:
            raise AssertionError("unexpected GET request")
        response = self.get_responses.popleft()
        if isinstance(response, Exception):
            raise response
        return response

    def put(self, url, json=None, timeout=None):
        self.put_calls.append((url, json, timeout))
        return FakeResponse({})


def test_selects_matching_output_and_sets_requested_volume():
    session = FakeSession(
        [
            FakeResponse(
                {
                    "outputs": [
                        {"id": "12", "name": "Office"},
                        {"id": "17", "name": "HomePod"},
                    ]
                }
            )
        ]
    )
    client = OwnToneClient(session=session)

    output_id = client.select_speaker_and_set_volume(
        "HomePod", start_volume=42, max_attempts=1, poll_interval_s=0
    )

    assert output_id == "17"
    assert session.put_calls == [
        (
            "http://127.0.0.1:3689/api/outputs/17",
            {"selected": True, "volume": 42},
            10.0,
        ),
    ]


def test_retries_until_speaker_appears(monkeypatch):
    session = FakeSession(
        [
            FakeResponse({"outputs": [{"id": "2", "name": "Kitchen"}]}),
            FakeResponse({"outputs": [{"id": "9", "name": "HomePod"}]}),
        ]
    )
    client = OwnToneClient(session=session)
    monkeypatch.setattr("needledrop.owntone.time.sleep", lambda _seconds: None)

    output_id = client.select_speaker_and_set_volume(
        "HomePod", start_volume=55, max_attempts=3, poll_interval_s=0.001
    )

    assert output_id == "9"
    assert len(session.get_calls) == 2


def test_speaker_match_is_case_sensitive():
    session = FakeSession([FakeResponse({"outputs": [{"id": "7", "name": "homepod"}]})])
    client = OwnToneClient(session=session)

    with pytest.raises(OwnToneSpeakerNotFound, match="HomePod"):
        client.select_speaker_and_set_volume(
            "HomePod", start_volume=20, max_attempts=1, poll_interval_s=0
        )


def test_uses_default_start_volume_when_config_value_is_none():
    session = FakeSession([FakeResponse({"outputs": [{"id": "7", "name": "HomePod"}]})])
    client = OwnToneClient(session=session)

    client.select_speaker_and_set_volume(
        "HomePod",
        start_volume=None,
        default_start_volume=30,
        max_attempts=1,
        poll_interval_s=0,
    )

    assert session.put_calls[0] == (
        "http://127.0.0.1:3689/api/outputs/7",
        {"selected": True, "volume": 30},
        10.0,
    )


def test_timeout_raises_connection_error():
    session = FakeSession([requests.Timeout("timed out")])
    client = OwnToneClient(session=session)

    with pytest.raises(OwnToneConnectionError, match="OwnTone request failed"):
        client.select_speaker_and_set_volume(
            "HomePod", start_volume=30, max_attempts=1, poll_interval_s=0
        )


def test_http_error_raises_api_error():
    session = FakeSession([FakeResponse({"outputs": []}, status_code=503)])
    client = OwnToneClient(session=session)

    with pytest.raises(OwnToneApiError, match="OwnTone returned HTTP error"):
        client.select_speaker_and_set_volume(
            "HomePod", start_volume=30, max_attempts=1, poll_interval_s=0
        )


def test_deselect_speaker_sets_selected_false():
    session = FakeSession(
        [FakeResponse({"outputs": [{"id": "17", "name": "HomePod"}]})]
    )
    client = OwnToneClient(session=session)

    output_id = client.deselect_speaker("HomePod")

    assert output_id == "17"
    assert session.put_calls == [
        ("http://127.0.0.1:3689/api/outputs/17", {"selected": False}, 10.0),
    ]


def test_deselect_speaker_returns_none_when_not_found():
    session = FakeSession([FakeResponse({"outputs": [{"id": "2", "name": "Kitchen"}]})])
    client = OwnToneClient(session=session)

    assert client.deselect_speaker("HomePod") is None
    assert session.put_calls == []
