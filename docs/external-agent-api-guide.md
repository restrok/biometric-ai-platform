# External Agent API Integration Guide

This guide provides instructions for external agentic frameworks (like OpenClaw, OpenDevin, or custom GPTs) to interact with the Biometric AI Platform via its REST API.

## 🚀 Overview
The platform exposes its internal biometric analysis, synchronization, and coaching tools as standard REST endpoints. This allows any external system to retrieve biometric data and perform high-precision physiological analysis without needing to handle Garmin authentication or complex Python dependencies.

## 🔐 Authentication & Base URL
- **Base URL:** `http://localhost:8000` (Default)
- **Authentication:** All requests must include your `GOOGLE_API_KEY` in the environment or as part of the configuration if the agent handles it. 
- **Self-Healing Auth:** You do **not** need to handle Garmin passwords. The API manages tokens internally and performs automatic refreshes.

## 🛠️ Available Tool Endpoints

All tool endpoints are prefixed with `/api/v1/tools`.

### 1. Retrieve Biometrics
**Endpoint:** `POST /api/v1/tools/biometric/retrieve`
**Payload:**
```json
{
  "project_id": "optional-gcp-project",
  "dataset": "optional-dataset-name",
  "limit": 20,
  "offset": 0,
  "activity_type": "running"
}
```
**Description:** Fetches activity history, sleep data, and telemetry. Supports pagination via `limit`/`offset` and filtering by `activity_type`.

### 2. Analyze Activity Efficiency
**Endpoint:** `POST /api/v1/tools/activity/analyze_efficiency`
**Payload:**
```json
{
  "activity_id": "22659217587"
}
```
**Description:** Calculates Aerobic Decoupling, Form Efficiency, and Oscillation Ratios for a specific activity.

### 3. Sync Biometric Data
**Endpoint:** `POST /api/v1/tools/biometric/sync`
**Payload:** `{}`
**Description:** Triggers a fresh synchronization from the provider (e.g., Garmin) to the Data Lake.

### 4. Upload Training Plan
**Endpoint:** `POST /api/v1/tools/training_plan/upload`
**Payload:**
```json
{
  "workouts": [
    {
      "name": "Z2 Sunday Base",
      "description": "75 mins at Aerobic Threshold",
      "duration": 75,
      "date": "2026-04-26",
      "steps": [
        {
          "type": "run",
          "duration": 75,
          "target": {
            "target_type": "heart.rate.zone",
            "min_target": 145,
            "max_target": 155
          }
        }
      ]
    }
  ]
}
```

### 5. Search Exercise Science
**Endpoint:** `POST /api/v1/tools/science/search`
**Payload:**
```json
{
  "query": "polarized training 80/20 rule"
}
```

### 6. Streaming Chat (Real-time)
**Endpoint:** `POST /chat/stream`
**Payload:** `{"message": "Analyze my month"}`
**Description:** Returns a Server-Sent Events (SSE) stream of tokens, tool calls, and tool results. Perfect for providing immediate feedback in UI applications.
**Stream Events:**
- `{"type": "token", "text": "..."}`: Real-time LLM response tokens.
- `{"type": "tool_start", "tool": "..."}`: Indicates the agent is starting a tool execution.
- `{"type": "tool_end", "tool": "...", "output": "..."}`: Returns the raw output of a tool.
- `[DONE]`: Final event in the stream.

## 📖 OpenAPI Documentation
The API provides an interactive Swagger UI for testing and full schema definitions:
👉 [http://localhost:8000/docs](http://localhost:8000/docs)

External agents can fetch the raw OpenAPI specification at:
👉 [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)

## 💡 Pro-Tip for Agents
When initializing, you can tell your agent:
> "You have access to a Biometric REST API. If you encounter a 401 error during a tool call, invoke the `POST /api/v1/tools/session/refresh` endpoint to rotate the Garmin tokens automatically before retrying."
