FROM python:slim

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

RUN pip install -i https://pypi.tuna.tsinghua.edu.cn/simple pip -U \
    && pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

COPY . /app/

RUN cd /app \
    && ( pip install --no-cache-dir -r requirements.txt || true ) 

WORKDIR /jav

CMD ["python", "/app/Movie_Data_Capture.py"]
