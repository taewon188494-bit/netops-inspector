"""가상 Device Health와 Config Compliance를 학습용 기준으로 점검합니다."""

# 명령줄에서 간단한 시나리오와 값을 받기 위해 sys를 불러옵니다.
import sys

# 기존 topology와 CPU overload 주입 함수를 그대로 재사용합니다.
from network_simulator import create_network, inject_device_overload


# 아래 값은 실제 KT나 Vendor 장비 기준이 아닌 학습용 Health Rule입니다.
DEVICE_HEALTH_RULES = {
    "cpu_warning_percent": 80,
    "cpu_critical_percent": 90,
    "memory_warning_percent": 80,
    "memory_critical_percent": 90,
    "temperature_warning_c": 70,
    "temperature_critical_c": 80,
}


# 모든 장비에 공통으로 기대하는 학습용 Config입니다.
CONFIG_STANDARD = {
    "ntp_enabled": True,
    "logging_enabled": True,
    "backup_enabled": True,
}


# 장비마다 달라야 하는 hostname과 management IP 기준입니다.
DEVICE_EXPECTED_CONFIGS = {
    "CORE-01": {"hostname": "CORE-01", "management_ip": "10.0.0.1"},
    "AGG-01": {"hostname": "AGG-01", "management_ip": "10.0.0.2"},
    "AGG-02": {"hostname": "AGG-02", "management_ip": "10.0.0.3"},
    "EDGE-01": {"hostname": "EDGE-01", "management_ip": "10.0.0.11"},
    "EDGE-02": {"hostname": "EDGE-02", "management_ip": "10.0.0.12"},
    "EDGE-03": {"hostname": "EDGE-03", "management_ip": "10.0.0.13"},
    "EDGE-04": {"hostname": "EDGE-04", "management_ip": "10.0.0.14"},
}


# 장비별 정상 Health Metric은 실제 장비 측정값이 아닌 가상 기본값입니다.
DEVICE_DEFAULT_STATES = {
    "CORE-01": {"cpu_usage": 25, "memory_usage_percent": 40, "temperature_c": 42},
    "AGG-01": {"cpu_usage": 30, "memory_usage_percent": 45, "temperature_c": 44},
    "AGG-02": {"cpu_usage": 28, "memory_usage_percent": 42, "temperature_c": 43},
    "EDGE-01": {"cpu_usage": 15, "memory_usage_percent": 30, "temperature_c": 38},
    "EDGE-02": {"cpu_usage": 18, "memory_usage_percent": 32, "temperature_c": 39},
    "EDGE-03": {"cpu_usage": 20, "memory_usage_percent": 35, "temperature_c": 40},
    "EDGE-04": {"cpu_usage": 22, "memory_usage_percent": 38, "temperature_c": 41},
}


# Device Health와 가상 Config를 NetworkX Node attribute에 저장합니다.
def initialize_device_operations_data(network):
    for device in network.nodes:
        if device not in DEVICE_DEFAULT_STATES:
            raise ValueError(f"기본 Health 값이 없는 가상 장비입니다: {device}")
        if device not in DEVICE_EXPECTED_CONFIGS:
            raise ValueError(f"기대 Config가 없는 가상 장비입니다: {device}")

        default_state = DEVICE_DEFAULT_STATES[device]
        network.nodes[device]["cpu_usage"] = default_state["cpu_usage"]
        network.nodes[device]["memory_usage_percent"] = default_state[
            "memory_usage_percent"
        ]
        network.nodes[device]["temperature_c"] = default_state["temperature_c"]
        network.nodes[device]["interface_status"] = "UP"
        # CORE-01, AGG-01 같은 이름에서 첫 부분을 학습용 role로 사용합니다.
        network.nodes[device]["role"] = device.split("-")[0]

        device_expected = DEVICE_EXPECTED_CONFIGS[device]
        config = {
            "hostname": device_expected["hostname"],
            "management_ip": device_expected["management_ip"],
            "ntp_enabled": CONFIG_STANDARD["ntp_enabled"],
            "logging_enabled": CONFIG_STANDARD["logging_enabled"],
            "backup_enabled": CONFIG_STANDARD["backup_enabled"],
        }
        # Config는 실제 CLI 문자열이 아니라 Node 안에 저장한 Python dict입니다.
        network.nodes[device]["config"] = config


