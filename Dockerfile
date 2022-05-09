FROM python:3.10-slim

RUN apt-get update && apt-get install -y \
  curl \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/app

ENV POETRY_HOME=/usr/local/share/pypoetry
ENV POETRY_VIRTUALENVS_CREATE=false

RUN ["/bin/bash", "-c", "set -o pipefail && curl -sSL https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py | python -"]

COPY pyproject.toml poetry.lock ./
RUN /usr/local/share/pypoetry/bin/poetry install --no-dev

COPY . .

CMD [ "/usr/local/share/pypoetry/bin/poetry", "run", "python", "./start_ofd.py" ]
