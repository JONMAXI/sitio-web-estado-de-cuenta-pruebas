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
# ------------------ PROCESAR ESTADO DE CUENTA ------------------
def procesar_estado_cuenta(estado_cuenta):
    try:
        # Obtenemos cargos y pagos del estado de cuenta
        cargos = estado_cuenta.get("datosCargos") or []
        if not isinstance(cargos, list):
            cargos = []

        pagos = estado_cuenta.get("datosPagos") or []
        if not isinstance(pagos, list):
            pagos = []

        pagos_list = []

        # ------------------ PREPARAR PAGOS ------------------
        for p in pagos:
            monto_pago = safe_float(p.get("montoPago"), 0.0)
            extemporaneos = safe_float(p.get("extemporaneos"), 0.0)
            monto_real = max(monto_pago - extemporaneos, 0.0)
            cuotas = _parse_cuotas_field(p.get("numeroCuotaSemanal"))

            pagos_list.append({
                "idPago": p.get("idPago"),
                "remaining": monto_real,
                "cuotas": cuotas,
                "fechaValor": p.get("fechaValor"),
                "fechaRegistro": p.get("fechaRegistro"),
                "montoPagoOriginal": monto_pago,
                "extemporaneos": extemporaneos,
                "_extemporaneo_aplicado": False  # marcador para evitar duplicados
            })

        # ------------------ ORDENAR CARGOS ------------------
        cargos_sorted = sorted(cargos, key=lambda c: safe_int(c.get("idCargo"), 0))
        tabla = []

        # ------------------ PROCESAR CADA CARGO ------------------
        for cargo in cargos_sorted:
            concepto = cargo.get("concepto", "")
            cuota_num = _extraer_numero_cuota(concepto)
            if cuota_num is None:
                cuota_num = safe_int(cargo.get("idCargo"))

            monto_cargo = safe_float(cargo.get("monto"))
            capital = safe_float(cargo.get("capital"))
            interes = safe_float(cargo.get("interes"))
            seguro_total = sum(safe_float(cargo.get(k)) for k in ["seguroBienes", "seguroVida", "seguroDesempleo"])
            fecha_venc = cargo.get("fechaVencimiento")

            monto_restante_cargo = monto_cargo
            aplicados = []

            # ------------------ APLICAR PAGOS A LA CUOTA ------------------
            for pago in pagos_list:
                if cuota_num not in pago["cuotas"]:
                    continue

                # Aplicar monto real del pago
                if monto_restante_cargo > 0 and pago["remaining"] > 0:
                    aplicar = min(pago["remaining"], monto_restante_cargo)
                    aplicados.append({
                        "idPago": pago.get("idPago"),
                        "montoPago": round(pago["remaining"], 2),
                        "aplicado": round(aplicar, 2),
                        "fechaRegistro": pago.get("fechaRegistro"),
                        "fechaPago": fecha_venc,
                        "diasMora": None,
                        "extemporaneos": 0.0
                    })
                    pago["remaining"] = max(round(pago["remaining"] - aplicar, 2), 0)
                    monto_restante_cargo = max(round(monto_restante_cargo - aplicar, 2), 0)

                # Registrar extemporáneos solo una vez por pago
                if pago.get("extemporaneos", 0.0) > 0 and not pago["_extemporaneo_aplicado"]:
                    aplicados.append({
                        "idPago": pago.get("idPago"),
                        "montoPago": round(pago["extemporaneos"], 2),
                        "aplicado": round(pago["extemporaneos"], 2),
                        "fechaRegistro": pago.get("fechaRegistro"),
                        "fechaPago": fecha_venc,
                        "diasMora": None,
                        "extemporaneos": pago.get("extemporaneos", 0.0)
                    })
                    pago["_extemporaneo_aplicado"] = True  # marcamos como aplicado

            total_aplicado = round(monto_cargo - monto_restante_cargo, 2)
            pendiente = round(max(monto_cargo - total_aplicado, 0.0), 2)
            excedente = max(round(total_aplicado - monto_cargo, 2), 0.0)

            tabla.append({
                "cuota": cuota_num,
                "fecha": fecha_venc,
                "monto_cargo": round(monto_cargo, 2),
                "capital": round(capital, 2),
                "interes": round(interes, 2),
                "seguro": round(seguro_total, 2),
                "aplicados": aplicados,
                "total_pagado": total_aplicado,
                "pendiente": pendiente,
                "excedente": excedente,
                "raw_cargo": cargo
            })

        return tabla

    except Exception as e:
        print(f"[ERROR] procesar_estado_cuenta: {e}")
        return []


