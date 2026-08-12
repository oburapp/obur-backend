"""Response schema for the health check endpoint."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Health check result, including real dependency connectivity."""

    status: str
    database: bool
    redis: bool
