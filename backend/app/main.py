from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="CyliaTales Backend", version="0.1.0")

class HealthResponse(BaseModel):
    status: str

@app.get("/health", response_model=HealthResponse)
async def health_check():
    return {"status": "ok"}

# Placeholder endpoint: create a new project (skeleton)
class CreateProjectRequest(BaseModel):
    name: str
    description: str | None = None

@app.post("/projects")
async def create_project(req: CreateProjectRequest):
    # TODO: implement project creation, character registry, and persistence
    return {"project_id": "proj_0001", "name": req.name}