# ------------------ BÚSQUEDA DE CRÉDITO ------------------
def buscar_credito_por_nombre(nombre):
    db_clientes = os.environ.get('DB_NAME_CLIENTES')
    if not db_clientes:
        print("[DB ERROR] Variable de entorno DB_NAME_CLIENTES no definida")
        return []

    query = """
        SELECT id_credito, id_cliente, Nombre_cliente, Fecha_inicio
        FROM lista_cliente
        WHERE Nombre_cliente LIKE %s
        LIMIT 1000
    """
    resultados = []
    with get_connection(db_clientes) as conn:
        if conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(query, (f"%{nombre}%",))
            resultados = cursor.fetchall()
            cursor.close()
    return resultados

# ------------------ RUTAS ------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = hashlib.sha256(request.form['password'].encode()).hexdigest()
        try:
            with get_connection() as conn:
                if not conn:
                    return "Error de conexión a la base de datos", 500
                cur = conn.cursor(dictionary=True)
                cur.execute("SELECT * FROM usuarios WHERE username = %s AND password = %s", (username, password))
                user = cur.fetchone()
                cur.close()
        except Exception as err:
            return f"Error de conexión a MySQL: {err}"

        if user:
            session['usuario'] = {
                'username': user['username'],
                'nombre_completo': user['nombre_completo'],
                'puesto': user['puesto'],
                'grupo': user['grupo']
            }
            return redirect('/')
        else:
            return render_template("login.html", error="Credenciales inválidas")
    return render_template("login.html")

@app.route('/logout')
def logout():
    session.pop('usuario', None)
    return redirect('/login')
#----------------------------------------------------

