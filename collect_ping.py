"""Windows ping 명령으로 네트워크 상태를 한 번 측정합니다."""

# 날짜와 시간을 얻기 위해 datetime을 불러옵니다.
from datetime import datetime
# 측정 결과를 JSON 문자열로 바꾸기 위해 json을 불러옵니다.
import json
# 운영체제와 관계없이 파일 경로를 다루기 위해 Path를 불러옵니다.
from pathlib import Path
# ping 명령을 실행하기 위해 subprocess를 불러옵니다.
import subprocess
# 명령줄에서 target을 선택적으로 받기 위해 sys를 불러옵니다.
import sys
# 다음 측정 전까지 기다리기 위해 time을 불러옵니다.
import time
# ping 결과 문자열에서 숫자를 찾기 위해 re를 불러옵니다.
import re


# 현재 Python 파일을 기준으로 저장할 JSONL 파일의 위치를 정합니다.
DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "network_metrics.jsonl"
# 자동 측정 사이의 기본 대기 시간을 5초로 정합니다.
DEFAULT_INTERVAL_SECONDS = 5
# 프로그램을 한 번 실행했을 때의 기본 측정 횟수를 12회로 정합니다.
DEFAULT_MEASUREMENT_COUNT = 12


# Windows ping 결과에서 평균 지연시간과 패킷 손실률을 꺼내는 함수입니다.
def parse_ping_result(ping_output):
    # 한국어의 "평균 = 10ms"와 영어의 "Average = 10ms"를 모두 찾습니다.
    latency_match = re.search(r"(?:평균|Average)\s*=\s*(\d+)ms", ping_output, re.IGNORECASE)
    # 한국어의 "(0% 손실)"과 영어의 "(0% loss)"를 모두 찾습니다.
    loss_match = re.search(r"\((\d+)%\s*(?:손실|loss)\)", ping_output, re.IGNORECASE)

    # 평균 지연시간을 찾았다면 숫자를 정수로 바꾸고, 없다면 None을 사용합니다.
    average_latency = int(latency_match.group(1)) if latency_match else None
    # 패킷 손실률을 찾았다면 숫자를 정수로 바꾸고, 없다면 None을 사용합니다.
    packet_loss = int(loss_match.group(1)) if loss_match else None

    # 추출한 두 값을 이 함수를 호출한 곳으로 돌려줍니다.
    return average_latency, packet_loss


# 지정한 target으로 ping 측정을 한 번 실행하는 함수입니다.
def collect_ping(target):
    # Windows의 ping 명령을 실행하며, -n 4는 패킷을 4번 보내라는 뜻입니다.
    result = subprocess.run(
        # 실행할 명령과 옵션을 목록으로 전달합니다.
        ["ping", "-n", "4", target],
        # ping이 출력한 내용을 Python에서 사용할 수 있도록 저장합니다.
        capture_output=True,
        # 출력 결과를 bytes가 아닌 문자열로 받습니다.
        text=True,
        # 일부 문자를 해석하지 못해도 프로그램이 중단되지 않도록 합니다.
        errors="replace",
        # ping이 너무 오래 응답하지 않으면 30초 뒤에 측정을 중단합니다.
        timeout=30,
        # ping 실패도 직접 처리하기 위해 자동 예외 발생 기능은 사용하지 않습니다.
        check=False,
    )

    # ping 명령의 요약 결과에서 필요한 두 값을 추출합니다.
    average_latency, packet_loss = parse_ping_result(result.stdout)
    # 측정이 끝난 현재 시간을 초 단위 문자열로 만듭니다.
    measured_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 측정 시간, 대상, 평균 지연시간, 패킷 손실률을 돌려줍니다.
    return measured_at, target, average_latency, packet_loss


# 한 번의 측정 결과를 JSONL 파일에 한 줄로 추가하는 함수입니다.
def save_result(timestamp, target, latency_ms, packet_loss_percent):
    # 조건에서 정한 필드 이름으로 하나의 딕셔너리를 만듭니다.
    metric = {
        # 사람이 읽을 수 있는 측정 날짜와 시간을 저장합니다.
        "timestamp": timestamp,
        # ping을 보낸 주소를 저장합니다.
        "target": target,
        # 평균 지연시간을 밀리초 단위로 저장합니다.
        "latency_ms": latency_ms,
        # 패킷 손실률을 퍼센트 단위로 저장합니다.
        "packet_loss_percent": packet_loss_percent,
    }

    # data 폴더가 없을 경우를 대비해 폴더를 만듭니다.
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

    # "a" 모드는 기존 내용을 지우지 않고 파일 끝에 내용을 추가합니다.
    with DATA_FILE.open("a", encoding="utf-8") as file:
        # 딕셔너리를 JSON 문자열로 바꾸고 줄바꿈을 붙여 한 줄을 저장합니다.
        file.write(json.dumps(metric, ensure_ascii=False) + "\n")

    # 호출한 곳에서 저장 위치를 출력할 수 있도록 파일 경로를 돌려줍니다.
    return DATA_FILE


