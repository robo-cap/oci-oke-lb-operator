
import requests
import traceback

import oci
from oci.pagination import list_call_get_all_results
from oci.exceptions import ClientError
import asyncio


def get_cluster_ocid(logger):

    logger.debug("Attempting to fetch OKE cluster OCID using instance metadata.")
    
    try:
        response = requests.get(
            "http://169.254.169.254/opc/v2/instance/metadata/", 
            headers={"Authorization": "Bearer Oracle"}, 
            timeout=5)
    
        if response.status_code != 200:
            logger.warn(
                (f"Unexpected response code received when attempting to fetch instance metadata: "
                f"{response.status_code}. Response text: {response.text}."))
            return None
    
        cluster_id = response.json().get("oke-cluster-id")
        logger.debug(f"Successfuly fetched OKE cluster OCID: {cluster_id}.")
    
    except Exception as e:
        logger.error(f"An unexpected error occured during attempt to fetch cluster OCID: {e}.")
        return None
    
    return cluster_id



def get_compartment_ocid(cluster_id, logger):

    logger.debug("Attempting to fetch OKE compartment OCID using cluster OCID.")

    try:
        signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
    
    except Exception as e:
        raise ClientError("Failed to get Instance Principal Signer")

    try:
        container_engine_client = oci.container_engine.ContainerEngineClient(
            {},
            signer=signer,
            timeout=5)
        
        get_cluster_response = container_engine_client.get_cluster(
            cluster_id=cluster_id)
        
        if get_cluster_response.status != 200:
            logger.warn(
                (f"Unexpected response code received when attempting to fetch cluster {cluster_id} information: "
                f"{get_cluster_response.status}. Response text: {get_cluster_response.data}."))
            return None

        compartment_id = get_cluster_response.data.compartment_id
        logger.debug(f"Successfuly fetched OKE cluster {cluster_id} compartment OCID: {compartment_id}")

    except Exception as e:
        logger.error(
            (f"An unexpected error occured during attempt to fetch cluster {cluster_id} compartment_id: "
            f"{traceback.print_exc()}."))
        return None

    return compartment_id



def get_service_lb_ocid(compartment_id, namespace, service_name, uid, logger):

    logger.debug(f"Attempting to get Load Balancer OCID for the service {namespace}/{service_name}.")

    try:

        signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
    
    except Exception as e:
        raise ClientError("Failed to get Instance Principal Signer")

    try:

        lb_ocid = ""
        load_balancer_client = oci.load_balancer.LoadBalancerClient(
                {},
                signer=signer,
                timeout=5)
        list_load_balancers_response = list_call_get_all_results(
            load_balancer_client.list_load_balancers,
            compartment_id = compartment_id)
        
        if list_load_balancers_response.status != 200:
            logger.warn(
                f"Unexpected response code received when attempting to retrieve load balancers in compartment {compartment_id}: \
                {list_load_balancers_response.status}. Response text: {list_load_balancers_response.data}.")
            return None

        for entry in list_load_balancers_response.data:
            if entry.display_name == uid:
                lb_ocid = entry.id
                break
        logger.debug(f"Successfuly fetched service {namespace}/{service_name} load balancer OCID: {lb_ocid}")

    except Exception as e:
        logger.error(f"An unexpected error occured during attempt to fetch load balancers list in compartment {compartment_id}: {traceback.print_exc()}.")
        return None

    return lb_ocid



def get_current_waf_configuration(lb_ocid, logger):

    # Searching for WAF attached to the load balancer
    logger.debug(f"Attempting to fetch current configuration for Load Balancer {lb_ocid}.")

    current_waf_ocid = ''
    current_waf_policy_ocid = ''
    try:

        signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
    
    except Exception as e:
        raise ClientError("Failed to get Instance Principal Signer")

    try:
        # Listing WAF attached to the load balancer
        resource_search_client = oci.resource_search.ResourceSearchClient(
                {},
                signer=signer,
                timeout=5)
        
        search_resources_response = list_call_get_all_results(
            resource_search_client.search_resources,
            search_details=oci.resource_search.models.StructuredSearchDetails(
                type="Structured",
                query=f'query WebAppFirewall resources where loadBalancerId = "{lb_ocid}"'),
            tenant_id = signer.tenancy_id)
        
        if search_resources_response.status != 200:
            logger.warn(
                (f"Unexpected response code received when attempting to retrieve WAFs in tenancy {signer.tenancy_id} information: "
                f"{search_resources_response.status}. Response text: {search_resources_response.data}."))
            return None

        if len(search_resources_response.data) > 0:
            current_waf_ocid = search_resources_response.data[0].identifier
            
            waf_client = oci.waf.WafClient(
                {},
                signer=signer,
                timeout=5)

            get_web_app_firewall_response = waf_client.get_web_app_firewall(
                web_app_firewall_id=current_waf_ocid)
            
            if get_web_app_firewall_response.status == 200:
                current_waf_policy_ocid = get_web_app_firewall_response.data.web_app_firewall_policy_id
            else:
                logger.warn(
                    (f"Unexpected response code received when attempting to retrieve WAF {current_waf_ocid} information: "
                    f"{get_web_app_firewall_response.status}. Response text: {get_web_app_firewall_response.data}."))
            
            
        logger.debug(f"Successfuly fetched WAF firewalls configured in tenancy {signer.tenancy_id}")

    except Exception as e:
        logger.error(f"An unexpected error occured during attempt to fetch load balancers list in tenancy {signer.tenancy_id}: {traceback.print_exc()}.")
        return None

    return {"waf": { "ocid": current_waf_ocid, "policy_ocid": current_waf_policy_ocid}}



