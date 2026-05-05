# Telegram A2A Multi-User Gateway Plan

## Objective
Design a scalable, multi-tenant Telegram Gateway that acts as a unified entry point for the user and their family. The gateway will use a **Supervisor/Orchestrator Agent** and an **Agent-to-Agent (A2A)** protocol to route, coordinate, and fulfill complex queries across specialized backend agents (Coach, Weather, Finance, etc.).

## Background & Motivation
The user wants to deploy a Telegram bot that serves multiple users (e.g., the user and their wife) without duplicating backend deployments. Additionally, queries may span multiple domains (e.g., "How will the weather affect my run tomorrow?"), requiring dynamic coordination between specialized AI agents. The architecture must be "future-proof", supporting natural chat features, rich media, and a standardized (but not over-engineered) integration pattern for new agents.

## Architecture

### 1. Telegram Gateway (The Client)
- **Role:** A lightweight Python microservice built on `python-telegram-bot` or `aiogram`.
- **Multi-User Mapping:** Maintains a configuration mapping Telegram `user_id`s to internal platform `user_id`s (e.g., `123456789 -> fsirio`). Unauthorized Telegram IDs are ignored.
- **Future-Proof Client Features:**
  - **Streaming UX:** Consumes the existing Server-Sent Events (SSE) stream from the main API. It sends an initial "thinking..." message and uses `editMessageText` to stream the response back to the user in chunks, avoiding long loading silences.
  - **Multi-Modal Intake:** Natively intercepts Telegram Voice Notes and Images. Voice notes are transcribed to text (via a lightweight transcription service) before forwarding to the API.
- **Action:** Forwards the user's natural language message, media context, and a `thread_id` (Telegram Chat ID) to the Supervisor Agent via HTTP POST, attaching the `X-User-ID` header.

### 2. Supervisor Agent (The Orchestrator)
- **Role:** The core router, planner, and memory manager. Built on LangGraph within the main API.
- **Stateful Memory (Threading):** Uses the incoming `thread_id` to retrieve past messages from a BigQuery/Postgres session store. This ensures the agent understands context (e.g., "Move *it* to tomorrow").
- **A2A Protocol (OpenAPI/Skills):** The Supervisor treats other specialized agents as standard tools. **Crucially, this system will NOT use MCP.** Instead, future agents will be integrated using either:
  1. Standard **OpenAPI specifications** that the Supervisor can dynamically read and invoke as REST tools.
  2. The existing **`SKILL.md` pattern**, where an agent's capabilities and prompts are defined in a modular Markdown file within the project.
- **Workflow:**
  1. Receives message + `X-User-ID` + `thread_id`.
  2. Retrieves conversation history.
  3. Analyzes intent and coordinates with sub-agents via standard HTTP/OpenAPI calls.
  4. Synthesizes responses and streams the final reply back to the Gateway.

### 3. Specialized Sub-Agents (The Experts)
- **Biometric Coach:** Existing agent. Reads `X-User-ID` to fetch the correct BigQuery profile and Garmin tokens.
- **Weather Agent:** A standalone API/Agent that checks forecasts.
- **Future Agents:** Deployed independently and registered via OpenAPI specs or Skills.

## Phased Implementation Plan

### Phase 1: The Dumb Gateway (Foundation)
- Create `telegram-gateway/` with `python-telegram-bot`.
- Implement simple text forwarding to the existing Biometric API, mapping `X-User-ID` for basic multi-user support.

### Phase 2: The Smart Gateway (UX & Media)
- Update the gateway to handle the SSE streaming endpoint (`/chat/stream`) for typing-like UX.
- Add voice note interception and transcription.

### Phase 3: Memory & Supervisor Orchestrator (A2A)
- Update the main API LangGraph to persist state using the `thread_id`.
- Create the `Supervisor` node.
- Abstract the Biometric Coach into an OpenAPI-compliant tool that the Supervisor calls, proving the A2A pattern.

## Verification
- Send a message from User A's Telegram and verify it retrieves User A's data.
- Test conversation continuity (e.g., User asks a follow-up question requiring context).
- Send a voice note and verify the transcribed text is handled correctly.
- Ensure streaming UX provides immediate feedback in the Telegram chat.