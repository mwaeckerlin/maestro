FROM python:slim
WORKDIR /tests
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install --with-deps chromium
COPY conftest.py test_*.py ./
