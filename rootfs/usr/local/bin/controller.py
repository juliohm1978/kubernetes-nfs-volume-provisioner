#!/usr/local/bin/python3

import logging
import sys
import random
import string
import subprocess
import json
import jinja2
import time
import kubernetes
import urllib3
import os
import controllerargs

args = controllerargs.p.parse_args()

nfsversion = "nfs"
if args.nfsVersion == "4":
    nfsversion = "nfs4"

PROVISIONER_NAME     = "nfs-provisioner.juliohm.com.br"
ANNOTATION_INITPERMS = "nfs-provisioner.juliohm.com.br/init-perms"
ANNOTATION_UID       = "nfs-provisioner.juliohm.com.br/uid"
ANNOTATION_GID       = "nfs-provisioner.juliohm.com.br/gid"
ANNOTATION_MODE      = "nfs-provisioner.juliohm.com.br/mode"

LABEL_PVCNAME          = "nfs-provisioner.juliohm.com.br/pvcName"
LABEL_PVCNAMESPACE     = "nfs-provisioner.juliohm.com.br/pvcNamespace"
LABEL_STORAGECLASSNAME = "nfs-provisioner.juliohm.com.br/storageClassName"

debuglevel = logging.INFO
if args.debugLevel:
    debuglevel = logging._nameToLevel[args.debugLevel.upper()]

logging.basicConfig(level=debuglevel, format="%(asctime)s [%(levelname)s] %(message)s")

if "KUBERNETES_SERVICE_HOST" in os.environ:
    kubernetes.config.load_incluster_config()
else:
    kubernetes.config.load_kube_config(args.kubeconfig)

coreapi = kubernetes.client.CoreV1Api()
storageapi = kubernetes.client.StorageV1Api()

################################################################################
## Initialize the data inside the NFS share to match specifications defined
## in the StorageClass and PVC. Skip if any flags mark otherwise.
################################################################################
def init_pv_data(pvc, sc):
    pvcfullname = pvc.metadata.namespace + '-' + pvc.metadata.name
    logging.info("PVC "+pvcfullname+". Initializing NFS share directories")

    if pvc.metadata.annotations and ANNOTATION_INITPERMS in pvc.metadata.annotations and pvc.metadata.annotations[ANNOTATION_INITPERMS] == "false":
        return False

    server       = sc.parameters["server"]
    share        = sc.parameters["share"]
    path         = "/"
    if "path" in sc.parameters:
        path = sc.parameters["path"]

    localdir = args.nfsroot + '/' + sc.metadata.name
    if not os.path.exists(localdir):
        logging.error("PVC "+pvcfullname+". Path "+localdir+" does not exist. Mount NFS share here to allow PV Initialization.")
        return False
    if not os.path.isdir(localdir):
        logging.error("PVC "+pvcfullname+". Path "+localdir+" is not a directory. Mount NFS share here to allow PV Initialization.")
        return False

    localdir = localdir + share + path + '/' + pvcfullname

    if ".." in localdir:
        logging.error("PVC "+pvcfullname+". Invalid path "+localdir+". Refusing to initialize PV data")
        return False

    cmd = ["mkdir", "-p", localdir]
    subprocess.check_call(cmd)

    # adjust user permissions
    if ANNOTATION_UID in pvc.metadata.annotations:
        cmd = ["chown", pvc.metadata.annotations[ANNOTATION_UID], localdir]
        subprocess.check_call(cmd)
        logging.debug("PVC "+pvcfullname+". User permissions adjusted for "+pvcfullname+": "+pvc.metadata.annotations[ANNOTATION_UID])

    # adjust group permissions
    if ANNOTATION_GID in pvc.metadata.annotations:
        cmd = ["chgrp", pvc.metadata.annotations[ANNOTATION_GID], localdir]
        subprocess.check_call(cmd)
        logging.debug("PVC "+pvcfullname+". Group permissions adjusted for "+pvcfullname+": "+pvc.metadata.annotations[ANNOTATION_UID])

    # adjust access mode
    if ANNOTATION_MODE in pvc.metadata.annotations:
        cmd = ["chmod", pvc.metadata.annotations[ANNOTATION_MODE], localdir]
        subprocess.check_call(cmd)
        logging.debug("PVC "+pvcfullname+". File permissions adjusted for "+pvcfullname+": "+pvc.metadata.annotations[ANNOTATION_MODE])

    return True

