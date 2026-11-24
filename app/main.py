from fastapi import FastAPI

app = FastAPI(title="Adrobot Keitaro tool")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
