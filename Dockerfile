FROM python:3.12-slim

ENV PYTHONFAULTHANDLER=1 \
  PYTHONUNBUFFERED=1 \
  PYTHONHASHSEED=random \
  PIP_NO_CACHE_DIR=off \
  PIP_DISABLE_PIP_VERSION_CHECK=on \
  PIP_DEFAULT_TIMEOUT=100 \
  POETRY_VERSION=2.0.1\
  POETRY_VIRTUALENVS_CREATE=false \
  POETRY_CACHE_DIR='/var/cache/pypoetry'\
  PYTHONPATH='/opt/:$PYTHONPATH'

EXPOSE 8000

RUN apt-get update \
  && apt-get install -y --no-install-recommends libpq5 openssl \
  && apt-get autoremove -y && apt-get clean -y && rm -rf /var/lib/apt/lists/* \
  && pip install idna "poetry==$POETRY_VERSION" && poetry --version

RUN mkdir -p /opt/services/app/src
WORKDIR /opt/services/app/src

COPY . /opt/services/app/src
COPY ./boot.sh /boot.sh

RUN poetry config installer.max-workers 10

# Project initialization:
RUN poetry install

RUN chmod +x /boot.sh
