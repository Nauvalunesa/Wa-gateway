"""Run the Utusan gateway; application code lives in the gateway package."""
import uvicorn

from gateway.application import app


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8880, reload=False)
