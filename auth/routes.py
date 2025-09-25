from flask import Blueprint, request, render_template, session, redirect
import hashlib
import mysql.connector
from config import DB_CONFIG

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        username = request.form['username']
        password = hashlib.sha256(request.form['password'].encode()).hexdigest()
        try:
            conn = mysql.connector.connect(**DB_CONFIG)
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT * FROM usuarios WHERE username=%s AND password=%s", (username,password))
            user = cur.fetchone()
            cur.close()
            conn.close()
        except Exception as e:
            return f"Error DB: {e}"

        if user:
            session['usuario'] = {'username': user['username'], 'nombre_completo': user['nombre_completo'], 'puesto': user['puesto'], 'grupo': user['grupo']}
            return redirect('/')
        else:
            return render_template("login.html", error="Credenciales inválidas")
    return render_template("login.html")

@auth_bp.route('/logout')
def logout():
    session.pop('usuario', None)
    return redirect('/login')
