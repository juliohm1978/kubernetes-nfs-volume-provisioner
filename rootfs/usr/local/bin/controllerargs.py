import argparse

p = argparse.ArgumentParser(
    description="""

A Kubernetes controller that uses kubectl as a full featured API client to
provision NFS volumes in the cluster. When a PersistentVolumeClaim (PVC) is
created, this controller will look for an associated StorageClass and use it to prepare and deliver
a PersistentVolume (PV) to match that PVC. When the PVC is removed, the associated
PV will also be removed.

All options to control how the PV is provisioned can be declared in the
StorageClass or the PVC. Some options can be overriden globally via command
line options passed directly to this controller.

""")

p.add_argument(
    "--kubeconfig",
    default="~/.kube/config",
    help="Kubectl config file to load. In-cluster credentials take precedence over this argument. Mostly useful for local testing and debug. If the controller can load in-cluster credentials, this argument is ignored."
)

p.add_argument(
    "--nfsroot",
    default="/mnt/nfs",
    help="Directory where all NFS shares should be mounted to allow PV Data Initialization. If --disablePvInit is given, this argument will be ignored."
)

p.add_argument(
    "--disablePvInit",
    action="store_true",
    default=False,
    help="Disable PV initialization."
)

p.add_argument(
    "--namespace",
    help="Restrict the controller actions to a specific namespace."
)

p.add_argument(
    "--interval",
    type=int,
    default=30,
    help="Interval between checks for new PVCs in the cluster."
)

p.add_argument(
    "--debugLevel",
    default="info",
    metavar="LEVEL",
    help="Change the debug level for the logging package to either error, warning, info or debug. Default: info"
)

