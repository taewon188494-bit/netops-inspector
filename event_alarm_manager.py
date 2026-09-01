"""Time-series Metric 이상을 Event와 Alarm Log로 자동 기록합니다."""

# 명령줄에서 간단한 시나리오 종류와 대상을 받기 위해 sys를 불러옵니다.
import sys

# 기존 Time-series가 만든 snapshot list를 그대로 재사용합니다.
from time_series_simulator import (
    run_congestion_time_series,
    run_device_overload_time_series,
    run_link_failure_time_series,
)


# 아래 값은 실제 KT나 통신사의 NMS 기준이 아닌 학습용 threshold입니다.
EVENT_RULES = {
    "high_utilization_percent": 85,
    "high_latency_ms": 50,
    "high_packet_loss_percent": 3,
    "high_cpu_percent": 90,
}


# Event dict의 공통 key를 읽기 쉬운 한 곳에서 만듭니다.
def create_event_record(
    tick,
    event_type,
    target_type,
    target,
    value,
    threshold,
    description,
):
    event = {
        # event_id는 중복 확인 후 Event Log에 넣을 때 순서대로 추가합니다.
        "tick": tick,
        "event_type": event_type,
        "target_type": target_type,
        "target": target,
        "value": value,
        "threshold": threshold,
        "description": description,
    }
    return event


# Link snapshot 하나에서 동시에 발생한 모든 이상 Event를 찾습니다.
def detect_link_events(link_snapshot, tick):
    events = []
    target = f"{link_snapshot['source']} <-> {link_snapshot['destination']}"

    if link_snapshot["status"] == "DOWN":
        event = create_event_record(
            tick,
            "LINK_DOWN",
            "LINK",
            target,
            "DOWN",
            "status == DOWN",
            "가상 Link 상태가 DOWN으로 관측되었습니다.",
        )
        events.append(event)

    utilization = link_snapshot["utilization_percent"]
    utilization_threshold = EVENT_RULES["high_utilization_percent"]
    if utilization >= utilization_threshold:
        event = create_event_record(
            tick,
            "HIGH_UTILIZATION",
            "LINK",
            target,
            utilization,
            utilization_threshold,
            "Link utilization이 학습용 threshold 이상입니다.",
        )
        events.append(event)

    latency = link_snapshot["latency_ms"]
    latency_threshold = EVENT_RULES["high_latency_ms"]
    if latency > latency_threshold:
        event = create_event_record(
            tick,
            "HIGH_LATENCY",
            "LINK",
            target,
            latency,
            latency_threshold,
            "Link latency가 학습용 threshold를 초과했습니다.",
        )
        events.append(event)

    packet_loss = link_snapshot["packet_loss_percent"]
    packet_loss_threshold = EVENT_RULES["high_packet_loss_percent"]
    if packet_loss > packet_loss_threshold:
        event = create_event_record(
            tick,
            "HIGH_PACKET_LOSS",
            "LINK",
            target,
            packet_loss,
            packet_loss_threshold,
            "Link packet loss가 학습용 threshold를 초과했습니다.",
        )
        events.append(event)

    # 한 Link에서 여러 Rule이 동시에 참일 수 있으므로 list를 반환합니다.
    return events


# Device snapshot의 CPU가 학습용 기준 이상인지 확인합니다.
def detect_device_events(device_snapshot, tick):
    events = []
    cpu_usage = device_snapshot["cpu_usage_percent"]
    cpu_threshold = EVENT_RULES["high_cpu_percent"]

    if cpu_usage >= cpu_threshold:
        event = create_event_record(
            tick,
            "HIGH_CPU",
            "DEVICE",
            device_snapshot["device"],
            cpu_usage,
            cpu_threshold,
            "Device CPU 사용률이 학습용 threshold 이상입니다.",
        )
        events.append(event)

    return events


