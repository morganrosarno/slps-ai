import os
import base64
from openai import OpenAI

# Inizializza client OpenAI (legge automaticamente OPENAI_API_KEY dalle env)
client = OpenAI()

def analizza_immagine(percorso_immagine):
    """
    Analizza un'immagine di cantiere e restituisce:
    - livello di rischio
    - punteggio
    - spiegazione tecnica
    - eventuali domande da porre
    """

    # 🔒 Controllo file
    if not os.path.exists(percorso_immagine):
        return {
            "livello": "errore",
            "punteggio": 0,
            "descrizione": "Immagine non trovata",
            "domande": []
        }

    # 📷 Legge immagine e la converte in base64
    with open(percorso_immagine, "rb") as f:
        img_base64 = base64.b64encode(f.read()).decode("utf-8")

    # 🧠 PROMPT SERIO (generico, NON hardcoded su casi specifici)
    prompt = """
Sei uno specialista sicurezza sul lavoro (SLPS) esperto in ambito svizzero.

Analizza l'immagine fornita e:
1. Identifica possibili pericoli o situazioni non sicure
2. Valuta il livello di rischio (basso, medio, alto)
3. Assegna un punteggio da 0 a 100
4. Spiega il ragionamento tecnico (NON generico)
5. Indica eventuali incertezze
6. Formula domande utili per migliorare la valutazione

ATTENZIONE:
- NON inventare rischi se non evidenti
- Se l'immagine è ambigua, dichiaralo chiaramente
- NON dare per scontato l'uso dell'attrezzatura
- Il rischio dipende da contesto (carico, quota, uso reale)

Rispondi SOLO in JSON con questo formato:

{
  "livello": "basso | medio | alto",
  "punteggio": numero,
  "descrizione": "spiegazione tecnica",
  "domande": ["domanda1", "domanda2"]
}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{img_base64}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=800
        )

        risposta = response.choices[0].message.content

        # 🔁 Prova a interpretare JSON
        import json
        try:
            dati = json.loads(risposta)
            return dati
        except:
            # fallback se AI risponde male
            return {
                "livello": "errore",
                "punteggio": 0,
                "descrizione": risposta,
                "domande": []
            }

    except Exception as e:
        return {
            "livello": "errore",
            "punteggio": 0,
            "descrizione": f"Errore AI: {str(e)}",
            "domande": []
        }
