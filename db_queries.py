# db_queries.py
import os
from db import get_connection

DB3_NAME = os.getenv("DB3_NAME")  # Nombre de la base de datos DB3 en RDS

def buscar_credito_por_nombre(nombre):
    """
    Busca créditos por nombre completo.
    Retorna lista de diccionarios con id_credito y nombre_cliente.
    """
    sql = """
    SELECT o.id_oferta AS id_credito,
           CONCAT(p.primer_nombre, ' ', p.apellido_paterno, ' ', p.apellido_materno) AS Nombre_cliente,
           DATE_FORMAT(o.fecha_inicio, '%Y-%m-%d') AS Fecha_inicio
    FROM oferta o
    INNER JOIN persona p ON o.fk_persona = p.id_persona
    WHERE CONCAT(p.primer_nombre, ' ', p.apellido_paterno, ' ', p.apellido_materno) LIKE %s
    LIMIT 50
    """
    with get_connection(database=DB3_NAME, use_rds=True) as conn:
        if not conn:
            print("[DEBUG] No se pudo conectar a la base de datos DB3")
            return []
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, (f"%{nombre}%",))
        resultados = cursor.fetchall()
        cursor.close()
        return resultados


def obtener_datos_cliente(id_credito):
    """
    Obtiene los datos de un crédito específico, incluyendo referencias.
    Retorna un diccionario con valores seguros (sin None).
    """
    sql = """
    SELECT 
        o.id_oferta AS id_credito,
        CONCAT(p.primer_nombre, ' ', p.apellido_paterno, ' ', p.apellido_materno) AS nombre_completo,
        CONCAT(
            COALESCE(p2.nombre_referencia1,''), ' ',
            COALESCE(p2.apellido_paterno_referencia1,''), ' ',
            COALESCE(p2.apellido_materno_referencia1,'')
        ) AS nombre_completo_referencia1,
        COALESCE(p2.telefono_referencia1,'') AS telefono_referencia1,
        CONCAT(
            COALESCE(p2.nombre_referencia2,''), ' ',
            COALESCE(p2.apellido_paterno_referencia2,''), ' ',
            COALESCE(p2.apellido_materno_referencia2,'')
        ) AS nombre_completo_referencia2,
        COALESCE(p2.telefono_referencia2,'') AS telefono_referencia2,
        '' AS nombre_referencia_3,
        '' AS telefono_referencia_3
    FROM oferta o
    INNER JOIN persona p ON o.fk_persona = p.id_persona
    LEFT JOIN persona_adicionales p2 ON p2.fk_persona = p.id_persona
    WHERE o.id_oferta = %s
    """
    with get_connection(database=DB3_NAME, use_rds=True) as conn:
        if not conn:
            print(f"[DEBUG] No se pudo conectar a DB3 para id_credito={id_credito}")
            return None
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, (id_credito,))
        row = cursor.fetchone()
        cursor.close()

        if not row:
            print(f"[DEBUG] No se encontró registro para id_credito={id_credito}")
            return None

        # Garantiza siempre 3 referencias aunque estén vacías
        for key in [
            "nombre_completo_referencia1", "telefono_referencia1",
            "nombre_completo_referencia2", "telefono_referencia2",
            "nombre_referencia_3", "telefono_referencia_3"
        ]:
            if key not in row or row[key] is None:
                row[key] = ""

        return row
