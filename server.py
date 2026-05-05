from flask import Flask, request, jsonify, render_template
from slps_ai import analizza_immagine
import os

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/analizza", methods=["POST"])
def analizza():
    try:
        if "file" not in request.files:
            return jsonify({"risultato": "Nessun file ricevuto"})

        file = request.files["file"]

        if file.filename == "":
            return jsonify({"risultato": "File non valido"})

        path = os.path.join(UPLOAD_FOLDER, file.filename)
        file.save(path)

        risultato = analizza_immagine(path)

        # 🔥 RISPOSTA SEMPRE COERENTE
        return jsonify({"risultato": risultato})

    except Exception as e:
        return jsonify({"risultato": f"Errore backend: {str(e)}"})


if __name__ == "__main__":
    app.run(debug=True)