# 기존 Service Quality 판정이 DEGRADED 또는 CRITICAL인지 확인합니다.
def detect_service_events(service_result, tick):
    events = []
    quality_status = service_result["quality_status"]
    target = f"{service_result['flow_id']} / {service_result['service']}"

    if quality_status == "DEGRADED":
        event = create_event_record(
            tick,
            "SERVICE_DEGRADED",
            "SERVICE",
            target,
            quality_status,
            f"{service_result['service']} learning quality rule",
            "Service E2E Quality가 DEGRADED로 판정되었습니다.",
        )
        events.append(event)
    elif quality_status == "CRITICAL":
        event = create_event_record(
            tick,
            "SERVICE_CRITICAL",
            "SERVICE",
            target,
            quality_status,
            f"{service_result['service']} learning quality rule",
            "Service E2E Quality가 CRITICAL로 판정되었습니다.",
        )
        events.append(event)

    return events


# 자동 탐지된 Event를 운영자가 확인할 학습용 Alarm dict로 바꿉니다.
def create_alarm_from_event(event):
    event_type = event["event_type"]

    # Link Down과 Service Critical만 CRITICAL, 나머지는 WARNING으로 단순화합니다.
    if event_type == "LINK_DOWN" or event_type == "SERVICE_CRITICAL":
        severity = "CRITICAL"
    else:
        severity = "WARNING"

    alarm_number = event["event_id"].replace("EVENT-", "")
    alarm = {
        "alarm_id": f"ALARM-{alarm_number}",
        "event_id": event["event_id"],
        "tick": event["tick"],
        "alarm_type": event_type,
        "severity": severity,
        "target": event["target"],
        "status": "ACTIVE",
        "description": event["description"],
    }
    return alarm


# Time-series snapshot을 순서대로 읽어 새 Event와 Alarm만 Log에 추가합니다.
def analyze_time_series_events(snapshots):
    event_log = []
    alarm_log = []
    # 같은 event_type과 target이 이미 active인지 문자열 key로 기억합니다.
    active_event_keys = []

    for snapshot in snapshots:
        tick = snapshot["tick"]
        detected_events = []

        if "link_snapshot" in snapshot:
            link_events = detect_link_events(snapshot["link_snapshot"], tick)
            for event in link_events:
                detected_events.append(event)

        if "device_snapshot" in snapshot:
            device_events = detect_device_events(snapshot["device_snapshot"], tick)
            for event in device_events:
                detected_events.append(event)

        service_results = snapshot.get("service_quality", [])
        for service_result in service_results:
            service_events = detect_service_events(service_result, tick)
            for event in service_events:
                detected_events.append(event)

        # 같은 이상이 T3/T4에도 유지되면 active key가 있으므로 다시 기록하지 않습니다.
        for event in detected_events:
            event_key = event["event_type"] + "|" + event["target"]

            if event_key not in active_event_keys:
                event_number = len(event_log) + 1
                event["event_id"] = f"EVENT-{event_number:03d}"
                event_log.append(event)
                active_event_keys.append(event_key)

                alarm = create_alarm_from_event(event)
                alarm_log.append(alarm)

    analysis = {
        "event_log": event_log,
        "alarm_log": alarm_log,
        "active_event_keys": active_event_keys,
    }
    return analysis


# Alarm Log에서 전체, WARNING과 CRITICAL 개수를 계산합니다.
def create_alarm_summary(alarm_log):
    summary = {
        "total_alarms": 0,
        "warning_alarms": 0,
        "critical_alarms": 0,
    }

    for alarm in alarm_log:
        summary["total_alarms"] = summary["total_alarms"] + 1
        if alarm["severity"] == "WARNING":
            summary["warning_alarms"] = summary["warning_alarms"] + 1
        else:
            summary["critical_alarms"] = summary["critical_alarms"] + 1

    return summary


