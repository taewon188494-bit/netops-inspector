"""기존 운영 분석 결과를 하나의 학습용 통합 Report로 요약합니다."""

import sys

from change_workflow_manager import run_change_workflow
from device_health_checker import create_device_check_summary, run_device_check_scenario
from event_alarm_manager import analyze_time_series_events, create_alarm_summary, run_event_alarm_scenario
from network_inventory import create_inventory_summary, run_inventory_scenario
from service_quality_analyzer import run_service_quality_scenario
from traffic_trend_analyzer import run_traffic_trend_scenario


def require_key(data, key, section_name):
    """필수 key가 없을 때 잘못된 기본값 대신 읽기 쉬운 오류를 냅니다."""
    if key not in data:
        raise ValueError(f"{section_name} Section에 필수 key가 없습니다: {key}")
    return data[key]


def collect_service_section(service_result):
    summary = require_key(service_result, "summary", "Service")
    results = require_key(service_result, "results", "Service")
    affected_services = []

    for result in results:
        if result.get("quality_status") != "NORMAL":
            affected_services.append({
                "flow_id": require_key(result, "flow_id", "Service"),
                "service": require_key(result, "service", "Service"),
                "status": require_key(result, "quality_status", "Service"),
            })

    return {
        "summary": {
            "total_services": require_key(summary, "total_services", "Service"),
            "normal": require_key(summary, "normal_services", "Service"),
            "degraded": require_key(summary, "degraded_services", "Service"),
            "critical": require_key(summary, "critical_services", "Service"),
        },
        "affected_services": affected_services,
    }


def collect_alarm_section(alarm_result):
    summary = require_key(alarm_result, "summary", "Alarm")
    alarm_log = require_key(alarm_result, "alarm_log", "Alarm")
    critical_alarms = []
    warning_alarms = []

    for alarm in alarm_log:
        item = {
            "alarm_id": require_key(alarm, "alarm_id", "Alarm"),
            "event_type": require_key(alarm, "alarm_type", "Alarm"),
            "target": require_key(alarm, "target", "Alarm"),
            "severity": require_key(alarm, "severity", "Alarm"),
        }
        if item["severity"] == "CRITICAL":
            critical_alarms.append(item)
        elif item["severity"] == "WARNING":
            warning_alarms.append(item)

    return {
        "summary": {
            "total_alarms": require_key(summary, "total_alarms", "Alarm"),
            "warning": require_key(summary, "warning_alarms", "Alarm"),
            "critical": require_key(summary, "critical_alarms", "Alarm"),
        },
        "critical_alarms": critical_alarms,
        "warning_alarms": warning_alarms,
    }


def collect_device_section(device_results):
    """하나 이상의 기존 Device 시나리오 결과를 장비별로 합칩니다."""
    if not device_results:
        raise ValueError("Device Section에 분석 결과가 없습니다.")

    merged_records = []
    first_results = require_key(device_results[0], "results", "Device")
    for first_record in first_results:
        merged_records.append(first_record)

    # 뒤 시나리오에서 문제가 발견된 부분만 기존 판정 결과 그대로 선택합니다.
    for scenario in device_results[1:]:
        for new_record in require_key(scenario, "results", "Device"):
            for merged_record in merged_records:
                if merged_record["device"] == new_record["device"]:
                    if new_record["health"]["status"] != "NORMAL":
                        merged_record["health"] = new_record["health"]
                    if new_record["config_compliance"]["status"] != "PASS":
                        merged_record["config_compliance"] = new_record["config_compliance"]

    # 상태별 count도 기존 Device Summary 함수에 맡깁니다.
    summary = create_device_check_summary(merged_records)
    attention_devices = []
    for record in merged_records:
        health_status = record["health"]["status"]
        config_status = record["config_compliance"]["status"]
        if health_status != "NORMAL" or config_status != "PASS":
            attention_devices.append({
                "device_id": record["device"],
                "health_status": health_status,
                "config_status": config_status,
            })

    return {"summary": summary, "attention_devices": attention_devices}


def collect_inventory_section(inventory_results):
    if not inventory_results:
        raise ValueError("Inventory Section에 분석 결과가 없습니다.")

    merged_inventory = []
    for record in require_key(inventory_results[0], "inventory", "Inventory"):
        merged_inventory.append(record)

    for scenario in inventory_results[1:]:
        for new_record in require_key(scenario, "inventory", "Inventory"):
            if new_record["operational_status"] == "ATTENTION":
                for index in range(len(merged_inventory)):
                    if merged_inventory[index]["device_id"] == new_record["device_id"]:
                        merged_inventory[index] = new_record

    # Role과 상태 count는 기존 Inventory Summary 함수가 담당합니다.
    source_summary = create_inventory_summary(merged_inventory)
    return {"summary": {
        "total_devices": source_summary["total_devices"],
        "core": source_summary["core_devices"],
        "agg": source_summary["agg_devices"],
        "edge": source_summary["edge_devices"],
        "up": source_summary["up_devices"],
        "attention": source_summary["attention_devices"],
    }}


