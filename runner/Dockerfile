FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends g++ && rm -rf /var/lib/apt/lists/*
COPY sandbox.py /opt/ib/sandbox.py
ENV PYTHONDONTWRITEBYTECODE=1
WORKDIR /work
USER 65534:65534
ENTRYPOINT ["python", "-I", "/opt/ib/sandbox.py"]
