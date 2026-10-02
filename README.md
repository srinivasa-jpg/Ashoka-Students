# Smart Notes AI

A mobile-friendly study-notes summarizer for Ashoka students.

## Features
- Paste study notes
- Upload PDF or TXT notes (up to 10 MB)
- Generate a concise summary and key points
- FastAPI backend with built-in web UI
- No API key required for V2

## Run locally

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`.

## Next milestone
Mobile camera/gallery image upload with text extraction, followed by AI summaries, flashcards, quizzes, and Ask AI.
