"""Disposable loopback server for browser acceptance; never a deployment entrypoint.

All identities, media and analysis responses are synthetic. No master is read.
Outbound sockets are blocked even if developer credentials exist in the shell.
"""
import hashlib
import json
import os
from pathlib import Path
import socket
import signal
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw
from werkzeug.serving import make_server


def main():
    def stop(_signal, _frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    with tempfile.TemporaryDirectory(prefix="slps-browser-acceptance-") as directory:
        root = Path(directory)
        for name in tuple(os.environ):
            if name.startswith(("SLPS_", "OPENAI_")):
                del os.environ[name]
        os.environ.update({
            "SLPS_DATA_MODE": "synthetic",
            "SLPS_RATE_DB_PATH": str(root / "limits.sqlite3"),
            "SLPS_CASE_DB_PATH": str(root / "cases.sqlite3"),
            "SLPS_ACCOUNT_DB_PATH": str(root / "accounts.sqlite3"),
            "SLPS_HISTORY_ROOT": str(root / "media"),
        })

        def forbid_outbound(*_args, **_kwargs):
            raise RuntimeError("Browser acceptance forbids outbound connections")

        socket.socket.connect = forbid_outbound
        socket.socket.connect_ex = forbid_outbound
        socket.create_connection = forbid_outbound
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        import server
        from account_delivery_runtime import synthetic_registration_capability

        def synthetic_analysis(image, _mime, _context):
            return {
                "summary": "SYNTHETIC SOFTWARE TEST — no real safety assessment.",
                "findings": [{
                    "id": "F1", "title": "Synthetic observation", "risk": "medium",
                    "evidence": "Generated geometric shape, not a workplace photograph.",
                    "certainty": "visible", "exposed_people": "Synthetic fixture",
                    "action": "Verify the displayed software flow.",
                    "deadline": "During this software test", "question": "",
                    "critical_unknown": False, "references": [],
                    "bbox": {"x": .1, "y": .4, "width": .7, "height": .3},
                }],
                "questions": [], "sources": [], "needs_clarification": False,
                "limitations": ["Synthetic response; no AI provider or SLPS validation."],
                "meta": {"model": "synthetic-browser-fixture", "method_version": "test-only",
                         "image_sha256": hashlib.sha256(image).hexdigest()},
            }

        server.is_analysis_configured = lambda: True
        server.analizza_immagine = synthetic_analysis
        app = server.create_app({
            "TESTING": True, "AUTH_MODE": "accounts", "DATA_MODE": "synthetic",
            "SECRET_KEY": os.urandom(32), "SESSION_COOKIE_SECURE": False,
            "ACCOUNT_REGISTRATION_OPEN": True, "BILLING_SANDBOX_ENABLED": True,
            "ACCOUNT_REGISTRATION_TEST_CAPABILITY": synthetic_registration_capability(),
            "ANALYSES_PER_HOUR": 100,
        })
        accounts = app.extensions["account_store"]
        password = "synthetic-browser-test-password"
        for locale in ("it", "de", "fr", "en"):
            for width in (390, 1440):
                name = f"{locale}{width}"
                user = accounts.register(email=f"{name}@example.test", password=password,
                                         company_name=f"Synthetic {name}",
                                         company_identifier=f"test-{name}", role="owner", locale=locale)
                accounts.consume_token(accounts.issue_token(user["id"], "email"), "email")
                accounts.verify_company(user["company_id"], user["id"])
                accounts.assign_consultation_policy(user["company_id"], included=1, period_months=12)
        photo = root / "synthetic-photo.png"
        picture = Image.new("RGB", (640, 480), "#e8edf3")
        ImageDraw.Draw(picture).rectangle((65, 190, 510, 335), fill="#eaaf45")
        picture.save(photo)
        video = root / "synthetic-audio-video.mp4"
        subprocess.run([
            "ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
            "color=c=blue:s=160x90:d=0.4", "-f", "lavfi", "-i",
            "sine=frequency=440:duration=0.4", "-shortest", "-c:v", "libx264",
            "-pix_fmt", "yuv420p", "-c:a", "aac", str(video),
        ], check=True, timeout=15)

        @app.after_request
        def mark_synthetic(response):
            if response.mimetype == "text/html":
                response.set_data(response.get_data().replace(
                    b"<body>", b'<body><p role="note" id="synthetic-test-banner">'
                    b'SYNTHETIC SOFTWARE TEST / NO REAL AI / NO PAYMENTS</p>', 1))
            return response

        http = make_server("127.0.0.1", 0, app, threaded=True)
        print(json.dumps({"url": f"http://127.0.0.1:{http.server_port}",
                          "photo": str(photo), "video": str(video),
                          "password": password}), flush=True)
        try:
            http.serve_forever()
        finally:
            http.server_close()


if __name__ == "__main__":
    main()
