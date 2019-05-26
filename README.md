# Kubernetes NFS Volume Provisioner

## Introduction

A somewhat flexible Kubernetes controller that can provision NFS Persistent Volumes in a consistent and predictable way. It relies on the `kubectl` binary as a robust API client to watch for PersistentVolumeClaim events and react in order to provision PersistentVolumes accordingly.

## Installation

Before you can use this controller, please note a few things.

### Requirements and Considerations

This controller **does not** provide an NFS server to your cluster. You will need at least one NFS service accessible in your network, and this controller will not give you that.

### Install using helm

You can also use a helm chart created for this project. The chart is hosted in [one of my Github repositories](https://github.com/juliohm1978/charts). First, add the repo to your local helm installation.

```shell
helm repo add juliohm1978 https://raw.githubusercontent.com/juliohm1978/charts/master/index
helm repo up
```

*OPTIONAL*: Edit `values.yaml` to declare your StorageClasses.

Now, use the chart `juliohm1978/k8s-nfs-provisioner`.

```shell
helm upgrade --install -f myvalues.yaml nfsprov juliohm1978/k8s-nfs-provisioner
```

Uninstall should be a straight forward `helm del`.

```shell
helm del --purge nfsprov
```

### StorageClasses

The provisioner controller can automatically create subdirectories and adjust permissions in the NFS share before delivering PVs to the cluster. In order to use this feature, the NFS shares used by your StorageClasses must be mounted into the controller Pod as volumes. Using the provided helm chart, you can declare StorageClasses in your `values.yaml`. They will be deployed along with the controller and mounted for you. Inside the controller Pod, these will be mounted at:

```text
/mnt/nfs/<StorageClassName>
```

If you deploy the controller without using the helm chart, you will need to provide these volumes manually.

### The controller runs as root

In order to provide PV Data Initialization, the controller runs as root inside its container. Please consider this if you have restrictions to Pods running with elevated privileges in your cluster.

### Cutomize your deployment

To further customize your deployment, take a look at the chart [`values.yaml`](https://github.com/juliohm1978/charts/tree/master/charts/k8s-nfs-provisioner) for details.

## How to use it

Once installed, you should have a single `Pod` managed by a simple `Deployment`. There are no services or ingresses to be exposed, since all work is done in-cluster.

The StorageClasses you declare must use the provisioner `nfs-provisioner.juliohm.com.br` in order for its events to be picked up by the controller. You can declare as many StorageClasses as you want with different parameters and different servers.

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
  ## NOTE: When removed, reclaim policies will be applied.
  ## Optional
  ## Default: false
  keepPv: "false"

  ## Marks the readOnly flag in the PV NFS definition.
  ## In the PersistentVolume, refers to the field .spec.nfs.readOnly
  ## Optional
  ## Default: false
  readOnly: "false"
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
    nvs-provisioner.juliohm.com.br/mode: "755"
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

**IMPORTANT**: In order for this feature to work, the controller Pod needs to have access to the same NFS share declared in your StorageClass. In practice, that means the NFS share must be mounted on the controller at `/nfs/<storage-class-name>`. Using the provided helm chart, this should farily easy. Simply declare your StorageClasses in your `values.yaml` for deployment. If you are not using helm, you will need to declare all necessary volume mounts in the controller Pod manually.

## Controller command line options

The controller itself accepts a few command line options. They allow debugging information to be shown and some options to be defined globally.

| Option | Description |
|---|---|
| `--kubeconfig`    | Kube config file to load. Default: `~/.kube/config`. In-cluster credentials are loaded first and take precedence. If the controller realizes it's running inside a Kubernetes Pod, this argument will be ignored. |
| `--disablePvInit` | Globally disable PV initialization. When disabled, the controller will not attempt to mount the NFS share to adjust directories and permissions before delivering the PV. |
| `--namespace`     | Restrict all StorageClasses to one particular namespace. If this value is defined, The `namespace` parameter in all StorageClasses will be ignored. |
| `--interval`      | Polling interval, in seconds, on the Kubernetes API. Default 30. |
| `--debugLevel`    | Adjust log level displayed on stdout. Possible values: error, warning, info, debug. Default: info. |
| `--nfsVersion`    | Which version of NFS mount to use. Possible values: 3 or 4. Default: 4. |

## Troubleshooting

In case of problems, you can always check the output of the controller's Pod using kubectl directly. It should print any Exception stacktraces if there are any. I tried to include as many relevant log messages as possible to make sure you can see what exactly the controller is trying to do at any time. If you need to see more details, you can increase verbosity by adjusting the `debugLevel`, which is one of the controller's command line arguments.

If the controller is having problems mounting the NFS share to provide PV Data Initialization, you might want to try changing the NFS version used by the controller using the `nfsVersion` argument.
