import os
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def analizza_immagine(path):

    prompt = f"""
Sei uno specialista SLPS.

Analizza l'immagine fornita e:

1. Descrivi il rischio osservato
2. Indica il livello di rischio (basso, medio, alto)
3. Spiega cosa verificare prima di giudicare
4. Indica possibili basi legali (OPI, OLCostr, OLL)
5. Suggerisci misure concrete

NON fare assunzioni non verificabili.
Se mancano dati, chiedi ulteriori informazioni.
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Sei un esperto sicurezza lavoro svizzero."},
            {"role": "user", "content": prompt}
        ]
    )

    return response.choices[0].message.content
