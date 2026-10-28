"""Send a single-turn test message to Claude Opus 5.5 (or configured model) via Bedrock Mantle.

Usage:
    python -m app.llm_hello [--model <model_id>]
"""

import argparse
import sys
from pathlib import Path

import anthropic

from app.config import settings

# Allow running directly as a script without -m
if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def send_hello(model: str | None = None) -> anthropic.types.Message:
    selected_model = model or settings.parser_model

    create_kwargs: dict = {
        "model": selected_model,
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": "In one sentence: what is an ISO week?"}],
        "output_config": {"effort": "low"},
    }

    if selected_model.startswith(("us.", "global.")):
        client = anthropic.AnthropicBedrock(aws_region="us-east-1")
        create_kwargs["extra_body"] = {"anthropic_version": "bedrock-2023-05-31"}
        try:
            response = client.messages.create(**create_kwargs)
        except anthropic.BadRequestError as err:
            if "output_config" in str(err) or "effort" in str(err):
                create_kwargs.pop("output_config", None)
                response = client.messages.create(**create_kwargs)
            else:
                raise
    else:
        client = anthropic.AnthropicBedrockMantle(aws_region="us-east-1")
        try:
            response = client.messages.create(**create_kwargs)
        except anthropic.PermissionDeniedError as exc:
            fallback_model = "us.anthropic.claude-opus-4-6-v1"
            print(
                f"Note: Bedrock Mantle returned 403 for '{selected_model}':\n"
                f"  {exc.message}\n"
                f"Falling back to available Bedrock model '{fallback_model}'...\n"
            )
            fallback_client = anthropic.AnthropicBedrock(aws_region="us-east-1")
            response = fallback_client.messages.create(
                model=fallback_model,
                max_tokens=1024,
                messages=[{"role": "user", "content": "In one sentence: what is an ISO week?"}],
                output_config={"effort": "low"},
                extra_body={"anthropic_version": "bedrock-2023-05-31"},
            )

    text = "".join(block.text for block in response.content if hasattr(block, "text"))

    print("Response text:")
    print(text)
    print(f"stop_reason: {response.stop_reason}")
    print(
        f"usage: input_tokens={response.usage.input_tokens}, "
        f"output_tokens={response.usage.output_tokens}"
    )
    return response


def main() -> None:
    parser = argparse.ArgumentParser(description="Test LLM connection to Bedrock Mantle")
    parser.add_argument(
        "--model",
        default=None,
        help="Model ID to invoke (defaults to settings.parser_model)",
    )
    args = parser.parse_args()
    send_hello(model=args.model)


if __name__ == "__main__":
    main()
