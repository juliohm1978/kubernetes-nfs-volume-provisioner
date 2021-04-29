# CHANGELOG

## 2020-04-29 1.2.8

* Improve PV name provisioning as a hash of the Namespace+PVC string. Avoid using more than the 63 characater limit.
* Bump python version to 3.9.4

## 2020-03-24 1.2.7

* Merge upstream security fixes.

## 2020-02-12 1.2.6

* Add new argument `--forcePvInit` which forces PV initialization without annotations on the PVC.
* Bump version to 1.2.6 to match the helm chart version.

## 2019-05-27 1.2.3

* Fix error message when provisioner name does not match the one declared in the StorageClass.
* Remove nfs-utils from Dockerfile, not needed since v1.2.
* Remove kubectl from Dockerfile, not needed since v1.2.
* Remove --nfsVersion from cmd arguments, not used since v1.2.

## 2019-05-26 1.2.2

* Fix #5 - When --disablePvInit flag is used, PVs are not provisioned
* Fix #6 - mountOptions from StorageClass are not being passed to PV

## 2019-05-24 1.2.1

* Fix annotation mispelling: "nvs" should be "nfs"

## 2019-05-23 1.2

Change the way PV Data Initialization works so that it won't need a Pod running with `privileged: true` flag. This requires all NFS shares be mounted into the controller Pod as volumes.

## 2019-05-23 1.1

Fix issue [#2 Error: argument of type 'NoneType' is not iterable](https://github.com/juliohm1978/kubernetes-nfs-volume-provisioner/issues/2)

## 2019-05-22 1.0

First release
