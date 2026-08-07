# Frontend image — build from the repo root:
#   docker build -f frontend/Dockerfile -t tea-frontend .
FROM python:3.12-slim

WORKDIR /srv
COPY frontend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY frontend/ui.py .
COPY .streamlit ./.streamlit

EXPOSE 8501

CMD ["streamlit", "run", "ui.py", "--server.port=8501", "--server.address=0.0.0.0", \
     "--browser.gatherUsageStats=false"]
