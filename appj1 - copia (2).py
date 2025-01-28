import os
from sqlite3 import Row
from tkinter.tix import ROW  
import pymysql
from flask import Flask, render_template
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from db_config import DB_CONFIG
from email.mime.image import MIMEImage
import json


app = Flask(__name__)

# Función para cargar la configuración desde un JSON
def load_email_config(config_file="config.json"):
    try:
        with open(config_file, "r") as file:
            return json.load(file)
    except Exception as e:
        print(f"Error al cargar el archivo de configuración: {e}")
        return {"cc": [], "cco": []}


# Función para obtener datos de la base de datos
def get_data_from_db():
    query = """
    SELECT 
        vehiculo.name,
        vehiculo.description,
        vehiculo.tipo,
        vehiculo.marca,
        vehiculo.itv,
        DATE_FORMAT(vehiculo.fecha_prxima_i_t_v, '%d/%m/%Y') AS fecha_prxima_i_t_v ,
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
        # Conexión a la base de datos
        connection = pymysql.connect(
            host=DB_CONFIG["host"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
            database=DB_CONFIG["database"],
            port=DB_CONFIG["port"]
        )
        with connection.cursor() as cursor:
            # Ejecuta la consulta
            cursor.execute(query)
            # Obtiene los resultados
            results = cursor.fetchall()
            # Devolver valores
            return results
    except Exception as e:
        print(f"Error al conectar con la base de datos: {e}")
        return None
    finally:
        connection.close()

# Función para enviar correo electrónico
def send_email(data):
    smtp_server = "smtp.office365.com"
    smtp_port = 587
    smtp_user = "sistemas@tabisam.es"
    smtp_password = "J1rm3t5$$"

    # Cargar configuración de CC y CCO
    email_config = load_email_config()
    print(f"Configuración cargada: {email_config}")
    cc_emails = email_config.get("cc", [])
    cco_emails = email_config.get("cco", [])
    
    for row in data:
        # Extraer los datos del destinatario y del vehículo
        conductor_first_name = row[6]
        vehiculo_name = row[0]
        fecha_prxima_i_t_v = row[5]

        # Verificar si 'dias_restantes' cumple las condiciones
        dias_restantes = row[14]
        if dias_restantes in [31, 25, 20, 15] or dias_restantes < 12:

            # Renderizar contenido dinámico desde la plantilla
            html_content = render_template(
                "email_template.html",
                conductor={"first_name": conductor_first_name},
                vehiculo={"name": vehiculo_name, "fecha_prxima_i_t_v": fecha_prxima_i_t_v}
            )

            # Configurar el mensaje de correo
            msg = MIMEMultipart("related")
            msg["From"] = "sistemas@tabisam.es"
            msg["To"] = "josemaria.hernandez@tabisam.es" 
            msg["Subject"] = "Notificación de Inspección Técnica de Vehículos"

            # Agregar CC y CCO al mensaje
            if cc_emails:
                msg["Cc"] = ", ".join(cc_emails)  # Correos en CC
            if cco_emails:
                msg["Bcc"] = ", ".join(cco_emails)  # Correos en CCO

            # Adjuntar la parte HTML
            msg_alternative = MIMEMultipart("alternative")
            msg.attach(msg_alternative)
            msg_alternative.attach(MIMEText(html_content, "html"))

            # Adjuntar la imagen embebida
            with open("static/image001.png", "rb") as img_file:
                mime_image = MIMEImage(img_file.read())
                mime_image.add_header("Content-ID", "<logo_tabisam>")
                mime_image.add_header("Content-Disposition", "inline", filename="image001.png")
                msg.attach(mime_image)

            # Enviar el correo
            try:
                with smtplib.SMTP(smtp_server, smtp_port) as server:
                    server.set_debuglevel(0)  # valor (1) = Activa msg de depuración ; (0) desactiva msg de depuración del servidor SMTP
                    server.starttls()
                    server.login(smtp_user, smtp_password)
                    server.send_message(msg)
                    print(f"Correo enviado correctamente a {row[13]}.")
            except Exception as e:
                print(f"Error al enviar el correo a {row[13]}: {e}")
 
        else:
            print(f"No se envió el correo para {row[0]} porque 'dias_restantes' {row[14]}  no cumple las condiciones '[31, 25, 20, 15] or dias_restantes < 12'.")
        

# Ruta para enviar correo de prueba
@app.route("/send_email")
def send_email_route():
    data = get_data_from_db()
    if data:
        send_email(data)
        return "Correo enviado correctamente."
    else:
        return "No se obtuvieron datos para enviar el correo."

# Ruta para ver los datos recuperados
@app.route("/view_data")
def view_data():
    data = get_data_from_db()
    return render_template("email_template.html", content=str(data))

if __name__ == "__main__":
    # Obtiene el puerto desde la variable de entorno, por defecto usa 5000
    port = int(os.environ.get("PORT", 5000))
    # Ejecuta la aplicación en el host "0.0.0.0" y el puerto definido
    app.run(host="0.0.0.0", port=port, debug=True)
