from pathlib import Path
import re
from io import BytesIO

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pypdf import PdfReader

app = FastAPI(title="Smart Notes AI", version="0.2.0")
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

class NotesRequest(BaseModel):
    text: str = Field(min_length=20)

class SummaryResponse(BaseModel):
    summary: str
    key_points: list[str]

def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]

def summarize_notes(text: str) -> SummaryResponse:
    sentences = split_sentences(text)
    if not sentences:
        raise ValueError("No readable sentences found.")
    scored = sorted(enumerate(sentences), key=lambda item: len(set(re.findall(r"\w+", item[1].lower()))), reverse=True)
    chosen = sorted(i for i, _ in scored[:min(3, len(scored))])
    return SummaryResponse(
        summary=" ".join(sentences[i] for i in chosen),
        key_points=[sentence for _, sentence in scored[:min(5, len(scored))]],
    )

@app.get("/")
def home():
    return FileResponse(STATIC_DIR / "index.html")

@app.post("/summarize", response_model=SummaryResponse)
def summarize(request: NotesRequest):
    try:
        return summarize_notes(request.text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@app.post("/upload", response_model=SummaryResponse)
async def upload(file: UploadFile = File(...)):
    name = (file.filename or "").lower()
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File must be 10 MB or smaller.")
    try:
        if name.endswith(".pdf"):
            reader = PdfReader(BytesIO(data))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        elif name.endswith(".txt"):
            text = data.decode("utf-8")
        else:
            raise HTTPException(status_code=415, detail="Upload a PDF or TXT file.")
        if len(text.strip()) < 20:
            raise HTTPException(status_code=400, detail="Not enough readable text found.")
        return summarize_notes(text)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Could not read this file.") from exc