def collect_capacity_section(capacity_result):
    return {
        "target": (
            f"{require_key(capacity_result, 'source', 'Capacity')} <-> "
            f"{require_key(capacity_result, 'destination', 'Capacity')}"
        ),
        "trend_direction": require_key(capacity_result, "trend_direction", "Capacity"),
        "latest_utilization_percent": require_key(
            capacity_result, "latest_utilization_percent", "Capacity"
        ),
        "average_change_percent_per_tick": require_key(
            capacity_result, "average_change_percent_per_tick", "Capacity"
        ),
        "status": require_key(capacity_result, "capacity_status", "Capacity"),
        "reason": require_key(capacity_result, "capacity_reason", "Capacity"),
    }


def collect_change_section(change_result=None):
    if change_result is None:
        return {"executed": False, "status": "NOT_EXECUTED"}

    post_check = require_key(change_result, "post_check", "Change")
    recovery_check = require_key(change_result, "recovery_check", "Change")
    rollback = require_key(change_result, "rollback", "Change")
    if post_check is None or recovery_check is None:
        raise ValueError("Change Section에 Post-check 또는 Recovery 결과가 없습니다.")
    return {
        "executed": True,
        "change_id": require_key(change_result, "change_id", "Change"),
        "status": require_key(change_result, "status", "Change"),
        "post_check_result": require_key(post_check, "result", "Change"),
        "rollback_performed": require_key(rollback, "performed", "Change"),
        "recovery_result": require_key(recovery_check, "result", "Change"),
    }


def determine_overall_status(report):
    service = report["service"]["summary"]
    alarm = report["alarm"]["summary"]
    device = report["device"]["summary"]
    inventory = report["inventory"]["summary"]
    capacity_status = report["capacity"]["status"]
    change = report["change"]

    if (
        service["critical"] > 0
        or alarm["critical"] > 0
        or device["health_critical"] > 0
        or capacity_status == "CRITICAL"
        or change["status"] == "ROLLBACK_FAILED"
    ):
        return "CRITICAL"
    if (
        service["degraded"] > 0
        or alarm["warning"] > 0
        or device["health_warning"] > 0
        or device["config_fail"] > 0
        or inventory["attention"] > 0
        or capacity_status == "WATCH"
        or capacity_status == "WARNING"
        or change["status"] == "ROLLBACK_VERIFIED"
        or change.get("post_check_result") == "WARNING"
    ):
        return "ATTENTION"
    return "NORMAL"


def create_key_findings(report):
    findings = []
    for service in report["service"]["affected_services"]:
        findings.append(
            f"{service['flow_id']} {service['service']} service quality is {service['status']}."
        )
    for alarm in report["alarm"]["critical_alarms"] + report["alarm"]["warning_alarms"]:
        findings.append(
            f"{alarm['alarm_id']} {alarm['event_type']} alarm is {alarm['severity']}."
        )
    for device in report["device"]["attention_devices"]:
        if device["health_status"] != "NORMAL":
            findings.append(
                f"{device['device_id']} health status is {device['health_status']}."
            )
        if device["config_status"] != "PASS":
            findings.append(
                f"{device['device_id']} config compliance is {device['config_status']}."
            )
    if report["capacity"]["status"] != "NORMAL":
        findings.append(
            f"{report['capacity']['target']} capacity trend is {report['capacity']['status']}."
        )
    if report["change"]["executed"]:
        findings.append(
            f"{report['change']['change_id']} change status is {report['change']['status']}."
        )
    if not findings:
        findings.append("No major operational issue detected.")
    return findings


def create_integrated_report(scenario_type="NORMAL"):
    scenario_type = scenario_type.upper()
    if scenario_type not in ("NORMAL", "DEGRADED", "CHANGE_FAILURE"):
        raise ValueError(f"지원하지 않는 Integrated Report 시나리오입니다: {scenario_type}")

    if scenario_type == "DEGRADED":
        service_result = run_service_quality_scenario(
            "CONGESTION", ("AGG-01", "EDGE-01")
        )
        alarm_result = run_event_alarm_scenario(
            "CONGESTION", ("AGG-01", "EDGE-01")
        )
        device_results = [
            run_device_check_scenario("DEVICE_OVERLOAD", "AGG-02"),
            run_device_check_scenario(
                "CONFIG_MISMATCH", ("AGG-01", "logging_enabled", False)
            ),
        ]
        inventory_results = [
            run_inventory_scenario("DEVICE_OVERLOAD", "AGG-02"),
            run_inventory_scenario(
                "CONFIG_MISMATCH", ("AGG-01", "logging_enabled", False)
            ),
        ]
        capacity_result = run_traffic_trend_scenario()
        change_result = None
    else:
        service_result = run_service_quality_scenario()
        empty_alarm_analysis = analyze_time_series_events([])
        empty_alarm_analysis["summary"] = create_alarm_summary(
            empty_alarm_analysis["alarm_log"]
        )
        alarm_result = empty_alarm_analysis
        device_results = [run_device_check_scenario()]
        inventory_results = [run_inventory_scenario()]
        capacity_result = run_traffic_trend_scenario(
            "CORE-01", "AGG-01", 300, 0, 5
        )
        if scenario_type == "CHANGE_FAILURE":
            change_result = run_change_workflow("CORE-01", "AGG-01", 450)
        else:
            change_result = None

    report = {
        "scenario": scenario_type,
        "overall_status": None,
        "service": collect_service_section(service_result),
        "alarm": collect_alarm_section(alarm_result),
        "device": collect_device_section(device_results),
        "inventory": collect_inventory_section(inventory_results),
        "capacity": collect_capacity_section(capacity_result),
        "change": collect_change_section(change_result),
        "key_findings": [],
    }
    report["overall_status"] = determine_overall_status(report)
    report["key_findings"] = create_key_findings(report)
    return report


