from flask import Flask
from auth.routes import auth_bp
from estado_cuenta.routes import estado_cuenta_bp
from documentos.routes import documentos_bp

app = Flask(__name__)
app.secret_key = 'clave_super_secreta'

# Registrar blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(estado_cuenta_bp)
app.register_blueprint(documentos_bp)

if __name__=="__main__":
    import os
    port = int(os.environ.get("PORT",8080))
    app.run(host="0.0.0.0", port=port)
