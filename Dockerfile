# Usa una imagen base de Python
FROM python:3.9-slim

# Establece el directorio de trabajo en /app
WORKDIR /app

# Copia el script de Python y cualquier otro archivo necesario en el contenedor
COPY app.py /app/

# Si tienes otras dependencias, puedes copiarlas e instalarlas aquí
# Supongamos que tienes un archivo requirements.txt con las dependencias
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Ejecuta el script de Python por defecto al iniciar el contenedor
CMD ["python", "app.py"]