################################################################################
## Provision a new PV for a given PVC
################################################################################
def provision_pv(pvc):
    pvcfullname = pvc.metadata.namespace + "-" + pvc.metadata.name
    scname = str(pvc.spec.storage_class_name)
    
    sc = None
    for item in storageapi.list_storage_class().items:
        if item.metadata.name == scname:
            sc = item
            break
    
    if not sc:
        logging.debug("PVC "+pvcfullname+" StorageClass not found "+scname)
        return
    
    if not sc.provisioner == PROVISIONER_NAME:
        logging.warning("PVC "+pvcfullname+" storageClassName does not match "+PROVISIONER_NAME+". Ingoring event.")
        return

    if args.namespace and pvc.metadata.namespace != args.namespace:
        logging.warning("PVC "+pvcfullname+" namespace does not patch provisioner scope: "+args.namespace+". Ingoring event.")
        return

    if ("namespace" in sc.parameters) and (sc.parameters["namespace"] != pvc.metadata.namespace):
        logging.warning("PVC "+pvcfullname+" namespace does not patch StorageClass scope: "+sc.parameters['namespace']+". Ingoring event.")
        return
    
    pvNamePrefix = None
    server       = None
    share        = "/"
    path         = ""
    readOnly     = False
    mountOptions = None
    keepPv       = False

    if "pvNamePrefix" in sc.parameters:
        pvNamePrefix = sc.parameters["pvNamePrefix"]
    if "server" in sc.parameters:
        server = sc.parameters["server"]
    if "share" in sc.parameters:
        share = sc.parameters["share"]
    if "path" in sc.parameters:
        path = sc.parameters["path"]
    if "readOnly" in sc.parameters and sc.parameters["readOnly"] == "true":
        readOnly = True
    if "mountOptions" in sc.parameters:
        mountOptions = sc.parameters["mountOptions"]
    if "keepPv" in sc.parameters and sc.parameters["keepPv"] == "true":
        keepPv = True

    if not server:
        logging.warning("PVC "+pvcfullname+". StorageClass "+scname+". Missing parameter 'server'. Ingoring event.")
        return

    pvname = pvc.metadata.namespace + "-" + pvc.metadata.name
    if pvNamePrefix:
        pvname = pvNamePrefix + "-" + pvname

    pv = coreapi.list_persistent_volume(field_selector="metadata.name="+pvname)
    if len(pv.items) > 0:
        logging.info("PVC "+pvcfullname+". PV "+pvname+" already exists. Ingoring event.")
        return

    if pvc.metadata.annotations and ANNOTATION_INITPERMS in pvc.metadata.annotations:
        if pvc.metadata.annotations[ANNOTATION_INITPERMS] == "true" and not args.disablePvInit:
            if not init_pv_data(pvc, sc):
                logging.info("PVC "+pvcfullname+". PV "+pvname+" data cannot be initialized. Ingoring event.")
                return

    pv = kubernetes.client.V1PersistentVolume()
    pv.metadata = kubernetes.client.V1ObjectMeta()
    pv.metadata.name = pvname
    pv.metadata.labels = dict()
    pv.metadata.labels[LABEL_PVCNAME] = pvc.metadata.name
    pv.metadata.labels[LABEL_PVCNAMESPACE] = pvc.metadata.namespace
    pv.metadata.labels[LABEL_STORAGECLASSNAME] = scname
    pv.spec = kubernetes.client.V1PersistentVolumeSpec()
    pv.status = kubernetes.client.V1PersistentVolumeStatus()
    if sc.volume_binding_mode and sc.volume_binding_mode.upper() == "IMMEDIATE":
        pv.status.phase             = "Bound"
        pv.spec.claim_ref           = kubernetes.client.V1ObjectReference()
        pv.spec.claim_ref.name      = pvc.metadata.name
        pv.spec.claim_ref.namespace = pvc.metadata.namespace
        pv.spec.claim_ref.uid       = pvc.metadata.uid
    pv.spec.access_modes = pvc.spec.access_modes
    pv.spec.persistent_volume_reclaim_policy = sc.reclaim_policy
    pv.spec.mount_options = list()
    pv.spec.capacity = dict()
    pv.spec.capacity["storage"] = pvc.spec.resources.requests["storage"]
    pv.spec.nfs = kubernetes.client.V1NFSVolumeSource(
        server=server, path=share + path + "/" + pvcfullname, read_only=readOnly)

    coreapi.create_persistent_volume(pv)

    logging.info("PV created successfully "+pvname+", wait for binding to occur")

