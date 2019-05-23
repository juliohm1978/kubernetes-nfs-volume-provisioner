FROM python:3.7.3-alpine3.9

ENV KUBECTL_VERSION=v1.14.1

RUN apk add --update nfs-utils

RUN pip install jinja2 kubernetes

ADD "https://storage.googleapis.com/kubernetes-release/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" /usr/local/bin/kubectl

RUN chmod +x /usr/local/bin/kubectl

COPY rootfs /

STOPSIGNAL 9

ENTRYPOINT ["/usr/local/bin/controller.py"]
