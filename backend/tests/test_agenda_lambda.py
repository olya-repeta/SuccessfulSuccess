"""Tests for the agenda Lambda function URL handler."""

import base64
import json
from datetime import date
from unittest.mock import patch

from app.ai.agenda import AgendaItem, AgendaParseError, ParsedAgenda
from app.ai.agenda_lambda import calculate_cost_usd, handler
from tests.tokens import KID, make_token


def test_calculate_cost_usd_opus():
    # Opus 5.5: $4/1M in, $20/1M out
    cost = calculate_cost_usd(
        model="anthropic.claude-opus-5-5",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    assert cost == 24.0

    cost_small = calculate_cost_usd(
        model="us.anthropic.claude-opus-4-6-v1",
        input_tokens=1_000,
        output_tokens=500,
    )
    # (1000 * 4e-6) + (500 * 20e-6) = 0.004 + 0.010 = 0.014
    assert cost_small == 0.014


def test_calculate_cost_usd_haiku():
    # Haiku 5.5: $0.10/1M in, $0.50/1M out
    cost = calculate_cost_usd(
        model="anthropic.claude-haiku-5-5",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    assert cost == 0.60

    cost_small = calculate_cost_usd(
        model="claude-3-5-haiku",
        input_tokens=10_000,
        output_tokens=2_000,
    )
    # (10000 * 0.1e-6) + (2000 * 0.5e-6) = 0.001 + 0.001 = 0.002
    assert cost_small == 0.002


def test_handler_options_preflight():
    event = {
        "requestContext": {"http": {"method": "OPTIONS"}},
    }
    res = handler(event)
    assert res["statusCode"] == 204
    assert res["headers"]["Access-Control-Allow-Methods"] == "POST, OPTIONS"


def test_handler_missing_auth():
    event = {
        "headers": {},
        "body": json.dumps({"text": "Hello"}),
    }
    res = handler(event)
    assert res["statusCode"] == 401
    assert "Missing or invalid Authorization header" in res["body"]


def test_handler_invalid_jwt():
    event = {
        "headers": {"authorization": "Bearer invalid.jwt.token"},
        "body": json.dumps({"text": "Hello"}),
    }
    res = handler(event)
    assert res["statusCode"] == 401
    assert "Unauthorized" in res["body"]


def test_handler_text_exceeds_10000_chars(private_key, monkeypatch):
    import jwt

    pub_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    jwks = {"keys": [pub_jwk | {"kid": KID, "alg": "RS256", "use": "sig"}]}
    monkeypatch.setattr("app.config.settings.cognito_jwks", json.dumps(jwks))

    token = make_token(private_key, sub="user-abc")
    long_text = "a" * 10001
    event = {
        "headers": {"Authorization": f"Bearer {token}"},
        "body": json.dumps({"text": long_text}),
    }

    res = handler(event)
    assert res["statusCode"] == 413
    assert "exceeds 10,000 characters" in res["body"]


def test_handler_missing_body_or_text(private_key, monkeypatch):
    import jwt

    pub_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    jwks = {"keys": [pub_jwk | {"kid": KID, "alg": "RS256", "use": "sig"}]}
    monkeypatch.setattr("app.config.settings.cognito_jwks", json.dumps(jwks))

    token = make_token(private_key)

    # Missing body
    res = handler({"headers": {"Authorization": f"Bearer {token}"}})
    assert res["statusCode"] == 400

    # Missing text field
    res = handler({"headers": {"Authorization": f"Bearer {token}"}, "body": json.dumps({})})
    assert res["statusCode"] == 400
    assert "Field 'text' is required" in res["body"]


def test_handler_agenda_parse_error(private_key, monkeypatch):
    import jwt

    pub_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    jwks = {"keys": [pub_jwk | {"kid": KID, "alg": "RS256", "use": "sig"}]}
    monkeypatch.setattr("app.config.settings.cognito_jwks", json.dumps(jwks))

    token = make_token(private_key, sub="user-error")
    event = {
        "headers": {"Authorization": f"Bearer {token}"},
        "body": json.dumps({"text": "Parse this text"}),
    }

    with patch(
        "app.ai.agenda_lambda.parse_agenda", side_effect=AgendaParseError("Model failed twice")
    ):
        res = handler(event)
        assert res["statusCode"] == 422
        body = json.loads(res["body"])
        assert "Model failed twice" in body["detail"]


def test_handler_success_and_cloudwatch_log(private_key, monkeypatch, capsys):
    import jwt

    pub_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    jwks = {"keys": [pub_jwk | {"kid": KID, "alg": "RS256", "use": "sig"}]}
    monkeypatch.setattr("app.config.settings.cognito_jwks", json.dumps(jwks))
    monkeypatch.setattr("app.config.settings.parser_model", "anthropic.claude-opus-5-5")

    token = make_token(private_key, sub="user-success-789")

    mock_agenda = ParsedAgenda(
        title="Engineering Standup",
        items=[AgendaItem(topic="Blockers", owner="Alice", minutes=15)],
        language="English",
    )
    mock_usage = {"input_tokens": 1200, "output_tokens": 300}

    event = {
        "headers": {"Authorization": f"Bearer {token}"},
        "body": json.dumps(
            {
                "text": "Standup at 10am to discuss blockers with Alice for 15m.",
                "today": "2026-10-28",
                "tz": "UTC",
            }
        ),
    }

    with patch(
        "app.ai.agenda_lambda.parse_agenda", return_value=(mock_agenda, mock_usage)
    ) as mock_parse:
        res = handler(event)

        assert res["statusCode"] == 200
        data = json.loads(res["body"])
        assert data["model"] == "anthropic.claude-opus-5-5"
        assert data["prompt_version"] == "agenda-v1"
        assert data["agenda"]["title"] == "Engineering Standup"
        assert len(data["agenda"]["items"]) == 1
        assert data["agenda"]["items"][0]["topic"] == "Blockers"

        mock_parse.assert_called_once_with(
            text="Standup at 10am to discuss blockers with Alice for 15m.",
            today=date(2026, 10, 28),
            tz="UTC",
        )

    # Check CloudWatch log emission
    captured = capsys.readouterr().out
    lines = [line.strip() for line in captured.splitlines() if line.strip().startswith("{")]
    assert len(lines) >= 1
    log_data = json.loads(lines[-1])
    assert log_data["event"] == "agenda_parsed"
    assert log_data["sub"] == "user-success-789"
    assert log_data["model"] == "anthropic.claude-opus-5-5"
    assert log_data["prompt_version"] == "agenda-v1"
    assert log_data["input_tokens"] == 1200
    assert log_data["output_tokens"] == 300
    assert "latency_ms" in log_data
    # (1200 * 4e-6) + (300 * 20e-6) = 0.0048 + 0.0060 = 0.0108
    assert log_data["cost_usd"] == 0.0108


def test_handler_base64_encoded_body(private_key, monkeypatch):
    import jwt

    pub_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    jwks = {"keys": [pub_jwk | {"kid": KID, "alg": "RS256", "use": "sig"}]}
    monkeypatch.setattr("app.config.settings.cognito_jwks", json.dumps(jwks))

    token = make_token(private_key, sub="user-b64")
    body_str = json.dumps({"text": "Discussion text"})
    b64_body = base64.b64encode(body_str.encode("utf-8")).decode("utf-8")

    event = {
        "headers": {"authorization": f"Bearer {token}"},
        "isBase64Encoded": True,
        "body": b64_body,
    }

    mock_agenda = ParsedAgenda(
        title="Sync",
        items=[AgendaItem(topic="General")],
        language="en",
    )
    mock_usage = {"input_tokens": 100, "output_tokens": 50}

    with patch("app.ai.agenda_lambda.parse_agenda", return_value=(mock_agenda, mock_usage)):
        res = handler(event)
        assert res["statusCode"] == 200
        data = json.loads(res["body"])
        assert data["agenda"]["title"] == "Sync"
