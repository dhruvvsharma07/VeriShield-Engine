import os
import time
import json
import hashlib
import cv2
import numpy as np
from fastapi import FastAPI, UploadFile, File, HTTPException
from insightface.app import FaceAnalysis
from roboflow import Roboflow
import easyocr
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="VeriShield_Inference_Engine_HF")

# --- 1. RISK CALIBRATION ---
BIOMETRIC_WEIGHT = 0.65
STRUCTURAL_WEIGHT = 0.25
GOV_ID_WEIGHT = 0.10
APPROVAL_THRESHOLD = 0.75

# --- 2. ENGINE INITIALIZATION (Warm Start) ---
# High-RAM environment allows for the Large (L) model for better accuracy
face_app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
face_app.prepare(ctx_id=0, det_size=(640, 640)) 

# Warm up EasyOCR
ocr_engine = easyocr.Reader(['en'], gpu=False)

# Warm up YOLO (Roboflow)
api_key = os.getenv("ROBOFLOW_API_KEY")
rf = Roboflow(api_key=api_key)
try:
    # Leaving workspace() empty is the safest strategy for dynamic environments
    workspace = rf.workspace() 
    project = workspace.project("verishield-kyc") 
    yolo_engine = project.version(1).model
    print(f"✅ YOLO Engine Loaded from workspace: {workspace.id}")
except Exception as e:
    print(f"⚠️ Roboflow Error: {e}")
    yolo_engine = None

def get_integrity_hash(audit_data: dict) -> str:
    audit_str = json.dumps(audit_data, sort_keys=True)
    return hashlib.sha256(audit_str.encode()).hexdigest()

# --- 3. ENDPOINTS ---

@app.get("/")
def read_root():
    """Professional root endpoint to avoid 404 errors in monitoring."""
    return {
        "status": "VeriShield Engine is Online",
        "documentation": "/docs",
        "pillars": ["Biometrics", "Structural", "OCR"]
    }

@app.post("/verify")
async def verify_identity(id_card: UploadFile = File(...), selfie: UploadFile = File(...)):
    start_time = time.time()
    
    try:
        id_bytes = await id_card.read()
        selfie_bytes = await selfie.read()
        img_id = cv2.imdecode(np.frombuffer(id_bytes, np.uint8), cv2.IMREAD_COLOR)
        img_selfie = cv2.imdecode(np.frombuffer(selfie_bytes, np.uint8), cv2.IMREAD_COLOR)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Image Data")

    # PILLAR 1: Biometrics
    id_faces = face_app.get(cv2.cvtColor(img_id, cv2.COLOR_BGR2RGB))
    selfie_faces = face_app.get(cv2.cvtColor(img_selfie, cv2.COLOR_BGR2RGB))
    
    similarity = 0.0
    face_match = False
    if id_faces and selfie_faces:
        similarity = float(np.dot(id_faces[0].normed_embedding, selfie_faces[0].normed_embedding))
        face_match = (similarity > 0.45) 

    # PILLAR 2: Structural (Anti-Forgery)
    anchors_found = 0
    if yolo_engine:
        yolo_res = yolo_engine.predict(img_id, confidence=40).json()
        anchors_found = len(yolo_res.get("predictions", []))

    # PILLAR 3: OCR (Compliance Validation)
    ocr_results = ocr_engine.readtext(img_id)
    raw_text_list = [res[1].upper() for res in ocr_results]
    extracted_text = " ".join(raw_text_list)
    
    # Regulatory Keyword Check (Aadhaar/PAN focus)
    keywords = ["INCOME TAX", "GOVERNMENT OF INDIA", "AADHAAR", "ELECTION COMMISSION", "FATHER'S NAME"]
    is_gov_doc = any(word in extracted_text for word in keywords)
    is_pan = "PERMANENT" in extracted_text or "ACCOUNT NUMBER" in extracted_text

    # --- DECISION LOGIC ---
    bio_score = 1.0 if face_match else 0.0
    struct_score = min(anchors_found, 5) / 5.0
    gov_score = 1.0 if is_gov_doc else 0.0
    
    trust_score = (bio_score * BIOMETRIC_WEIGHT) + (struct_score * STRUCTURAL_WEIGHT) + (gov_score * GOV_ID_WEIGHT)
    
    is_approved = (trust_score >= APPROVAL_THRESHOLD and face_match and is_gov_doc)
    
    audit_log = {
        "timestamp": time.time(),
        "decision": "APPROVED" if is_approved else "REJECTED",
        "trust_score": round(trust_score, 4),
        "face_match_confidence": round(similarity, 4),
        "structural_anchors": anchors_found,
        "is_gov_verified": is_gov_doc,
        "document_type": "PAN/GOV_ID" if is_pan else "UNKNOWN",
        "extracted_data_preview": raw_text_list[:10],
        "latency_sec": round(time.time() - start_time, 2)
    }
    
    audit_log["integrity_hash"] = get_integrity_hash(audit_log)
    
    return audit_log
