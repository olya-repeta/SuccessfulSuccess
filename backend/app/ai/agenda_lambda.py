"""Lambda entry point for AI agenda parsing behind a Function URL."""

import base64
import json
import time
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import jwt

from app.ai.agenda import PROMPT_VERSION, AgendaParseError, parse_agenda
from app.auth import _parse_jwks
from app.config import settings

# Rates per 1,000,000 tokens in USD
MODEL_RATES = {
    "opus": {"input": 4.0 / 1_000_000, "output": 20.0 / 1_000_000},
    "haiku": {"input": 0.10 / 1_000_000, "output": 0.50 / 1_000_000},
}

_jwks_clients: dict[str, jwt.PyJWKClient] = {}


def calculate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate inference cost in USD from model token rates."""
    m = model.lower()
    if "haiku" in m:
        rates = MODEL_RATES["haiku"]
    else:
        # Default to Opus 5.5 rates
        rates = MODEL_RATES["opus"]

    cost = (input_tokens * rates["input"]) + (output_tokens * rates["output"])
    return round(cost, 6)


def get_jwks_url() -> str:
    """Return the Cognito user pool's JWKS URL."""
    return f"{settings.cognito_issuer}/.well-known/jwks.json"


def verify_cognito_jwt(token: str) -> dict[str, Any]:
    """Verify Cognito JWT against the JWKS URL or configured static JWKS."""
    if settings.cognito_jwks:
        doc = _parse_jwks(settings.cognito_jwks)
        jwk_set = jwt.PyJWKSet.from_dict(doc)
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        signing_key = None
        for k in jwk_set.keys:
            if k.key_id == kid:
                signing_key = k
                break
        if not signing_key:
            raise ValueError(f"Key ID {kid} not found in JWKS")
        key = signing_key.key
    else:
        jwks_url = get_jwks_url()
        if jwks_url not in _jwks_clients:
            _jwks_clients[jwks_url] = jwt.PyJWKClient(jwks_url)
        client = _jwks_clients[jwks_url]
        signing_key = client.get_signing_key_from_jwt(token)
        key = signing_key.key

    claims = jwt.decode(
        token,
        key,
        algorithms=["RS256"],
        options={"verify_exp": True, "require": ["exp", "sub"]},
    )
    return claims


def _extract_bearer_token(headers: dict[str, str] | None) -> str | None:
    if not headers:
        return None
    for k, v in headers.items():
        if k.lower() == "authorization":
            parts = v.strip().split()
            if len(parts) == 2 and parts[0].lower() == "bearer":
                return parts[1]
            if len(parts) == 1:
                return parts[0]
            return None
    return None


def _response(status_code: int, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
        },
        "body": json.dumps(data),
    }


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    # Handle CORS preflight if reached
    method = (
        event.get("requestContext", {}).get("http", {}).get("method")
        or event.get("httpMethod")
        or ""
    ).upper()
    if method == "OPTIONS":
        return {
            "statusCode": 204,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Authorization, Content-Type",
            },
            "body": "",
        }

    # 1. Inspect Authorization header and verify Cognito JWT
    headers = event.get("headers") or {}
    token = _extract_bearer_token(headers)
    if not token:
        return _response(401, {"detail": "Missing or invalid Authorization header"})

    try:
        claims = verify_cognito_jwt(token)
    except Exception as exc:
        return _response(401, {"detail": f"Unauthorized: {exc}"})

    user_sub = claims.get("sub", "")

    # 2. Parse body and check character limit
    raw_body = event.get("body")
    if event.get("isBase64Encoded") and isinstance(raw_body, str):
        try:
            raw_body = base64.b64decode(raw_body).decode("utf-8")
        except Exception:
            return _response(400, {"detail": "Invalid base64 encoding"})

    if isinstance(raw_body, dict):
        payload = raw_body
    elif isinstance(raw_body, str):
        try:
            payload = json.loads(raw_body)
        except Exception:
            return _response(400, {"detail": "Invalid JSON in request body"})
    else:
        return _response(400, {"detail": "Missing request body"})

    text = payload.get("text")
    if not isinstance(text, str):
        return _response(400, {"detail": "Field 'text' is required and must be a string"})

    if len(text) > 10000:
        return _response(413, {"detail": "Input text exceeds 10,000 characters"})

    # 3. Extract text, today, and tz
    tz_str = payload.get("tz") or settings.app_timezone
    today_val = payload.get("today")
    if today_val:
        try:
            today_date = date.fromisoformat(today_val)
        except Exception:
            return _response(400, {"detail": "Invalid 'today' date, expected YYYY-MM-DD"})
    else:
        try:
            tz_info = ZoneInfo(tz_str)
        except Exception:
            tz_info = UTC
        today_date = datetime.now(tz_info).date()

    # 4. Call parse_agenda
    start_time = time.perf_counter()
    try:
        parsed, usage = parse_agenda(text=text, today=today_date, tz=tz_str)
    except AgendaParseError as exc:
        return _response(422, {"detail": str(exc)})
    latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

    # 5. Calculate cost in USD
    model = settings.parser_model
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    cost_usd = calculate_cost_usd(model, input_tokens, output_tokens)

    # 6. Emit single-line CloudWatch JSON log
    log_entry = {
        "event": "agenda_parsed",
        "sub": user_sub,
        "user_sub": user_sub,
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "latency_ms": latency_ms,
        "cost_usd": cost_usd,
    }
    print(json.dumps(log_entry))

    # 7. Return 200 with JSON payload
    return _response(
        200,
        {
            "agenda": parsed.model_dump(mode="json"),
            "model": model,
            "prompt_version": PROMPT_VERSION,
        },
    )
