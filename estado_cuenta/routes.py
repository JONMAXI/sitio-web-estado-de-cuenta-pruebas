from flask import Blueprint, render_template, request, session
import requests
from datetime import datetime
from utils import safe_int, safe_float, safe_date, parse_cuotas_field, extraer_numero_cuota
from auditoria import auditar_estado_cuenta
from config import TOKEN, ENDPOINT

estado_cuenta_bp = Blueprint('estado_cuenta', __name__)

def procesar_estado_cuenta(estado_cuenta):
    # Aquí va tu código completo de procesamiento de cargos y pagos (igual que tu script original)
    # Devuelve lista de cargos con pagos aplicados, total_pagado, pendiente, excedente
    return []  # placeholder para simplificar ejemplo

@estado_cuenta_bp.route('/', methods=['GET','POST'])
def index():
    if 'usuario' not in session:
        return redirect('/login')

    if request.method=='POST':
        id_credito = request.form['idCredito']
        fecha_corte = request.form['fechaCorte'].strip()
        try:
            datetime.strptime(fecha_corte,"%Y-%m-%d")
        except ValueError:
            return render_template("index.html", error="Fecha inválida", fecha_actual_iso=fecha_corte)

        payload = {"idCredito": int(id_credito), "fechaCorte": fecha_corte}
        headers = {"Token": TOKEN, "Content-Type":"application/json"}
        try:
            res = requests.post(ENDPOINT,json=payload,headers=headers,timeout=15)
            data = res.json()
        except Exception:
            auditar_estado_cuenta(session['usuario']['username'], id_credito, fecha_corte, 0, "Respuesta no válida")
            return render_template("resultado.html", error="Respuesta no válida del servidor")

        if res.status_code != 200 or "estadoCuenta" not in data:
            mensaje = data.get("mensaje",["Error desconocido"])[0] if data else "No se encontraron datos"
            auditar_estado_cuenta(session['usuario']['username'], id_credito, fecha_corte, 0, mensaje)
            return render_template("resultado.html", error=mensaje)

        estado_cuenta = data["estadoCuenta"]
        auditar_estado_cuenta(session['usuario']['username'], id_credito, fecha_corte, 1, None)
        tabla = procesar_estado_cuenta(estado_cuenta)
        return render_template("resultado.html", datos=estado_cuenta, resultado=tabla)

    fecha_actual_iso = datetime.now().strftime("%Y-%m-%d")
    return render_template("index.html", fecha_actual_iso=fecha_actual_iso)
