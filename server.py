from flask import Flask, request, jsonify, render_template
import os
import cv2
from ultralytics import YOLO
from openai import OpenAI

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

model = YOLO("yolov8n.pt")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/analizza", methods=["POST"])
def analizza():

    file = request.files["file"]
    path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(path)

    img = cv2.imread(path)
    results = model(img)

    oggetti = []

    for r in results:
        for c in r.boxes.cls:
            oggetti.append(model.names[int(c)])

    descrizione = ", ".join(set(oggetti)) if oggetti else "nessun oggetto"

    categoria = "attrezzatura / oggetti"

    prompt = f"""
Sei un esperto SLPS.

Oggetti rilevati: {descrizione}

Analizza la situazione e fornisci:
- non conformità
- rischio (senza inventare)
- domande
- basi legali se pertinenti
"""

    response = client.chat.completions.create(
        model="gpt-5.3",
        messages=[{"role": "user", "content": prompt}]
    )

    return jsonify({
        "analisi": response.choices[0].message.content
    })


if __name__ == "__main__":
    app.run()