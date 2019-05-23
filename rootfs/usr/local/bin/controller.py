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
import controllerargs

args = controllerargs.p.parse_args()

nfsversion = "nfs"
if args.nfsVersion == "4":
    nfsversion = "nfs4"

PROVISIONER_NAME     = "nfs-provisioner.juliohm.com.br"
ANNOTATION_INITPERMS = "nvs-provisioner.juliohm.com.br/init-perms"
ANNOTATION_UID       = "nvs-provisioner.juliohm.com.br/uid"
ANNOTATION_GID       = "nvs-provisioner.juliohm.com.br/gid"
ANNOTATION_MODE      = "nvs-provisioner.juliohm.com.br/mode"

LABEL_PVCNAME          = "nfs-provisioner.juliohm.com.br/pvcName"
LABEL_PVCNAMESPACE     = "nfs-provisioner.juliohm.com.br/pvcNamespace"
LABEL_STORAGECLASSNAME = "nfs-provisioner.juliohm.com.br/storageClassName"

debuglevel = logging.INFO
if args.debugLevel:
    debuglevel = logging._nameToLevel[args.debugLevel.upper()]

logging.basicConfig(level=debuglevel, format="%(asctime)s [%(levelname)s] %(message)s")

kubernetes.config.load_kube_config("/home/lamento/.kube/config.k3s")
coreapi = kubernetes.client.CoreV1Api()
storageapi = kubernetes.client.StorageV1Api()

################################################################################
## Generate a random string of a given size
################################################################################
def randomString(size):
    return ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(size))

################################################################################
## Initialize the data inside the NFS share to match specifications defined
## in the StorageClass and PVC. Skip if any flags mark otherwise.
################################################################################
def initPVData(pvc, sc):
    try:
        if args.disablePvInit:
            return

        if not "annotations" in pvc["metadata"]:
            return

        if ANNOTATION_INITPERMS in pvc["metadata"]["annotations"] and pvc["metadata"]["annotations"][ANNOTATION_INITPERMS] == "false":
            return

        pvname = pvc["metadata"]["namespace"] + "-" + pvc["metadata"]["name"]
        server = sc["parameters"]["server"]
        share  = sc["parameters"]["share"]
        path   = "/"
        if "path" in sc["parameters"]:
            path = sc["parameters"]["path"]

        remote = server + ":" + share
        dirlocal  = "/tmp/"+randomString(18)
        dirlocalfull = dirlocal + path + "/" + pvname

        if ".." in remote:
            logging.error("Invalid path "+remote+". Refusing to initialize PV data")
            return

        # create temporary dir
        cmd = ["mkdir", "-p", dirlocal]
        subprocess.check_call(cmd)

        try:
            # mount the remote share temporarily
            cmd = ["mount", "-t", nfsversion, remote, dirlocal]
            subprocess.check_call(cmd)
            logging.debug("Temporary mount for "+pvname+": "+remote+" > "+dirlocal)

            try:
                # create a subdirectory derived from pvname
                cmd = ["mkdir", "-p", dirlocalfull]
                subprocess.check_call(cmd)

                # adjust user permissions
                if ANNOTATION_UID in pvc["metadata"]["annotations"]:
                    cmd = ["chown", pvc["metadata"]["annotations"][ANNOTATION_UID], dirlocalfull]
                    subprocess.check_call(cmd)
                    logging.debug("User permissions adjusted for "+pvname+": "+pvc["metadata"]["annotations"][ANNOTATION_UID])

                # adjust group permissions
                if ANNOTATION_GID in pvc["metadata"]["annotations"]:
                    cmd = ["chgrp", pvc["metadata"]["annotations"][ANNOTATION_GID], dirlocalfull]
                    subprocess.check_call(cmd)
                    logging.debug("Group permissions adjusted for "+pvname+": "+pvc["metadata"]["annotations"][ANNOTATION_UID])

                # adjust group permissions
                if ANNOTATION_MODE in pvc["metadata"]["annotations"]:
                    cmd = ["chmod", pvc["metadata"]["annotations"][ANNOTATION_MODE], dirlocalfull]
                    subprocess.check_call(cmd)
                    logging.debug("File permissions adjusted for "+pvname+": "+pvc["metadata"]["annotations"][ANNOTATION_MODE])
            finally:
                # umount
                cmd = ["umount", dirlocal]
                subprocess.check_call(cmd)
                logging.debug("Initialization complete for "+pvname+": "+dirlocal+" umounted")
        finally:
            # remove temporary dir
            cmd = ["rm", "-rf", dirlocal]
            subprocess.check_call(cmd)

    except Exception as err:
        logging.error("Failed to initialize data inside NFS share: "+str(err))
        raise err

