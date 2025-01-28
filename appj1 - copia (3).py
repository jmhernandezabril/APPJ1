import os
import pymysql
from flask import Flask, render_template
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from db_config import DB_CONFIG
from email.mime.image import MIMEImage
import json
import schedule
import time
from threading import Thread, Lock
from datetime import datetime
import threading


app = Flask(__name__)

# Variable para evitar duplicaciones en la ejecución
last_run_time = None
scheduler_running = False
scheduler_lock = threading.Lock()


# Función para cargar la configuración desde un JSON
def load_email_config(config_file="config.json"):
    try:
        with open(config_file, "r") as file:
            return json.load(file)
    except Exception as e:
        print(f"Error al cargar el archivo de configuración: {e}")
        return {"cc": [], "cco": [], "send_time": "08:00", "repeat_interval": 0}

# Función para obtener datos de la base de datos
def get_data_from_db():
    query = """
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
    INNER JOIN comercialcrm.user
        ON conductor.id = user.conductor_id
    INNER JOIN comercialcrm.entity_email_address
        ON user.id = entity_email_address.entity_id 
        AND entity_email_address.entity_type = 'User'
    INNER JOIN comercialcrm.email_address
        ON entity_email_address.email_address_id = email_address.id
    WHERE 
        (fecha_prxima_i_t_v < CURDATE() OR fecha_prxima_i_t_v < CURDATE() + INTERVAL 32 DAY)
        AND vehiculo.deleted = 0
        AND vehiculo_conductor.deleted = 0
    """
    try:
        connection = pymysql.connect(
            host=DB_CONFIG["host"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
            database=DB_CONFIG["database"],
            port=DB_CONFIG["port"]
        )
        with connection.cursor() as cursor:
            cursor.execute(query)
            results = cursor.fetchall()
            return results
    except Exception as e:
        print(f"Error al conectar con la base de datos: {e}")
        return None
    finally:
        connection.close()

# Función para enviar correos
def send_email(data):
    smtp_server = "smtp.office365.com"
    smtp_port = 587
    smtp_user = "sistemas@tabisam.es"
    smtp_password = "J1rm3t5$$"

    email_config = load_email_config()
    cc_emails = email_config.get("cc", [])
    cco_emails = email_config.get("cco", [])
    
    for row in data:
        dias_restantes = row[14]
        if dias_restantes in [31, 25, 20, 15] or dias_restantes < 13:
            html_content = render_template(
                "email_template.html",
                conductor={"first_name": row[6]},
                vehiculo={"name": row[0], "fecha_prxima_i_t_v": row[5]}
            )
            msg = MIMEMultipart("related")
            msg["From"] = smtp_user
            msg["To"] = "josemaria.hernandez@tabisam.es"
            msg["Subject"] = "Notificación de Inspección Técnica de Vehículos"
            if cc_emails:
                msg["Cc"] = ", ".join(cc_emails)
            if cco_emails:
                msg["Bcc"] = ", ".join(cco_emails)

            msg_alternative = MIMEMultipart("alternative")
            msg.attach(msg_alternative)
            msg_alternative.attach(MIMEText(html_content, "html"))

            with open("static/image001.png", "rb") as img_file:
                mime_image = MIMEImage(img_file.read())
                mime_image.add_header("Content-ID", "<logo_tabisam>")
                mime_image.add_header("Content-Disposition", "inline", filename="image001.png")
                msg.attach(mime_image)

            try:
                with smtplib.SMTP(smtp_server, smtp_port) as server:
                    server.starttls()
                    server.login(smtp_user, smtp_password)
                    server.send_message(msg)
                    print(f"Correo enviado a {row[13]}.")
            except Exception as e:
                print(f"Error enviando correo a {row[13]}: {e}")

# ENVIO PLANIFICADO
def scheduled_task():
    global last_run_time

    now = datetime.now().strftime("%d/%m/%Y_%H:%M:%S.%f")[:-3]  # Formato con milisegundos
    print(f"📌 Comprobando ejecución de la tarea a las {now}...")

    with threading.Lock():  # 🔒 Bloqueo de concurrencia
        if last_run_time:
            last_run_minute = last_run_time[:16]  # Tomamos todo excepto los segundos
            now_minute = now[:16]

            if last_run_minute == now_minute:
                print(f"🚫 Evitando ejecución duplicada en el mismo minuto {now}")
                return

        last_run_time = now  # Actualizar última ejecución

        print(f"✅ Ejecutando tarea a las {now}")

        # Obtener datos y enviar correo si es necesario
        data = get_data_from_db()
        if data:
            print("✉️ Enviando Correos...")
            with app.app_context():  # 🔹 Asegurar contexto de Flask
                send_email(data)
        else:
            print("⚠️ No se obtuvieron datos para enviar el correo.")

def configure_schedule():
    """Configura las tareas programadas"""
    global last_run_time
    email_config = load_email_config()
    send_time = email_config.get("send_time", "").strip()
    repeat_interval = email_config.get("repeat_interval", 0)

    print(f"📋 Tareas activas en schedule.jobs ANTES de programar: {len(schedule.jobs)}")

    schedule.clear()  # Asegurar que no haya tareas duplicadas

    if send_time:
        print(f"🕒 Programando tarea para la hora exacta {send_time}...")
        schedule.every().day.at(send_time).do(scheduled_task)

    if repeat_interval > 0:
        print(f"🔄 Programando tarea repetitiva cada {repeat_interval} minutos...")
        schedule.every(repeat_interval).minutes.do(scheduled_task)

    print(f"📋 Tareas activas en schedule.jobs DESPUÉS de programar: {len(schedule.jobs)}")


def run_scheduler():
    """Ejecuta el loop del scheduler en un hilo separado"""
    global scheduler_running

    print("🔄 Iniciando loop del scheduler...")

    with scheduler_lock:
        if scheduler_running:
            print("⚠️ Scheduler ya estaba en ejecución. No se iniciará otro hilo.")
            return  

        scheduler_running = True  # ✅ Marcamos que el scheduler está corriendo

    while True:
        schedule.run_pending()
        time.sleep(1)


# 🔹 Nueva función para evitar reinicios dobles por Flask
def start_scheduler():
    """Inicia el scheduler solo si Flask no está en modo recarga"""
    global scheduler_running

    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":  # Solo ejecuta si Flask no está recargando
        print("⚠️ Flask se está recargando. No iniciaré otro scheduler.")
        return

    with scheduler_lock:
        if scheduler_running:
            print("⚠️ El scheduler ya estaba en ejecución. No se iniciará otro.")
            return  

        scheduler_thread = threading.Thread(target=run_scheduler, name="SchedulerThread", daemon=True)
        scheduler_thread.start()
        print("✅ Scheduler iniciado correctamente.")


# 🚀 **Iniciar el scheduler solo si no está en ejecución**
if not scheduler_running:
    configure_schedule()  # Asegura que las tareas están programadas antes de iniciar
    start_scheduler()


# Flask routes
@app.route("/send_email")
def send_email_route():
    data = get_data_from_db()
    if data:
        send_email(data)
        return "Correo enviado correctamente."
    return "No se obtuvieron datos para enviar el correo."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
