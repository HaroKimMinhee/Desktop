import time
import json
import mysql.connector
import requests  # API 요청
from datetime import datetime

# ----------------------------
# 🔹 데이터베이스 설정
# ----------------------------
DB_HOST = "210.117.212.110"
DB_USER = "iot"
DB_PASSWORD = "password"
DB_NAME = "IoT"

# 데이터베이스 연결 함수
def connect_db():
    try:
        conn = mysql.connector.connect(
            host=DB_HOST, user=DB_USER, password=DB_PASSWORD, database=DB_NAME
        )
        if conn.is_connected():
            print("✅ MariaDB 연결 성공")
        return conn
    except mysql.connector.Error as e:
        print(f"❌ 데이터베이스 연결 실패: {e}")
        return None

# ----------------------------
# 🔹 백엔드 API로 출퇴근 시간 전송
# ----------------------------
def send_attendance_to_api(attendance_data):
    """
    API로 출퇴근 시간 데이터를 전송하는 함수.
    :param attendance_data: [{"card_uuid": "A123", "check_in_time": "...", "check_out_time": "..."}, ...]
    """
    api_url = "http://spring.mirae.network:8082/api/attendances"
    headers = {"Content-Type": "application/json"}  # 헤더 추가
    data = {"attendances": attendance_data}

    # JSON 변환 후 전송
    json_data = json.dumps(data, ensure_ascii=False)

    print(f"📡 요청 데이터: {json_data}")  # 전송 데이터 확인

    for attempt in range(3):  # 3회 재시도
        try:
            response = requests.post(api_url, data=json_data, headers=headers)  # 헤더 포함 요청

            print(f"📢 서버 응답 코드: {response.status_code}")  # 응답 코드 출력
            print(f"📢 서버 응답 본문: {response.text}")  # 응답 본문 출력

            if response.status_code == 200:
                print("✅ 출퇴근 시간 전송 성공!")
                return  # 성공하면 종료
            else:
                print(f"❌ 출퇴근 시간 전송 실패 (응답 코드: {response.status_code})")
                print(f"🔍 서버 응답: {response.text}")  # 응답 본문 출력
                time.sleep(2)  # 2초 대기 후 재시도

        except Exception as e:
            print(f"❌ API 요청 오류: {e}, 재시도 {attempt + 1}/3")
            time.sleep(2)

# ----------------------------
# 🔹 UUID별 첫/마지막 인식 시간 조회
# ----------------------------
def check_uuid_logs():
    """
    데이터베이스에서 UUID별 첫/마지막 체크 시간을 가져와 API로 전송하는 함수.
    """
    conn = connect_db()
    if conn:
        try:
            cursor = conn.cursor()
            query = """
                SELECT uuid, DATE(check_time) AS date,
                       MIN(check_time) AS first_check_time,
                       MAX(check_time) AS last_check_time
                FROM iot_data
                WHERE uuid IS NOT NULL
                AND DATE(check_time) = CURDATE() - INTERVAL 1 DAY  -- 어제 날짜 필터링
                GROUP BY uuid, DATE(check_time)
                ORDER BY date DESC, uuid;
            """
            cursor.execute(query)
            results = cursor.fetchall()

            if results:
                attendance_data = []

                for row in results:
                    uuid = row[0].encode('utf-8').decode('utf-8')  # UTF-8 변환
                    date = row[1]
                    check_in_time = row[2]  # datetime 객체
                    check_out_time = row[3]  # datetime 객체

                    # None 값 처리
                    check_in_time_str = check_in_time.strftime('%Y-%m-%d %H:%M:%S') if check_in_time else "NULL"
                    check_out_time_str = check_out_time.strftime('%Y-%m-%d %H:%M:%S') if check_out_time else "NULL"

                    print(f"🆔 UUID: {uuid} | 📅 날짜: {date} | ⏳ 출근: {check_in_time_str} | ⏳ 퇴근: {check_out_time_str}")

                    attendance_data.append({
                        "card_uuid": uuid,
                        "check_in_time": check_in_time_str,
                        "check_out_time": check_out_time_str
                    })

                # API로 출퇴근 시간 전송 (여러 개를 한 번에 보냄)
                if attendance_data:
                    send_attendance_to_api(attendance_data)
            else:
                print("🔍 전송할 데이터 없음")

        except mysql.connector.Error as e:
            print(f"❌ UUID 로그 조회 오류: {e}")
        finally:
            cursor.close()
            conn.close()

# ----------------------------
# 🔹 프로그램 실행 (한 번만 실행 후 종료)
# ----------------------------
check_uuid_logs()

