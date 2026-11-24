# Plotline environment image: data pipeline, semantic layer, SQL, Python, dashboard, MCP and LLM access.
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOST=0.0.0.0 PORT=8765
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8765
# First start downloads Land Registry data (~565 MB) into the warehouse volume and builds DuckDB.
CMD ["sh", "-c", "[ -f 1_data/warehouse.duckdb ] || python 1_data/ingest.py; python -m plotline.publish && exec python -m plotline.server"]
