FROM python:3.9.4-alpine3.13

RUN pip install jinja2 kubernetes

COPY rootfs /

STOPSIGNAL 9

ENTRYPOINT ["/usr/local/bin/controller.py"]
