FROM ubuntu:18.04

ENV KUBECTL_VERSION=1.14.1

RUN apt-get update

RUN apt-get install -y python3-pip python3-setuptools

RUN pip3 install jinja2