def print_integrated_report(report):
    print("=" * 72)
    print("INTEGRATED NETWORK OPERATIONS REPORT")
    print("LEARNING SIMULATION")
    print("=" * 72)
    print(f"Scenario       : {report['scenario']}")
    print(f"Overall Status : {report['overall_status']}")

    service = report["service"]
    print("\n[Service Quality]")
    print(f"Total Services : {service['summary']['total_services']}")
    print(f"NORMAL         : {service['summary']['normal']}")
    print(f"DEGRADED       : {service['summary']['degraded']}")
    print(f"CRITICAL       : {service['summary']['critical']}")
    print("Affected:")
    if not service["affected_services"]:
        print("- None")
    for item in service["affected_services"]:
        print(f"- {item['flow_id']} / {item['service']} / {item['status']}")

    alarm = report["alarm"]
    print("\n[Alarm]")
    print(f"Total    : {alarm['summary']['total_alarms']}")
    print(f"WARNING  : {alarm['summary']['warning']}")
    print(f"CRITICAL : {alarm['summary']['critical']}")
    for item in alarm["critical_alarms"] + alarm["warning_alarms"]:
        print(f"- {item['alarm_id']} / {item['event_type']} / {item['target']}")

    device = report["device"]
    print("\n[Device]")
    for label, key in (
        ("Total Devices", "total_devices"), ("Health NORMAL", "health_normal"),
        ("Health WARNING", "health_warning"), ("Health CRITICAL", "health_critical"),
        ("Config PASS", "config_pass"), ("Config FAIL", "config_fail"),
    ):
        print(f"{label:<15}: {device['summary'][key]}")
    print("Attention:")
    if not device["attention_devices"]:
        print("- None")
    for item in device["attention_devices"]:
        print(
            f"- {item['device_id']} / Health {item['health_status']} / "
            f"Config {item['config_status']}"
        )

    inventory = report["inventory"]["summary"]
    print("\n[Inventory]")
    for label, key in (
        ("Total", "total_devices"), ("CORE", "core"), ("AGG", "agg"),
        ("EDGE", "edge"), ("UP", "up"), ("ATTENTION", "attention"),
    ):
        print(f"{label:<10}: {inventory[key]}")

    capacity = report["capacity"]
    print("\n[Capacity]")
    print(f"Target             : {capacity['target']}")
    print(f"Trend              : {capacity['trend_direction']}")
    print(f"Latest Utilization : {capacity['latest_utilization_percent']:.2f}%")
    print(f"Average Change     : {capacity['average_change_percent_per_tick']:.2f}%")
    print(f"Status             : {capacity['status']}")
    print(f"Reason             : {capacity['reason']}")

    change = report["change"]
    print("\n[Change]")
    print(f"Executed : {change['executed']}")
    print(f"Status   : {change['status']}")
    if change["executed"]:
        print(f"Post-check : {change['post_check_result']}")
        print(f"Rollback   : {change['rollback_performed']}")
        print(f"Recovery   : {change['recovery_result']}")

    print("\n[Key Findings]")
    for finding in report["key_findings"]:
        print(f"- {finding}")
    print("\n" + "=" * 72)
    print(f"Overall Status: {report['overall_status']}")
    print("=" * 72)
    print("This is a learning simulation, not a real carrier NMS/OSS report.")


if __name__ == "__main__":
    arguments = sys.argv[1:]
    try:
        if len(arguments) > 1:
            raise ValueError(
                "사용법: python src/integrated_operations_report.py "
                "[NORMAL | DEGRADED | CHANGE_FAILURE]"
            )
        selected_scenario = arguments[0] if arguments else "NORMAL"
        generated_report = create_integrated_report(selected_scenario)
        print_integrated_report(generated_report)
    except ValueError as error:
        print(f"Integrated Operations Report를 만들 수 없습니다: {error}")
