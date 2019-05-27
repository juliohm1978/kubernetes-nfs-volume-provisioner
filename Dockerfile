FROM python:3.7.3-alpine3.9

RUN pip install jinja2 kubernetes

RUN chmod +x /usr/local/bin/kubectl

COPY rootfs /

STOPSIGNAL 9

ENTRYPOINT ["/usr/local/bin/controller.py"]