################################################################################
## Provision a new PV for a given PVC
################################################################################
def provisionPV(pvc):
    pvcfullname = pvc.metadata.namespace + "-" + pvc.metadata.name
    scname = pvc.spec.storage_class_name
    
    sc = storageapi.list_storage_class(field_selector="metadata.name="+scname)
    if len(sc.items) <= 0:
        logging.warning("PVC "+pvcfullname+" StorageClass not found "+scname)
        return
    
    sc = sc.items[0]
    
    if not sc.provisioner == PROVISIONER_NAME:
        logging.warning("PVC "+pvcfullname+" storageClassName does not match "+PROVISIONER_NAME+". Ingoring event.")
        return
    if ("namespace" in sc.parameters) and (sc.parameters["namespace"] != pvc.metadata.namespace):
        logging.warning("PVC "+pvcfullname+" namespace does not patch provisioner scope: "+sc.parameters['namespace']+". Ingoring event.")
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
        logging.debug("PVC "+pvcfullname+". PV "+pvname+" already exists. Ingoring event.")
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

    pvcpatch = '''{
        "spec": {
            "volumeName": "'''+pvname+'''"
        },
        "status": {
            "phase": "Bound"
        }
    }
    '''

    coreapi.patch_namespaced_persistent_volume_claim(
        name=pvc.metadata.name, namespace=pvc.metadata.namespace, body=json.loads(pvcpatch))

    logging.info("PV created successfully "+pvname+", wait for binding to occur")

################################################################################
## Try mounting the NFS share related to a PV and delete its data according
## to the PV reclaim policy.
################################################################################
def deletePVData(sc, pvname, reclaimPolicy):
    try:
        server = sc["parameters"]["server"]
        share  = sc["parameters"]["share"]
        path   = "/"
        if "path" in sc["parameters"]:
            path = sc["parameters"]["path"]

        remote = server + ":" + share
        dirlocal  = "/tmp/"+randomString(18)
        dirlocalfull = dirlocal + path + "/" + pvname

        # create temporary dir
        cmd = ["mkdir", "-p", dirlocal]
        subprocess.check_call(cmd)

        if ".." in remote:
            logging.error("Invalid path "+remote+". Refusing to delete PV data")
            return

        try:
            # mount the remote share temporarily
            cmd = ["mount", "-t", nfsversion, remote, dirlocal]
            subprocess.check_call(cmd)
            logging.debug("Mount "+pvname+": "+remote+" > "+dirlocal)
            try:
                cmd = ["rm", "-rf", dirlocalfull]
                subprocess.check_call(cmd)
                logging.info(reclaimPolicy+" reclaim policy complete for "+pvname+": "+dirlocalfull)
            finally:
                # umount
                cmd = ["umount", dirlocal]
                subprocess.check_call(cmd)
                logging.debug("Umount "+pvname+": "+remote+" > "+dirlocal)
        finally:
            # remove temporary dir
            cmd = ["rm", "-rf", dirlocal]
            subprocess.check_call(cmd)

    except Exception as err:
        logging.error("Failed to remove data from NFS share: "+str(err))
        raise err


################################################################################
## Remove a given PV
################################################################################
def removePV(pvc):
    scname = pvc.spec.storage_class_name
    sc = storageapi.list_storage_class(field_selector="metadata.name="+scname)
    if len(sc.items) <= 0:
        logging.warning("PVC "+pvcfullname+" StorageClass not found "+scname)
        return
    
    sc = sc.items[0]
    
    if not sc.provisioner == PROVISIONER_NAME:
        logging.warning("PVC "+pvcfullname+" storageClassName does not match "+PROVISIONER_NAME+". Ingoring event.")
        return
    if ("namespace" in sc.parameters) and (sc.parameters["namespace"] != pvc.metadata.namespace):
        logging.warning("PVC "+pvcfullname+" namespace does not patch provisioner scope: "+sc.parameters['namespace']+". Ingoring event.")
        return

    pvname = pvc.spec.volume_name
    if not pvname:
        logging.warning("PVC "+pvcfullname+" is not associated to a volumeName. Ingoring event.")
        return

    coreapi.delete_persistent_volume(name=pvname)

    # if pv.spec.persistent_volume_reclaim_policy and pv.spec.persistent_volume_reclaim_policy.upper() == "DELETE":
    #     deletePVData(sc, pvname, rp)

    logging.info("PVC "+pvcfullname+". PV "+pvname+" removed successfully.")

################################################################################
## Main loop
################################################################################
logging.info("WELCOME: nfs-volume-provisioner, juliohm.com.br")
while True:
    try:
        logging.info("Watching for PVCs")
        w = kubernetes.watch.Watch()
        for event in w.stream(coreapi.list_persistent_volume_claim_for_all_namespaces, _request_timeout=60):
            eventtype = event["type"]
            pvc = event["object"]
            pvcfullname = pvc.metadata.namespace+"-"+pvc.metadata.name
            try:
                logging.debug("Event: "+eventtype+" "+pvcfullname)
                if eventtype == "ADDED":
                    provisionPV(pvc)
                elif eventtype == "DELETED":
                    removePV(pvc)
            except Exception as err:
                logging.error("Error processing event "+eventtype+" for PVC "+pvcfullname)
                logging.error(err, exc_info=True)
    except urllib3.exceptions.ReadTimeoutError:
        logging.debug("API timeout. We'll return after these messages...")
    except Exception as err:
        logging.error("Unable to check for PVCs")
        logging.error(err, exc_info=True)
    time.sleep(5)