def get_desired_waf_configuration(obj):

    # Checking attached WAFs to the load balancer
    desired_waf_policy_ocid = obj.metadata.annotations.get('service.beta.kubernetes.io/oci-load-balancer-waf-policy-ocid', '')
    return {"waf": {"policy_ocid": desired_waf_policy_ocid }}



def remove_existing_waf(lb_ocid, current_waf_ocid, logger):
    
    # Remove exsting WAF firewall from the load balancer
    logger.debug(f"Attempting to remove existing WAF firewall from the load balancer: {lb_ocid}.")

    try:

        signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
    
    except Exception as e:
        raise ClientError("Failed to get Instance Principal Signer")

    try:
        # Listing current WAFs attached to the load balancer
        waf_client = oci.waf.WafClient(
                {},
                signer=signer,
                timeout=60)
        waf_composite_operations = oci.waf.WafClientCompositeOperations(waf_client)
        delete_web_app_firewall_response = waf_composite_operations.delete_web_app_firewall_and_wait_for_state(
            web_app_firewall_id = current_waf_ocid,
            wait_for_states=["SUCCEEDED"],
            waiter_kwargs={
                "max_wait_seconds":90,
                "succeed_on_not_found": True})
            
        
        if delete_web_app_firewall_response.status != 200:
            logger.warn(
                (f"Unexpected response code received when attempting to delete existing WAF {current_waf_ocid} information: "
                f"{delete_web_app_firewall_response.status}. Response text: {delete_web_app_firewall_response.data}."))
            return None

        logger.debug(f"Successfuly removed existing WAF {current_waf_ocid} enabled on Load Balancer: {lb_ocid}")

    except Exception as e:
        logger.error(
            (f"An unexpected error occured during attempt to remove exsting WAF {current_waf_ocid} "
            f"enabled on Load Balancer {lb_ocid}: {traceback.print_exc()}."))
        return None

    return True



def add_waf_to_load_balancer(compartment_id, lb_ocid, waf_policy_ocid, logger):
    
    # Remove exsting WAF firewall from the load balancer
    logger.debug(f"Attempting to add WAF to the load balancer: {lb_ocid}.")

    try:

        signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
    
    except Exception as e:
        raise ClientError("Failed to get Instance Principal Signer")

    try:
        # Listing current WAFs attached to the load balancer
        waf_client = oci.waf.WafClient(
                {},
                signer=signer,
                timeout=60)
        waf_composite_operations = oci.waf.WafClientCompositeOperations(waf_client)
        create_web_app_firewall_response = waf_composite_operations.create_web_app_firewall_and_wait_for_state(
            create_web_app_firewall_details   = oci.waf.models.CreateWebAppFirewallLoadBalancerDetails(
                backend_type="LOAD_BALANCER",
                compartment_id=compartment_id,
                load_balancer_id=lb_ocid,
                web_app_firewall_policy_id=waf_policy_ocid),
            wait_for_states=["SUCCEEDED"],
            waiter_kwargs={
                "max_wait_seconds": 60,
                "succeed_on_not_found": True})
            
        
        if create_web_app_firewall_response.status != 200:
            logger.warn(
                (f"Unexpected response code received when attempting to attach WAF policy {waf_policy_ocid} to the load balancer {lb_ocid}: "
                f"{create_web_app_firewall_response.status}. Response text: {create_web_app_firewall_response.data}."))
            return None

        logger.debug(f"Successfuly attached WAF policy {waf_policy_ocid} on the Load Balancer: {lb_ocid}")

    except Exception as e:
        logger.error(
            (f"An unexpected error occured during attempt to attach WAF policy {waf_policy_ocid} "
            f"on Load Balancer: {lb_ocid}: {traceback.print_exc()}."))
        return None

    return True



