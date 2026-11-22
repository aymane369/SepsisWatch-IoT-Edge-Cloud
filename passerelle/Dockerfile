FROM python:3.10-slim
WORKDIR /app
RUN pip install --no-cache-dir "paho-mqtt>=2.0" confluent-kafka
COPY passerelle.py features.py modele.json tampon.py apprentissage.py ./
ENV PYTHONUNBUFFERED=1
CMD ["python", "passerelle.py"]