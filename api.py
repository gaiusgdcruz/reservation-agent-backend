from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from db import db
import uvicorn

app = FastAPI(title="Marriot Kochi Analytics API")

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your Vercel URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/analytics/summaries")
async def get_summaries():
    """Fetch all call summaries and usage data."""
    try:
        summaries = await db.get_all_summaries()
        return {"status": "success", "data": summaries}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
