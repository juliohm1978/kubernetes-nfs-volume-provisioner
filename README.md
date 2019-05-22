# Kubernetes NFS Volume Provisioner

## Introduction

A somewhat flexible Kubernetes controller that can provision NFS Persistent Volumes in a consistent and predictable way. It relies on the `kubectl` binary as a robust API client to watch for PersistentVolumeClaim events and react in order to provision PersistentVolumes accordingly.

## Installation

Before you can use this controller, please note a few things.

### Requirements and Considerations

This controller **does not** provide an NFS server to your cluster. You will need at least one NFS service accessible in your network, and this controller will not give you that.

If you wish to use the PV Data Initalization feature (details below), the NFS servers used in your StorageClasses should be available to the Pod running this controller. In order to prepare directories and permissions inside the NFS share, the controller needs be able to mount it before creating the PersistentVolume.

**IMPORTANT:** This also means the controller Pod must run with `privileged: true` so it can perform `mount -t nfs` inside the cluster.

In some cases, privileged containers are not allowed in the cluster. You can still run the controller without privilege escalation and disable PV initalization with command line arguments to the controller. Without this feature, directory and permissions inside the NFS share cannot be adjusted automatically, but the controller can still create PersistentVolumes assuming those steps will be done manually.

### Install using kubectl

For a quick local test, you can use `kubectl` directly. Use the files included in the `installation` directory. The easiest way is to call the `install` or `uninstall` targets in the `Makefile` provided. This will create all objects in the `default` namespace, and provides a way to get the controller running for a quick test.

```shell
# install
make install

# remove
make unisntall
```

### Install using helm

