FROM python:3.10-slim
WORKDIR /app
RUN pip install --no-cache-dir paho-mqtt pandas
COPY simulateur.py .
ENV PYTHONUNBUFFERED=1
CMD ["python", "simulateur.py"]