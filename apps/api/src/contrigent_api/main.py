from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI

from contrigent_api.routes.run_routes import router as runs_router


app = FastAPI(
    title="Contrigent API",
    description="Backend API for the Contrigent AI software engineering agent.",
    version="0.1.0",
)

app.include_router(runs_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "contrigent-api",
    }