from fastapi import APIRouter, FastAPI

app = FastAPI()
router = APIRouter()


@app.post("/api/chat")
async def chat_endpoint(payload: dict):
    return await run_chat(payload)


@router.get("/api/session/{session_id}")
def read_session(session_id: str):
    return load_session(session_id)


@app.route("/api/admin/reset", methods=["POST"])
def reset_admin_state():
    clear_state()
    return {"ok": True}


async def run_chat(payload: dict):
    return {"type": "chat", "payload": payload}


def load_session(session_id: str):
    return {"session_id": session_id}


def clear_state():
    return True


app.include_router(router)