# 탐지된 Event를 Tick 순서대로 출력합니다.
def print_event_log(event_log):
    print("=" * 68)
    print("EVENT LOG - LEARNING SIMULATION")
    print("=" * 68)

    if not event_log:
        print("탐지된 Event가 없습니다.")
        return

    for event in event_log:
        print(f"\n{event['event_id']}")
        print(f"Tick        : T{event['tick']}")
        print(f"Type        : {event['event_type']}")
        print(f"Target Type : {event['target_type']}")
        print(f"Target      : {event['target']}")
        print(f"Value       : {event['value']}")
        print(f"Threshold   : {event['threshold']}")
        print(f"Description : {event['description']}")


# Event에서 만들어진 Alarm을 Tick 순서대로 출력합니다.
def print_alarm_log(alarm_log):
    print("\n" + "=" * 68)
    print("ALARM LOG - LEARNING SIMULATION")
    print("실제 KT 또는 상용 NMS의 Alarm/Severity 체계가 아닙니다.")
    print("=" * 68)

    if not alarm_log:
        print("생성된 Alarm이 없습니다.")
        return

    for alarm in alarm_log:
        print(f"\n{alarm['alarm_id']}")
        print(f"Event       : {alarm['event_id']}")
        print(f"Tick        : T{alarm['tick']}")
        print(f"Type        : {alarm['alarm_type']}")
        print(f"Severity    : {alarm['severity']}")
        print(f"Target      : {alarm['target']}")
        print(f"Status      : {alarm['status']}")


# 선택한 Time-series를 만들고 자동 Event/Alarm 분석까지 실행합니다.
def run_event_alarm_scenario(scenario_type, target):
    if scenario_type == "CONGESTION":
        snapshots = run_congestion_time_series(target[0], target[1])
    elif scenario_type == "LINK_FAILURE":
        snapshots = run_link_failure_time_series(target[0], target[1])
    elif scenario_type == "DEVICE_OVERLOAD":
        snapshots = run_device_overload_time_series(target)
    else:
        raise ValueError(f"지원하지 않는 시나리오입니다: {scenario_type}")

    analysis = analyze_time_series_events(snapshots)
    analysis["scenario"] = scenario_type
    analysis["snapshots"] = snapshots
    analysis["summary"] = create_alarm_summary(analysis["alarm_log"])
    return analysis


# 이 파일을 직접 실행하면 선택한 Time-series에서 Event와 Alarm을 출력합니다.
if __name__ == "__main__":
    arguments = sys.argv[1:]

    try:
        if not arguments:
            generated_analysis = run_event_alarm_scenario(
                "CONGESTION",
                ("AGG-01", "EDGE-01"),
            )
        elif len(arguments) == 3 and arguments[0].upper() == "CONGESTION":
            generated_analysis = run_event_alarm_scenario(
                "CONGESTION",
                (arguments[1], arguments[2]),
            )
        elif len(arguments) == 3 and arguments[0].upper() == "LINK_FAILURE":
            generated_analysis = run_event_alarm_scenario(
                "LINK_FAILURE",
                (arguments[1], arguments[2]),
            )
        elif len(arguments) == 2 and arguments[0].upper() == "DEVICE_OVERLOAD":
            generated_analysis = run_event_alarm_scenario(
                "DEVICE_OVERLOAD",
                arguments[1],
            )
        else:
            raise ValueError(
                "사용법: python src/event_alarm_manager.py "
                "[CONGESTION 장비1 장비2 | LINK_FAILURE 장비1 장비2 | "
                "DEVICE_OVERLOAD 장비]"
            )

        print(f"Scenario: {generated_analysis['scenario']}\n")
        print_event_log(generated_analysis["event_log"])
        print_alarm_log(generated_analysis["alarm_log"])

        summary = generated_analysis["summary"]
        print("\n[Alarm Summary]")
        print(f"Total    : {summary['total_alarms']}")
        print(f"WARNING  : {summary['warning_alarms']}")
        print(f"CRITICAL : {summary['critical_alarms']}")
    except ValueError as error:
        print(f"Event/Alarm 분석을 실행할 수 없습니다: {error}")
