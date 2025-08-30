import os, re, json, uuid, pathlib
from typing import Dict, Any, List
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
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

# ----- DB -----
client = MongoClient(MONGO_URI, server_api=ServerApi("1"), tls=True, tlsAllowInvalidCertificates=False)
db = client[DB_NAME]
companies = db[COMPANIES_COLL]

# ----- App -----
app = FastAPI(title="Company Export (shortcuts)", version="0.2")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

EXPORT_DIR.mkdir(parents=True, exist_ok=True)

# ----- Shortcuts -----
# keys are case-insensitive. Add more aliases as you like.
SHORTCUTS: Dict[str, str] = {
    # One-letter keys:
    "c": "Continental AG (Germany, Fed. Rep.) (NBB: CTTA Y)",
    "a": "Airbus SE (NBB: EADS Y)",
    "b": "Boeing Co. (The) (NYS: BA)",
    "d": "Denso Corp (NBB: DNZO Y)",
    "m": "Magna International Inc (NYS: MGA)",
    "i": "Infineon Technologies AG (NBB: IFNN Y)",
    "s": "STMicroelectronics NV (NYS: STM)",

    # Helpful aliases:
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

# ----- Helpers -----
def anchored_ci_exact(s: str) -> Dict[str, Any]:
    s = (s or "").strip()
    return {"$regex": f"^{re.escape(s)}$", "$options": "i"}

def safe_filename(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", (s or "")).strip("_")[:80]

def resolve_target(input_value: str) -> str:
    key = (input_value or "").strip().lower()
    return SHORTCUTS.get(key, input_value.strip())

# ----- Routes -----
@app.get("/")
def root():
    return {
        "try": ["/export?c=c", "/shortcuts", "/health"],
        "note": "Use /export?c=<shortcut_or_full_name>. Example: c=c or c=infineon"
    }

@app.get("/shortcuts")
def list_shortcuts():
    # return sorted list for convenience
    items = sorted({k: v for k, v in SHORTCUTS.items()}.items(), key=lambda x: x[0])
    return {"shortcuts": [{ "key": k, "name": v } for k, v in items]}

@app.get("/health")
def health():
    client.admin.command("ping")
    return {
        "status": "ok",
        "db": DB_NAME,
        "collection": COMPANIES_COLL,
        "companies_estimated": companies.estimated_document_count(),
    }

@app.get("/export")
def export_company(
    request: Request,
    c: str = Query(..., description="Shortcut key (e.g., c,a,b,...) OR the full company name")
) -> FileResponse:
    target_name = resolve_target(c)

    projection = {
        "_id": 1, "name": 1, "country": 1, "industry": 1,
        "website": 1, "traded_as": 1, "number_of_employees": 1, "revenue": 1
    }

    # 1) exact (case-insensitive)
    docs: List[Dict[str, Any]] = list(
        companies.find({"name": anchored_ci_exact(target_name)}, projection).limit(10)
    )

    # 2) fallback contains on name if exact not found
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

    link = request.url_for("download_file", filename=filename)
    headers = {"X-Download-Link": str(link)}

    return FileResponse(
        path=str(file_path),
        media_type="application/json",
        filename=filename,
        headers=headers,
    )

@app.get("/download/{filename}")
def download_file(filename: str):
    file_path = EXPORT_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path=str(file_path), media_type="application/json", filename=filename)
