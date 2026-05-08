import os
import io
import uuid
import datetime
import qrcode
from PIL import Image
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google.cloud import firestore, storage

app = FastAPI(title="Colorimetric Sensor API")

# Allow CORS for local testing and cross-origin requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize GCP Clients
db = firestore.Client()
storage_client = storage.Client()
BUCKET_NAME = os.environ.get("BUCKET_NAME", "your-default-bucket-name")

# Ensure static directory exists
os.makedirs("static", exist_ok=True)

# --- Data Models ---
class GenerateLabelRequest(BaseModel):
    sensor_type_id: str  # e.g., "SENSOR_A", "SENSOR_B"
    batch_number: str    # e.g., "B-2026-05"

# --- API Endpoints ---
@app.post("/api/sensors/generate")
async def generate_sensor(payload: GenerateLabelRequest):
    """Generates a Smart ID, creates the QR label, uploads to GCS, and saves to Firestore."""
    
    # 1. Generate the Smart ID: TYPE - DATE - HASH
    date_str = datetime.datetime.utcnow().strftime("%Y%m%d")
    short_hash = str(uuid.uuid4())[:4] # 4-character random hash
    smart_id = f"{payload.sensor_type_id}-{date_str}-{short_hash}"
    
    base_url = os.environ.get("APP_URL", "http://localhost:8080")
    # Note: URL now uses 'id=' instead of 'sensor='
    qr_data = f"{base_url}/?id={smart_id}"

    try:
        # 2. Generate QR Code
        qr = qrcode.make(qr_data)
        
        # 3. Stitch onto Template using exact UI measurements
        template_path = "static/template.jpg"
        if not os.path.exists(template_path):
            # Create a fallback white canvas if template is missing locally
            img = Image.new('RGB', (1024, 512), color=(255, 255, 255))
            img.save(template_path)
            
        template = Image.open(template_path).convert("RGB") 
        
        # Exact Dimensions: W=114, H=114
        exact_size = (114, 114)
        qr = qr.resize(exact_size) 
        
        # Convert the QR code to standard RGB (forces solid white background/black squares)
        qr_solid = qr.convert('RGB')
        
        # Exact Coordinates: X=250, Y=40
        pasting_coords = (250, 40) 
        
        # Paste the solid QR code directly over the template at the exact coordinates
        template.paste(qr_solid, pasting_coords) 

        # 4. Save image to memory buffer
        img_byte_arr = io.BytesIO()
        template.save(img_byte_arr, format='JPEG')
        img_byte_arr = img_byte_arr.getvalue()

        # 5. Upload to Google Cloud Storage
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(f"labels/{smart_id}.jpg")
        blob.upload_from_string(img_byte_arr, content_type="image/jpeg")
        label_url = blob.public_url
        
        # 6. Save Transactional Data to Firestore
        doc_ref = db.collection("generated_labels").document(smart_id)
        doc_ref.set({
            "generated_at": datetime.datetime.utcnow().isoformat(),
            "type_id": payload.sensor_type_id,
            "batch_number": payload.batch_number,
            "label_url": label_url,
            "status": "Active"
        })

        return {"id": smart_id, "label_url": label_url, "message": "Success"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/sensors/scan/{smart_id}")
async def scan_sensor(smart_id: str):
    """Fetches the specific generated label, then fetches its associated catalog Master Data."""
    # 1. Fetch Label Data
    label_ref = db.collection("generated_labels").document(smart_id)
    label_doc = label_ref.get()
    
    if not label_doc.exists:
        raise HTTPException(status_code=404, detail="Label not found")
        
    label_data = label_doc.to_dict()
    
    # 2. Fetch Master Catalog Data based on type_id
    type_id = label_data.get("type_id")
    catalog_ref = db.collection("sensor_catalog").document(type_id)
    catalog_doc = catalog_ref.get()
    
    catalog_data = catalog_doc.to_dict() if catalog_doc.exists else None

    # 3. Merge and return both to the frontend
    return {
        "label_info": label_data,
        "catalog_info": catalog_data
    }

# --- Frontend Serving ---
@app.get("/")
async def serve_frontend():
    # Use absolute path to ensure Uvicorn always finds it
    file_path = os.path.join(os.getcwd(), "static", "index.html")
    return FileResponse(file_path)

app.mount("/static", StaticFiles(directory="static"), name="static")