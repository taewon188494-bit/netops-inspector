"""가상 Link Capacity 변경의 Pre-check, Post-check와 Rollback을 수행합니다."""

# 명령줄에서 간단한 Change 시나리오를 받기 위해 sys를 불러옵니다.
import sys

# 기존 Change Analyzer의 계산과 판정 함수를 그대로 재사용합니다.
from change_analyzer import (
    TEST_TARGET_TRAFFIC_MBPS,
    apply_utilization_effects,
    capture_link_baseline_metrics,
    change_link_capacity,
    collect_quality_metrics,
    evaluate_change,
)
# 기존 Device Health와 Config Compliance 분석을 Pre-check에서 재사용합니다.
from device_health_checker import (
    analyze_all_devices,
    initialize_device_operations_data,
)
# 기존 topology와 DEVICE_OVERLOAD 주입 함수를 그대로 재사용합니다.
from network_simulator import create_network, inject_device_overload


# 변경하려는 내용만 기록하고 실제 Network 상태는 아직 바꾸지 않습니다.
def create_change_request(change_id, target_link, new_capacity_mbps):
    change_request = {
        "change_id": change_id,
        "change_type": "LINK_CAPACITY_CHANGE",
        "target": {
            "source": target_link[0],
            "destination": target_link[1],
        },
        "requested_capacity_mbps": new_capacity_mbps,
        "status": "REQUESTED",
    }
    return change_request


# Rollback에 필요한 Target Link의 변경 전 값을 명시적으로 저장합니다.
def create_change_snapshot(network, source, destination):
    if not network.has_edge(source, destination):
        raise ValueError(f"가상 Link를 찾을 수 없습니다: {source} <-> {destination}")

    link = network[source][destination]
    snapshot = {
        "source": source,
        "destination": destination,
        "capacity_mbps": link["capacity_mbps"],
        "traffic_mbps": link["traffic_mbps"],
        "latency_ms": link["latency_ms"],
        "packet_loss_percent": link["packet_loss_percent"],
        "status": link["status"],
        "baseline_latency_ms": link["baseline_latency_ms"],
        "baseline_packet_loss_percent": link[
            "baseline_packet_loss_percent"
        ],
        "utilization_percent": (
            link["traffic_mbps"] / link["capacity_mbps"] * 100
        ),
    }
    return snapshot


# 변경 전 현재 Network가 Change 수행에 적합한지 PASS/FAIL로 확인합니다.
def run_pre_check(network, change_request):
    checks = []
    reasons = []
    source = change_request["target"]["source"]
    destination = change_request["target"]["destination"]

    target_exists = network.has_edge(source, destination)
    checks.append(
        {"check": "TARGET_LINK_EXISTS", "result": "PASS" if target_exists else "FAIL"}
    )
    if not target_exists:
        reasons.append("TARGET_LINK_NOT_FOUND")

    if target_exists:
        link_status = network[source][destination]["status"]
        # 기존 graph는 사용할 수 있는 Link를 NORMAL로 표시하므로 UP과 함께 허용합니다.
        if link_status == "NORMAL" or link_status == "UP":
            status_result = "PASS"
        else:
            status_result = "FAIL"
            reasons.append("TARGET_LINK_NOT_ACTIVE")
    else:
        link_status = "NOT_FOUND"
        status_result = "FAIL"

    checks.append(
        {
            "check": "TARGET_LINK_STATUS",
            "result": status_result,
            "value": link_status,
        }
    )

    requested_capacity = change_request["requested_capacity_mbps"]
    if requested_capacity > 0:
        capacity_result = "PASS"
    else:
        capacity_result = "FAIL"
        reasons.append("REQUESTED_CAPACITY_MUST_BE_POSITIVE")
    checks.append(
        {
            "check": "REQUESTED_CAPACITY",
            "result": capacity_result,
            "value": requested_capacity,
        }
    )

    network_summary = collect_quality_metrics(network)
    disconnected = network_summary["disconnected_edge_nodes"]
    if disconnected == 0:
        connectivity_result = "PASS"
    else:
        connectivity_result = "FAIL"
        reasons.append("DISCONNECTED_EDGE_EXISTS")
    checks.append(
        {
            "check": "NETWORK_CONNECTIVITY",
            "result": connectivity_result,
            "disconnected_edge_nodes": disconnected,
        }
    )

    # 초기화는 Workflow 시작 때 한 번만 했으므로 현재 overload/config 상태를 읽습니다.
    device_results = analyze_all_devices(network)
    critical_devices = []
    failed_config_devices = []
    for device_result in device_results:
        if device_result["health"]["status"] == "CRITICAL":
            critical_devices.append(device_result["device"])
        if device_result["config_compliance"]["status"] == "FAIL":
            failed_config_devices.append(device_result["device"])

    if critical_devices:
        health_result = "FAIL"
        reasons.append("CRITICAL_DEVICE_HEALTH_EXISTS")
    else:
        health_result = "PASS"
    checks.append(
        {
            "check": "DEVICE_HEALTH",
            "result": health_result,
            "critical_devices": critical_devices,
        }
    )

    if failed_config_devices:
        config_result = "FAIL"
        reasons.append("CONFIG_COMPLIANCE_FAILURE_EXISTS")
    else:
        config_result = "PASS"
    checks.append(
        {
            "check": "CONFIG_COMPLIANCE",
            "result": config_result,
            "failed_devices": failed_config_devices,
        }
    )

    if reasons:
        result = "FAIL"
    else:
        result = "PASS"
    return {"result": result, "checks": checks, "reasons": reasons}


