import uvicorn
from fastapi import FastAPI

from app.api.health import router as health_router
from app.config import settings

app = FastAPI(title="Luna AI Service")

app.include_router(health_router)

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.server_port,
        reload=True,
        log_level=settings.log_level.lower()
    )
