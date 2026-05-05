import sys
video_path = sys.argv[1]

from ultralytics import YOLO
import cv2
import os
import math

# === CONFIG ===
FRAME_FOLDER = "frames"
MODEL = YOLO("yolov8n.pt")

# === FUNZIONE DISTANZA ===
def distanza(p1, p2):
    return math.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)

# === ANALISI ===
tot_persone = 0
tot_mezzi = 0
interferenze = 0

frames = sorted([f for f in os.listdir(FRAME_FOLDER) if f.endswith(".jpg")])

for frame_name in frames:
    path = os.path.join(FRAME_FOLDER, frame_name)
    img = cv2.imread(path)

    results = MODEL(img)[0]

    persone = []
    mezzi = []

    for box in results.boxes:
        cls = int(box.cls[0])
        label = MODEL.names[cls]

        x1, y1, x2, y2 = box.xyxy[0]
        cx = int((x1 + x2) / 2)
        cy = int((y1 + y2) / 2)

        if label == "person":
            persone.append((cx, cy))
        if label in ["truck", "bus", "car"]:
            mezzi.append((cx, cy))

    tot_persone += len(persone)
    tot_mezzi += len(mezzi)

    # === INTERFERENZA ===
    for p in persone:
        for m in mezzi:
            d = distanza(p, m)
            if d < 300:  # soglia empirica
                interferenze += 1

# === CALCOLO RISCHIO ===
rischio = 0

if tot_persone > 0 and tot_mezzi > 0:
    rischio += 40

if interferenze > 0:
    rischio += 40

if tot_mezzi > 3:
    rischio += 10

if tot_persone > 3:
    rischio += 10

# clamp
if rischio > 100:
    rischio = 100

# === CLASSIFICAZIONE ===
if rischio >= 70:
    livello = "ELEVATO"
elif rischio >= 40:
    livello = "MEDIO"
else:
    livello = "BASSO"

# === OUTPUT PROFESSIONALE ===
print("\n=== ANALISI SLPS ===\n")

if rischio == 0:
    print("⚪ RISCHIO NON VALUTABILE")
    print("\nOSSERVAZIONE:")
    print("Nessuna interazione significativa rilevata tra lavoratori e mezzi.")

else:
    print(f"🔴 RISCHIO: {livello}")
    print(f"PUNTEGGIO: {rischio}/100\n")

    print("SCENARIO:")
    print("Presenza simultanea di lavoratori e mezzi operativi nel medesimo spazio.")

    print("\nPERICOLO:")
    print("Rischio di investimento o schiacciamento durante le manovre dei mezzi.")

    print("\nFATTORI CRITICI:")
    print("- Possibili angoli ciechi dei macchinisti")
    print("- Mancanza di separazione uomo-mezzo")
    print("- Interferenza operativa nello stesso spazio")

    print("\nVALUTAZIONE:")
    if livello == "ELEVATO":
        print("Situazione pericolosa immediata con elevata probabilità di incidente grave.")
    elif livello == "MEDIO":
        print("Situazione da monitorare con rischio concreto in caso di errore operativo.")
    else:
        print("Rischio contenuto ma presente in condizioni dinamiche.")

    print("\nAZIONE IMMEDIATA:")
    print("- Interrompere le interferenze uomo-mezzo")
    print("- Allontanare i lavoratori dalle zone di manovra")

    print("\nMISURE:")
    print("- Separazione fisica aree lavoro")
    print("- Definizione zone mezzi")
    print("- Addetto segnalazione manovre")
    print("- Formazione lavoratori su rischi investimento")

print("\nBASI LEGALI:")
print("- OPI art. 6 (informazione, istruzione e formazione dei lavoratori)")
print("- OLCostr art. 3 (principi di sicurezza sul lavoro)")
print("- OLCostr art. 4 (misure di protezione)")
print("- OLCostr art. 19 (coordinamento e sicurezza nei lavori con più operatori/mezz i)")