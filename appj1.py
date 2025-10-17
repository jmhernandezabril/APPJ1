# appj1.py
# - endpoint /send_email responde 202 inmediato y ejecuta el envio en background
# - ignora send_time del config.json (solo usa cc y cco)
# - sin variables de entorno: SMTP_* dentro del codigo
# - logs simples por stdout para ver en Render

import os
import json
import time
import smtplib
import pymysql
import threading
from datetime import datetime, timedelta
from threading import Thread
from flask import Flask, jsonify, render_template
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

from db_config import DB_CONFIG  # debe existir en tu proyecto

app = Flask(__name__)

# ---------- configuracion SMTP en codigo ----------
SMTP_SERVER = "smtp.office365.com"
SMTP_PORT = 587
SMTP_USER = "notificaciones@tabisam.es"
smtp_password = "Hola!N.T*"

# ---------- util de log ----------
def log(msg: str) -> None:
    print(f"[APPJ1] {datetime.now().isoformat(timespec='seconds')} | {msg}", flush=True)

# ---------- config de email (solo cc/cco) ----------
def load_email_config(path: str = "config.json") -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.loads(f.read())
    except Exception as e:
        log(f"error cargando config.json: {e}")
        data = {}
    # solo tomamos cc/cco; ignoramos send_time y repeat_interval
    return {
        "cc": data.get("cc", []),
        "cco": data.get("cco", []),
    }

# ---------- helpers de fecha ----------
def weekday_today() -> int:
    # 0=lunes ... 6=domingo
    return datetime.now().weekday()

def weekday_yesterday() -> int:
    return (datetime.now() - timedelta(days=1)).weekday()

# ---------- DB ----------
def get_data_from_db():
    sql = """
    SELECT 
        vehiculo.name,
        vehiculo.description,
        vehiculo.tipo,
        vehiculo.marca,
        vehiculo.itv,
        DATE_FORMAT(vehiculo.fecha_prxima_i_t_v, '%d/%m/%Y') AS fecha_prxima_i_t_v,
        conductor.first_name,
        conductor.last_name,
        user.user_name,
        user.first_name,
        user.last_name,
        user.title,
        user.centro_de_trabajo,
        email_address.name,
        DATEDIFF(vehiculo.fecha_prxima_i_t_v, CURDATE()) AS dias_restantes
    FROM comercialcrm.vehiculo
    INNER JOIN comercialcrm.vehiculo_conductor
        ON vehiculo.id = vehiculo_conductor.vehiculo_id
    INNER JOIN comercialcrm.conductor
        ON conductor.id = vehiculo_conductor.conductor_id
    INNER JOIN comercialcrm.`user`
        ON conductor.id = `user`.conductor_id
    INNER JOIN comercialcrm.entity_email_address
        ON `user`.id = entity_email_address.entity_id 
        AND entity_email_address.entity_type = 'User'
    INNER JOIN comercialcrm.email_address
        ON entity_email_address.email_address_id = email_address.id
    WHERE 
        (fecha_prxima_i_t_v < CURDATE() OR fecha_prxima_i_t_v < CURDATE() + INTERVAL 32 DAY)
        AND vehiculo.deleted = 0
        AND vehiculo_conductor.deleted = 0
    """
    conn = None
    try:
        conn = pymysql.connect(
            host=DB_CONFIG["host"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
            database=DB_CONFIG["database"],
            port=DB_CONFIG["port"],
            charset="utf8mb4",
            cursorclass=pymysql.cursors.Cursor,
            connect_timeout=10,
            read_timeout=30,
            write_timeout=30,
        )
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
            return rows
    except Exception as e:
        log(f"error DB: {e}")
        return None
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass

# ---------- envio de emails ----------
def send_email_batch(rows) -> None:
    cfg = load_email_config()
    cc_emails = cfg.get("cc", [])
    cco_emails = cfg.get("cco", [])

    hoy = weekday_today()
    ayer = weekday_yesterday()

    enviados = 0

    for row in rows or []:
        try:
            # columnas usadas:
            # row[5] fecha_proxima_itv (string dd/mm/yyyy)
            # row[6] conductor.first_name
            # row[13] email destinatario
            # row[14] dias_restantes (int)
            dias_restantes = row[14]

            # logica de ventanas de aviso
            debe_enviar = (
                hoy != 6 and (
                    dias_restantes in [31, 25, 20, 15]
                    or dias_restantes < 13
                    or (ayer == 6 and dias_restantes in [30, 24, 19, 14])
                )
            )
            if not debe_enviar:
                continue

            # render del HTML con plantilla Jinja2
            html = render_template(
                "email_template.html",
                conductor={"first_name": row[6]},
                vehiculo={"name": row[0], "fecha_prxima_i_t_v": row[5]},
            )

            msg = MIMEMultipart("related")
            msg["From"] = SMTP_USER
            msg["To"] = row[13]
            msg["Subject"] = "Notificacion de Inspeccion Tecnica de Vehiculos"
            if cc_emails:
                msg["Cc"] = ", ".join(cc_emails)
            if cco_emails:
                msg["Bcc"] = ", ".join(cco_emails)

            alt = MIMEMultipart("alternative")
            alt.attach(MIMEText(html, "html"))
            msg.attach(alt)

            # imagen inline opcional
            try:
                with open("static/image001.png", "rb") as f:
                    img = MIMEImage(f.read())
                    img.add_header("Content-ID", "<logo_tabisam>")
                    img.add_header("Content-Disposition", "inline", filename="image001.png")
                    msg.attach(img)
            except Exception as e_img:
                log(f"no se adjunta imagen inline: {e_img}")

            # envio
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=60) as s:
                s.starttls()
                s.login(SMTP_USER, SMTP_PASS)
                s.send_message(msg)

            enviados += 1
            log(f"correo enviado a {row[13]}")
        except Exception as e:
            log(f"error enviando a {row[13]}: {e}")

    log(f"envio finalizado. enviados={enviados}")

# ---------- job async ----------
def job_enviar_async():
    try:
        with app.app_context():
            rows = get_data_from_db()
            if not rows:
                log("no hay filas para enviar")
                return
            log(f"filas recuperadas: {len(rows)}")
            send_email_batch(rows)
    except Exception as e:
        log(f"job error: {e}")

# ---------- rutas ----------
@app.route("/")
def home():
    return "APPJ1 ok"

@app.route("/send_email", methods=["GET"])
def send_email_route():
    # devuelve 202 aceptado y lanza envio en background
    Thread(target=job_enviar_async, name="job_enviar_async_http", daemon=True).start()
    return jsonify({"status": "accepted"}), 202

# ---------- arranque ----------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # debug=False para evitar doble arranque del reloader
    app.run(host="0.0.0.0", port=port, debug=False)
