import os, re
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.server_api import ServerApi

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "")
DB_NAME = os.getenv("DB_NAME", "Supply_Chain_Network_Mar2025")
COMPANIES_COLL = os.getenv("COMPANIES_COLL", "companies")

if not MONGO_URI:
    raise RuntimeError("MONGO_URI not set (put it in .env)")

# --- DB ---
client = MongoClient(MONGO_URI, server_api=ServerApi("1"))
db = client[DB_NAME]
companies = db[COMPANIES_COLL]

# --- App ---
app = FastAPI(title="Company Lookup (Minimal)", version="0.0.1")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

def anchored_ci_exact(s: str) -> Dict[str, Any]:
    """
    Case-insensitive 'exact' match using regex: ^<escaped>$ with 'i' option.
    Trims input before matching.
    """
    s = (s or "").strip()
    return {"$regex": f"^{re.escape(s)}$", "$options": "i"}

@app.get("/", tags=["meta"])
def root():
    return {"try": ["/health", "/company?name=Continental%20AG",
                    "/company?name=Continental%20AG&country=Germany"]}

@app.get("/health", tags=["meta"])
def health():
    client.admin.command("ping")
    # quick sanity: how many docs?
    count = companies.estimated_document_count()
    return {"status": "ok", "companies_estimated": count, "db": DB_NAME, "collection": COMPANIES_COLL}

@app.get("/company", tags=["company"])
def company_by_name(
    name: str = Query(..., description="Exact company name (case-insensitive)"),
    country: Optional[str] = Query(None, description="Optional exact country to disambiguate"),
    limit: int = Query(5, ge=1, le=50)
) -> List[Dict[str, Any]]:
    """
    Returns company docs whose name equals `name` ignoring case/whitespace differences.
    If `country` is provided, also requires exact country match (case-sensitive compare as stored).
    """
    filt: Dict[str, Any] = {"name": anchored_ci_exact(name)}
    if country:
        filt["country"] = country

    projection = {
        "_id": 1, "name": 1, "country": 1, "industry": 1,
        "website": 1, "traded_as": 1, "number_of_employees": 1, "revenue": 1
    }

    docs = list(companies.find(filt, projection).limit(limit))
    if not docs:
        # fallback: also try name_normalized if you have it (optional)
        alt = list(companies.find({"name_normalized": (name or "").strip().lower()}, projection).limit(limit))
        if alt:
            return alt
        raise HTTPException(status_code=404, detail=f"No company found for name='{name}'"
                                                    f"{' and country='+country if country else ''}")
    return docs

#
#http://127.0.0.1:8000/company?name=Continental%20AG%20(Germany,%20Fed.%20Rep.)%20(NBB:%20CTTA%20Y)
#http://127.0.0.1:8000/company?name=Continental%20AG%20%28Germany%2C%20Fed.%20Rep.%29%20%28NBB%3A%20CTTA%20Y%29
#http://127.0.0.1:8000/company?name=Airbus%20SE%20%28NBB%3A%20EADS%20Y%29
#http://127.0.0.1:8000/company?name=Boeing%20Co.%20%28The%29%20%28NYS%3A%20BA%29
#http://127.0.0.1:8000/company?name=Denso%20Corp%20%28NBB%3A%20DNZO%20Y%29
#http://127.0.0.1:8000/company?name=Magna%20International%20Inc%20%28NYS%3A%20MGA%29
#http://127.0.0.1:8000/company?name=Infineon%20Technologies%20AG%20%28NBB%3A%20IFNN%20Y%29
#http://127.0.0.1:8000/company?name=STMicroelectronics%20NV%20%28NYS%3A%20STM%29