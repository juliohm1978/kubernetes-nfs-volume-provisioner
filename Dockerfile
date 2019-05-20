FROM ubuntu:18.04

ENV KUBECTL_VERSION=v1.14.1

RUN apt-get update

RUN apt-get install -y python3-pip python3-setuptools

RUN pip3 install jinja2

ADD "https://storage.googleapis.com/kubernetes-release/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" /usr/local/bin/kubectl

RUN chmod +x /usr/local/bin/kubectl

COPY rootfs /