@app.route('/', methods=['GET', 'POST'])
def index():
    if 'usuario' not in session:
        return redirect('/login')

    fecha_actual_iso = datetime.now().strftime("%Y-%m-%d")

    if request.method == 'POST':
        nombre_busqueda = request.form.get('nombre', '').strip()
        id_credito_form = request.form.get('idCredito', '').strip()
        fecha_corte = request.form.get('fechaCorte', '').strip() or fecha_actual_iso

        # Validación de fecha
        try:
            datetime.strptime(fecha_corte, "%Y-%m-%d")
        except ValueError as ve:
            print(f"[DEBUG] Fecha inválida: {ve}")
            return render_template("index.html", error="Fecha inválida", fecha_actual_iso=fecha_corte)

        # Búsqueda por nombre o ID
        resultados = []
        try:
            if nombre_busqueda:
                resultados = buscar_credito_por_nombre(nombre_busqueda)
                if not resultados:
                    return render_template("index.html", error="No se encontraron créditos con ese nombre", fecha_actual_iso=fecha_corte)
                if len(resultados) > 1:
                    return render_template("index.html", resultados=resultados, fecha_actual_iso=fecha_corte)
                id_credito = resultados[0]['id_credito']
            elif id_credito_form:
                try:
                    id_credito = int(id_credito_form)
                except ValueError as ve:
                    print(f"[DEBUG] ID de crédito inválido: {ve}")
                    return render_template("index.html", error="ID de crédito inválido", fecha_actual_iso=fecha_corte)
            else:
                return render_template("index.html", error="Debes proporcionar nombre o ID de crédito", fecha_actual_iso=fecha_corte)
        except Exception as e:
            print(f"[DEBUG] Error buscando crédito: {e}")
            return render_template("index.html", error="Error buscando crédito", fecha_actual_iso=fecha_corte)

        # Llamada API externa
        payload = {"idCredito": int(id_credito), "fechaCorte": fecha_corte}
        headers = {"Token": TOKEN, "Content-Type": "application/json"}
        try:
            res = requests.post(ENDPOINT, json=payload, headers=headers, timeout=15)
            data = res.json()
        except Exception as e:
            print(f"[DEBUG] Error llamando API externa: {e}")
            auditar_estado_cuenta(session['usuario']['username'], id_credito, fecha_corte, 0, "Respuesta no válida del servidor")
            return render_template("resultado.html", error="Respuesta no válida del servidor")

        if res.status_code != 200 or "estadoCuenta" not in data:
            mensaje = data.get("mensaje", ["Error desconocido"])[0] if data else "No se encontraron datos para este crédito"
            auditar_estado_cuenta(session['usuario']['username'], id_credito, fecha_corte, 0, mensaje)
            print(f"[DEBUG] API retornó error o datos faltantes: {mensaje}")
            return render_template("resultado.html", error=mensaje)

        estado_cuenta = data["estadoCuenta"]
        if (
            not estado_cuenta.get("idCredito")
            and not estado_cuenta.get("datosCliente")
            and not estado_cuenta.get("datosCargos")
            and not estado_cuenta.get("datosPagos")
        ):
            auditar_estado_cuenta(session['usuario']['username'], id_credito, fecha_corte, 0, "Crédito vacío")
            print(f"[DEBUG] Crédito vacío para id_credito={id_credito}")
            return render_template("resultado.html", usuario_no_existe=True)

        # -------------------- Traer datos de referencias con debug --------------------
        try:
            datos_referencias = obtener_datos_cliente(id_credito)
            if not datos_referencias:
                print(f"[DEBUG] No se encontraron referencias para id_credito={id_credito}")
            estado_cuenta["datosReferencias"] = datos_referencias or {}
        except Exception as e:
            print(f"[DEBUG] Error al obtener datos de referencias para id_credito={id_credito}: {e}")
            estado_cuenta["datosReferencias"] = {}
        # ----------------------------------------------------------------------

        try:
            auditar_estado_cuenta(session['usuario']['username'], id_credito, fecha_corte, 1, None)
            tabla = procesar_estado_cuenta(estado_cuenta)
        except Exception as e:
            print(f"[DEBUG] Error procesando estado de cuenta para id_credito={id_credito}: {e}")
            return render_template("resultado.html", error="Error procesando estado de cuenta")

        return render_template("resultado.html", datos=estado_cuenta, resultado=tabla)

    # GET
    return render_template("index.html", fecha_actual_iso=fecha_actual_iso)
####-----------------------------------------------------------------------------------

@app.route('/documentos', methods=['GET', 'POST'])
def documentos():
    if 'usuario' not in session:
        return redirect('/login')
    return render_template("consulta_documentos.html")

# ------------------ DESCARGA DE DOCUMENTOS ------------------
# ------------------ DESCARGA DE DOCUMENTOS CON WATERMARK ------------------


def agregar_watermark(pdf_bytes: BytesIO, watermark_text="SIN VALOR") -> BytesIO:
    """Agrega watermark diagonal repetido a cada página del PDF."""
    from PyPDF2 import PdfReader, PdfWriter
    from reportlab.pdfgen import canvas
    import io

    reader = PdfReader(pdf_bytes)
    writer = PdfWriter()

    for page in reader.pages:
        # Obtener tamaño de la página
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)

        # Crear watermark temporal del tamaño exacto de la página
        packet = io.BytesIO()
        can = canvas.Canvas(packet, pagesize=(width, height))
        can.setFont("Helvetica-Bold", 50)
        can.setFillColorRGB(1, 0, 0, alpha=0.3)
        step_x = 200
        step_y = 150
        angle = -45
        for y in range(-int(height), int(height*2), step_y):
            for x in range(-int(width), int(width*2), step_x):
                can.saveState()
                can.translate(x + step_x/2, y + step_y/2)
                can.rotate(angle)
                can.drawCentredString(0, 0, watermark_text)
                can.restoreState()
        can.save()
        packet.seek(0)

        watermark_pdf = PdfReader(packet)
        page.merge_page(watermark_pdf.pages[0])
        writer.add_page(page)

    salida = BytesIO()
    writer.write(salida)
    salida.seek(0)
    return salida
