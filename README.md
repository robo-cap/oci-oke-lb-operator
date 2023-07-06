# OKE Operator to attach WAF to OKE Services of type Load Balancer

This Kubernetes operator, built using Kopf, is monitoring the Kubernetes services labeled `use-oci-lb-operator: "yes"`, and is attempting to allign the WAF Policy OCID defined using the service annotation `service.beta.kubernetes.io/oci-load-balancer-waf-policy-ocid` with  the actual Load Balancer configuration.

The operator performs the following operations:

1. Each 10 minutes is checking for consistency of the WAF configuration for each labeled service.
2. Automatically updates the service configuration when the annotation `service.beta.kubernetes.io/oci-load-balancer-waf-policy-ocid` is changed.


## Prerequisites:

- [OKE](https://docs.oracle.com/en-us/iaas/Content/ContEng/Concepts/contengoverview.htm) cluster with managed Kubernetes worker nodes
- Authenticate build environment and OKE with [Oracle Cloud Infrastructure Registry (OCIR)](https://docs.oracle.com/en-us/iaas/Content/Functions/Tasks/functionslogintoocir.htm)

## Getting Started

### Preparing the container image

Execute below commands to build and push the container image to OCIR:

  `$ docker build -t <region-key>.ocir.io/<tenancy-namespace>/oci-oke-waf-operator:latest .`
  
  `$ docker push <region-key>.ocir.io/<tenancy-namespace>/oci-oke-waf-operator:latest`

### Setup OCI Dynamic Group and Policies

1. Create one dynamic group named `oke-waf-operator` with the following matching rule:
  `instance.compartment.id = '<OKE_cluster_compartment_ocid>'`

    **Note**:

    It's strongly recommended to:
    - use [NodeAffinity](https://kubernetes.io/docs/concepts/scheduling-eviction/assign-pod-node/) when deploying the operator and take advantage of the [NodePool Kubernetes Labels](https://docs.oracle.com/en-us/iaas/Content/ContEng/Tasks/contengmodifyingnodepool.htm) for this.

    - define Tags for nodePool where operator should run using Defined Tags (the configured tags and labels will not apply to the exiting nodes in the node pool but only to the ones which will be created in the future). Update the dynamic-group match rule to include the defined tags configured before:

    `All {instance.compartment.id='<OKE_cluster_compartment_ocid>', tag.<tag_namespace>.<tag_key>.value='<tag_value>'}`

2. Create operator policy in the root compartment (required to identify WAF attached to the load balancer outside of the OKE compartment):
   
  `Allow dynamic-group oke-waf-operator to read waf-family in tenancy`
4. Create operator policy in the OKE cluster compartment

  `Allow dynamic-group oke-waf-operator to read clusters in compartment <compartment_name>`

  `Allow dynamic-group oke-waf-operator to read load-balancers in compartment <compartment_name>`

  `Allow dynamic-group oke-waf-operator to read waf-policy in compartment <compartment_name>`
  
  `Allow dynamic-group oke-waf-operator to manage web-app-firewall in compartment <compartment_name>`

  

### Configure Kubernetes ImagePull Secret

  ```$ kubectl create secret docker-registry ocirsecret --docker-server=<region-key>.ocir.io --docker-username='<tenancy-namespace>/<oci-username>' --docker-password='<oci-auth-token>' --docker-email='<email-address>'```

[More details](https://www.oracle.com/webfolder/technetwork/tutorials/obe/oci/oke-and-registry/index.html#CreateaSecretfortheTutorial)


### Create the Service Account required by the operator

  `$ kubectl apply -f deploy/rbac.yaml`

### Deploy the operator

Update the container `image` and `imagePullSecrets` in the `operator.yaml` file and depoy the operator.

  `$ kubectl apply -f deploy/operator.yaml`

## Configuration

The default compartment where certificates will be created is the same compartment where the OKE cluster is created.
It is possible to customize the compartment by setting the container environment variable: `COMPARTMENT_OCID` to the desired compartment_ocid (`ocid1.compartment.oc1..diqq`).

## Test

1. Create a WAF policy in the same compartment with the OKE cluster.
2. Create an OKE service of type `LoadBalancer`.
3. Label the new created service with `use-oci-lb-operator: "yes"`.
4. Annotate the new service with `service.beta.kubernetes.io/oci-load-balancer-waf-policy-ocid: "<WAF_POLICY_OCID>"`

  **Note**:
  Load balancer listeners must be of type `HTTP` or `HTTPS` for the WAF to work.

## Limitations

None known.

## License

Copyright (c) 2023 Oracle and/or its affiliates.
Released under the Universal Permissive License v1.0 as shown at <https://oss.oracle.com/licenses/upl/>.
