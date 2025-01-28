import json
import os

def load_email_config(config_file="config.json"):
    try:
        print(f"Intentando cargar archivo JSON desde: {os.path.abspath(config_file)}")
        with open(config_file, "r", encoding="utf-8") as file:
            config = json.load(file)
            print("Configuración cargada correctamente:")
            print(json.dumps(config, indent=4))  # Imprime el contenido de manera legible
            return config
    except Exception as e:
        print(f"Error al cargar el archivo de configuración: {e}")
        return {"cc": [], "cco": []}

if __name__ == "__main__":
    config = load_email_config("config.json")

    # Mostrar CC y CCO si existen
    if config.get("cc"):
        print("Correos en CC:")
        print(config["cc"])
    else:
        print("No hay correos en CC.")

    if config.get("cco"):
        print("Correos en CCO:")
        print(config["cco"])
    else:
        print("No hay correos en CCO.")
