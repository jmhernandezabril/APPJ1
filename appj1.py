# appj1.py con Microsoft Graph (sin smtp)
# responde 202 y envia en background
# sin tildes ni letra n

import os, json, time, threading, pymysql, requests, base64
from datetime import datetime, timedelta
from threading import Thread
from flask import Flask, jsonify, render_template
from email.mime.multipart import MIMEMultipart  # solo para mantener tu render_template; no se usa para enviar

from db_config import DB_CONFIG

app = Flask(__name__)

# --------- credenciales de Azure AD (rellenar) ---------
TENANT_ID = os.getenv("GRAPH_TENANT_ID")
CLIENT_ID = os.getenv("GRAPH_CLIENT_ID")
CLIENT_SECRET = os.getenv("GRAPH_CLIENT_SECRET")
SENDER_UPN = os.getenv("GRAPH_SENDER_UPN", "notificaciones@tabisam.es")

missing = [k for k,v in {
    "GRAPH_TENANT_ID":TENANT_ID,
    "GRAPH_CLIENT_ID":CLIENT_ID,
    "GRAPH_CLIENT_SECRET":CLIENT_SECRET
}.items() if not v]
if missing:
    raise RuntimeError(f"Faltan variables: {', '.join(missing)}")

# --------- utils ---------
def log(msg: str):
    print(f"[APPJ1] {datetime.now().isoformat(timespec='seconds')} | {msg}", flush=True)

def load_email_config(path: str = "config.json") -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.loads(f.read())
    except Exception as e:
        log(f"error cargando config.json: {e}")
        data = {}
    return {"cc": data.get("cc", []), "cco": data.get("cco", [])}

def weekday_today() -> int:
    return datetime.now().weekday()  # 0 lunes .. 6 domingo

def weekday_yesterday() -> int:
    return (datetime.now() - timedelta(days=1)).weekday()

# --------- DB ---------
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
            return cur.fetchall()
    except Exception as e:
        log(f"error DB: {e}")
        return None
    finally:
        try:
            if conn: conn.close()
        except Exception:
            pass

# --------- Graph helpers ---------
def graph_token() -> str:
    url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }
    r = requests.post(url, data=data, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]

def send_mail_graph(to_list, cc_list, bcc_list, subject, html, inline_png_path: str | None = None):
    token = graph_token()
    url = f"https://graph.microsoft.com/v1.0/users/{SENDER_UPN}/sendMail"

    message = {
        "subject": subject,
        "body": {"contentType": "HTML", "content": html},
        "toRecipients": [{"emailAddress": {"address": x}} for x in to_list],
        "ccRecipients": [{"emailAddress": {"address": x}} for x in cc_list],
        "bccRecipients": [{"emailAddress": {"address": x}} for x in bcc_list],
    }

    # inline image opcional: cid:logo_tabisam
    if inline_png_path and os.path.exists(inline_png_path):
        with open(inline_png_path, "rb") as f:
            content_bytes = f.read()
        attachment = {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": "image001.png",
            "contentId": "logo_tabisam",
            "isInline": True,
            "contentBytes": base64.b64encode(content_bytes).decode("ascii"),
            "contentType": "image/png",
        }
        message["attachments"] = [attachment]

    payload = {"message": message, "saveToSentItems": True}
    headers = {"Authorization": f"Bearer {token}"}

    r = requests.post(url, json=payload, headers=headers, timeout=30)
    r.raise_for_status()

# --------- envio batch ---------
def send_email_batch(rows) -> None:
    cfg = load_email_config()
    cc_emails = cfg.get("cc", [])
    cco_emails = cfg.get("cco", [])

    hoy = weekday_today()
    ayer = weekday_yesterday()

    enviados = 0
    for row in rows or []:
        try:
            dias_restantes = row[14]
            debe_enviar = (
                hoy != 6 and (
                    dias_restantes in [31, 25, 20, 15]
                    or dias_restantes < 13
                    or (ayer == 6 and dias_restantes in [30, 24, 19, 14])
                )
            )
            if not debe_enviar:
                continue

            html = render_template(
                "email_template.html",
                conductor={"first_name": row[6]},
                vehiculo={"name": row[0], "fecha_prxima_i_t_v": row[5]},
            )

            send_mail_graph(
                to_list=[row[13]],
                cc_list=cc_emails,
                bcc_list=cco_emails,
                subject="Notificacion de Inspeccion Tecnica de Vehiculos",
                html=html,
                inline_png_path="static/image001.png",
            )
            enviados += 1
            log(f"correo enviado a {row[13]}")
        except Exception as e:
            log(f"error enviando a {row[13]}: {e}")

    log(f"envio finalizado. enviados={enviados}")

# --------- job async ---------
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

# --------- rutas ---------
@app.route("/")
def home():
    return "APPJ1 ok"

@app.route("/send_email", methods=["GET"])
def send_email_route():
    Thread(target=job_enviar_async, name="job_enviar_async_http", daemon=True).start()
    return jsonify({"status": "accepted"}), 202

# --------- arranque ---------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
