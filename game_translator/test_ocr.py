import cv2
import numpy as np
from ocr_engine import ocr_engine

print("Creating image...")
img = np.zeros((200, 600, 3), dtype=np.uint8)
cv2.putText(img, 'Test Game Subtitle', (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

print("Initializing OCR...")
ocr_engine.initialize()

print("Running OCR predict direct...")
try:
    res = list(ocr_engine.ocr.predict(img))
    print(f"PREDICT RAW: {res}")
    for item in res:
        print(f"TYPE: {type(item)}")
        if hasattr(item, '__dict__'):
            print(f"VARS: {vars(item)}")
        elif hasattr(item, 'keys'):
            print(f"KEYS: {item.keys()}")
            
except Exception as e:
    print(f"Predict error: {e}")

print("Running ocr_engine classify...")
res2 = ocr_engine.recognize(img)
print(f"RECOGNIZE PARSED: {res2}")
