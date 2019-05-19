#!/usr/bin/python3

import kubernetes
import logging
import sys
import random
import string
import subprocess

PROVISIONER_NAME     = "nfs-provisioner.juliohm.com.br"
ANNOTATION_INITPERMS = "nvs-provisioner.juliohm.com.br/init-perms"
ANNOTATION_UID       = "nvs-provisioner.juliohm.com.br/uid"
ANNOTATION_GID       = "nvs-provisioner.juliohm.com.br/gid"
ANNOTATION_MODE      = "nvs-provisioner.juliohm.com.br/mode"
ANNOTATION_READONLY  = "nvs-provisioner.juliohm.com.br/read-only"

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")

kubernetes.config.load_kube_config("/home/lamento/.kube/config.k3s")
coreapi = kubernetes.client.CoreV1Api()
storageapi = kubernetes.client.StorageV1Api()

################################################################################
## Generate a random string of a given size
################################################################################
def gen_random_string(size):
    return ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(size))

################################################################################
## Find a StorageClass object with a given name
################################################################################
def find_storage_class(storageclassname):
    for item in storageapi.list_storage_class().items:
        if item.metadata.name == storageclassname:
            return item
    return None

################################################################################
## Provision new a PV for a given PVC.
## PV name is randomly chosen.
## If the PVC is already bound to a PV, nothing will be done here.
################################################################################
def provisionPV(pvc):
    pvcname = pvc.metadata.name
    scname = pvc.spec.storage_class_name

    if not scname:
        logging.warning("PVC "+pvcname+" does not have a storage class")
        return

    sc = find_storage_class(scname)
    if not sc:
        logging.warning("No storage class object found for "+scname)
        return
    if sc.provisioner != PROVISIONER_NAME:
        logging.warning("Storage class provisioner for "+scname+" does not match "+PROVISIONER_NAME)
        return

    pvcnamespace = "default"
    if sc.metadata.namespace:
        pvcnamespace = sc.metadata.namespace

    pvname = pvcnamespace+"-"+pvcname
    if "pvNamePrefix" in sc.parameters:
        pvname = sc.parameters["pvNamePrefix"] + pvname

    res = coreapi.list_persistent_volume(field_selector="metadata.name="+pvname)
    if len(res.items) > 0:
        logging.warning("PV already exists "+pvname+", ignoring event "+pv.items)
        return

    if not "server" in sc.parameters:
        logging.error("StorageClass "+scname+" does not define parameter: server")
        return
    if not "share" in sc.parameters:
        logging.error("StorageClass "+scname+" does not define parameter: share")
        return

    scparam_server = sc.parameters["server"]
    scparam_share  = sc.parameters["share"]
    scparam_path   = ""
    if "path" in sc.parameters:
        scparam_path = sc.parameters["path"]

    ## Try to mount the NFS share temporarily to create the subdirectory
    ## for the new PV and adjust user/group/mode permissions.
    ## All parameters for this operation are obtained from the PVC and
    ## the StorageClass found for this provisioning.
    if ANNOTATION_INITPERMS in pvc.metadata.annotations and pvc.metadata.annotations[ANNOTATION_INITPERMS] == "true":
        try:
            logging.info("Configuring volume properties before")
            mountpath = "/tmp/"+gen_random_string(12)
            cmd = ["mkdir", "-p", mountpath]
            subprocess.check_call(cmd)
            cmd = ["mount", "-t", "nfs", scparam_server+":"+scparam_share, mountpath]
            logging.info(str(cmd))
            subprocess.check_call(cmd)
            try:
                logging.info("Temporary mount "+mountpath)
                fullsharepath = mountpath+scparam_path+"/"+pvname
                cmd = ["mkdir", "-p", fullsharepath]
                logging.info("Created path inside NFS share: "+fullsharepath)
                subprocess.check_call(cmd)
                if ANNOTATION_UID in pvc.metadata.annotations:
                    uid = pvc.metadata.annotations[ANNOTATION_UID]
                    logging.info("Adjusting user  permission: "+fullsharepath+" to "+uid)
                    cmd = ["chown", uid, fullsharepath]
                    subprocess.check_call(cmd)
                if ANNOTATION_GID in pvc.metadata.annotations:
                    gid = pvc.metadata.annotations[ANNOTATION_GID]
                    logging.info("Adjusting group permission: "+fullsharepath+" to "+gid)
                    cmd = ["chgrp", gid, fullsharepath]
                    subprocess.check_call(cmd)
                if ANNOTATION_MODE in pvc.metadata.annotations:
                    mode = pvc.metadata.annotations[ANNOTATION_MODE]
                    logging.info("Adjusting mode  permission: "+fullsharepath+" to "+mode)
                    cmd = ["chmod", mode, fullsharepath]
                    subprocess.check_call(cmd)
            finally:
                cmd = ["umount", mountpath]
                subprocess.check_call(cmd)
                cmd = ["rm", "-rf", mountpath]
                logging.info("Temporary umount "+mountpath)
        except Exception as ex:
            logging.error("Unable to mount NFS to adjust permissions PVC="+pvcname+": "+str(ex))
            return

    ##
    ## Create the PV object using all specs from PVC and StorageClass
    ##
    logging.info("Creating new PV="+pvname+" for PVC="+pvcname)
    pv = kubernetes.client.V1PersistentVolume()
    pv.metadata = kubernetes.client.V1ObjectMeta()
    pv.metadata.name = pvname
    pv.spec = kubernetes.client.V1PersistentVolumeSpec()
    if pvc.spec.access_modes:
        pv.spec.access_modes = pvc.spec.access_modes
    
    # https://github.com/kubernetes-client/python/issues/834
    # if sc.reclaimPolicy:
    #     pv.spec.persistent_volume_reclaim_policy = sc.reclaimPolicy
    pv.spec.persistent_volume_reclaim_policy = "Retain"
    
    pv.spec.capacity = dict()
    pv.spec.capacity["storage"] = pvc.spec.resources.requests["storage"]
    pv.spec.nfs = kubernetes.client.V1NFSVolumeSource()
    pv.spec.nfs.server = scparam_server
    pv.spec.nfs.path = scparam_share + scparam_path + "/" + pvname
    if ANNOTATION_READONLY in pvc.metadata.annotations:
        pv.spec.nfs.read_only = True

    pvc.spec.volumeMode = pvname
    coreapi.patch_namespaced_persistent_volume_claim(pvcname, pvcnamespace, pvc)

    # coreapi.create_persistent_volume(pv)

################################################################################
## Main loop
################################################################################
w = kubernetes.watch.Watch()
for event in w.stream(coreapi.list_persistent_volume_claim_for_all_namespaces):
    pvc = event["object"]
    try:
        if event['type'] == "ADDED":
            provisionPV(pvc)
        elif event['type'] == "DELETED":
            logging.info(
                "PVC removido namespace="+pvc.metadata.namespace+
                ", name="+pvc.metadata.name+
                ", storageClassName="+pvc.spec.storage_class_name
                )
            
            ## https://github.com/kubernetes-client/python/blob/master/kubernetes/docs/CoreV1Api.md#list_persistent_volume
            #coreapi.list_persistent_volume(...)
    except Exception as ex:
        logging.error("Unable to provision PVC "+pvc.metadata.name)
        logging.error(ex, exc_info=True)

