FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

RUN pip install --upgrade pip==26.2.2 setuptools==84.2.1 wheel==0.48.0 && \
    pip install future==1.0.0 pexpect==4.9.0 pymavlink==2.4.50 MAVProxy==1.8.75

WORKDIR /app

CMD ["python3", "-m", "MAVProxy.mavproxy"]
