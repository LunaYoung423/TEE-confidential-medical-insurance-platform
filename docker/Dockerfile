FROM docker.m.daocloud.io/library/python:3.8-slim

RUN rm -f /etc/apt/sources.list.d/* \
 && echo "deb https://mirrors.aliyun.com/debian bookworm main contrib non-free" > /etc/apt/sources.list \
 && echo "deb https://mirrors.aliyun.com/debian-security bookworm-security main contrib non-free" >> /etc/apt/sources.list \
 && echo "deb https://mirrors.aliyun.com/debian bookworm-updates main contrib non-free" >> /etc/apt/sources.list

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ make wget ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ \
 && pip config set global.timeout 600

COPY module1/requirements.txt /tmp/requirements-module1.txt
COPY module2/requirements.txt /tmp/requirements-module2.txt
COPY module3/requirements.txt /tmp/requirements-module3.txt

# snowland_smx 自带完整 pysmx（SM3 含 KDF 等，SM2 依赖之）；禁止整体替换 SM3/__init__.py，否则会丢 KDF。
# gmssl 供 attestation_agent 的 SM4 等；smx 作 csv-attestation 兜底导入。
RUN pip install --no-cache-dir --default-timeout=600 -r /tmp/requirements-module1.txt \
 && pip install --no-cache-dir --default-timeout=600 -r /tmp/requirements-module2.txt \
 && pip install --no-cache-dir --default-timeout=600 -r /tmp/requirements-module3.txt \
 && pip install --no-cache-dir --default-timeout=600 gmssl smx \
 && wget -qO /tmp/csv-req.txt https://enclave-cn-hangzhou.oss-cn-hangzhou.aliyuncs.com/csv/requirements.txt \
 && pip install --no-cache-dir --default-timeout=600 -r /tmp/csv-req.txt \
 && pip install --no-cache-dir --default-timeout=600 --force-reinstall snowland_smx==0.3.1 \
 && python3 -c "from pysmx.SM2 import Verify; from pysmx.SM3 import digest; print('pysmx SM2+SM3 OK')"

COPY module1/csv-attestation.py /app/csv-attestation.py
RUN chmod +x /app/csv-attestation.py

COPY module1 /app/module1
COPY module2 /app/module2
COPY module3 /app/module3

WORKDIR /app
ENV PYTHONPATH=/app

RUN python3 <<'PY'
import importlib.util
spec = importlib.util.spec_from_file_location("csv_att", "/app/csv-attestation.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
assert callable(m.digest) and callable(m.Verify)
print("csv-attestation: digest + Verify OK")
PY

EXPOSE 8000 8006

CMD ["sh", "-c", "python3 /app/module1/attestation_agent.py & uvicorn module2.main:app --host 0.0.0.0 --port 8000 --workers 2"]
