from flask import Blueprint, request, session, Response, redirect
import requests
from io import BytesIO
from PIL import Image
from datetime import datetime
from auditoria import auditar_documento
from config import TOKEN, ENDPOINT

documentos_bp = Blueprint('documentos', __name__)

@documentos_bp.route('/documentos', methods=['GET', 'POST'])
def documentos():
    if 'usuario' not in session:
        return redirect('/login')
    return render_template("consulta_documentos.html")


@documentos_bp.route('/descargar/<id>')
def descargar(id):
    if 'usuario' not in session:
        return "No autorizado", 403

    tipo = request.args.get('tipo', 'INE')
    usuario = session['usuario']['username']

    try:
        # ------------------ DESCARGA INE ------------------
        if tipo == 'INE':
            fecha_corte = datetime.now().strftime("%Y-%m-%d")
            payload = {"idCredito": int(id), "fechaCorte": fecha_corte}
            headers = {"Token": TOKEN, "Content-Type": "application/json"}
            res = requests.post(ENDPOINT, json=payload, headers=headers, timeout=15)
            data = res.json() if res.ok else None

            if not data or "estadoCuenta" not in data:
                auditar_documento(usuario, "INE", "INE completo", id, 0, "Crédito no encontrado o sin datosCliente")
                return "Crédito no encontrado o sin datosCliente", 404

            idCliente = data["estadoCuenta"].get("datosCliente", {}).get("idCliente")
            if not idCliente:
                auditar_documento(usuario, "INE", "INE completo", id, 0, "No se encontró idCliente")
                return "No se encontró idCliente para este crédito", 404

            # URLs de archivos
            url_frente = f"http://54.167.121.148:8081/s3/downloadS3File?fileName=INE/{idCliente}_frente.jpeg"
            url_reverso = f"http://54.167.121.148:8081/s3/downloadS3File?fileName=INE/{idCliente}_reverso.jpeg"
            r1 = requests.get(url_frente)
            r2 = requests.get(url_reverso)

            faltantes = []
            if r1.status_code != 200: faltantes.append("Frente")
            if r2.status_code != 200: faltantes.append("Reverso")
            if faltantes:
                auditar_documento(usuario, "INE", "INE completo", id, 0, f"No se encontraron los archivos: {', '.join(faltantes)}")
                return f"No se encontraron los archivos: {', '.join(faltantes)}", 404

            # Combinar en PDF
            img1 = Image.open(BytesIO(r1.content)).convert("RGB")
            img2 = Image.open(BytesIO(r2.content)).convert("RGB")
            pdf_bytes = BytesIO()
            img1.save(pdf_bytes, format='PDF', save_all=True, append_images=[img2])
            pdf_bytes.seek(0)

            auditar_documento(usuario, "INE", "INE completo", id, 1, None)
            return Response(pdf_bytes.read(),
                            mimetype='application/pdf',
                            headers={"Content-Disposition": f"inline; filename={id}_INE.pdf"})

        # ------------------ DESCARGA CEP ------------------
        elif tipo == 'CEP':
            url = f"http://54.167.121.148:8081/s3/downloadS3File?fileName=CEP/{id}_cep.jpeg"
            r = requests.get(url)
            if r.status_code != 200:
                auditar_documento(usuario, "CEP", "CEP completo", id, 0, "Archivo CEP no encontrado")
                return "Archivo CEP no encontrado", 404

            auditar_documento(usuario, "CEP", "CEP completo", id, 1, None)
            return Response(r.content, mimetype='image/jpeg',
                            headers={"Content-Disposition": f"inline; filename={id}_CEP.jpeg"})

        # ------------------ DESCARGA CONTRATO ------------------
        elif tipo == 'Contrato':
            url = f"http://54.167.121.148:8081/s3/downloadS3File?fileName=VALIDACIONES/{id}_validaciones.pdf"
            r = requests.get(url)
            if r.status_code != 200:
                auditar_documento(usuario, "Contrato", "Contrato validaciones", id, 0, "Cliente no encontrado")
                return "Cliente no encontrado en la Base de Datos", 404

            auditar_documento(usuario, "Contrato", "Contrato validaciones", id, 1, None)
            return Response(r.content, mimetype='application/pdf',
                            headers={"Content-Disposition": f"inline; filename={id}_Contrato.pdf"})

        else:
            auditar_documento(usuario, tipo, tipo, id, 0, "Tipo de documento no válido")
            return "Tipo de documento no válido", 400

    except Exception as e:
        auditar_documento(usuario, tipo, tipo, id, 0, f"Error interno: {e}")
        return "Error interno del servidor", 500
