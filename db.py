# db.py
import os
import mysql.connector
from mysql.connector import Error
from contextlib import contextmanager

@contextmanager
def get_connection(database=None, use_rds=False):
    """
    Context manager que retorna una conexión a la base de datos.

    - Por defecto usa Cloud SQL con unix_socket.
    - Si use_rds=True, usa la conexión RDS (host, puerto, usuario, password).
    - Siempre ajusta la zona horaria a America/Mexico_City.

    Parámetros:
        database (str): nombre de la base de datos a usar. Si es None, usa la principal.
        use_rds (bool): si True, se conecta al RDS de AWS.
    """
    if use_rds:
        db_config = {
            'host': os.environ.get("DB3_HOST", "maxi-base.cluster-csa4gsaishoe.us-east-1.rds.amazonaws.com"),
            'user': os.environ.get("DB3_USER", "jesus.ruvalcaba"),
            'password': os.environ.get("DB3_PASSWORD", "tu_password"),
            'database': database if database else os.environ.get("DB3_NAME", "maxi-prod"),
            'port': int(os.environ.get("DB3_PORT", 3306))
        }
    else:
        db_config = {
            'user': os.environ.get('DB_USER'),
            'password': os.environ.get('DB_PASSWORD'),
            'database': database if database else os.environ.get('DB_NAME'),
            'unix_socket': f"/cloudsql/{os.environ.get('DB_CONNECTION_NAME')}"
        }

    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute("SET time_zone = 'America/Mexico_City';")
        cursor.close()
        yield conn
    except Error as e:
        print(f"[DB ERROR] No se pudo conectar a la base de datos {db_config.get('database')}: {e}")
        yield None
    finally:
        if conn and conn.is_connected():
            conn.close()
