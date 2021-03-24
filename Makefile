IMAGE=juliohm/k8s-nfs-provisioner
TAG=1.2.7

build:
	docker build -t $(IMAGE):latest .

push: build
	docker tag $(IMAGE):latest $(IMAGE):$(TAG)
	docker push $(IMAGE):latest
	docker push $(IMAGE):$(TAG)

install:
	kubectl apply -f installation

uninstall:
	kubectl delete -f installation
