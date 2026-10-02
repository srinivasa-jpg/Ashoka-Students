from pathlib import Path
import re
from collections import Counter
from io import BytesIO

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pypdf import PdfReader

app = FastAPI(title="Smart Notes AI", version="3.1.0")
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

STOP = set("""the a an and or but if then than to of in on at for from with by as is are was were be been being this that these those it its into about over under between through during can could should would may might will do does did has have had not no so such their there they them he she we you your our i which who what when where how""".split())

class NotesRequest(BaseModel):
    text: str = Field(min_length=20)

class Term(BaseModel):
    term: str
    definition: str

class Flashcard(BaseModel):
    question: str
    answer: str

class PracticeQuestion(BaseModel):
    question: str
    answer: str

class StudyPack(BaseModel):
    quick_summary: str
    detailed_notes: list[str]
    key_points: list[str]
    key_terms: list[Term]
    exam_focus: list[str]
    flashcards: list[Flashcard]
    practice_questions: list[PracticeQuestion]

def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()

def split_sentences(text: str) -> list[str]:
    text = clean_text(text)
    parts = re.split(r"(?<=[.!?])\s+|\s*[•▪◦]\s*|\n+", text)
    return [p.strip(" -\t") for p in parts if len(p.strip()) > 15]

def words(text: str) -> list[str]:
    return [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z'-]{2,}", text) if w.lower() not in STOP]

def shorten(sentence: str, limit: int = 150) -> str:
    s = clean_text(sentence)
    if len(s) <= limit:
        return s
    cut = s[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "…"

def extract_definition(sentence: str):
    patterns = [
        r"^(.{2,55}?)\s+(?:is|are|means|refers to|is defined as)\s+(.{8,220})$",
        r"^(.{2,55}?):\s+(.{8,220})$",
    ]
    for pattern in patterns:
        m = re.match(pattern, sentence, re.I)
        if m:
            term = m.group(1).strip(" .,:;-")
            definition = m.group(2).strip(" .")
            if 1 <= len(term.split()) <= 7:
                return term, definition
    return None

def build_study_pack(text: str) -> StudyPack:
    sentences = split_sentences(text)
    if not sentences:
        raise ValueError("No readable sentences found.")

    freq = Counter(words(text))
    scored = []
    for i, sentence in enumerate(sentences):
        ws = words(sentence)
        score = sum(freq[w] for w in set(ws)) / max(1, len(ws) ** 0.5)
        if re.search(r"\b(important|key|main|because|therefore|defined|means|causes?|results?|includes?|types?|process)\b", sentence, re.I):
            score *= 1.15
        scored.append((score, i, sentence))
    ranked = sorted(scored, reverse=True)

    summary_ids = sorted(i for _, i, _ in ranked[:min(4, len(ranked))])
    quick_summary = " ".join(shorten(sentences[i], 190) for i in summary_ids)

    key_points = []
    for _, _, sentence in ranked:
        point = shorten(sentence, 145)
        if point not in key_points:
            key_points.append(point)
        if len(key_points) == 7:
            break

    detailed_notes = [shorten(sentences[i], 230) for i in range(min(10, len(sentences)))]

    terms = []
    seen = set()
    for sentence in sentences:
        found = extract_definition(sentence)
        if found and found[0].lower() not in seen:
            terms.append(Term(term=found[0], definition=shorten(found[1], 180)))
            seen.add(found[0].lower())
        if len(terms) == 6:
            break
    if len(terms) < 4:
        for word, _ in freq.most_common(10):
            if word not in seen and len(word) > 4:
                source = next((s for s in sentences if re.search(rf"\b{re.escape(word)}\b", s, re.I)), None)
                if source:
                    terms.append(Term(term=word.title(), definition=shorten(source, 170)))
                    seen.add(word)
            if len(terms) == 6:
                break

    exam_focus = key_points[:4]
    flashcards = [Flashcard(question=f"What should you remember about {t.term}?", answer=t.definition) for t in terms[:5]]
    if len(flashcards) < 3:
        flashcards += [Flashcard(question=f"Explain this key idea: {p[:55]}…", answer=p) for p in key_points[:3-len(flashcards)]]

    practice = []
    for i, point in enumerate(key_points[:5], 1):
        starter = ["Explain", "Describe", "Why is this important:", "Write a short note on", "What does this statement mean:"][i-1]
        practice.append(PracticeQuestion(question=f"{starter} {point[:80]}", answer=point))

    return StudyPack(
        quick_summary=quick_summary,
        detailed_notes=detailed_notes,
        key_points=key_points,
        key_terms=terms,
        exam_focus=exam_focus,
        flashcards=flashcards,
        practice_questions=practice,
    )

@app.get("/")
def home():
    return FileResponse(STATIC_DIR / "index.html")

@app.get("/health")
def health():
    return {"status": "ok", "version": "3.1.0"}

@app.post("/summarize", response_model=StudyPack)
def summarize(request: NotesRequest):
    try:
        return build_study_pack(request.text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@app.post("/upload", response_model=StudyPack)
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
        return build_study_pack(text)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Could not read this file.") from exc
