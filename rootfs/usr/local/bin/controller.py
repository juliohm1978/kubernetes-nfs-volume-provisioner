#!/usr/bin/python3

import logging
import sys
import random
import string
import subprocess
import json
import jinja2
import time
import controllerargs

args = controllerargs.p.parse_args()

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

################################################################################
## Generate a random string of a given size
################################################################################
def randomString(size):
    return ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(size))

################################################################################
## Search for a storage class
################################################################################
def findStorageClass(scname):
    try:
        cmd = ["kubectl", "get", "sc", "-ojson", scname]
        s = subprocess.check_output(cmd, universal_newlines=True)
        return json.loads(s)
    except subprocess.CalledProcessError as err:
        logging.debug(err, exc_info=True)
        pass

################################################################################
## Search for a persistent volume
################################################################################
def findPersistentVolume(pvname):
    try:
        cmd = ["kubectl", "get", "pv", "-ojson", pvname]
        s = subprocess.check_output(cmd, universal_newlines=True, stderr=subprocess.DEVNULL)
        return json.loads(s)
    except subprocess.CalledProcessError as err:
        logging.debug(err, exc_info=True)
        pass

################################################################################
## PVC Patch Template
################################################################################
def pvcPatchTemplate():
    return jinja2.Template("""
spec:
  volumeName: {{ pvname }}
status:
  phase: Bound
""")

################################################################################
## PV Template
################################################################################
def pvTemplate():
    return jinja2.Template("""
apiVersion: v1
kind: PersistentVolume
metadata:
  name: {{ name }}
  labels:
    {{ labelPvcName }}: {{ pvcName }}
    {{ labelPvcNameSpace }}: {{ pvcNamespace }}
    {{ labelStorageClassName }}: {{ storageClassName }}
spec:
  storageClassName: {{ storageClassName }}
  capacity:
    storage: {{ storage }}
  accessModes:
  {% for am in accessModes %}
  - {{ am }}
  {% endfor %}
  persistentVolumeReclaimPolicy: {{ reclaimPolicy }}
  nfs: 
    path: {{ path }}
    server: {{ server }}
    readOnly: {{ readOnly }}
status:
  phase: Bound
""")

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

        # create temporary dir
        cmd = ["mkdir", "-p", dirlocal]
        subprocess.check_call(cmd)

        try:
            # mount the remote share temporarily
            cmd = ["mount", "-t", "nfs", remote, dirlocal]
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
def provisionPV(pvcnamespace, pvcname):
    cmd = ["kubectl", "get", "pvc", "--namespace", pvcnamespace, pvcname, "-ojson"]
    s = subprocess.check_output(cmd, universal_newlines=True)
    pvc = json.loads(s)
    if not "storageClassName" in pvc["spec"]:
        logging.warning("PVC "+pvcnamespace+"/"+pvcname+" does not have a storageClassName")
        return
    scname = pvc["spec"]["storageClassName"]
    sc = findStorageClass(scname)
    if not sc:
        return
    if not "provisioner" in sc:
        logging.warning("StorageClass "+scname+" has no provisioner defined")
        return
    scprovisioner = sc["provisioner"]
    if scprovisioner != PROVISIONER_NAME:
        logging.warning("StorageClass "+scname+" provisioner does not match "+PROVISIONER_NAME)
        return

    if not "parameters" in sc:
        logging.warning("StorageClass "+scname+" does not have any parameters")
        return

    if args.namespace and pvcnamespace != args.namespace:
        logging.warning("StorageClass "+scname+" GLOBALLY restricted to namespace "+args.namespace+", ignoring PV "+pvcnamespace+"/"+pvcname)
        return

    if "namespace" in sc["parameters"] and pvcnamespace != sc["parameters"]["namespace"]:
        logging.warning("StorageClass "+scname+" restricted to namespace "+sc["parameters"]["namespace"]+", ignoring PV "+pvcnamespace+"/"+pvcname)
        return

    pvnameprefix  = None
    nfsserver     = None
    nfsshare      = None
    nfspath       = ""
    nfsreadonly   = "false"
    scnamespace   = None

    if not "server" in sc["parameters"]:
        logging.warning("StorageClass "+scname+" missing parameter: server")
        return
    nfsserver = sc["parameters"]["server"]

    if not "share" in sc["parameters"]:
        logging.warning("StorageClass "+scname+" missing parameter: share")
        return
    nfsshare = sc["parameters"]["share"]

    if "path" in sc["parameters"]:
        nfspath = sc["parameters"]["path"]

    if "readOnly" in sc["parameters"]:
        nfsreadonly = sc["parameters"]["readOnly"]

    if "pvNamePrefix" in sc["parameters"]:
        pvnameprefix = sc["parameters"]["pvNamePrefix"]

    if "namespace" in sc["parameters"]:
        scnamespace = sc["parameters"]
    if scnamespace and scnamespace != pvcnamespace:
        logging.warning("StorageClass "+scname+" restricted to "+scnamespace+", ignoring PVC "+pvcnamespace+"/"+pvcname)
        return

    accessModes = list()
    if "accessModes" in pvc["spec"]:
        accessModes = pvc["spec"]["accessModes"]

    if not "reclaimPolicy" in sc:
        logging.warning("StorageClass "+scname+" missing reclaimPolicy")
        return
    reclaimPolicy = sc["reclaimPolicy"]

    storage = pvc["spec"]["resources"]["requests"]["storage"]

    pvname = pvcnamespace+"-"+pvcname
    if pvnameprefix:
        pvname = pvnameprefix+"-"+pvname
    
    pvexists = findPersistentVolume(pvname)
    if pvexists:
        logging.info("PV "+pvname+" already exists. Ignoring event")
        return

    ## Try to create subdirectories inside NFS share and adjust permissions
    ## before delivering the PV.
    initPVData(pvc, sc)

    ## Patch PVC with a bind to the PV that will be created.
    s = pvcPatchTemplate().render(pvname=pvname)
    cmd = ["kubectl", "patch", "pvc", "--namespace", pvcnamespace, pvcname, "--patch", s]
    logging.info("PVC patched "+pvcnamespace+"/"+pvcname+" with volumeName="+pvname)
    subprocess.check_output(cmd)

    ## Create a PV alredy bound to the PVC
    s = pvTemplate().render(
        name=pvname,
        path=nfsshare+nfspath+"/"+pvname,
        server=nfsserver,
        readOnly=nfsreadonly,
        accessModes=accessModes,
        reclaimPolicy=reclaimPolicy,
        storage=storage,
        storageClassName=scname,
        pvcName=pvcname,
        pvcNamespace=pvcnamespace,
        labelPvcName=LABEL_PVCNAME,
        labelPvcNameSpace=LABEL_PVCNAMESPACE,
        labelStorageClassName=LABEL_STORAGECLASSNAME
    )
    cmd = ["kubectl", "apply", "-f", "-"]
    subprocess.check_output(cmd, input=s.encode())
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

        if ".." in dirlocalfull:
            logging.error("Invalid path "+dirlocalfull)
            return

        try:
            # mount the remote share temporarily
            cmd = ["mount", "-t", "nfs", remote, dirlocal]
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
        logging.error("Failed to initialize data inside NFS share: "+str(err))
        raise err


