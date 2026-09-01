"""가상 Network Device 정보를 조회용 Inventory list로 정리합니다."""

# 명령줄에서 간단한 Inventory 시나리오를 받기 위해 sys를 불러옵니다.
import sys

# 기존 Health, Config 초기화와 판정 및 Config mismatch 기능을 재사용합니다.
from device_health_checker import (
    check_config_compliance,
    check_device_health,
    initialize_device_operations_data,
    inject_config_mismatch,
    parse_config_value,
)
# 기존 topology와 Device Overload 기능을 재사용합니다.
from network_simulator import create_network, inject_device_overload


# Health와 Config 상태를 Inventory 조회용 Operational Status로 요약합니다.
def determine_operational_status(health_status, config_status):
    if health_status == "NORMAL" and config_status == "PASS":
        return "UP"
    return "ATTENTION"


# Device 하나의 기존 관리 정보를 읽어 간단한 Inventory Record를 만듭니다.
def create_inventory_record(network, device):
    if device not in network:
        raise ValueError(f"가상 장비를 찾을 수 없습니다: {device}")

    node = network.nodes[device]
    config = node.get("config")
    if config is None:
        raise ValueError(f"가상 Config가 초기화되지 않았습니다: {device}")

    # Health와 Config 판정을 Inventory에서 다시 구현하지 않고 기존 함수를 호출합니다.
    health = check_device_health(network, device)
    compliance = check_config_compliance(network, device)
    operational_status = determine_operational_status(
        health["status"],
        compliance["status"],
    )

    record = {
        # NetworkX Node 이름 자체를 별도 변환 없이 Device ID로 사용합니다.
        "device_id": device,
        "hostname": config.get("hostname", device),
        "role": node.get("role", "UNKNOWN"),
        # 10.0.0.x 값은 실제 통신망 주소가 아닌 가상 Management IP입니다.
        "management_ip": config.get("management_ip", "NOT_SET"),
        "operational_status": operational_status,
        "health_status": health["status"],
        "config_status": compliance["status"],
        "health_reasons": health["reasons"],
        "config_failed_keys": compliance["failed_keys"],
    }
    return record


# NetworkX의 모든 Device Node를 조회용 Inventory Record list로 바꿉니다.
def build_inventory(network):
    inventory = []

    for device in network.nodes:
        record = create_inventory_record(network, device)
        inventory.append(record)

    return inventory


# Device ID가 같은 Inventory Record 하나를 단순 for 반복으로 찾습니다.
def find_device(inventory, device_id):
    for record in inventory:
        if record["device_id"] == device_id:
            return record

    raise ValueError(f"Inventory에서 장비를 찾을 수 없습니다: {device_id}")


# 입력한 Role과 같은 모든 Device Record를 list로 반환합니다.
def find_devices_by_role(inventory, role):
    matching_devices = []
    requested_role = role.upper()

    for record in inventory:
        if record["role"].upper() == requested_role:
            matching_devices.append(record)

    return matching_devices


# Health 또는 Config 문제로 추가 확인이 필요한 Device만 반환합니다.
def find_attention_devices(inventory):
    attention_devices = []

    for record in inventory:
        if record["operational_status"] == "ATTENTION":
            attention_devices.append(record)

    return attention_devices


# Inventory Record list에서 Role과 상태별 Device 개수를 계산합니다.
def create_inventory_summary(inventory):
    summary = {
        "total_devices": 0,
        "core_devices": 0,
        "agg_devices": 0,
        "edge_devices": 0,
        "up_devices": 0,
        "attention_devices": 0,
        "health_normal": 0,
        "health_warning": 0,
        "health_critical": 0,
        "config_pass": 0,
        "config_fail": 0,
    }

    for record in inventory:
        summary["total_devices"] = summary["total_devices"] + 1

        role = record["role"]
        if role == "CORE":
            summary["core_devices"] = summary["core_devices"] + 1
        elif role == "AGG":
            summary["agg_devices"] = summary["agg_devices"] + 1
        elif role == "EDGE":
            summary["edge_devices"] = summary["edge_devices"] + 1

        if record["operational_status"] == "UP":
            summary["up_devices"] = summary["up_devices"] + 1
        else:
            summary["attention_devices"] = summary["attention_devices"] + 1

        if record["health_status"] == "NORMAL":
            summary["health_normal"] = summary["health_normal"] + 1
        elif record["health_status"] == "WARNING":
            summary["health_warning"] = summary["health_warning"] + 1
        else:
            summary["health_critical"] = summary["health_critical"] + 1

        if record["config_status"] == "PASS":
            summary["config_pass"] = summary["config_pass"] + 1
        else:
            summary["config_fail"] = summary["config_fail"] + 1

    return summary


