FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p logs

EXPOSE 8501

ENV PORT=8501

CMD streamlit run app.py \
    --server.address=0.0.0.0 \
    --server.port=$PORT \
    --server.headless=true \
    --browser.gatherUsageStats=false
