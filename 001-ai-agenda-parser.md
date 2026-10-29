# ADR 001: Integration of AI Agenda Parser via AWS Lambda Function URL

## Status
Accepted

## Context
Users require a fast way to pre-fill meeting details (title, time slot, list of participants, description) from raw unstructured text such as emails or notes. To address this, an AI model (via Bedrock Mantle / Claude) is used to extract information and return a structured JSON response.

## Decision
1. **Lambda Function URL + Auth NONE (Cognito Bearer Verification):**
   - The AI parser is deployed as a standalone AWS Lambda function with a dedicated Function URL.
   - Requests are sent directly from the frontend (Next.js) to the Lambda Function URL, bypassing the main REST API backend.
   - Authentication is performed by validating the Cognito JWT (Bearer Token) directly within the Lambda/FastAPI application code.

2. **Build-time Environment Injection:**
   - The `NEXT_PUBLIC_AGENDA_PARSER_URL` environment variable is injected as a Docker build argument during the static export phase of Next.js in the Makefile and frontend Dockerfile.

3. **Error Isolation & Graceful Fallback:**
   - Authentication errors (401) from the AI service are isolated within `parseAgenda` and no longer trigger an automatic `signOut()`, preserving the user's active session in the main application.

## Consequences
- **Positive:**
  - Low latency due to direct client-to-Lambda communication.
  - Independent scaling and deployment of the AI service from the primary REST API.
  - Robust security via direct Cognito token validation.
- **Negative / Trade-offs:**
  - Requires explicit CORS configuration on the Lambda Function URL for the CloudFront domain.
  - The parser URL variable must be accurately provided during the frontend build step.