# 측정 결과를 터미널에서 읽기 좋은 모양으로 출력하는 함수입니다.
def print_result(measured_at, target, average_latency, packet_loss):
    # 값을 찾지 못한 경우에는 숫자 대신 "측정 불가"라고 표시합니다.
    latency_text = f"{average_latency} ms" if average_latency is not None else "측정 불가"
    # 값을 찾지 못한 경우에는 숫자 대신 "측정 불가"라고 표시합니다.
    loss_text = f"{packet_loss}%" if packet_loss is not None else "측정 불가"

    # 결과의 시작을 구분하는 선을 출력합니다.
    print("=" * 40)
    # 프로그램 이름을 출력합니다.
    print("NetOps Inspector - Ping 측정 결과")
    # 결과의 제목과 내용을 구분하는 선을 출력합니다.
    print("-" * 40)
    # 측정 시간을 출력합니다.
    print(f"측정 시간       : {measured_at}")
    # ping을 보낸 주소를 출력합니다.
    print(f"Target          : {target}")
    # 평균 지연시간을 출력합니다.
    print(f"평균 Latency    : {latency_text}")
    # 패킷 손실률을 출력합니다.
    print(f"Packet Loss     : {loss_text}")
    # 결과의 끝을 구분하는 선을 출력합니다.
    print("=" * 40)


# 이 파일을 직접 실행했을 때만 아래 코드를 실행합니다.
if __name__ == "__main__":
    # 명령줄에 주소가 있으면 사용하고, 없으면 기본 주소 8.8.8.8을 사용합니다.
    target = sys.argv[1] if len(sys.argv) > 1 else "8.8.8.8"
    # 이번 실행에서 사용할 측정 간격을 기본값으로 정합니다.
    interval_seconds = DEFAULT_INTERVAL_SECONDS
    # 이번 실행에서 사용할 측정 횟수를 기본값으로 정합니다.
    measurement_count = DEFAULT_MEASUREMENT_COUNT

    # 자동 측정을 시작한다는 안내를 출력합니다.
    print("NetOps Inspector 자동 측정을 시작합니다.")
    # 사용자가 측정 간격을 확인할 수 있도록 출력합니다.
    print(f"측정 간격: {interval_seconds}초")
    # 사용자가 전체 측정 횟수를 확인할 수 있도록 출력합니다.
    print(f"측정 횟수: {measurement_count}회")
    # 사용자가 중간에 종료하는 방법을 알 수 있도록 출력합니다.
    print("중간에 종료하려면 Ctrl+C를 누르세요.\n")

    # 자동 측정 도중 발생할 수 있는 상황을 처리합니다.
    try:
        # 1부터 전체 측정 횟수까지 차례로 반복합니다.
        for current_number in range(1, measurement_count + 1):
            # 현재 몇 번째 측정인지 전체 횟수와 함께 출력합니다.
            print(f"[{current_number}/{measurement_count}] 측정 중...")
            # 선택한 target의 네트워크 상태를 한 번 측정합니다.
            measured_at, target, average_latency, packet_loss = collect_ping(target)
            # 측정 결과를 JSONL 파일의 새 줄에 추가하고 저장 위치를 받습니다.
            saved_file = save_result(measured_at, target, average_latency, packet_loss)
            # 측정한 결과를 터미널에 출력합니다.
            print_result(measured_at, target, average_latency, packet_loss)
            # 사용자가 저장 여부를 확인할 수 있도록 저장된 파일 위치를 출력합니다.
            print(f"저장 파일       : {saved_file}\n")

            # 마지막 측정이 아니라면 다음 측정 전까지 정해진 시간만큼 기다립니다.
            if current_number < measurement_count:
                # time.sleep에 초를 전달하여 여기서는 5초 동안 쉽니다.
                time.sleep(interval_seconds)

        # 정해진 횟수를 모두 측정했다는 메시지를 출력합니다.
        print("자동 측정을 완료했습니다.")
    # 사용자가 Ctrl+C를 누르면 아래 코드를 실행합니다.
    except KeyboardInterrupt:
        # 긴 오류 메시지 대신 안전하게 종료되었다는 안내를 출력합니다.
        print("\n사용자 요청으로 자동 측정을 안전하게 종료했습니다.")
    # 30초 안에 ping이 끝나지 않으면 아래 코드를 실행합니다.
    except subprocess.TimeoutExpired:
        # 사용자가 원인을 알 수 있도록 오류 메시지를 출력합니다.
        print("Ping 측정 시간이 30초를 초과했습니다.")
    # ping 명령 자체를 찾지 못한 경우 아래 코드를 실행합니다.
    except FileNotFoundError:
        # Windows의 ping 명령을 사용할 수 없다는 메시지를 출력합니다.
        print("Windows ping 명령을 찾을 수 없습니다.")
