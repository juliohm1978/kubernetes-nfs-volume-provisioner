#!/usr/bin/python3

import logging
import sys
import random
import string
import subprocess
import json
import jinja2

PROVISIONER_NAME     = "nfs-provisioner.juliohm.com.br"
ANNOTATION_INITPERMS = "nvs-provisioner.juliohm.com.br/init-perms"
ANNOTATION_UID       = "nvs-provisioner.juliohm.com.br/uid"
ANNOTATION_GID       = "nvs-provisioner.juliohm.com.br/gid"
ANNOTATION_MODE      = "nvs-provisioner.juliohm.com.br/mode"
ANNOTATION_READONLY  = "nvs-provisioner.juliohm.com.br/read-only"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

################################################################################
## Generate a random string of a given size
################################################################################
def gen_random_string(size):
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
## PV Template
################################################################################
def pvTemplate():
    return jinja2.Template("""
apiVersion: v1
kind: PersistentVolume
metadata:
  name: {{ name }}
  labels:
    nfs-provisioner.juliohm.com.br/storageClassName: {{ storageClassName }}
    nfs-provisioner.juliohm.com.br/pvcName: {{ pvcName }}
    nfs-provisioner.juliohm.com.br/pvcNamespace: {{ pvcNamespace }}
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
""")

################################################################################
## Provision a new PV for a given PVC
################################################################################
def provisionPV(pvcnamespace, pvcname):
    try:
        cmd = ["kubectl", "get", "pvc", "--namespace", pvcnamespace, pvcname, "-ojson"]
        s = subprocess.check_output(cmd, universal_newlines=True)
        pvc = json.loads(s)
        if not "storageClassName" in pvc["spec"]:
            logging.warning("PVC "+pvcnamespace+"/"+pvname+" does not have a storageClassName")
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

        pvnameprefix  = None
        nfsserver     = None
        nfsshare      = None
        nfspath       = ""
        nfsreadonly   = "false"

        if not "parameters" in sc:
            logging.warning("StorageClass "+scname+" does not have any parameters")
            return

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
            logging.debug("PV "+pvname+" already exists, ignoring event")
            return

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
            pvcNamespace=pvcnamespace
            )

        pvcpatch = '{ "spec": { "volumeName": "'+pvname+'" } }'
        cmd = ["kubectl", "patch", "pvc", "--namespace", pvcnamespace, pvcname, "--patch", pvcpatch]
        logging.info("PVC patched "+pvcnamespace+"/"+pvcname+" with volumeName="+pvname)
        subprocess.check_output(cmd)

        cmd = ["kubectl", "apply", "-f", "-"]
        subprocess.check_output(cmd, input=s.encode())
        logging.info("PV created successfully "+pvname+", waiting for binding to occur")

    except subprocess.CalledProcessError as err:
        logging.debug(err, exc_info=True)
        pass

################################################################################
## Search for a persistent volume
################################################################################
def removePV(pvcnamespace, pvcname):
    try:
        pvname = pvcnamespace+"-"+pvcname
        cmd = ["kubectl", "delete", "pv", pvname]
        subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
        logging.info("PV removed successfully "+pvname)
    except subprocess.CalledProcessError as err:
        logging.debug(err, exc_info=True)
        pass

################################################################################
## Main loop
################################################################################
logging.info("WELCOME: nfs-volume-provisioner, juliohm.com.br")
cmd = ["kubectl", "get", "pvc", "--watch-only", "--all-namespaces", "--no-headers"]
proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
logging.info("Watching for PVC events")
while True:
    try:
        line = proc.stdout.readline().decode("utf-8")
        line = line.split(" ")
        pvcnamespace = line[0]
        pvcname      = line[3]
        pvcstatus    = line[6]
        if pvcstatus.upper() == "PENDING":
            provisionPV(pvcnamespace, pvcname)
        elif pvcstatus.upper() == "TERMINATING":
            removePV(pvcnamespace, pvcname)
        else:
            logging.info("PVC "+pvcnamespace+"/"+pvcname+" is "+pvcstatus)
    except Exception as ex:
        logging.error("Unable to process PVC event")
        logging.error(ex, exc_info=True)
    rc = proc.poll()
    if rc:
        logging.info("kubectl exit code: "+str(rc))
        break;
