from pathlib import Path
import re
from collections import Counter
from io import BytesIO
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pypdf import PdfReader

app=FastAPI(title="Smart Notes AI",version="3.2.0")
STATIC_DIR=Path(__file__).parent/"static"; app.mount("/static",StaticFiles(directory=STATIC_DIR),name="static")
STOP=set("""the a an and or but if then than to of in on at for from with by as is are was were be been being this that these those it its into about over under between through during can could should would may might will do does did has have had not no so such their there they them he she we you your our i which who what when where how also very more most some any each other used using use called make made many much""".split())

class NotesRequest(BaseModel): text:str=Field(min_length=20)
class Term(BaseModel): term:str; definition:str
class Flashcard(BaseModel): question:str; answer:str
class PracticeQuestion(BaseModel): question:str; answer:str
class StudyPack(BaseModel):
    quick_summary:str; keywords:list[str]; detailed_notes:list[str]; key_points:list[str]
    key_terms:list[Term]; exam_focus:list[str]; flashcards:list[Flashcard]; practice_questions:list[PracticeQuestion]

def clean(t): return re.sub(r"\s+"," ",t).strip()
def sentences(t):
    raw=re.split(r"(?<=[.!?])\s+|\n+|\s*[•▪◦]\s*",t.strip())
    return [clean(x.strip(" -\t")) for x in raw if len(clean(x))>=12]
def tokens(t): return [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z'-]{2,}",t) if w.lower() not in STOP]
def clip(s,n=115):
    s=clean(s)
    if len(s)<=n:return s.rstrip(" .;:")
    return s[:n].rsplit(" ",1)[0].rstrip(" ,;:")+"."
def pointify(s):
    s=clean(s).strip("•- ")
    s=re.sub(r"^(however|therefore|moreover|furthermore|in addition|for example|thus|hence)[, ]+","",s,flags=re.I)
    s=re.sub(r"^(this|it)\s+(is|was)\s+","",s,flags=re.I)
    return clip(s,105)
def definition(s):
    for p in [r"^(.{2,50}?)\s+(?:is|are|means|refers to|is defined as)\s+(.{8,200})$",r"^(.{2,50}?):\s+(.{8,200})$"]:
        m=re.match(p,s,re.I)
        if m and 1<=len(m.group(1).split())<=6:return m.group(1).strip(" .,:;-"),m.group(2).strip(" .")
def build_study_pack(text):
    ss=sentences(text)
    if not ss: raise ValueError("No readable sentences found.")
    freq=Counter(tokens(text)); total=max(freq.values(),default=1)
    ranked=[]
    for i,s in enumerate(ss):
        ws=tokens(s); unique=set(ws)
        score=sum(freq[w]/total for w in unique)/max(1,len(unique)**.45)
        if 35<=len(s)<=180: score*=1.12
        if re.search(r"\b(important|main|key|because|therefore|means|defined|causes?|results?|includes?|types?|process|function|purpose|effect)\b",s,re.I):score*=1.18
        ranked.append((score,i,s))
    ranked.sort(reverse=True)

    keywords=[]
    for w,c in freq.most_common(40):
        if len(w)>=4 and not any(w in k.lower().split() for k in keywords):
            keywords.append(w.title())
        if len(keywords)==10:break

    points=[]
    seen=set()
    for _,_,s in ranked:
        p=pointify(s); signature=set(tokens(p))
        if len(signature)<2:continue
        if any(len(signature & old)/max(1,len(signature|old))>.58 for old in seen):continue
        points.append(p);seen.add(frozenset(signature))
        if len(points)==7:break

    chosen=sorted(ranked[:min(3,len(ranked))],key=lambda x:x[1])
    summary_parts=[]
    for _,_,s in chosen:
        p=clip(s,155)
        if p not in summary_parts:summary_parts.append(p)
    quick=" ".join(summary_parts)

    terms=[];termseen=set()
    for s in ss:
        d=definition(s)
        if d and d[0].lower() not in termseen:
            terms.append(Term(term=d[0],definition=clip(d[1],155)));termseen.add(d[0].lower())
        if len(terms)>=6:break
    for kw in keywords:
        if len(terms)>=6:break
        if kw.lower() in termseen:continue
        src=next((s for s in ss if re.search(rf"\b{re.escape(kw)}\b",s,re.I)),None)
        if src:
            terms.append(Term(term=kw,definition=clip(src,150)));termseen.add(kw.lower())

    detailed=[clip(s,210) for s in ss[:10]]
    exam=points[:4]
    cards=[Flashcard(question=f"What is important about {t.term}?",answer=t.definition) for t in terms[:5]]
    practice=[PracticeQuestion(question=f"{['Explain','Describe','Write a short note on','Why is this important:','What do you understand by'][i%5]} {p[:72]}",answer=p) for i,p in enumerate(points[:5])]
    return StudyPack(quick_summary=quick,keywords=keywords,detailed_notes=detailed,key_points=points,key_terms=terms,exam_focus=exam,flashcards=cards,practice_questions=practice)

@app.get("/")
def home():return FileResponse(STATIC_DIR/"index.html")
@app.get("/health")
def health():return {"status":"ok","version":"3.2.0"}
@app.post("/summarize",response_model=StudyPack)
def summarize(request:NotesRequest):
    try:return build_study_pack(request.text)
    except ValueError as e:raise HTTPException(status_code=400,detail=str(e)) from e
@app.post("/upload",response_model=StudyPack)
async def upload(file:UploadFile=File(...)):
    name=(file.filename or "").lower();data=await file.read()
    if len(data)>10*1024*1024:raise HTTPException(status_code=413,detail="File must be 10 MB or smaller.")
    try:
        if name.endswith(".pdf"):text="\n".join(p.extract_text() or "" for p in PdfReader(BytesIO(data)).pages)
        elif name.endswith(".txt"):text=data.decode("utf-8")
        else:raise HTTPException(status_code=415,detail="Upload a PDF or TXT file.")
        if len(text.strip())<20:raise HTTPException(status_code=400,detail="Not enough readable text found.")
        return build_study_pack(text)
    except HTTPException:raise
    except Exception as e:raise HTTPException(status_code=400,detail="Could not read this file.") from e
