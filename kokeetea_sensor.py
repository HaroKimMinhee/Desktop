import time
import threading
import json
import drivers
import adafruit_dht
import board
import busio
import schedule
import mysql.connector
from mysql.connector import Error
from gpiozero.pins.pigpio import PiGPIOFactory
from gpiozero import Servo
from adafruit_pn532.i2c import PN532_I2C
import RPi.GPIO as GPIO
from time import sleep

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
    except Error as e:
        print(f"❌ 데이터베이스 연결 실패: {e}")
        return None

# ----------------------------
# 🔹 JSON 데이터 로드 (허용된 NFC 카드 목록)
# ----------------------------
CARD_DATABASE = "authorized_cards.json"

def load_authorized_cards():
    try:
        with open(CARD_DATABASE, "r") as file:
            data = json.load(file)
            return set(data.get("authorized_uids", []))
    except (FileNotFoundError, json.JSONDecodeError):
        print("❌ 카드 데이터 로드 오류")
        return set()

# ----------------------------
# 🔹 Piezo 설정
# ----------------------------
#Disable warnings (optional)
GPIO.setwarnings(False)
#Select GPIO mode
GPIO.setmode(GPIO.BCM)
#Set buzzer - pin 17 as output
buzzer=17
GPIO.setup(buzzer,GPIO.OUT)

# ----------------------------
# 🔹 NFC 데이터 저장
# ----------------------------
def insert_nfc_log(uid):
    conn = connect_db()
    if conn:
        try:
            cursor = conn.cursor()
            query = "INSERT INTO iot_data (uuid, check_time) VALUES (%s, NOW())"
            cursor.execute(query, (uid,))
            conn.commit()
        except Error as e:
            print(f"❌ NFC 데이터 저장 오류: {e}")
        finally:
            cursor.close()
            conn.close()

# ----------------------------
# 🔹 온습도 데이터 저장
# ----------------------------
def insert_temp_humi_log(temp, humi):
    conn = connect_db()
    if conn:
        try:
            cursor = conn.cursor()
            query = "INSERT INTO iot_data (temp, humi, t_h_check_time) VALUES (%s, %s, NOW())"
            cursor.execute(query, (temp, humi))
            conn.commit()
        except Error as e:
            print(f"❌ 온습도 데이터 저장 오류: {e}")
        finally:
            cursor.close()
            conn.close()

# ----------------------------
# 🔹 하드웨어 설정 (LCD, 서보모터, NFC 리더기, DHT11)
# ----------------------------
# 🌡️ 온습도 센서 (GPIO 4 사용)
dht_device = adafruit_dht.DHT11(board.D4)

# 🏟️ LCD 디스플레이 초기화
display = drivers.Lcd(0x27)

# ⚙️ 서보모터 설정 (GPIO 18 사용)
factory = PiGPIOFactory()
servo = Servo(18, pin_factory=factory)

# 🏷️ NFC 리더기 설정 (I2C)
i2c = busio.I2C(board.SCL, board.SDA)
PN532_I2C_ADDRESS = 0x24
pn532 = PN532_I2C(i2c, address=PN532_I2C_ADDRESS, debug=False)
pn532.SAM_configuration()
print("✅ NFC 리더기 준비 완료")

door_open = False  # 문 상태 변수

# ----------------------------
# 🔹 문 열기 및 닫기 기능
# ----------------------------
servo.value = 1
def open_door():
    global door_open
    door_open = True
    print("🚪 문 열림")
    display.lcd_clear()
    display.lcd_display_string("Opening Door...", 1)
    servo.value = -1
    time.sleep(2)
    threading.Timer(5, close_door).start()

def close_door():
    global door_open
    print("🚪 문 닫힘")
    display.lcd_clear()
    display.lcd_display_string("Closing Door...", 1)
    servo.value = 1
    time.sleep(2)
    door_open = False

# ----------------------------
# 🔹 NFC 카드 인식
# ----------------------------
def read_nfc():
    authorized_cards = load_authorized_cards()
    while True:
        uid = pn532.read_passive_target(timeout=0.5)
        if uid:
            uid_hex = uid.hex().upper()

            # 🔊 비프음 울리기 (0.5초)
            GPIO.output(buzzer, GPIO.HIGH)
            time.sleep(0.1)  # 0.1초 동안 유지
            GPIO.output(buzzer, GPIO.LOW)  # 비프음 끄기

            print(f"🔍 감지된 카드 UID: {uid_hex}")
            insert_nfc_log(uid_hex)

            if uid_hex in authorized_cards:
                print("✅ 인증된 카드. 문 열기!")
                if not door_open:
                    open_door()
            else:
                print("❌ 미등록 카드")
                GPIO.output(buzzer, GPIO.HIGH)
                time.sleep(0.1)  # 0.1초 동안 유지
                GPIO.output(buzzer, GPIO.LOW)  # 비프음 끄기
                display.lcd_clear()
                display.lcd_display_string("Access Denied!", 1)
                time.sleep(2)

# ----------------------------
# 🔹 온습도 데이터 업데이트
# ----------------------------
def update_temperature_humidity():
    while True:
        try:
            temperature = dht_device.temperature
            humidity = dht_device.humidity
            if temperature is not None and humidity is not None:
                display.lcd_clear()
                display.lcd_display_string(f"Temp: {temperature:.1f}C", 1)
                display.lcd_display_string(f"Humidity: {humidity:.1f}%", 2)
                insert_temp_humi_log(temperature, humidity)
        except RuntimeError as e:
            print(f"DHT 센서 오류: {e}")
        time.sleep(10)

# ----------------------------
# 🔹 UUID별 첫/마지막 인식 시간 조회
# ----------------------------
def check_uuid_logs():
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
                GROUP BY uuid, DATE(check_time)
                ORDER BY date DESC, uuid;
            """
            cursor.execute(query)
            results = cursor.fetchall()
            for row in results:
                print(f"🆔 UUID: {row[0]} | 📅 날짜: {row[1]} | ⏳ 첫 인식: {row[2]} | ⏳ 마지막 인식: {row[3]}")
        except Error as e:
            print(f"❌ UUID 로그 조회 오류: {e}")
        finally:
            cursor.close()
            conn.close()

schedule.every().day.at("00:00").do(check_uuid_logs)

# ----------------------------
# 🔹 멀티스레드 실행
# ----------------------------
nfc_thread = threading.Thread(target=read_nfc, daemon=True)
temp_thread = threading.Thread(target=update_temperature_humidity, daemon=True)
nfc_thread.start()
temp_thread.start()

while True:
    schedule.run_pending()
    time.sleep(1)

