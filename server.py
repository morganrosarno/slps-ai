from flask import Flask, request, jsonify, render_template
from slps_ai import analizza_immagine
import os

app = Flask(__name__)
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/analizza", methods=["POST"])
def analizza():
    if "file" not in request.files:
        return jsonify({"risultato": "Nessun file caricato"})

    file = request.files["file"]

    if file.filename == "":
        return jsonify({"risultato": "File non valido"})

    path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(path)

    try:
        risultato = analizza_immagine(path)
    except Exception as e:
        return jsonify({"risultato": f"Errore AI: {str(e)}"})

    return jsonify({"risultato": risultato})


if __name__ == "__main__":
    app.run(debug=True)