@app.route('/descargar/<id>')
def descargar(id):
    if 'usuario' not in session:
        return "No autorizado", 403

    tipo = request.args.get('tipo', 'INE')
    usuario = session['usuario']['username']

    try:
        # -------------------- INE --------------------
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

            # Descargar imágenes
            urls = {
                "Frente": f"http://54.167.121.148:8081/s3/downloadS3File?fileName=INE/{idCliente}_frente.jpeg",
                "Reverso": f"http://54.167.121.148:8081/s3/downloadS3File?fileName=INE/{idCliente}_reverso.jpeg"
            }
            imgs = []
            faltantes = []
            for k, u in urls.items():
                r = requests.get(u, timeout=10)
                if r.status_code != 200:
                    faltantes.append(k)
                else:
                    img = Image.open(BytesIO(r.content)).convert("RGB")
                    img.info['dpi'] = (150, 150)
                    imgs.append(img)
            if faltantes:
                auditar_documento(usuario, "INE", "INE completo", id, 0, f"No se encontraron los archivos: {', '.join(faltantes)}")
                return f"No se encontraron los archivos: {', '.join(faltantes)}", 404

            # Crear PDF en memoria
            pdf_bytes = BytesIO()
            imgs[0].save(pdf_bytes, format='PDF', save_all=True, append_images=imgs[1:])
            pdf_bytes.seek(0)

            # Agregar watermark
            pdf_bytes = agregar_watermark(pdf_bytes, watermark_text="SIN VALOR")

            auditar_documento(usuario, "INE", "INE completo", id, 1, None)
            filename = f"{id}_INE.pdf"
            return Response(
                pdf_bytes.read(),
                mimetype='application/pdf',
                headers={"Content-Disposition": _content_disposition_inline(filename)}
            )

        # -------------------- PDFs existentes --------------------
        elif tipo in ("Factura", "Contrato", "FAD_DOC"):
            if tipo == "Factura":
                url = f"http://54.167.121.148:8081/s3/downloadS3File?fileName=FACTURA/{id}_factura.pdf"
                filename = f"{id}_factura.pdf"
            elif tipo == "Contrato":
                url = f"http://54.167.121.148:8081/s3/downloadS3File?fileName=VALIDACIONES/{id}_validaciones.pdf"
                filename = f"{id}_validaciones.pdf"
            elif tipo == "FAD_DOC":
                # Aquí asumimos que ya resolviste nombre_archivo como en tu código
                pk = int(id)
                with get_connection(database=DB3_NAME, use_rds=True) as conn:
                    cursor = conn.cursor(dictionary=True)
                    cursor.execute("""
                        SELECT nombre_archivo FROM oferta_documentos
                        WHERE tipo_documento='FAD' AND fk_oferta=%s
                    """, (pk,))
                    row = cursor.fetchone()
                    cursor.close()
                if not row:
                    return "Documento no encontrado", 404
                safe_name = os.path.basename(row['nombre_archivo'])
                url = f"http://54.167.121.148:8081/s3/downloadS3File?fileName=FAD/{urllib.parse.quote(safe_name)}"
                filename = safe_name

            # Descargar
            r = requests.get(url, timeout=10)
            if r.status_code != 200:
                return "Archivo no encontrado", 404

            # Detectar PDF o imagen
            _, ext = os.path.splitext(filename.lower())
            if ext == '.pdf':
                pdf_bytes = BytesIO(r.content)
            else:  # Convertir imagen a PDF
                img = Image.open(BytesIO(r.content)).convert("RGB")
                img.info['dpi'] = (150, 150)
                pdf_bytes = BytesIO()
                img.save(pdf_bytes, format='PDF')
            pdf_bytes.seek(0)

            # Agregar watermark
            pdf_bytes = agregar_watermark(pdf_bytes, watermark_text="SIN VALOR")

            return Response(
                pdf_bytes.read(),
                mimetype='application/pdf',
                headers={"Content-Disposition": _content_disposition_inline(filename)}
            )

        else:
            return "Tipo de documento no válido", 400

    except Exception as e:
        return f"Error interno: {e}", 500

# ------------------ INICIO ------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
