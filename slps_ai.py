import os
from openai import OpenAI

# Legge la chiave da Render (Environment Variables)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def analizza_immagine(path: str) -> str:
    """
    Analisi SLPS generica (NON hard-coded su casi specifici).
    Non usa direttamente l'immagine (per ora), ma genera una
    valutazione strutturata e chiede eventuali info mancanti.
    """

    if not os.getenv("OPENAI_API_KEY"):
        return "Errore: OPENAI_API_KEY non configurata su Render"

    prompt = """
Sei uno specialista SLPS in Svizzera.

Analizza la situazione di lavoro rappresentata (se i dati non sono chiari, NON inventare).

Fornisci:
1) Descrizione del rischio osservabile
2) Livello di rischio (basso / medio / alto) con motivazione
3) Fattori critici da verificare (altezza, carico, modalità uso, formazione, ecc.)
4) Possibili basi legali (OPI, OLCostr, OLL) pertinenti al caso
5) Misure concrete e pratiche
6) Domande mirate per completare la valutazione (se mancano dati)

Mantieni un approccio professionale, prudente e realistico.
"""

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Esperto sicurezza lavoro svizzero (SLPS)."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            timeout=20
        )

        return resp.choices[0].message.content.strip()

    except Exception as e:
        return f"Errore AI: {str(e)}"
