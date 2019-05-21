IMAGE=juliohm/k8s-nfs-provisioner
TAG=1.0

build:
	docker build --squash -t $(IMAGE):latest .

push: build
	docker tag $(IMAGE):latest $(IMAGE):$(TAG)
	docker push $(IMAGE):latest
	docker push $(IMAGE):$(TAG)

install:
	kubectl apply -f installation/serviceaccount.yaml
	kubectl apply -f installation/deployment.yaml

uninstall:
	kubectl delete -f installation/serviceaccount.yaml
	kubectl delete -f installation/deployment.yaml