# 기존 함수로 NetworkX Target Link의 capacity만 변경합니다.
def apply_change(network, change_request):
    source = change_request["target"]["source"]
    destination = change_request["target"]["destination"]
    old_capacity = network[source][destination]["capacity_mbps"]
    new_capacity = change_request["requested_capacity_mbps"]

    change_link_capacity(
        network,
        source,
        destination,
        new_capacity,
        print_details=False,
    )
    return {
        "applied": True,
        "old_capacity_mbps": old_capacity,
        "new_capacity_mbps": new_capacity,
    }


# 변경 후 기존 quality effect와 PASS/WARNING/FAIL 평가를 실행합니다.
def run_post_check(network, before_summary, baseline_metrics):
    apply_utilization_effects(network, baseline_metrics, print_details=False)
    after_summary = collect_quality_metrics(network)
    result, reasons = evaluate_change(before_summary, after_summary)
    return {
        "result": result,
        "after_summary": after_summary,
        "reasons": reasons,
    }


# Snapshot에 저장한 Target Link 값을 모두 원래 상태로 복원합니다.
def rollback_change(network, snapshot):
    source = snapshot["source"]
    destination = snapshot["destination"]
    link = network[source][destination]
    capacity_before_rollback = link["capacity_mbps"]

    link["capacity_mbps"] = snapshot["capacity_mbps"]
    link["traffic_mbps"] = snapshot["traffic_mbps"]
    link["latency_ms"] = snapshot["latency_ms"]
    link["packet_loss_percent"] = snapshot["packet_loss_percent"]
    link["status"] = snapshot["status"]
    link["baseline_latency_ms"] = snapshot["baseline_latency_ms"]
    link["baseline_packet_loss_percent"] = snapshot[
        "baseline_packet_loss_percent"
    ]
    link["utilization_percent"] = snapshot["utilization_percent"]

    return {
        "performed": True,
        "result": "APPLIED",
        "capacity_before_rollback_mbps": capacity_before_rollback,
        "restored_capacity_mbps": snapshot["capacity_mbps"],
    }


