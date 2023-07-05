FROM python:3.9-alpine

RUN apk --no-cache add \
    bash \
    curl \
    gcc \
    musl-dev  

RUN pip install --upgrade pip

RUN addgroup -S kopf && adduser -D -h /home/opc -s /bin/bash opc -G kopf

USER opc

WORKDIR /home/opc

COPY requirements.txt requirements.txt

RUN pip install --no-cache-dir --user -r requirements.txt

ENV PATH="/home/opc/.local/bin:${PATH}"

COPY --chown=opc:kopf ./app/ /home/opc/app/

# RUN ls -ltr /home/opc/app
RUN chmod +x /home/opc/app/entrypoint.sh

ENTRYPOINT ["/bin/bash", "-c", "/home/opc/app/entrypoint.sh"]