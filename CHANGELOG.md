# CHANGELOG

## 2019-05-23 1.2

Change the way PV Data Initialization works so that it won't need a Pod running with `privileged: true` flag. This requires all NFS shares be mounted into the controller Pod as volumes.

## 2019-05-23 1.1

Fix issue [#2 Error: argument of type 'NoneType' is not iterable](https://github.com/juliohm1978/kubernetes-nfs-volume-provisioner/issues/2)

## 2019-05-22 1.0

First release
