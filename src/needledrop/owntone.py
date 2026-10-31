"""OwnTone API client for selecting a speaker and setting startup volume."""

from __future__ import annotations

import time
from typing import Any

import requests


class OwnToneError(RuntimeError):
    """Base error for OwnTone control failures."""


class OwnToneConnectionError(OwnToneError):
    """Network-level failure talking to OwnTone."""


class OwnToneApiError(OwnToneError):
    """Unexpected or unsuccessful API response from OwnTone."""


class OwnToneSpeakerNotFound(OwnToneError):
    """Configured speaker was not found in OwnTone outputs."""


class OwnToneClient:
    """Small JSON API client for output selection and per-output volume."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:3689",
        timeout_s: float = 10.0,
        session: requests.Session | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._session = session or requests.Session()

    def select_speaker_and_set_volume(
        self,
        speaker_name: str,
        start_volume: int | None,
        *,
        default_start_volume: int = 30,
        poll_interval_s: float = 1.0,
        max_attempts: int | None = None,
    ) -> str:
        """Select ``speaker_name`` and set output volume.

        Matching is exact and case-sensitive. The lookup retries until the
        speaker appears, unless ``max_attempts`` is provided.
        """
        if max_attempts is not None and max_attempts < 1:
            raise ValueError("max_attempts must be >= 1 when provided")

        volume = default_start_volume if start_volume is None else start_volume
        self._validate_volume(volume)

        attempts = 0
        candidates: list[str] = []
        while True:
            attempts += 1
            output_id, candidates = self._find_output_id_by_name(speaker_name)
            if output_id is not None:
                self._set_output_selected(output_id, selected=True)
                self._set_output_volume(output_id, volume)
                return output_id

            if max_attempts is not None and attempts >= max_attempts:
                raise OwnToneSpeakerNotFound(
                    f"speaker {speaker_name!r} not found in OwnTone outputs "
                    f"(candidates: {', '.join(candidates) or 'none'})"
                )
            time.sleep(poll_interval_s)

    def _find_output_id_by_name(
        self, speaker_name: str
    ) -> tuple[str | None, list[str]]:
        outputs = self._list_outputs()
        candidates: list[str] = []
        for output in outputs:
            name = output.get("name")
            if isinstance(name, str):
                candidates.append(name)
            if name == speaker_name:
                output_id = output.get("id")
                if output_id is None:
                    raise OwnToneApiError(
                        f"output {speaker_name!r} has no usable 'id' field"
                    )
                return str(output_id), candidates
        return None, candidates

    def _list_outputs(self) -> list[dict[str, Any]]:
        response = self._request("get", "/api/outputs")
        try:
            payload = response.json()
        except ValueError as exc:
            raise OwnToneApiError(
                "OwnTone /api/outputs did not return valid JSON"
            ) from exc
        outputs = payload.get("outputs")
        if not isinstance(outputs, list):
            raise OwnToneApiError(
                "OwnTone /api/outputs response missing 'outputs' list"
            )
        if not all(isinstance(item, dict) for item in outputs):
            raise OwnToneApiError(
                "OwnTone /api/outputs returned invalid output entries"
            )
        return outputs

    def _set_output_selected(self, output_id: str, *, selected: bool) -> None:
        selected_value = "true" if selected else "false"
        self._request(
            "put",
            f"/api/outputs/{output_id}",
            params={"selected": selected_value},
        )

    def _set_output_volume(self, output_id: str, volume: int) -> None:
        self._validate_volume(volume)
        self._request(
            "put",
            f"/api/outputs/{output_id}/volume",
            params={"volume": volume},
        )

    def _request(
        self, method: str, path: str, params: dict[str, str | int] | None = None
    ) -> requests.Response:
        url = f"{self._base_url}{path}"
        requester = getattr(self._session, method)
        try:
            response = requester(url, params=params, timeout=self._timeout_s)
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise OwnToneApiError(
                f"OwnTone returned HTTP error ({method.upper()} {path}): {exc}"
            ) from exc
        except requests.RequestException as exc:
            raise OwnToneConnectionError(
                f"OwnTone request failed ({method.upper()} {path}): {exc}"
            ) from exc
        return response

    @staticmethod
    def _validate_volume(volume: int) -> None:
        if not 0 <= volume <= 100:
            raise ValueError("volume must be between 0 and 100")