# Rollback 후 Target Link와 Network Summary가 변경 전 값으로 돌아왔는지 확인합니다.
def run_recovery_check(network, before_summary, snapshot):
    source = snapshot["source"]
    destination = snapshot["destination"]
    link = network[source][destination]
    recovered_summary = collect_quality_metrics(network)
    reasons = []

    if link["capacity_mbps"] != snapshot["capacity_mbps"]:
        reasons.append("CAPACITY_NOT_RESTORED")
    if link["status"] != snapshot["status"]:
        reasons.append("LINK_STATUS_NOT_RESTORED")
    if recovered_summary["disconnected_edge_nodes"] != before_summary[
        "disconnected_edge_nodes"
    ]:
        reasons.append("CONNECTIVITY_NOT_RESTORED")

    summary_keys = [
        "connected_edge_nodes",
        "disconnected_edge_nodes",
        "average_path_latency_ms",
        "average_packet_loss_percent",
        "max_utilization_percent",
    ]
    for summary_key in summary_keys:
        before_value = round(before_summary[summary_key], 2)
        recovered_value = round(recovered_summary[summary_key], 2)
        if before_value != recovered_value:
            reasons.append(f"SUMMARY_NOT_RESTORED: {summary_key}")

    if reasons:
        result = "FAIL"
    else:
        result = "PASS"
    return {
        "result": result,
        "recovered_summary": recovered_summary,
        "reasons": reasons,
    }


# Change Request부터 필요 시 Rollback 검증까지 전체 순서를 연결합니다.
def run_change_workflow(
    source,
    destination,
    new_capacity_mbps,
    precheck_overload_device=None,
):
    network = create_network()
    # 이 초기화는 한 번만 실행하며 이후 Pre/Post-check는 현재 값을 읽기만 합니다.
    initialize_device_operations_data(network)
    change_request = create_change_request(
        "CHANGE-001",
        (source, destination),
        new_capacity_mbps,
    )
    timeline = ["CHANGE_REQUEST_CREATED"]

    # 기존 Change Analyzer 대표 시나리오와 같은 500Mbps workload를 사용합니다.
    if network.has_edge(source, destination):
        network[source][destination]["traffic_mbps"] = TEST_TARGET_TRAFFIC_MBPS

    if precheck_overload_device is not None:
        inject_device_overload(
            network,
            precheck_overload_device,
            print_details=False,
        )

    before_summary = collect_quality_metrics(network)
    baseline_metrics = capture_link_baseline_metrics(network)
    pre_check = run_pre_check(network, change_request)

    record = {
        "change_id": change_request["change_id"],
        "change_type": change_request["change_type"],
        "status": "REQUESTED",
        "request": change_request,
        "pre_check": pre_check,
        "before_snapshot": None,
        "before_summary": before_summary,
        "apply_result": None,
        "post_check": None,
        "rollback": {"performed": False, "result": "NOT_REQUIRED"},
        "recovery_check": None,
        "timeline": timeline,
    }

    # Pre-check FAIL이면 Network를 변경하지 않고 함수 실행을 여기서 끝냅니다.
    if pre_check["result"] == "FAIL":
        change_request["status"] = "PRECHECK_FAILED"
        record["status"] = "PRECHECK_FAILED"
        timeline.append("PRECHECK_FAILED")
        return record

    change_request["status"] = "PRECHECK_PASSED"
    timeline.append("PRECHECK_PASSED")
    snapshot = create_change_snapshot(network, source, destination)
    record["before_snapshot"] = snapshot

    record["apply_result"] = apply_change(network, change_request)
    change_request["status"] = "APPLIED"
    timeline.append("CHANGE_APPLIED")

    post_check = run_post_check(network, before_summary, baseline_metrics)
    record["post_check"] = post_check

    if post_check["result"] == "PASS":
        record["status"] = "POSTCHECK_PASSED"
        timeline.append("POSTCHECK_PASSED")
    elif post_check["result"] == "WARNING":
        # WARNING은 주의 상태이므로 변경을 유지하고 자동 Rollback하지 않습니다.
        record["status"] = "POSTCHECK_WARNING"
        timeline.append("POSTCHECK_WARNING")
    else:
        record["status"] = "POSTCHECK_FAILED"
        timeline.append("POSTCHECK_FAILED")

        record["rollback"] = rollback_change(network, snapshot)
        timeline.append("ROLLBACK_APPLIED")
        recovery_check = run_recovery_check(network, before_summary, snapshot)
        record["recovery_check"] = recovery_check

        if recovery_check["result"] == "PASS":
            record["status"] = "ROLLBACK_VERIFIED"
            timeline.append("ROLLBACK_VERIFIED")
        else:
            record["status"] = "ROLLBACK_FAILED"
            timeline.append("ROLLBACK_FAILED")

    return record


