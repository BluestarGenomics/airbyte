FROM python:3.9.11-alpine3.15 as base

# build and load all requirements
FROM base as builder
WORKDIR /airbyte/integration_code

# upgrade pip to the latest version
RUN apk --no-cache upgrade \
    && pip install --upgrade pip \
    && apk --no-cache add tzdata build-base g++ gcc libxslt-dev


COPY setup.py ./
# install necessary packages to a temporary folder
RUN pip install --prefix=/install .

# build a clean environment
FROM base
WORKDIR /airbyte/integration_code

# copy all loaded and built libraries to a pure basic image
COPY --from=builder /install /usr/local
# add default timezone settings
COPY --from=builder /usr/share/zoneinfo/Etc/UTC /etc/localtime
RUN echo "Etc/UTC" > /etc/timezone
# lxml dependencies
COPY --from=builder /usr/lib/libxslt.so.1 /usr/lib/libxslt.so.1
COPY --from=builder /usr/lib/libexslt.so.0 /usr/lib/libexslt.so.0
COPY --from=builder /usr/lib/libxml2.so.2 /usr/lib/libxml2.so.2
COPY --from=builder /usr/lib/libgcrypt.so.20 /usr/lib/libgcrypt.so.20
COPY --from=builder /usr/lib/libgpg-error.so.0 /usr/lib/libgpg-error.so.0

# bash is installed for more convenient debugging.
RUN apk --no-cache add bash

# copy payload code only
COPY main.py ./
COPY source_medrio ./source_medrio

ENV AIRBYTE_ENTRYPOINT "python /airbyte/integration_code/main.py"
ENTRYPOINT ["python", "/airbyte/integration_code/main.py"]

LABEL io.airbyte.version=0.1.1
LABEL io.airbyte.name=airbyte/source-medrio
