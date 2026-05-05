import os
from flask import Flask, render_template, request
from slps_ai import analizza_immagine

app = Flask(__name__)
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/analizza", methods=["POST"])
def analizza():
    file = request.files["file"]
    percorso = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(percorso)

    risultato = analizza_immagine(percorso)

    return render_template(
        "index.html",
        risultato=risultato,
        immagine=percorso
    )

# 🔥 QUESTO È FONDAMENTALE PER RENDER
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
