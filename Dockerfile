FROM python:3.8-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends git && \
    apt-get purge -y --auto-remove && \
    rm -rf /var/lib/apt/lists/*

WORKDIR .

ENV PYTHONUNBUFFERED 1

# install required packages
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# copy config files
COPY . .

# start the Bot
CMD ["python", "FateBot.py"]