# 현재 Device Metric을 각각 확인하고 모든 이상 이유를 list에 저장합니다.
def check_device_health(network, device):
    if device not in network:
        raise ValueError(f"가상 장비를 찾을 수 없습니다: {device}")

    node = network.nodes[device]
    metrics = {
        # 기존 DEVICE_OVERLOAD와 호환되도록 cpu_usage key를 그대로 읽습니다.
        "cpu_usage_percent": node.get("cpu_usage", 0),
        "memory_usage_percent": node.get("memory_usage_percent", 0),
        "temperature_c": node.get("temperature_c", 0),
        "interface_status": node.get("interface_status", "UP"),
    }
    reasons = []

    # if/elif는 한 Metric 안의 CRITICAL과 WARNING 중 하나만 선택합니다.
    # 다른 Metric도 계속 확인하므로 여러 문제가 reasons에 함께 들어갈 수 있습니다.
    if metrics["cpu_usage_percent"] >= DEVICE_HEALTH_RULES["cpu_critical_percent"]:
        reasons.append("CPU_CRITICAL")
    elif metrics["cpu_usage_percent"] >= DEVICE_HEALTH_RULES["cpu_warning_percent"]:
        reasons.append("CPU_WARNING")

    if metrics["memory_usage_percent"] >= DEVICE_HEALTH_RULES["memory_critical_percent"]:
        reasons.append("MEMORY_CRITICAL")
    elif metrics["memory_usage_percent"] >= DEVICE_HEALTH_RULES["memory_warning_percent"]:
        reasons.append("MEMORY_WARNING")

    if metrics["temperature_c"] >= DEVICE_HEALTH_RULES["temperature_critical_c"]:
        reasons.append("TEMPERATURE_CRITICAL")
    elif metrics["temperature_c"] >= DEVICE_HEALTH_RULES["temperature_warning_c"]:
        reasons.append("TEMPERATURE_WARNING")

    if metrics["interface_status"] == "DOWN":
        reasons.append("INTERFACE_DOWN")

    # 모든 이유를 모은 뒤 CRITICAL 우선, WARNING 다음 순서로 최종 상태를 정합니다.
    has_critical_reason = False
    has_warning_reason = False
    for reason in reasons:
        if "CRITICAL" in reason or reason == "INTERFACE_DOWN":
            has_critical_reason = True
        elif "WARNING" in reason:
            has_warning_reason = True

    if has_critical_reason:
        status = "CRITICAL"
    elif has_warning_reason:
        status = "WARNING"
    else:
        status = "NORMAL"

    return {
        "device": device,
        "metrics": metrics,
        "status": status,
        "reasons": reasons,
    }


# 장비별 Expected Config와 현재 Actual Config를 key마다 비교합니다.
def check_config_compliance(network, device):
    if device not in network:
        raise ValueError(f"가상 장비를 찾을 수 없습니다: {device}")

    actual_config = network.nodes[device].get("config")
    if actual_config is None:
        raise ValueError(f"가상 Config가 초기화되지 않았습니다: {device}")

    device_expected = DEVICE_EXPECTED_CONFIGS[device]
    expected_config = {
        "hostname": device_expected["hostname"],
        "management_ip": device_expected["management_ip"],
        "ntp_enabled": CONFIG_STANDARD["ntp_enabled"],
        "logging_enabled": CONFIG_STANDARD["logging_enabled"],
        "backup_enabled": CONFIG_STANDARD["backup_enabled"],
    }

    checks = []
    failed_keys = []
    for config_key in expected_config:
        expected = expected_config[config_key]
        actual = actual_config.get(config_key)

        if expected == actual:
            result = "PASS"
        else:
            result = "FAIL"
            failed_keys.append(config_key)

        check = {
            "key": config_key,
            "expected": expected,
            "actual": actual,
            "result": result,
        }
        checks.append(check)

    if failed_keys:
        status = "FAIL"
    else:
        status = "PASS"

    return {
        "device": device,
        "status": status,
        "checks": checks,
        "failed_keys": failed_keys,
    }


# 실제 장비가 아닌 메모리 속 Virtual Config 값 하나를 변경합니다.
def inject_config_mismatch(network, device, config_key, new_value):
    if device not in network:
        raise ValueError(f"가상 장비를 찾을 수 없습니다: {device}")

    config = network.nodes[device].get("config")
    if config is None:
        raise ValueError(f"가상 Config가 초기화되지 않았습니다: {device}")
    if config_key not in config:
        raise ValueError(f"지원하지 않는 Config key입니다: {config_key}")

    config[config_key] = new_value


# Health와 Config Compliance 결과를 하나의 Device Operations Record로 묶습니다.
def analyze_device(network, device):
    health = check_device_health(network, device)
    config_compliance = check_config_compliance(network, device)

    record = {
        "device": device,
        "role": network.nodes[device].get("role", "UNKNOWN"),
        # 두 상태를 별도 key에 보관하여 하나의 상태로 섞지 않습니다.
        "health": health,
        "config_compliance": config_compliance,
    }
    return record


# NetworkX graph의 모든 Device를 단순 for 반복으로 분석합니다.
def analyze_all_devices(network):
    results = []

    for device in network.nodes:
        result = analyze_device(network, device)
        results.append(result)

    return results


