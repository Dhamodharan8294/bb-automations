## Database

### Tablewide Schema

```
Primary Key   |  Sort Key
-------------------------
pk            |  sk
```

### Tenant Metadata

#### Schema

```
pk                                | sk        |  CreatedAt               | UpdateAt                 | Version | OutboundQueueArn | OutboundQueueUrl | InboundQueueArn | InboundQueueUrl
----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

TENANT_ID#032400-000000-0000-0002 | METADATA  | 2020-08-31T16:02:16.808Z | 2020-08-31T16:02:16.808Z | 0.1.12  | arn...            | https://...     | arn...           | https://...
TENANT_ID#005320-000000-0000-0003 | METADATA  | 2020-08-31T16:02:16.808Z | 2020-08-31T16:02:16.808Z | 0.1.14  | arn...            | https://...     | arn...           | https://...
```

**pk -** TENANT_ID#{id}

**sk -** Metadata

**CreatedAt -** timstamp when the stack was first created

**UpdatedAt -** timestamp of last update

**Version -** Current tenant CloudFormation definition [version.txt](../functions/tenant_resources/deploy_stack/version.txt)

**OutboundQueueArn -** ~~Outbound queue Aws arn~~
- Column still exists for older tenant stacks, but will be cleared as stacks get upgraded and the queue is deleted.

**OutboundQueueUrl -** ~~Outbound queue url~~
- Column still exists for older tenant stacks, but will be cleared as stacks get upgraded and the queue is deleted.

**InboundQueueArn -** Inbound queue Aws arn

**InboundQueueUrl -** Inbound queue url

#### Access Patterns

Get Queue by tenantId for getQueue Endpoint
Created and Updated via custom resource in cdk program

### Tenant Operation Audit

#### Schema

```
pk                                | sk                             |  UpdatedAt               | Execution          | Status  
----------------------------------------------------------------------------------------------------------------------------

TENANT_ID#000000-000000-0000-0000 | AUDIT#CREATE                   | 2020-08-31T16:02:16.808Z | arn:aws:states:... | Started
TENANT_ID#000000-000000-0000-0000 | AUDIT#UPDATE#0.1.18            | 2020-08-31T16:02:16.808Z | arn:aws:states:... | Failure
TENANT_ID#000000-000000-0000-0000 | AUDIT#DELETE                   | 2020-08-31T16:02:16.808Z | arn:aws:states:... | Success
```

pk - TENANT_ID#{id}

sk - AUDIT#{operation}(#{version}) - operations exist of CREATE, UPDATE, DELETE and version is not present for DELETE

UpdatedAt - timestamp of last update

Execution - arn of step function execution

Status - Started | Failure | Success - based on the result of the step function

#### Access Patterns

GetQueue request comes in, but there is no queue metadata in the db:
- Check if a provision has kicked off for the current cdk program version
    - no provision has started for this version, kick one off
    - provision has kicked off tell client to wait
    - provision failed notify client with an error
