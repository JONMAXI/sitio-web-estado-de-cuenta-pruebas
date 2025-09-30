from flask import Flask, render_template, request, redirect, session, Response
import requests
from datetime import datetime
import hashlib
import os
from io import BytesIO
from PIL import Image
import re
from db import get_connection
from db_queries import obtener_datos_cliente
from db_queries import DB3_NAME
import mimetypes
import urllib.parse
from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
import tempfile

app = Flask(__name__)
app.secret_key = 'clave_super_secreta'

# ------------------ CONFIGURACIÓN API EXTERNA ------------------
TOKEN = "3oJVoAHtwWn7oBT4o340gFkvq9uWRRmpFo7p"
ENDPOINT = "https://servicios.s2movil.net/s2maxikash/estadocuenta"

# ------------------ UTILIDADES ------------------
def _extraer_numero_cuota(concepto):
    if not concepto:
        return None
    m = re.search(r'CUOTA.*?(\d+)\s+DE', concepto, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m2 = re.search(r'(\d+)', concepto)
    if m2:
        return int(m2.group(1))
    return None

def _parse_cuotas_field(value):
    if value is None:
        return []
    if isinstance(value, (int, float)):
        return [int(value)]
    if isinstance(value, str):
        parts = [p.strip() for p in value.split(',') if p.strip()]
        out = []
        for p in parts:
            try:
                out.append(int(p))
            except:
                pass
        return out
    return []

def safe_float(value, default=0.0):
    try:
        return float(value)
    except (ValueError, TypeError):
        return default

def safe_int(value, default=0):
    try:
        return int(value)
    except (ValueError, TypeError):
        return default

def safe_date(date_str, fmt="%Y-%m-%d %H:%M:%S"):
    try:
        return datetime.strptime(date_str, fmt)
    except (ValueError, TypeError):
        return None

# ------------------ MARCA DE AGUA ------------------
def agregar_marca_agua(pdf_bytes: bytes, texto="SIN VALOR") -> bytes:
    """
    Recibe un PDF en bytes, le agrega marca de agua diagonal 'SIN VALOR'
    y devuelve los bytes del nuevo PDF.
    """
    try:
        # Crear PDF temporal con marca de agua
        tmp_watermark = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        c = canvas.Canvas(tmp_watermark.name, pagesize=letter)
        c.saveState()
        c.setFont("Helvetica-Bold", 60)
        c.setFillGray(0.6, 0.5)  # gris semitransparente
        c.translate(300, 400)
        c.rotate(45)
        c.drawCentredString(0, 0, texto)
        c.restoreState()
        c.save()
        tmp_watermark.close()

        # Mezclar con el PDF original
        original_reader = PdfReader(BytesIO(pdf_bytes))
        watermark_reader = PdfReader(tmp_watermark.name)
        writer = PdfWriter()

        watermark_page = watermark_reader.pages[0]
        for page in original_reader.pages:
            page.merge_page(watermark_page)
            writer.add_page(page)

        output = BytesIO()
        writer.write(output)
        output.seek(0)
        return output.read()

    except Exception as e:
        print(f"[MARCA DE AGUA] Error: {e}")
        return pdf_bytes

# ------------------ AUDITORÍA ------------------
def auditar_estado_cuenta(usuario, id_credito, fecha_corte, exito, mensaje_error=None):
    try:
        with get_connection() as conn:
            if not conn:
                return
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO auditoria_estado_cuenta (usuario, id_credito, fecha_corte, exito, mensaje_error)
                VALUES (%s, %s, %s, %s, %s)
            """, (usuario, id_credito, fecha_corte, exito, mensaje_error))
            conn.commit()
            cur.close()
    except Exception as e:
        print(f"[AUDITORIA] Error registrando estado de cuenta: {e}")

def auditar_documento(usuario, documento_clave, documento_nombre, id_referencia, exito, mensaje_error=None):
    try:
        with get_connection() as conn:
            if not conn:
                return
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO auditoria_documentos (usuario, documento_clave, documento_nombre, id_referencia, exito, mensaje_error)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (usuario, documento_clave, documento_nombre, id_referencia, exito, mensaje_error))
            conn.commit()
            cur.close()
    except Exception as e:
        print(f"[AUDITORIA] Error registrando documento: {e}")

# ------------------ PROCESAR ESTADO DE CUENTA ------------------
# (Mantengo tu función procesar_estado_cuenta igual, no la repito aquí por espacio)

# ------------------ RUTAS ------------------
# (Mantengo login, logout e index igual, no los repito aquí por espacio)

@app.route('/documentos', methods=['GET', 'POST'])
def documentos():
    if 'usuario' not in session:
        return redirect('/login')
    return render_template("consulta_documentos.html")

# ------------------ DESCARGA DE DOCUMENTOS ------------------
@app.route('/descargar/<id>')
def descargar(id):
    if 'usuario' not in session:
        return "No autorizado", 403

    tipo = request.args.get('tipo', 'INE')
    usuario = session['usuario']['username']

    try:
        # ------------------ Función interna para agregar marca de agua ------------------
        from PyPDF2 import PdfReader, PdfWriter
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import letter
        from io import BytesIO

        def agregar_marca_agua(pdf_bytes: BytesIO, texto="SIN VALOR") -> BytesIO:
            pdf_bytes.seek(0)
            lector = PdfReader(pdf_bytes)
            escritor = PdfWriter()

            for pagina in lector.pages:
                # Crear una marca de agua temporal
                packet = BytesIO()
                can = canvas.Canvas(packet, pagesize=letter)
                can.setFont("Helvetica-Bold", 50)
                can.setFillColorRGB(1, 0, 0, alpha=0.3)  # rojo con transparencia
                can.saveState()
                can.translate(300, 400)
                can.rotate(45)
                can.drawCentredString(0, 0, texto)
                can.restoreState()
                can.save()
                packet.seek(0)

                watermark = PdfReader(packet)
                pagina.merge_page(watermark.pages[0])
                escritor.add_page(pagina)

            out_bytes = BytesIO()
            escritor.write(out_bytes)
            out_bytes.seek(0)
            return out_bytes
        # ------------------------------------------------------------------------------

        if tipo == 'INE':
            fecha_corte = datetime.now().strftime("%Y-%m-%d")
            payload = {"idCredito": int(id), "fechaCorte": fecha_corte}
            headers = {"Token": TOKEN, "Content-Type": "application/json"}
            res = requests.post(ENDPOINT, json=payload, headers=headers, timeout=10)
            data = res.json() if res.ok else None

            if not data or "estadoCuenta" not in data:
                auditar_documento(usuario, "INE", "INE completo", id, 0, "Crédito no encontrado o sin datosCliente")
                return "Crédito no encontrado o sin datosCliente", 404

            idCliente = data["estadoCuenta"].get("datosCliente", {}).get("idCliente")
            if not idCliente:
                auditar_documento(usuario, "INE", "INE completo", id, 0, "No se encontró idCliente")
                return "No se encontró idCliente para este crédito", 404

            url_frente = f"http://54.167.121.148:8081/s3/downloadS3File?fileName=INE/{idCliente}_frente.jpeg"
            url_reverso = f"http://54.167.121.148:8081/s3/downloadS3File?fileName=INE/{idCliente}_reverso.jpeg"
            r1 = requests.get(url_frente, timeout=10)
            r2 = requests.get(url_reverso, timeout=10)

            faltantes = []
            if r1.status_code != 200:
                faltantes.append("Frente")
            if r2.status_code != 200:
                faltantes.append("Reverso")
            if faltantes:
                auditar_documento(usuario, "INE", "INE completo", id, 0, f"No se encontraron los archivos: {', '.join(faltantes)}")
                return f"No se encontraron los archivos: {', '.join(faltantes)}", 404

            # Convertir imágenes a PDF
            img1 = Image.open(BytesIO(r1.content)).convert("RGB")
            img2 = Image.open(BytesIO(r2.content)).convert("RGB")
            img1.info['dpi'] = (150, 150)
            img2.info['dpi'] = (150, 150)
            pdf_bytes = BytesIO()
            img1.save(pdf_bytes, format='PDF', save_all=True, append_images=[img2])
            pdf_bytes.seek(0)

            # Agregar marca de agua
            pdf_bytes_con_marca = agregar_marca_agua(pdf_bytes, "SIN VALOR")

            auditar_documento(usuario, "INE", "INE completo", id, 1, None)
            filename = f"{id}_INE.pdf"
            return Response(
                pdf_bytes_con_marca.read(),
                mimetype='application/pdf',
                headers={"Content-Disposition": _content_disposition_inline(filename)}
            )

        elif tipo == 'Factura':
            url = f"http://54.167.121.148:8081/s3/downloadS3File?fileName=FACTURA/{id}_factura.pdf"
            r = requests.get(url, timeout=10)
            if r.status_code != 200:
                auditar_documento(usuario, "Factura", "Factura", id, 0, "Archivo Factura no encontrado")
                return "Archivo Factura no encontrado", 404

            pdf_bytes = BytesIO(r.content)
            pdf_bytes_con_marca = agregar_marca_agua(pdf_bytes, "SIN VALOR")

            auditar_documento(usuario, "Factura", "Factura completo", id, 1, None)
            filename = f"{id}_factura.pdf"
            return Response(
                pdf_bytes_con_marca.read(),
                mimetype='application/pdf',
                headers={"Content-Disposition": _content_disposition_inline(filename)}
            )

        elif tipo == 'Contrato':
            url = f"http://54.167.121.148:8081/s3/downloadS3File?fileName=VALIDACIONES/{id}_validaciones.pdf"
            r = requests.get(url, timeout=10)
            if r.status_code != 200:
                auditar_documento(usuario, "Contrato", "Contrato validaciones", id, 0, "Cliente no encontrado en la Base de Datos")
                return "Cliente no encontrado en la Base de Datos", 404

            pdf_bytes = BytesIO(r.content)
            pdf_bytes_con_marca = agregar_marca_agua(pdf_bytes, "SIN VALOR")

            auditar_documento(usuario, "Contrato", "Contrato validaciones", id, 1, None)
            filename = f"{id}_validaciones.pdf"
            return Response(
                pdf_bytes_con_marca.read(),
                mimetype='application/pdf',
                headers={"Content-Disposition": _content_disposition_inline(filename)}
            )

        elif tipo == 'FAD_DOC':
            try:
                pk = int(id)
            except ValueError:
                auditar_documento(usuario, "FAD_DOC", "FAD_DOC", id, 0, "ID inválido para FAD_DOC")
                return "ID inválido", 400

            sql = """
            SELECT nombre_archivo
            FROM oferta_documentos
            WHERE tipo_documento = 'FAD' AND fk_oferta = %s
            """
            with get_connection(database=DB3_NAME, use_rds=True) as conn:
                if not conn:
                    auditar_documento(usuario, "FAD_DOC", "FAD_DOC", id, 0, "No se pudo conectar a la DB")
                    return "Error de conexión con la base de datos", 500
                cursor = conn.cursor(dictionary=True)
                cursor.execute(sql, (pk,))
                row = cursor.fetchone()
                cursor.close()

            if not row or not row.get("nombre_archivo"):
                auditar_documento(usuario, "FAD_DOC", "FAD_DOC", id, 0, "Documento no encontrado o sin nombre")
                return "Documento no encontrado en la base de datos", 404

            safe_name = os.path.basename(row["nombre_archivo"])
            url = f"http://54.167.121.148:8081/s3/downloadS3File?fileName=FAD/{urllib.parse.quote(safe_name)}"
            r = requests.get(url, timeout=10)
            if r.status_code != 200:
                auditar_documento(usuario, "FAD_DOC", "FAD_DOC", id, 0, f"Archivo {safe_name} no encontrado en S3")
                return "Archivo no encontrado en S3", 404

            _, ext = os.path.splitext(safe_name.lower())

            if ext == '.pdf':
                pdf_bytes = BytesIO(r.content)
                pdf_bytes_con_marca = agregar_marca_agua(pdf_bytes, "SIN VALOR")
                auditar_documento(usuario, "FAD_DOC", "FAD_DOC", id, 1, None)
                return Response(
                    pdf_bytes_con_marca.read(),
                    mimetype='application/pdf',
                    headers={"Content-Disposition": _content_disposition_inline(safe_name)}
                )

            elif ext in ('.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp'):
                img = Image.open(BytesIO(r.content)).convert("RGB")
                img.info['dpi'] = (150, 150)
                pdf_bytes = BytesIO()
                img.save(pdf_bytes, format='PDF')
                pdf_bytes.seek(0)

                pdf_bytes_con_marca = agregar_marca_agua(pdf_bytes, "SIN VALOR")
                auditar_documento(usuario, "FAD_DOC", "FAD_DOC", id, 1, None)
                filename = os.path.splitext(safe_name)[0] + '.pdf'
                return Response(
                    pdf_bytes_con_marca.read(),
                    mimetype='application/pdf',
                    headers={"Content-Disposition": _content_disposition_inline(filename)}
                )

            else:
                # Archivos desconocidos -> solo descargar binario
                ctype = r.headers.get('Content-Type') or mimetypes.guess_type(safe_name)[0] or 'application/octet-stream'
                auditar_documento(usuario, "FAD_DOC", "FAD_DOC", id, 1, None)
                return Response(
                    r.content,
                    mimetype=ctype,
                    headers={"Content-Disposition": _content_disposition_inline(safe_name)}
                )

        else:
            auditar_documento(usuario, tipo, tipo, id, 0, "Tipo de documento no válido")
            return "Tipo de documento no válido", 400

    except Exception as e:
        auditar_documento(usuario, tipo, tipo, id, 0, f"Error interno: {e}")
        return "Error interno al procesar el documento", 500
# ------------------ INICIO ------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
