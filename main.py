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

# --- 1. UTILITY FUNCTIONS (Defined first to avoid NameError) ---

def get_integrity_hash(audit_data: dict) -> str:
    """Creates a deterministic SHA-256 hash for audit immutability."""
    # We sort keys to ensure the hash is identical for the same data input
    audit_str = json.dumps(audit_data, sort_keys=True)
    return hashlib.sha256(audit_str.encode()).hexdigest()

# --- 2. RISK CALIBRATION ---
BIOMETRIC_WEIGHT = 0.65
STRUCTURAL_WEIGHT = 0.25
GOV_ID_WEIGHT = 0.10
APPROVAL_THRESHOLD = 0.75

# --- 3. ENGINE INITIALIZATION (Warm Start) ---
# High-RAM (16GB) allows for the Large (L) model
face_app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
face_app.prepare(ctx_id=0, det_size=(640, 640)) 

# Warm up EasyOCR
ocr_engine = easyocr.Reader(['en'], gpu=False)

# Warm up YOLO (Roboflow)
api_key = os.getenv("ROBOFLOW_API_KEY")
rf = Roboflow(api_key=api_key)
yolo_engine = None

try:
    # Using your specific workspace and project IDs discovered in logs
    workspace = rf.workspace("dhruvs-workspace-jwuyh") 
    project = workspace.project("pan-card-zu7gu-uh5oo")
    yolo_engine = project.version(1).model
    print(f"✅ YOLO Engine Loaded: {project.id}")
except Exception as e:
    print(f"❌ Roboflow Error: {e}")
    yolo_engine = None

# --- 4. ENDPOINTS ---

@app.get("/")
def read_root():
    return {
        "status": "VeriShield Engine is Online",
        "documentation": "/docs",
        "pillars": ["Biometrics", "Structural", "OCR"]
    }

@app.post("/verify")
async def verify_identity(id_card: UploadFile = File(...), selfie: UploadFile = File(...)):
    start_time = time.time()
    
    # --- HARDENED IMAGE DECODING ---
    try:
        id_bytes = await id_card.read()
        selfie_bytes = await selfie.read()
        
        nparr_id = np.frombuffer(id_bytes, np.uint8)
        nparr_selfie = np.frombuffer(selfie_bytes, np.uint8)
        
        img_id = cv2.imdecode(nparr_id, cv2.IMREAD_COLOR)
        img_selfie = cv2.imdecode(nparr_selfie, cv2.IMREAD_COLOR)
        
        if img_id is None or img_selfie is None:
            raise ValueError("Could not decode image files")
    except Exception as e:
        print(f"❌ Decode Error: {e}")
        raise HTTPException(status_code=400, detail="Invalid Image Data")

    # PILLAR 1: Biometrics (InsightFace)
    id_faces = face_app.get(cv2.cvtColor(img_id, cv2.COLOR_BGR2RGB))
    selfie_faces = face_app.get(cv2.cvtColor(img_selfie, cv2.COLOR_BGR2RGB))
    
    similarity = 0.0
    face_match = False
    if id_faces and selfie_faces:
        similarity = float(np.dot(id_faces[0].normed_embedding, selfie_faces[0].normed_embedding))
        face_match = (similarity > 0.45) 

    # PILLAR 2: Structural (Roboflow YOLO)
    anchors_found = 0
    if yolo_engine:
        try:
            yolo_res = yolo_engine.predict(img_id, confidence=40).json()
            anchors_found = len(yolo_res.get("predictions", []))
        except:
            anchors_found = 0

    # PILLAR 3: OCR (EasyOCR)
    ocr_results = ocr_engine.readtext(img_id)
    raw_text_list = [res[1].upper() for res in ocr_results]
    extracted_text = " ".join(raw_text_list)
    
    keywords = ["INCOME TAX", "GOVERNMENT OF INDIA", "AADHAAR", "ELECTION COMMISSION", "FATHER'S NAME"]
    is_gov_doc = any(word in extracted_text for word in keywords)
    is_pan = "PERMANENT" in extracted_text or "ACCOUNT NUMBER" in extracted_text

    # --- DECISION LOGIC ---
    bio_score = 1.0 if face_match else 0.0
    struct_score = min(anchors_found, 5) / 5.0
    gov_score = 1.0 if is_gov_doc else 0.0
    
    trust_score = (bio_score * BIOMETRIC_WEIGHT) + (struct_score * STRUCTURAL_WEIGHT) + (gov_score * GOV_ID_WEIGHT)
    
    is_approved = (trust_score >= APPROVAL_THRESHOLD and face_match and is_gov_doc)
    
    # Assemble Audit Log
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
    
    # Fix: Calling the function defined at the top
    audit_log["integrity_hash"] = get_integrity_hash(audit_log)
    
    return audit_log