# 기존 Health/Config 시나리오를 적용하고 현재 Inventory View를 만듭니다.
def run_inventory_scenario(scenario_type="NORMAL", target=None):
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
        raise ValueError(f"지원하지 않는 Inventory 시나리오입니다: {scenario_type}")

    inventory = build_inventory(network)
    summary = create_inventory_summary(inventory)
    return {
        "scenario": scenario_type,
        "scenario_details": scenario_details,
        "inventory": inventory,
        "summary": summary,
    }


# Device별 관리 정보와 Inventory Summary를 기본 print로 출력합니다.
def print_inventory_report(result):
    print("=" * 72)
    print("NETWORK DEVICE INVENTORY - LEARNING SIMULATION")
    print("실제 CMDB, 자산관리 또는 NMS Inventory가 아닙니다.")
    print("=" * 72)
    print(f"Scenario: {result['scenario']}")

    for record in result["inventory"]:
        print("\n" + "-" * 72)
        print(f"Device ID     : {record['device_id']}")
        print(f"Hostname      : {record['hostname']}")
        print(f"Role          : {record['role']}")
        print(f"Management IP : {record['management_ip']}")
        print(f"Operational   : {record['operational_status']}")
        print(f"Health        : {record['health_status']}")
        print(f"Config        : {record['config_status']}")
        if record["health_reasons"]:
            print(f"Health Issues : {', '.join(record['health_reasons'])}")
        if record["config_failed_keys"]:
            print(f"Config Issues : {', '.join(record['config_failed_keys'])}")

    summary = result["summary"]
    print("\n" + "=" * 72)
    print("Inventory Summary")
    print(f"Total Devices   : {summary['total_devices']}")
    print(f"CORE            : {summary['core_devices']}")
    print(f"AGG             : {summary['agg_devices']}")
    print(f"EDGE            : {summary['edge_devices']}")
    print(f"UP              : {summary['up_devices']}")
    print(f"ATTENTION       : {summary['attention_devices']}")
    print(f"Health NORMAL   : {summary['health_normal']}")
    print(f"Health WARNING  : {summary['health_warning']}")
    print(f"Health CRITICAL : {summary['health_critical']}")
    print(f"Config PASS     : {summary['config_pass']}")
    print(f"Config FAIL     : {summary['config_fail']}")
    print("=" * 72)


# 이 파일을 직접 실행하면 정상 또는 장애 상태의 Inventory를 출력합니다.
if __name__ == "__main__":
    arguments = sys.argv[1:]

    try:
        if not arguments:
            generated_result = run_inventory_scenario()
        elif len(arguments) == 2 and arguments[0].upper() == "DEVICE_OVERLOAD":
            generated_result = run_inventory_scenario(
                "DEVICE_OVERLOAD",
                arguments[1],
            )
        elif len(arguments) == 4 and arguments[0].upper() == "CONFIG_MISMATCH":
            parsed_value = parse_config_value(arguments[3])
            generated_result = run_inventory_scenario(
                "CONFIG_MISMATCH",
                (arguments[1], arguments[2], parsed_value),
            )
        else:
            raise ValueError(
                "사용법: python src/network_inventory.py "
                "[DEVICE_OVERLOAD 장비 | CONFIG_MISMATCH 장비 key value]"
            )

        print_inventory_report(generated_result)
    except ValueError as error:
        print(f"Network Inventory를 만들 수 없습니다: {error}")
