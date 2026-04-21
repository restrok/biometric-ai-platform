from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(
    title="Biometric AI Platform API",
    description="Agentic RAG Backend for Biometric Data Analysis",
    version="0.1.0"
)

class HealthCheck(BaseModel):
    status: str
    version: str

@app.get("/health", response_model=HealthCheck, tags=["System"])
async def health_check():
    """
    Returns the current health status of the API.
    """
    return HealthCheck(status="ok", version="0.1.0")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
