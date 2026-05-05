from flask import Flask, request, jsonify, render_template
import os
from slps_ai import analizza_immagine

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/analizza", methods=["POST"])
def analizza():
    if "file" not in request.files:
        return jsonify({"errore": "Nessun file inviato"})

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"errore": "Nome file vuoto"})

    path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(path)

    risultato = analizza_immagine(path)

    return jsonify(risultato)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
