import os
import io
import uuid
import datetime
import qrcode
import requests
from PIL import Image
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google.cloud import firestore, storage

app = FastAPI(title="Colorimetric Sensor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

db = firestore.Client()
storage_client = storage.Client()
BUCKET_NAME = os.environ.get("BUCKET_NAME", "your-default-bucket-name")
os.makedirs("static", exist_ok=True)

# --- Data Models ---
# Modification 1b: Removed manual batch_number from the request payload
class GenerateLabelRequest(BaseModel):
    sensor_type_id: str  

# --- API Endpoints ---

# Modification 1a: New endpoint to fetch available sensor types for the dropdown
@app.get("/api/catalog")
async def get_catalog():
    """Fetches all active sensor types from Master Data."""
    try:
        docs = db.collection("sensor_catalog").stream()
        catalog_items = []
        for doc in docs:
            data = doc.to_dict()
            catalog_items.append({
                "id": doc.id,
                "target": data.get("target_chemical", "Unknown Target")
            })
        return {"catalog": catalog_items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/sensors/generate")
async def generate_sensor(payload: GenerateLabelRequest):
    date_str = datetime.datetime.utcnow().strftime("%Y%m%d")
    time_str = datetime.datetime.utcnow().strftime("%H%M%S")
    short_hash = str(uuid.uuid4())[:4]
    
    smart_id = f"{payload.sensor_type_id}-{date_str}-{short_hash}"
    
    # Modification 1b: Auto-generate the Batch Number
    auto_batch_number = f"BATCH-{date_str}{time_str}-{short_hash}"
    
    base_url = "https://sensor-app-920027015367.asia-southeast2.run.app"
    qr_data = f"{base_url}/?id={smart_id}"

    try:
        # 1. Fetch Catalog Data for this Sensor Type
        catalog_ref = db.collection("sensor_catalog").document(payload.sensor_type_id)
        catalog_doc = catalog_ref.get()
        if not catalog_doc.exists:
            raise Exception(f"Sensor type '{payload.sensor_type_id}' not found in catalog.")
        catalog_data = catalog_doc.to_dict()

        # 2. Setup Template and QR
        qr = qrcode.make(qr_data).resize((114, 114)).convert('RGB')
        template_path = "static/template.jpg"
        template = Image.open(template_path).convert("RGB") 
        
        # Paste QR Code
        template.paste(qr, (250, 40)) 

        # Modification 2: Fetch and Paste the "Good" Reference Image
        good_img_url = catalog_data.get("image_good_url")
        if good_img_url:
            # Download the image to memory
            response = requests.get(good_img_url)
            if response.status_code == 200:
                good_img = Image.open(io.BytesIO(response.content)).convert("RGB")
                
                small_box_size = (57, 57) # Example: width=50, height=50
                good_img_resized = good_img.resize(small_box_size)
                
                # Example coordinates for the two smaller black boxes on the left
                top_small_box_coords = (175, 25)    # Update X, Y
                bottom_small_box_coords = (175, 115) # Update X, Y
                
                # Paste the good image into both smaller black boxes
                template.paste(good_img_resized, top_small_box_coords)
                template.paste(good_img_resized, bottom_small_box_coords)

        # 3. Save to GCS
        img_byte_arr = io.BytesIO()
        template.save(img_byte_arr, format='JPEG')
        img_byte_arr = img_byte_arr.getvalue()

        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(f"labels/{smart_id}.jpg")
        blob.upload_from_string(img_byte_arr, content_type="image/jpeg")
        label_url = blob.public_url
        
        # 4. Save to Firestore
        doc_ref = db.collection("generated_labels").document(smart_id)
        doc_ref.set({
            "generated_at": datetime.datetime.utcnow().isoformat(),
            "type_id": payload.sensor_type_id,
            "batch_number": auto_batch_number,
            "label_url": label_url,
            "status": "Active"
        })

        return {"id": smart_id, "label_url": label_url, "batch": auto_batch_number, "message": "Success"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/sensors/scan/{smart_id}")
async def scan_sensor(smart_id: str):
    label_ref = db.collection("generated_labels").document(smart_id)
    label_doc = label_ref.get()
    
    if not label_doc.exists:
        raise HTTPException(status_code=404, detail="Label not found")
    label_data = label_doc.to_dict()
    
    catalog_ref = db.collection("sensor_catalog").document(label_data.get("type_id"))
    catalog_doc = catalog_ref.get()
    catalog_data = catalog_doc.to_dict() if catalog_doc.exists else None

    return {"label_info": label_data, "catalog_info": catalog_data}

@app.get("/")
async def serve_frontend():
    file_path = os.path.join(os.getcwd(), "static", "index.html")
    return FileResponse(file_path)

app.mount("/static", StaticFiles(directory="static"), name="static")