from fastapi import FastAPI
from .routes import router

app = FastAPI(title="Line-Ups Game API")
app.include_router(router, prefix="/api")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app.main:app", host="0.0.0.0", port=8000, reload=True)
