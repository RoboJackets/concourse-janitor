"""
Clean up resources from retired Concourse workers
"""
from json import dumps
from os import environ
from re import search

from boto3 import client  # type: ignore

INSTANCE_ID_REGEX = r"(?P<instance_id>i-[0-9a-z]{17})"
HOSTED_ZONE_ID = environ["HOSTED_ZONE_ID"]

ec2 = client("ec2")
logs = client("logs")
route53 = client("route53")
sqs = client("sqs")


def handler(event: None, context: None) -> None:  # pylint: disable=unused-argument,too-many-locals
    """
    Get currently running instances and delete any CloudWatch log groups, SQS queues, or Route 53 records associated
    with instances that don't exist
    """
    instance_ids = []

    ec2_response = ec2.describe_instances(MaxResults=1000)

    for reservation in ec2_response["Reservations"]:
        for instance in reservation["Instances"]:
            instance_ids.append(instance["InstanceId"])

    print(dumps(instance_ids))

    log_group_response = logs.describe_log_groups()

    for log_group in log_group_response["logGroups"]:
        log_group_name = log_group["logGroupName"]
        match_parts = search(INSTANCE_ID_REGEX, log_group_name)
        if match_parts is not None:
            instance_id = match_parts.group("instance_id")
            if instance_id not in instance_ids:
                logs.delete_log_group(logGroupName=log_group_name)
                print(f"Deleted log group {log_group_name}")

    sqs_response = sqs.list_queues()

    for queue_url in sqs_response["QueueUrls"]:
        match_parts = search(INSTANCE_ID_REGEX, queue_url)
        if match_parts is not None:
            instance_id = match_parts.group("instance_id")
            if instance_id not in instance_ids:
                sqs.delete_queue(QueueUrl=queue_url)
                print(f"Deleted queue {queue_url}")

    route53_response = route53.list_resource_record_sets(HostedZoneId=HOSTED_ZONE_ID)
    route_53_changes = []

    for resource_record_set in route53_response["ResourceRecordSets"]:
        name = resource_record_set["Name"]
        match_parts = search(INSTANCE_ID_REGEX, name)
        if match_parts is not None:
            instance_id = match_parts.group("instance_id")
            if instance_id not in instance_ids:
                route_53_changes.append({"Action": "DELETE", "ResourceRecordSet": resource_record_set})
                print(f"Queued {name} for deletion")

    if len(route_53_changes) > 0:
        route53.change_resource_record_sets(
            HostedZoneId=HOSTED_ZONE_ID,
            ChangeBatch={"Comment": "Cleaning up old instance records", "Changes": route_53_changes},
        )
        print(f"Deleted {len(route_53_changes)} records")


if __name__ == "__main__":
    handler(None, None)
