# CHANGELOG

## 1.2.3-beta

* Fix error message when provisioner name does not match the one declared in the StorageClass.

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
