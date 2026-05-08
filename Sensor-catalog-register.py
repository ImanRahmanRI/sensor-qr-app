from google.cloud import firestore

db = firestore.Client(project="mipa-ugm")

db.collection("sensor_catalog").document("ZIF").set({
    "target_chemical": "Trimethylamine  (TMA)",
    "image_good_url": "https://storage.googleapis.com/mipa-ugm-sensor-assets/catalog/ZIF/good.jpg",
    "image_trans_url": "https://storage.googleapis.com/mipa-ugm-sensor-assets/catalog/ZIF/trans.jpg",
    "image_bad_url": "https://storage.googleapis.com/mipa-ugm-sensor-assets/catalog/ZIF/bad.jpg"
})

# db.collection("sensor_catalog").document("PDA").set({
#     "target_chemical": "Trimethylamine  (TMA)",
#     "image_good_url": "https://storage.googleapis.com/YOUR_BUCKET/catalog/sensor_a/good.jpg",
#     "image_trans_url": "https://storage.googleapis.com/YOUR_BUCKET/catalog/sensor_a/trans.jpg",
#     "image_bad_url": "https://storage.googleapis.com/YOUR_BUCKET/catalog/sensor_a/bad.jpg"
# })