################################################################################
## Try to delete PV data.
################################################################################
def delete_pv_data(pv, sc):
    server       = sc.parameters["server"]
    share        = sc.parameters["share"]
    path         = "/"
    if "path" in sc.parameters:
        path = sc.parameters["path"]

    localdir = args.nfsroot + '/' + sc.metadata.name
    if not os.path.exists(localdir):
        logging.error("PVC "+pv.metadata.name+". Path "+localdir+" does not exist. Mount NFS share here to allow PV Initialization.")
        return
    if not os.path.isdir(localdir):
        logging.error("PVC "+pv.metadata.name+". Path "+localdir+" is not a directory. Mount NFS share here to allow PV Initialization.")
        return

    localdir = localdir + share + path + '/' + pv.metadata.name

    if ".." in localdir:
        logging.error("PVC "+pv.metadata.name+". Invalid path "+localdir+". Refusing to initialize PV data")
        return

    logging.info("PV "+pv.metadata.name+". Deleting PV data... For large contents, this could take a while.")
    cmd = ["rm", "-rf", localdir]
    subprocess.check_call(cmd)
    logging.info("PV "+pv.metadata.name+". All data deleted successfully.")


################################################################################
## Remove a PV given the PVC that was removed from the cluster
################################################################################
def remove_pv(pvc):
    scname = str(pvc.spec.storage_class_name)
    sc = storageapi.list_storage_class(field_selector="metadata.name="+scname)
    if len(sc.items) <= 0:
        logging.debug("PVC "+pvcfullname+" StorageClass not found "+scname)
        return
    
    sc = sc.items[0]
    
    if not sc.provisioner == PROVISIONER_NAME:
        logging.warning("PVC "+pvcfullname+" storageClassName does not match "+PROVISIONER_NAME+". Ingoring event.")
        return
    if ("namespace" in sc.parameters) and (sc.parameters["namespace"] != pvc.metadata.namespace):
        logging.warning("PVC "+pvcfullname+" namespace does not patch StorageClass scope: "+sc.parameters['namespace']+". Ingoring event.")
        return

    pvname = pvc.spec.volume_name
    if not pvname:
        logging.warning("PVC "+pvcfullname+" is not associated to a volumeName. Ingoring event.")
        return

    if "keepPv" in sc.parameters and sc.parameters["keepPv"] == "true":
        logging.warning("PVC "+pvcfullname+" StorageClass "+scname+" wants to keep the PV. Ignoring event.")
        logging.warning("PVC "+pvcfullname+" This may cause problems to rebind the same PV later.")
        return

    pv = coreapi.list_persistent_volume(field_selector="metadata.name="+pvname).items
    if len(pv) <= 0:
        logging.debug("PVC "+pvcfullname+". PV "+pvname+" already exists. Ingoring event.")
        return
    pv = pv[0]

    coreapi.delete_persistent_volume(name=pvname)
    logging.debug("PVC "+pvcfullname+". PV "+pvname+" deleted")

    if pv.spec.persistent_volume_reclaim_policy and pv.spec.persistent_volume_reclaim_policy.upper() == "DELETE":
        delete_pv_data(pv, sc)

    logging.info("PVC "+pvcfullname+". PV "+pvname+" removal completed successfully")

################################################################################
## Main loop
################################################################################
logging.info("WELCOME: nfs-volume-provisioner, juliohm.com.br")
logging.info("Watching for PVCs")
while True:
    try:
        w = kubernetes.watch.Watch()
        for event in w.stream(coreapi.list_persistent_volume_claim_for_all_namespaces, _request_timeout=60):
            eventtype = event["type"]
            pvc = event["object"]
            pvcfullname = pvc.metadata.namespace+"-"+pvc.metadata.name
            try:
                logging.debug("Event: "+eventtype+" "+pvcfullname)
                if eventtype == "ADDED":
                    provision_pv(pvc)
                elif eventtype == "DELETED":
                    remove_pv(pvc)
            except Exception as err:
                logging.error("Error processing event "+eventtype+" for PVC "+pvcfullname)
                logging.error(err, exc_info=True)
    except urllib3.exceptions.ReadTimeoutError:
        logging.debug("API timeout. We'll return after these messages...")
    except Exception as err:
        logging.error("Unable to check for PVCs")
        logging.error(err, exc_info=True)
    time.sleep(5)