# Change Record의 각 단계를 실행 순서대로 출력합니다.
def print_change_workflow_report(record):
    request = record["request"]
    target = request["target"]
    print("=" * 72)
    print("CHANGE WORKFLOW - LEARNING SIMULATION")
    print("실제 장비 Change Management 또는 Network Transaction이 아닙니다.")
    print("=" * 72)
    print(f"Change ID : {record['change_id']}")
    print(f"Target    : {target['source']} <-> {target['destination']}")
    print(f"Requested : {request['requested_capacity_mbps']} Mbps")

    print("\n[Pre-check]")
    for check in record["pre_check"]["checks"]:
        print(f"{check['check']:<25}: {check['result']}")
    print(f"Result                    : {record['pre_check']['result']}")
    for reason in record["pre_check"]["reasons"]:
        print(f"- {reason}")

    if record["apply_result"] is not None:
        apply_result = record["apply_result"]
        print("\n[Apply]")
        print("Result   : APPLIED")
        print(
            f"Capacity : {apply_result['old_capacity_mbps']} -> "
            f"{apply_result['new_capacity_mbps']} Mbps"
        )

    if record["post_check"] is not None:
        post_check = record["post_check"]
        after = post_check["after_summary"]
        print("\n[Post-check]")
        print(f"Connected EDGE : {after['connected_edge_nodes']}")
        print(f"Max Utilization: {after['max_utilization_percent']:.2f}%")
        print(f"Avg Latency    : {after['average_path_latency_ms']:.2f} ms")
        print(f"Avg Loss       : {after['average_packet_loss_percent']:.2f}%")
        print(f"Result         : {post_check['result']}")
        for reason in post_check["reasons"]:
            print(f"- {reason}")

    print("\n[Rollback]")
    print(f"Performed : {record['rollback']['performed']}")
    print(f"Result    : {record['rollback']['result']}")
    if record["rollback"]["performed"]:
        print(
            f"Capacity  : {record['rollback']['capacity_before_rollback_mbps']} "
            f"-> {record['rollback']['restored_capacity_mbps']} Mbps"
        )

    if record["recovery_check"] is not None:
        print("\n[Recovery Check]")
        print(f"Result : {record['recovery_check']['result']}")
        for reason in record["recovery_check"]["reasons"]:
            print(f"- {reason}")

    print(f"\nFinal Status: {record['status']}")
    print("\n[Timeline]")
    for timeline_item in record["timeline"]:
        print(timeline_item)
    print("=" * 72)


# 이 파일을 직접 실행하면 선택한 Link Capacity Change를 수행합니다.
if __name__ == "__main__":
    arguments = sys.argv[1:]

    try:
        if not arguments:
            generated_record = run_change_workflow("CORE-01", "AGG-01", 450)
        elif len(arguments) == 4 and arguments[0].upper() == "CAPACITY":
            capacity = int(arguments[3])
            generated_record = run_change_workflow(
                arguments[1],
                arguments[2],
                capacity,
            )
        elif (
            len(arguments) == 5
            and arguments[0].upper() == "PRECHECK_DEVICE_OVERLOAD"
        ):
            capacity = int(arguments[3])
            generated_record = run_change_workflow(
                arguments[1],
                arguments[2],
                capacity,
                precheck_overload_device=arguments[4],
            )
        else:
            raise ValueError(
                "사용법: python src/change_workflow_manager.py "
                "[CAPACITY 장비1 장비2 capacity | "
                "PRECHECK_DEVICE_OVERLOAD 장비1 장비2 capacity 장비]"
            )

        print_change_workflow_report(generated_record)
    except ValueError as error:
        print(f"Change Workflow를 실행할 수 없습니다: {error}")
