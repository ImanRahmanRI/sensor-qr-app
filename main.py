import os
import io
import uuid
import datetime
import qrcode
from PIL import Image, ImageOps
from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from google.cloud import firestore, storage

app = FastAPI(title="Colorimetric Sensor API")

# Allow CORS for local testing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize GCP Clients
# Note: In Cloud Run, credentials are automatically picked up from the Service Account
db = firestore.Client()
storage_client = storage.Client()
BUCKET_NAME = os.environ.get("BUCKET_NAME", "your-default-bucket-name")

# Ensure static directory exists
os.makedirs("static", exist_ok=True)

@app.post("/api/sensors/generate")
async def generate_sensor(spec: str = Form(...)):
    """Generates a UUID, creates the QR label, uploads to GCS, and saves to Firestore."""
    sensor_id = str(uuid.uuid4())
    
    # The URL that the QR code will point to when scanned
    # In production, change this to your actual custom domain
    base_url = os.environ.get("APP_URL", "http://localhost:8080")
    qr_data = f"{base_url}/?sensor={sensor_id}"

    try:
        # 1. Generate QR Code
        qr = qrcode.make(qr_data)
        
        # 2. Stitch onto Template
        template_path = "static/template.jpg"
        if not os.path.exists(template_path):
            img = Image.new('RGB', (1024, 512), color=(255, 255, 255))
            img.save(template_path)
            
        template = Image.open(template_path).convert("RGB") 
        
        # --- NEW EXACT COORDINATE PASTING LOGIC ---
        # Based on UI measurements: W=113.39, H=113.39
        # Resizing to 114x114 guarantees the black placeholder is completely covered.
        exact_size = (114, 114)
        qr = qr.resize(exact_size) 
        
        # Convert the QR code to standard RGB (forces solid white background/black squares)
        qr_solid = qr.convert('RGB')
        
        # Based on UI measurements: X=250, Y=40
        pasting_coords = (250, 40) 
        
        # Paste the solid QR code directly over the template at the exact coordinates
        template.paste(qr_solid, pasting_coords) 
        # --- END OF NEW LOGIC ---

        # Save to memory buffer
        img_byte_arr = io.BytesIO()
        template.save(img_byte_arr, format='JPEG')
        img_byte_arr = img_byte_arr.getvalue()

        # 3. Upload to Google Cloud Storage
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(f"labels/{sensor_id}.jpg")
        blob.upload_from_string(img_byte_arr, content_type="image/jpeg")
        
        # Make the individual object public (if bucket isn't Uniform Public)
        # blob.make_public() 
        label_url = blob.public_url

        # 4. Save Data to Firestore
        doc_ref = db.collection("sensors").document(sensor_id)
        doc_ref.set({
            "created_at": datetime.datetime.utcnow().isoformat(),
            "sensor_specifications": spec,
            "label_url": label_url,
            "status": "Active"
        })

        return {"uuid": sensor_id, "label_url": label_url, "message": "Success"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/sensors/{sensor_id}")
async def get_sensor(sensor_id: str):
    """Fetches sensor data from Firestore."""
    doc_ref = db.collection("sensors").document(sensor_id)
    doc = doc_ref.get()
    
    if doc.exists:
        return doc.to_dict()
    else:
        raise HTTPException(status_code=404, detail="Sensor not found")

# Serve the frontend
@app.get("/")
async def serve_frontend():
    return FileResponse("static/index.html")

app.mount("/static", StaticFiles(directory="static"), name="static")