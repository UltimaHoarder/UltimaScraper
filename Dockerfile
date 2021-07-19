# Sets python:latest as the builder.
FROM python:latest as builder

# Updates and installs required Linux dependencies.
RUN set -eux \
    && apt-get -y update \
    && apt-get -y upgrade \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Installs required Python dependencies.
COPY requirements.txt /onlyfans/
WORKDIR /onlyfans
RUN pip install -r requirements.txt

# Sets python:slim as the release image.
FROM python:slim as release

# Defines new group and user for security reasons.
RUN groupadd -r onlyfans \
    && useradd -r -g onlyfans onlyfans

# Updates and installs required Linux dependencies.
RUN set -eux \
    && apt-get -y update \
    && apt-get -y upgrade \
    && apt-get install -y \
        libpq-dev \
        vim \
    \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copies Linux binaries, and Python packages from the main builder.
COPY --from=builder /usr/local/bin/ /usr/local/bin/
COPY --from=builder /usr/local/lib/python3.9/site-packages/ /usr/local/lib/python3.9/site-packages/

# Copies the source code from the host into the container.
COPY --chown=onlyfans:onlyfans . /onlyfans
WORKDIR /onlyfans

# Ensures that Python output will be sent to the terminal.
ENV PYTHONUNBUFFERED 1

# Changes to the new user for security reasons.
USER onlyfans
