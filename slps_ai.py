import os
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def analizza_immagine(path):
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Sei un esperto sicurezza lavoro."},
                {"role": "user", "content": "Analizza il rischio nell'immagine."}
            ],
            timeout=20
        )

        return response.choices[0].message.content

    except Exception as e:
        return f"ERRORE AI: {str(e)}"
