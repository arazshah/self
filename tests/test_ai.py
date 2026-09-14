import json

import httpx
import pytest

from app.ai import AIProviderError, AvalAIClient


@pytest.mark.asyncio
async def test_avalai_transcribes_and_extracts_structured_items():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/audio/transcriptions"):
            return httpx.Response(200, json={"text": "فردا قبض برق را پرداخت کنم"})
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output_text": json.dumps(
                    {
                        "items": [
                            {
                                "category": "finance",
                                "title": "پرداخت قبض برق",
                                "body": None,
                                "evidence": "قبض برق را پرداخت کنم",
                                "due_raw": "فردا",
                                "due_at": None,
                                "solar_date": None,
                                "confidence": 0.9,
                                "needs_confirmation": True,
                            }
                        ],
                        "clarification": None,
                        "reflection_summary": None,
                        "suggestion": None,
                    },
                    ensure_ascii=False,
                ),
            },
        )

    client = AvalAIClient(
        "key", "whisper-1", "text-model", transport=httpx.MockTransport(handler)
    )
    transcript = await client.transcribe(b"audio", "voice.ogg")
    result = await client.extract(transcript, "2026-09-14T08:00:00+00:00", "Asia/Tehran")
    await client.close()

    assert transcript == "فردا قبض برق را پرداخت کنم"
    assert result.items[0].category == "finance"
    assert len(calls) == 2
    extraction_request = calls[1]
    assert "due_raw" in extraction_request.content.decode()
    assert "due_at" in extraction_request.content.decode()
    assert "محاسبهٔ زمان" in extraction_request.content.decode()


@pytest.mark.asyncio
async def test_avalai_malformed_output_is_not_accepted():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/audio/transcriptions"):
            return httpx.Response(200, json={"text": "متن"})
        return httpx.Response(200, json={"status": "completed", "output_text": "bad"})

    client = AvalAIClient(
        "key", "whisper-1", "text-model", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(AIProviderError, match="ساختار"):
        await client.extract("متن", "2026-09-14T08:00:00+00:00", "Asia/Tehran")
    await client.close()


@pytest.mark.asyncio
async def test_avalai_non_object_output_is_rejected_safely():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    client = AvalAIClient(
        "key", "whisper-1", "text-model", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(AIProviderError, match="ساختار"):
        await client.extract("متن", "2026-09-14T08:00:00+00:00", "Asia/Tehran")
    await client.close()