################################################################################
## Remove a given PV
################################################################################
def removePV(pvname):
    cmd = ["kubectl", "get", "pv", "-ojson", pvname]
    pv = json.loads( subprocess.check_output(cmd, universal_newlines=True) )

    if not "labels" in pv["metadata"]:
        return
    
    if not LABEL_STORAGECLASSNAME in pv["metadata"]["labels"]:
        return

    scname = pv["metadata"]["labels"][LABEL_STORAGECLASSNAME]

    cmd = ["kubectl", "get", "sc", "-ojson", scname]
    sc = json.loads( subprocess.check_output(cmd, universal_newlines=True) )

    if not "provisioner" in sc:
        return

    if PROVISIONER_NAME != sc["provisioner"]:
        return

    keeppv = "false"
    if "keepPv" in sc["parameters"] and sc["parameters"]["keepPv"] == "true":
        return

    logging.info("Found PV "+pvname+" in state Released")

    cmd = ["kubectl", "delete", "pv", pvname]
    subprocess.check_call(cmd)
    logging.info("PV removed successfully "+pvname)

    if "persistentVolumeReclaimPolicy" in pv["spec"]:
        rp = pv["spec"]["persistentVolumeReclaimPolicy"].upper()
        if rp=="DELETE":
            deletePVData(sc, pvname, rp)

################################################################################
## Main loop
################################################################################
logging.info("WELCOME: nfs-volume-provisioner, juliohm.com.br")
logging.info("Watching for PVCs")
while True:
    try:
        # Look for pending PVCs
        cmd = ["kubectl", "get", "pvc", "--all-namespaces", "-ojson"]
        s = subprocess.check_output(cmd, universal_newlines=True)
        pvc = json.loads(s)
        for item in pvc["items"]:
            try:
                pvcnamespace = item["metadata"]["namespace"]
                pvcname      = item["metadata"]["name"]
                pvcstatus    = item["status"]["phase"].upper()
                if pvcstatus.upper() == "PENDING":
                    provisionPV(pvcnamespace, pvcname)
            except Exception as err:
                logging.error(err, exc_info=True)

        # Look for released PVs
        cmd = ["kubectl", "get", "pv", "-ojson"]
        s = subprocess.check_output(cmd, universal_newlines=True)
        pvc = json.loads(s)
        for item in pvc["items"]:
            try:
                pvname   = item["metadata"]["name"]
                pvstatus = item["status"]["phase"].upper()
                if pvstatus=="RELEASED" or pvstatus=="FAILED":
                    removePV(pvname)
            except Exception as err:
                logging.error(err, exc_info=True)

    except Exception as err:
        logging.error("Unable to check for PVCs")
        logging.error(err, exc_info=True)

    time.sleep(args.interval)
