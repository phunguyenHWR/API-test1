# api.py
import os, re, json, uuid, pathlib
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.server_api import ServerApi

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "")
DB_NAME = os.getenv("DB_NAME", "Supply_Chain_Network_Mar2025")
COMPANIES_COLL = os.getenv("COMPANIES_COLL", "companies")
EXPORT_DIR = pathlib.Path(os.getenv("EXPORT_DIR", "/tmp/exports"))

if not MONGO_URI:
    raise RuntimeError("MONGO_URI not set")

client = MongoClient(MONGO_URI, server_api=ServerApi("1"), tls=True, tlsAllowInvalidCertificates=False)
db = client[DB_NAME]
companies = db[COMPANIES_COLL]

app = FastAPI(title="Company Export (root-only)", version="0.4")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

EXPORT_DIR.mkdir(parents=True, exist_ok=True)

SHORTCUTS: Dict[str, str] = {
    "c": "Continental AG (Germany, Fed. Rep.) (NBB: CTTA Y)",
    "a": "Airbus SE (NBB: EADS Y)",
    "b": "Boeing Co. (The) (NYS: BA)",
    "d": "Denso Corp (NBB: DNZO Y)",
    "m": "Magna International Inc (NYS: MGA)",
    "i": "Infineon Technologies AG (NBB: IFNN Y)",
    "s": "STMicroelectronics NV (NYS: STM)",
    "conti": "Continental AG (Germany, Fed. Rep.) (NBB: CTTA Y)",
    "continental": "Continental AG (Germany, Fed. Rep.) (NBB: CTTA Y)",
    "airbus": "Airbus SE (NBB: EADS Y)",
    "eads": "Airbus SE (NBB: EADS Y)",
    "boeing": "Boeing Co. (The) (NYS: BA)",
    "ba": "Boeing Co. (The) (NYS: BA)",
    "denso": "Denso Corp (NBB: DNZO Y)",
    "dnzo": "Denso Corp (NBB: DNZO Y)",
    "magna": "Magna International Inc (NYS: MGA)",
    "mga": "Magna International Inc (NYS: MGA)",
    "infineon": "Infineon Technologies AG (NBB: IFNN Y)",
    "ifnn": "Infineon Technologies AG (NBB: IFNN Y)",
    "stmicro": "STMicroelectronics NV (NYS: STM)",
    "stm": "STMicroelectronics NV (NYS: STM)",
}

def anchored_ci_exact(s: str) -> Dict[str, Any]:
    s = (s or "").strip()
    return {"$regex": f"^{re.escape(s)}$", "$options": "i"}

def safe_filename(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", (s or "")).strip("_")[:80]

def resolve_target(input_value: str) -> str:
    key = (input_value or "").strip().lower()
    return SHORTCUTS.get(key, input_value.strip())

@app.get("/")
def export_at_root(
    request: Request,
    export: Optional[str] = Query(None, description="Shortcut or full name (preferred)"),
    c: Optional[str] = Query(None, description="Alias for 'export' for older clients"),
    mode: str = Query("file", description="file|json|link (default file)")
):
    """
    - Accepts ?export= or ?c=
    - mode=file -> return attachment (application/octet-stream)
    - mode=json -> inline JSON in body
    - mode=link -> JSON {download_url: ...}
    """
    value = export or c
    if not value:
        raise HTTPException(status_code=400, detail="Missing query param 'export' (or 'c').")

    target_name = resolve_target(value)
    projection = {
        "_id": 1, "name": 1, "country": 1, "industry": 1,
        "website": 1, "traded_as": 1, "number_of_employees": 1, "revenue": 1
    }

    docs: List[Dict[str, Any]] = list(
        companies.find({"name": anchored_ci_exact(target_name)}, projection).limit(10)
    )
    if not docs:
        contains = {"$regex": re.escape(target_name), "$options": "i"}
        docs = list(companies.find({"name": contains}, projection).limit(10))
    if not docs:
        raise HTTPException(status_code=404, detail=f"No company found for '{target_name}'")

    file_id = str(uuid.uuid4())
    filename = f"{safe_filename(target_name)}_{file_id}.json"
    file_path = EXPORT_DIR / filename
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(docs, f, ensure_ascii=False, indent=2)

    download_url = str(request.url_for("download_file", filename=filename))

    if mode == "json":
        # inline JSON (some tools prefer body instead of file)
        return JSONResponse(content={"download_url": download_url, "data": docs})

    if mode == "link":
        # just hand back the link
        return JSONResponse(content={"download_url": download_url})

    # default: return as a downloadable file with generic content-type
    # (many “file detector” tools expect application/octet-stream)
    return FileResponse(
        path=str(file_path),
        media_type="application/octet-stream",
        filename=filename,
        headers={"X-Download-Link": download_url},
    )

@app.get("/download/{filename}")
def download_file(filename: str):
    file_path = EXPORT_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path=str(file_path), media_type="application/octet-stream", filename=filename)

@app.get("/health")
def health():
    client.admin.command("ping")
    return {
        "status": "ok",
        "db": DB_NAME,
        "collection": COMPANIES_COLL,
        "companies_estimated": companies.estimated_document_count(),
    }

# ------------ test bilateral connection ----------- 
from fastapi import Body
from datetime import datetime

ingest_coll = db.get_collection("ingest_logs")

@app.post("/ingest")
def ingest(payload: dict = Body(...)):
    doc = {"received_at": datetime.utcnow(), "payload": payload}
    res = ingest_coll.insert_one(doc)
    return {"ok": True, "id": str(res.inserted_id)}

