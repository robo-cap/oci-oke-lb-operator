import asyncio
import logging
import os
import traceback

import kopf
from kubernetes import client


from utils import get_cluster_ocid, \
    get_compartment_ocid, \
    get_service_lb_ocid, \
    get_current_waf_configuration, \
    get_desired_waf_configuration, \
    remove_existing_waf, \
    align_configuration



default_lock = asyncio.Lock()
service_locks = {}

COMPARTMENT_OCID = None
SYNC_INTERVAL = 600 #in seconds
TASKS = {}

## Used for local test
# @kopf.on.login()
# def login_fn(**kwargs):
#     return kopf.login_via_client(**kwargs)


@kopf.on.startup(errors=kopf.ErrorsMode.PERMANENT)
async def configure(settings: kopf.OperatorSettings, logger, **_):
    global COMPARTMENT_OCID

    if os.environ.get("COMPARTMENT_OCID", None) != None:
    
        COMPARTMENT_OCID = os.environ.get("COMPARTMENT_OCID") 
    
    else:
    
        logger.info("COMPARTMENT_OCID environment variable is not set. Attempting to determine it using instance metadata.")
    
        cluster_ocid = get_cluster_ocid(logger)

        if cluster_ocid != None:
            compartment_id = get_compartment_ocid(cluster_ocid, logger)
        else:
            logger.error("Failed to fetch cluster_ocid")
            raise kopf.PermanentError
        
        if compartment_id != None:
            COMPARTMENT_OCID = compartment_id
        else:
            logger.error("Failed to fetch compartment_ocid.")
            raise kopf.PermanentError

    settings.peering.standalone = True
    settings.posting.level = logging.INFO
    settings.execution.max_workers = 20
    # settings.execution.executor = concurrent.futures.ThreadPoolExecutor()

    # settings.watching.server_timeout = 90
    # settings.watching.connect_timeout = 90
    
    settings.persistence.progress_storage = kopf.AnnotationsProgressStorage()
    settings.persistence.diffbase_storage = kopf.AnnotationsDiffBaseStorage(
        prefix='kopf.zalando.org',
        key='last-handled-configuration',
    )


async def ensure_consistency(logger, namespace, name, uid):
    global service_locks
    lb_ocid = None

    while True:
        
        # Fetch OCID of the load balancer associated with the service
        if not lb_ocid:
            lb_ocid = get_service_lb_ocid(COMPARTMENT_OCID, namespace, name, uid, logger)

        if not lb_ocid:
            continue

        logger.info(f"Checking consistency for service: {namespace}/{name} | {lb_ocid}")

        if lb_ocid and lb_ocid not in service_locks:
            service_locks[lb_ocid] = asyncio.Lock()

        # Checking if the Kubernetes resources exists and fetch latest data
        async with service_locks.get(lb_ocid, default_lock):
            try:
                api = client.CoreV1Api()
                response = api.list_namespaced_service(namespace=namespace, field_selector=f'metadata.name={name}', limit=1)
                if not len(response.items):

                    # Check if there are remaining WAF enabled after service deletion
                    existing_waf_configuration = get_current_waf_configuration(lb_ocid, logger)
                    if existing_waf_configuration.get('waf', {}).get('ocid', ''):
                        logger.info(
                            (f"Found WAF {existing_waf_configuration.get('waf', {}).get('ocid', '')} configured for {lb_ocid}. "
                             f"Attempting to remove it."))
                        if remove_existing_waf(lb_ocid, existing_waf_configuration.get('waf', {}).get('ocid', ''), logger):
                            logger.info(f'Successfuly removed.')
                    
                    TASKS[uid].cancel()
                    del TASKS[uid]
                else:

                    obj = response.items[0]

                    current_configuration = get_current_waf_configuration(lb_ocid, logger)
                    desired_configuration = get_desired_waf_configuration(obj)

                    if current_configuration is None or desired_configuration is None :
                        logger.error(f"Could not fetch current/desired state.")
                        await asyncio.sleep(SYNC_INTERVAL)
                        continue

                    logger.debug(f'Existing configuration: {current_configuration}')
                    logger.debug(f'Desired configuration: {desired_configuration}')
                    
                    await align_configuration(COMPARTMENT_OCID, desired_configuration, current_configuration, lb_ocid, logger)
                    
            except Exception:
                logger.error(f'An unexepected error occured during configuration alignment: {traceback.print_exc()}')
        
        await asyncio.sleep(SYNC_INTERVAL)




def label_is_satisfied(labels, **_):
    return labels.get('use-oci-lb-operator', '').lower() == 'yes'

def type_is_satisfied(spec, **_):
    return spec.get('type', '') == 'LoadBalancer'



@kopf.on.update("Service", when=kopf.all_([label_is_satisfied, type_is_satisfied]))
async def on_update(body, namespace, name, uid, logger, **kwargs):
    global service_locks
    try:
        waf_policy_ocid = body.metadata.annotations.get('service.beta.kubernetes.io/oci-load-balancer-waf-policy-ocid', None)
        lb_ocid = get_service_lb_ocid(COMPARTMENT_OCID, namespace, name, uid, logger)
        
        if not lb_ocid:
            return None
        
        if lb_ocid and lb_ocid not in service_locks:
            service_locks[lb_ocid] = asyncio.Lock()
        
        # Checking if the Kubernetes resources exists and fetch latest data
        async with service_locks.get(lb_ocid, default_lock):
            current_configuration = get_current_waf_configuration(lb_ocid, logger)
            desired_configuration = {"waf": {"policy_ocid": waf_policy_ocid }}

            await align_configuration(COMPARTMENT_OCID, desired_configuration, current_configuration, lb_ocid, logger)

    except Exception:
        logger.error(f'An unexepected error occured during configuration alignment: {traceback.print_exc()}')
        raise kopf.PermanentError



@kopf.on.resume("Service", when=kopf.all_([label_is_satisfied, type_is_satisfied]))
async def on_resume(name, namespace, uid, logger, **kwargs):
    if uid not in TASKS:
        TASKS[uid] = asyncio.create_task(ensure_consistency(logger, namespace, name, uid))



@kopf.on.create("Service", when=kopf.all_([label_is_satisfied, type_is_satisfied]))
async def on_create(name, namespace, uid, logger, **kwargs):
    if uid not in TASKS:
        TASKS[uid] = asyncio.create_task(ensure_consistency(logger, namespace, name, uid))