async def align_configuration(compartment_id, desired_configuration, current_configuration, lb_ocid, logger):

    # Wait for the load balancer status to become ACTIVE
    try:

        signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
    
    except Exception as e:
        raise ClientError("Failed to get Instance Principal Signer")

    try:
        load_balancer_client = oci.load_balancer.LoadBalancerClient(
            {},
            signer=signer,
            timeout=5)
        
        max_attempts = 12
        current_attempt = 1

        while current_attempt < max_attempts:
            logger.debug(f"Attempt {current_attempt} to check {lb_ocid} status.")
            get_load_balancer_response = load_balancer_client.get_load_balancer(lb_ocid)
            logger.debug(f"Response: {get_load_balancer_response.status} | {get_load_balancer_response.data}")
            if get_load_balancer_response.status == 200 and get_load_balancer_response.data.lifecycle_state == "ACTIVE":
                logger.debug(f"Load Balancer {lb_ocid} status is ACTIVE.")
                break
            else:
                logger.info(f"Load Balancer {lb_ocid} is not yet ACTIVE.")
                await asyncio.sleep(10)
                current_attempt += 1
                
        if current_attempt == max_attempts:
            raise ClientError(f"Load Balancer {lb_ocid} not found or not ready.")
        
    except Exception as e:
        raise

    # No WAF policy OCID annotation for the Kubernetes service, and only configured externally.
    # Need to align the configuration and remove the WAF configured externally.
    if ( not desired_configuration.get('waf', {}).get('policy_ocid', '') 
            and current_configuration.get('waf', {}).get('policy_ocid', '') ):
        logger.info(f'Need to remove existing WAF configuration')
        if not remove_existing_waf(lb_ocid, current_configuration.get('waf').get('ocid'), logger):
            logger.error('Could not remove existing WAF configured on the load balancer.')
        else:
            logger.info('Successfuly cleared existing configured WAF on the load balancer.')

    # WAF policy OCID annotation for the Kubernetes service is present but it is inconsisdent with the current configuration.
    # Need to remove existing WAF and attach the new WAF policy
    if  desired_configuration.get('waf', {}).get('policy_ocid', '') \
            and current_configuration.get('waf', {}).get('policy_ocid', '') \
            and current_configuration.get('waf', {}).get('policy_ocid', '') != desired_configuration.get('waf', {}).get('policy_ocid', ''):

        if not remove_existing_waf(lb_ocid, current_configuration.get('waf').get('ocid'), logger):
            logger.error('Could not remove existing WAF configured on the load balancer.')
        else:
            logger.info('Successfuly cleared existing configured WAF on the load balancer.')
            if add_waf_to_load_balancer(compartment_id, lb_ocid, desired_configuration.get('waf').get('policy_ocid'), logger):
                logger.info(
                    (f"Successfuly configured desired WAF policy {desired_configuration.get('waf').get('policy_ocid')}"
                    f"on the load balancer {lb_ocid}."))
            else:
                logger.error(
                    (f"Could not set desired WAF policy {desired_configuration.get('waf').get('policy_ocid')} "
                    f"on the load balancer {lb_ocid}."))

    # WAF policy OCID annotation for the kubernetes service is present and the current configuration is empty.
    # Need to attach WAF policy to the load balancer.
    if  desired_configuration.get('waf', {}).get('policy_ocid', '') \
            and not current_configuration.get('waf', {}).get('policy_ocid', ''):
        if add_waf_to_load_balancer(compartment_id, lb_ocid, desired_configuration.get('waf').get('policy_ocid'), logger):
                logger.info(
                    (f"Successfuly configured desired WAF policy {desired_configuration.get('waf').get('policy_ocid')}"
                    f"on the load balancer {lb_ocid}."))
        else:
            logger.error(
                (f"Could not set desired WAF policy {desired_configuration.get('waf').get('policy_ocid')} "
                f"on the load balancer {lb_ocid}."))

    # Confirm if the WAF Policy configuration is consistent      
    if desired_configuration.get('waf', {}).get('policy_ocid', '') == current_configuration.get('waf', {}).get('policy_ocid', ''):
        logger.info(f"Load Balancer {lb_ocid} configuration is consistent.")