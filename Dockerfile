# ----------------------------
# Etapa 1: Builder
# ----------------------------
FROM python:3.11-slim-bullseye AS builder

# Evita buffering de logs
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

# Carpeta de trabajo
WORKDIR /app

# Copia requirements e instala dependencias
COPY requirements.txt .
RUN pip install --prefix=/install --no-cache-dir -r requirements.txt

# Copia el código fuente
COPY . .

# ----------------------------
# Etapa 2: Imagen final
# ----------------------------
FROM python:3.11-slim-bullseye

ENV PORT=8080
WORKDIR /app

# Copia las dependencias instaladas en la etapa builder
COPY --from=builder /install /usr/local
COPY --from=builder /app /app

# Expone el puerto para Cloud Run
EXPOSE 8080

# Comando para iniciar tu app
CMD ["python", "app.py"]