You can also use a helm chart created for this project. It allows a more unique deployment and allow you to use a namespace other than `default`. The chart is hosted in [one of my Github repositories](https://github.com/juliohm1978/charts). First, add the repo to your local helm installation.

```shell
helm repo add juliohm1978 https://raw.githubusercontent.com/juliohm1978/charts/master/index
helm repo up
```

Now, use the chart `juliohm1978/k8s-nfs-provisioner`.

```shell
helm upgrade --install nfsprov juliohm1978/k8s-nfs-provisioner
```

Uninstall should be a straight forward `helm del`.

```shell
helm del --purge nfsprov
```

To further customize your deployment, take a look at the chart [`values.yaml`](https://github.com/juliohm1978/charts/tree/master/charts/k8s-nfs-provisioner) for details.

## How to use it

Once installed, you should have a single `Pod` managed by a simple `Deployment`. There are no services or ingresses to be exposed, since all its work is doe in-cluster.

At thispoint, you should create `StorageClass` objects in you cluster providing a number of values on how NFS volumes will be provisioned. You can declare as many StorageClasses as you want with different parameters. All they need in common the field `provisioner: nfs-provisioner.juliohm.com.br`.

Here's a full example:

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: sc01
provisioner: nfs-provisioner.juliohm.com.br
parameters:
  pvNamePrefix: ""
  server: 10.10.10.3
  share: /myshare
  path: /subpath
  namespace: some-namespace
  keepPv: "false"
reclaimPolicy: Delete
```

Now, with `sc01` defined, you can create PersistentVolumeClaims using your StorageClass.

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: myclaim
  namespace: default
spec:
  accessModes:
    - ReadWriteOnce
  volumeMode: Filesystem
  resources:
    requests:
      storage: 8Gi
  storageClassName: sc01
```

The controller will pick up on that claim and create the corresponding PersistentVolume, which would look similar to:

```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  labels:
    nfs-provisioner.juliohm.com.br/pvcName: myclaim
    nfs-provisioner.juliohm.com.br/pvcNamespace: default
    nfs-provisioner.juliohm.com.br/storageClassName: sc01
  name: default-myclaim
spec:
  accessModes:
  - ReadWriteOnce
  capacity:
    storage: 8Gi
  claimRef:
    apiVersion: v1
    kind: PersistentVolumeClaim
    name: myclaim
    namespace: default
    uid: 54aff2d6-7a84-11e9-8f64-641c678d3d92
  nfs:
    path: /myshare/subpath/default-myclaim
    server: 10.10.10.3
  persistentVolumeReclaimPolicy: Delete
  storageClassName: sc01
  volumeMode: Filesystem
status:
  phase: Bound
```

Metadata from the StorageClass and PVC are used to create the PV.

> **IMPORTANT**: The PV will contain some special labels related to the StorageClass and PVC used to create it. You should avoid removing or modifying these labels, since they help the controller find PVs that need to be removed from the cluster when their PVC counterparts are no longer available.

The StorageClass parameters may be quite self explanatory, but here is a rundown of what each one means:

```yaml
parameters:
  ## A prefix that should be placed on all PV names created from this StorageClass.
  ## Optional
  ## Default: empty
  pvNamePrefix: ""

  ## Remote NFS server
  ## Required
  server: 10.10.10.3

  ## Share name on the remote NFS server
  ## Required
  share: /myshare

  ## A subdirectory inside the share
  ## Optional
  ## Default: /
  path: /subpath

  ## Namespace to which this StorageClass should be restricted to.
  ## The controller will react to PVC events only from this namespace.
  ## Optional
  ## Default: empty (meaning, react to all PVC events in the cluster)
  namespace: some-namespace

  ## If "true", the PV object will not be removed when the PVC is deleted.
  ## NOTE: Reclaim policies from this StorageClass will be applied to all PVs
  ## removed from the cluster: RETAIN or DELETE.
  ## Optional
  ## Default: false
  keepPv: "false"
```

The controller uses the StorageClass parameters and the PVC metadata to fully provision the NFS volume. It is possible to use several PersistentVolumes on the same remote NFS share without conflict. To keep storage access unique, a PV will point exactly to:

```text
<REMOTE_SERVER> : <SHARE> + [PATH] + <PVC_NAMESPACE-PVC_NAME>
```

In the above example, the PV provisioned points to:

```text
10.10.10.3:/myshare/subpath/default-myclaim
```

As expected by Kubernetes, the `/subpath/default-myclaim` subdirectories **SHOULD** exist in the remote NFS share. Otherwise, the volume mount inside a Pod will fail.

## PV Data Initialization

To make your life easier, the controller can automatically create that unique path inside the NFS share and adjust owner and permissions before it delivers the PersistentVolume. This can be configured with annotations in the PVC.

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: myclaim
  annotations:
    nvs-provisioner.juliohm.com.br/init-perms: "true"
    nvs-provisioner.juliohm.com.br/uid: "1000"
    nvs-provisioner.juliohm.com.br/gid: "1000"
    nvs-provisioner.juliohm.com.br/mode: "644"
spec:
  accessModes:
    - ReadWriteOnce
  volumeMode: Filesystem
  resources:
    requests:
      storage: 8Gi
  storageClassName: sc01
```

When the `init-perms` annotation is `true`, the controller will attempt to mount the NFS share temporarily and create the subdirectories `/subpath/default-myclaim`. It will use the values from `uid`, `gid` and `mode` to adjust directory owner and permissions. If this initialization step fails, the PV will not be created.

These annotations allow PVs to be fully provisioned, making sure its volume directories exist on the remote NFS server with the correct owner and permissions.

**IMPORTANT**: In order for this feature to work, the controller Pod needs to run with `privileged: true`. If privileged Pods are not allowed in your cluster, you can safely disable the privilege escalation and run the controller with this feature disabled. For that, take a look at the [helm chart values.yaml](https://github.com/juliohm1978/charts/blob/master/charts/k8s-nfs-provisioner/values.yaml) and change the values of `privileged` and `args.disablePvInit` for your deployment.

## Controller command line options

The controller itself accepts a few command line options. They allow debugging information to be shown and some options to be defined globally.

| Option | Description |
|---|---|
| `--disablePvInit` | Globally disable PV initialization. When disabled, the controller will not attempt to mount the NFS share to adjust directories and permissions before delivering the PV. |
| `--namespace`     | Restrict all StorageClasses to one particular namespace. If this value is defined, The `namespace` parameter in all StorageClasses will be ignored. |
| `--interval`      | Polling interval, in seconds, on the Kubernetes API. Default 30. |
| `--debugLevel`    | Adjust log level displayed on stdout. Possible values: error, warning, info, debug. Default: info. |
