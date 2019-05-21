IMAGE=juliohm/k8s-nfs-provisioner
TAG=1.0

build:
	docker build -t $(IMAGE):latest .

push: build
	docker build --squash -t $(IMAGE):latest
	docker tag $(IMAGE):latest $(IMAGE):$(TAG)
	docker push $(IMAGE):latest
	docker push $(IMAGE):$(TAG)