# 전체 Device Record에서 Health와 Config 상태별 개수를 계산합니다.
def create_device_check_summary(results):
    summary = {
        "total_devices": 0,
        "health_normal": 0,
        "health_warning": 0,
        "health_critical": 0,
        "config_pass": 0,
        "config_fail": 0,
    }

    for result in results:
        summary["total_devices"] = summary["total_devices"] + 1

        health_status = result["health"]["status"]
        if health_status == "NORMAL":
            summary["health_normal"] = summary["health_normal"] + 1
        elif health_status == "WARNING":
            summary["health_warning"] = summary["health_warning"] + 1
        else:
            summary["health_critical"] = summary["health_critical"] + 1

        config_status = result["config_compliance"]["status"]
        if config_status == "PASS":
            summary["config_pass"] = summary["config_pass"] + 1
        else:
            summary["config_fail"] = summary["config_fail"] + 1

    return summary


# CLI의 true/false 문자열을 Python bool로 바꿉니다.
def parse_config_value(value_text):
    lower_value = value_text.lower()
    if lower_value == "true":
        return True
    if lower_value == "false":
        return False
    return value_text


# 선택한 Health 또는 Config 시나리오를 한 번 적용하고 전체 장비를 점검합니다.
def run_device_check_scenario(scenario_type="NORMAL", target=None):
    network = create_network()
    initialize_device_operations_data(network)
    scenario_details = None

    if scenario_type == "NORMAL":
        pass
    elif scenario_type == "DEVICE_OVERLOAD":
        inject_device_overload(network, target, print_details=False)
        scenario_details = {"device": target, "cpu_usage_percent": 95}
    elif scenario_type == "CONFIG_MISMATCH":
        device = target[0]
        config_key = target[1]
        new_value = target[2]
        inject_config_mismatch(network, device, config_key, new_value)
        scenario_details = {
            "device": device,
            "config_key": config_key,
            "new_value": new_value,
        }
    else:
        raise ValueError(f"지원하지 않는 시나리오입니다: {scenario_type}")

    results = analyze_all_devices(network)
    summary = create_device_check_summary(results)
    return {
        "scenario": scenario_type,
        "scenario_details": scenario_details,
        "results": results,
        "summary": summary,
    }


# 모든 Device의 Health와 Config 비교 Evidence를 출력합니다.
def print_device_check_report(scenario):
    print("=" * 72)
    print("DEVICE HEALTH / CONFIG CHECK - LEARNING SIMULATION")
    print("실제 장비 Telemetry 또는 실제 Vendor Config가 아닙니다.")
    print("=" * 72)
    print(f"Scenario: {scenario['scenario']}")

    for record in scenario["results"]:
        health = record["health"]
        metrics = health["metrics"]
        compliance = record["config_compliance"]

        print("\n" + "-" * 72)
        print(f"{record['device']} | Role: {record['role']}")
        print("[Health]")
        print(f"CPU         : {metrics['cpu_usage_percent']}%")
        print(f"Memory      : {metrics['memory_usage_percent']}%")
        print(f"Temperature : {metrics['temperature_c']} C")
        print(f"Interface   : {metrics['interface_status']}")
        print(f"Status      : {health['status']}")
        if health["reasons"]:
            print(f"Reasons     : {', '.join(health['reasons'])}")

        print("\n[Config Compliance]")
        for check in compliance["checks"]:
            print(check["key"])
            print(f"  Expected : {check['expected']}")
            print(f"  Actual   : {check['actual']}")
            print(f"  Result   : {check['result']}")
        print(f"Config Result : {compliance['status']}")

    summary = scenario["summary"]
    print("\n" + "=" * 72)
    print("Summary")
    print(f"Total Devices   : {summary['total_devices']}")
    print(f"Health NORMAL   : {summary['health_normal']}")
    print(f"Health WARNING  : {summary['health_warning']}")
    print(f"Health CRITICAL : {summary['health_critical']}")
    print(f"Config PASS     : {summary['config_pass']}")
    print(f"Config FAIL     : {summary['config_fail']}")
    print("=" * 72)


# 이 파일을 직접 실행하면 선택한 Device Check 시나리오를 출력합니다.
if __name__ == "__main__":
    arguments = sys.argv[1:]

    try:
        if not arguments:
            generated_scenario = run_device_check_scenario()
        elif len(arguments) == 2 and arguments[0].upper() == "DEVICE_OVERLOAD":
            generated_scenario = run_device_check_scenario(
                "DEVICE_OVERLOAD",
                arguments[1],
            )
        elif len(arguments) == 4 and arguments[0].upper() == "CONFIG_MISMATCH":
            parsed_value = parse_config_value(arguments[3])
            generated_scenario = run_device_check_scenario(
                "CONFIG_MISMATCH",
                (arguments[1], arguments[2], parsed_value),
            )
        else:
            raise ValueError(
                "사용법: python src/device_health_checker.py "
                "[DEVICE_OVERLOAD 장비 | CONFIG_MISMATCH 장비 key value]"
            )

        print_device_check_report(generated_scenario)
    except ValueError as error:
        print(f"Device 점검을 실행할 수 없습니다: {error}")
