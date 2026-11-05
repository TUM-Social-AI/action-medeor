"""Translation is opt-in, persisted, and reused only for the same source name."""

from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from app.api.routes import translate_request_item
from app.db.models import RequestItemRow
from app.parsing import item_translation
from app.parsing.llm_client import LlmUnavailable


@pytest.mark.asyncio
async def test_translation_saved_and_reused(monkeypatch):
    item = RequestItemRow(id=1, request_id="request", name="Sterile needle 21G")
    session = AsyncMock()
    session.scalar.return_value = item
    translate = Mock(return_value="Sterile Nadel 21G")
    monkeypatch.setattr(item_translation, "translate_item_name", translate)

    assert await translate_request_item("request", 1, session) == {
        "translation": "Sterile Nadel 21G"
    }
    assert item.german_translation == {
        "source": "Sterile needle 21G", "text": "Sterile Nadel 21G"
    }
    session.commit.assert_awaited_once()
    await translate_request_item("request", 1, session)
    translate.assert_called_once_with("Sterile needle 21G")

    item.name = "Sterile needle 18G"
    translate.return_value = "Sterile Nadel 18G"
    assert await translate_request_item("request", 1, session) == {
        "translation": "Sterile Nadel 18G"
    }
    assert translate.call_count == 2


@pytest.mark.asyncio
async def test_missing_item_and_provider_failure(monkeypatch):
    session = AsyncMock()
    session.scalar.return_value = None
    with pytest.raises(HTTPException) as missing:
        await translate_request_item("wrong-request", 1, session)
    assert missing.value.status_code == 404
    statement = session.scalar.call_args.args[0]
    assert statement.compile().params == {"id_1": 1, "request_id_1": "wrong-request"}
    assert statement._for_update_arg is not None

    item = RequestItemRow(id=1, request_id="request", name="Needle")
    session.scalar.return_value = item
    monkeypatch.setattr(item_translation, "translate_item_name", Mock(side_effect=LlmUnavailable()))
    with pytest.raises(HTTPException) as unavailable:
        await translate_request_item("request", 1, session)
    assert unavailable.value.status_code == 503
    session.commit.assert_not_awaited()
    assert item.german_translation is None


def test_translation_preserves_details_and_rejects_empty_response(monkeypatch):
    llm = Mock(return_value=item_translation.ItemTranslation(translation=" Nadel 21G "))
    monkeypatch.setattr(item_translation, "call_llm", llm)
    assert item_translation.translate_item_name("Needle 21G") == "Nadel 21G"
    assert '"Needle 21G"' in llm.call_args.args[0]
    assert "German" in llm.call_args.args[0]
    llm.return_value = item_translation.ItemTranslation(translation="  ")
    with pytest.raises(LlmUnavailable):
        item_translation.translate_item_name("Needle 21G")
