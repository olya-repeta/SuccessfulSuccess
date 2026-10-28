from unittest.mock import MagicMock, patch

from app.config import Settings
from app.llm_hello import send_hello


def test_settings_parser_model_default(monkeypatch):
    monkeypatch.delenv("PARSER_MODEL", raising=False)
    monkeypatch.delenv("parser_model", raising=False)
    # Instantiate without reading .env overrides
    s = Settings(_env_file=None)
    assert s.parser_model == "anthropic.claude-opus-5-5"
    assert s.PARSER_MODEL == "anthropic.claude-opus-5-5"


def test_settings_parser_model_env_override(monkeypatch):
    monkeypatch.setenv("PARSER_MODEL", "custom-opus-model")
    s = Settings(_env_file=None)
    assert s.parser_model == "custom-opus-model"
    assert s.PARSER_MODEL == "custom-opus-model"


def test_send_hello(capsys):
    mock_client = MagicMock()
    mock_block = MagicMock()
    mock_block.text = "An ISO week is a 7-day week beginning on Monday and ending on Sunday."
    mock_usage = MagicMock()
    mock_usage.input_tokens = 15
    mock_usage.output_tokens = 22

    mock_response = MagicMock()
    mock_response.content = [mock_block]
    mock_response.stop_reason = "end_turn"
    mock_response.usage = mock_usage
    mock_client.messages.create.return_value = mock_response

    with patch("anthropic.AnthropicBedrockMantle", return_value=mock_client) as mock_init:
        res = send_hello(model="anthropic.claude-opus-5-5")

        mock_init.assert_called_once_with(aws_region="us-east-1")
        mock_client.messages.create.assert_called_once_with(
            model="anthropic.claude-opus-5-5",
            max_tokens=1024,
            messages=[{"role": "user", "content": "In one sentence: what is an ISO week?"}],
            output_config={"effort": "low"},
        )
        assert res == mock_response

    captured = capsys.readouterr().out
    assert "An ISO week is a 7-day week beginning on Monday and ending on Sunday." in captured
    assert "stop_reason: end_turn" in captured
    assert "input_tokens=15" in captured
    assert "output_tokens=22" in captured


def test_send_hello_permission_denied_fallback(capsys):
    mantle_client = MagicMock()
    # Simulate 403 PermissionDeniedError from Mantle
    import anthropic
    import httpx

    request = httpx.Request(
        "POST", "https://bedrock-mantle.us-east-1.api.aws/anthropic/v1/messages"
    )
    response_403 = httpx.Response(
        403,
        request=request,
        json={
            "type": "error",
            "error": {
                "type": "permission_error",
                "message": "anthropic.claude-opus-5-5 is not available for this account.",
            },
        },
    )
    mantle_client.messages.create.side_effect = anthropic.PermissionDeniedError(
        message="anthropic.claude-opus-5-5 is not available for this account.",
        response=response_403,
        body=response_403.json(),
    )

    bedrock_client = MagicMock()
    mock_block = MagicMock()
    mock_block.text = "Fallback ISO week answer."
    mock_usage = MagicMock()
    mock_usage.input_tokens = 10
    mock_usage.output_tokens = 20
    mock_response = MagicMock()
    mock_response.content = [mock_block]
    mock_response.stop_reason = "end_turn"
    mock_response.usage = mock_usage
    bedrock_client.messages.create.return_value = mock_response

    with (
        patch("anthropic.AnthropicBedrockMantle", return_value=mantle_client),
        patch("anthropic.AnthropicBedrock", return_value=bedrock_client) as mock_bedrock_init,
    ):
        res = send_hello(model="anthropic.claude-opus-5-5")

        mock_bedrock_init.assert_called_once_with(aws_region="us-east-1")
        bedrock_client.messages.create.assert_called_once_with(
            model="us.anthropic.claude-opus-4-6-v1",
            max_tokens=1024,
            messages=[{"role": "user", "content": "In one sentence: what is an ISO week?"}],
            output_config={"effort": "low"},
            extra_body={"anthropic_version": "bedrock-2023-05-31"},
        )
        assert res == mock_response

    captured = capsys.readouterr().out
    assert "Falling back to available Bedrock model" in captured
    assert "Fallback ISO week answer." in captured


def test_send_hello_inference_profile_direct():
    bedrock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="ISO week direct")]
    mock_response.stop_reason = "end_turn"
    mock_response.usage = MagicMock(input_tokens=10, output_tokens=10)
    bedrock_client.messages.create.return_value = mock_response

    with patch("anthropic.AnthropicBedrock", return_value=bedrock_client) as mock_init:
        res = send_hello(model="us.anthropic.claude-opus-4-6-v1")
        mock_init.assert_called_once_with(aws_region="us-east-1")
        bedrock_client.messages.create.assert_called_once_with(
            model="us.anthropic.claude-opus-4-6-v1",
            max_tokens=1024,
            messages=[{"role": "user", "content": "In one sentence: what is an ISO week?"}],
            output_config={"effort": "low"},
            extra_body={"anthropic_version": "bedrock-2023-05-31"},
        )
        assert res == mock_response
