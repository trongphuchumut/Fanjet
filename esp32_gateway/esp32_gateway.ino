/*
 * ═══════════════════════════════════════════════════════════════════
 *  FanJet BMS – ESP32 PLC↔MQTT Gateway
 *  Kết nối: PLC (RS-485 Modbus RTU) ↔ ESP32 ↔ A7680C (4G LTE) ↔ MQTT
 * ═══════════════════════════════════════════════════════════════════
 *
 *  Libraries cần cài:
 *    - TinyGSM        (by Volodymyr Shymanskyy)
 *    - PubSubClient   (by Nick O'Leary)
 *    - ArduinoJson    (by Benoit Blanchon, v7+)
 *    - ModbusMaster   (by Doc Walker)
 *
 *  Board: ESP32 Dev Module
 * ═══════════════════════════════════════════════════════════════════
 */

// ── Chọn modem trước khi include TinyGSM ─────────────────────────
#define TINY_GSM_MODEM_A7680
#define TINY_GSM_RX_BUFFER 1024

#include <Arduino.h>
#include <HardwareSerial.h>
#include <Preferences.h>
#include <TinyGsmClient.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <ModbusMaster.h>

// ══════════════════════════════════════════════════════════════════
//  PINOUT & HARDWARE
// ══════════════════════════════════════════════════════════════════

// -- A7680C 4G Module (UART1) --
#define PIN_4G_TX       26    // ESP32 TX → A7680C RX
#define PIN_4G_RX       27    // ESP32 RX ← A7680C TX
#define PIN_4G_PWR      4     // Power key (LOW pulse 1.5s to toggle)
#define BAUD_4G         115200

// -- RS-485 / Modbus RTU (UART2) --
#define PIN_RS485_TX    17    // ESP32 TX → MAX485 DI
#define PIN_RS485_RX    16    // ESP32 RX ← MAX485 RO
#define PIN_RS485_DE    5     // MAX485 DE+RE (HIGH=transmit)
#define BAUD_RS485      9600

// -- Status LED --
#define PIN_LED         2     // Onboard LED

// ══════════════════════════════════════════════════════════════════
//  BẢNG APN NHÀ MẠNG VIỆT NAM (auto-detect)
// ══════════════════════════════════════════════════════════════════

struct CarrierAPN {
  const char* keyword;   // Chuỗi nhận dạng trong tên operator
  const char* apn;
  const char* user;
  const char* pass;
  const char* name;
};

// Danh sách nhà mạng VN – quét theo thứ tự
const CarrierAPN CARRIER_DB[] = {
  {"VIETTEL",     "v-internet",    "", "", "Viettel"},
  {"452 01",      "v-internet",    "", "", "Viettel"},
  {"VN VNPT",     "m3-world",      "mms", "mms", "Vinaphone"},
  {"VINAPHONE",   "m3-world",      "mms", "mms", "Vinaphone"},
  {"452 02",      "m3-world",      "mms", "mms", "Vinaphone"},
  {"VN MOB",      "m-wap",         "mms", "mms", "Mobifone"},
  {"MOBIFONE",    "m-wap",         "mms", "mms", "Mobifone"},
  {"452 04",      "m-wap",         "mms", "mms", "Mobifone"},
  {"VIETNAMOBILE","internet",      "", "", "Vietnamobile"},
  {"452 05",      "internet",      "", "", "Vietnamobile"},
  {"GMOBILE",     "internet",      "", "", "Gmobile"},
  {"452 07",      "internet",      "", "", "Gmobile"},
};
const int CARRIER_DB_SIZE = sizeof(CARRIER_DB) / sizeof(CARRIER_DB[0]);

// Ngưỡng cường độ tín hiệu (CSQ: 0-31, 99=unknown)
#define SIGNAL_EXCELLENT  20   // >= 20 CSQ (-73dBm trở lên)
#define SIGNAL_GOOD       15   // >= 15 CSQ (-83dBm)
#define SIGNAL_FAIR       10   // >= 10 CSQ (-93dBm)
#define SIGNAL_WEAK        5   // >= 5  CSQ (-103dBm)
// < 5 = Critical

// ══════════════════════════════════════════════════════════════════
//  DEFAULT CONFIG (ghi đè bằng NVS / Serial command)
// ══════════════════════════════════════════════════════════════════

// SIM / APN (auto-detect sẽ ghi đè nếu tìm thấy nhà mạng)
String cfg_apn       = "v-internet";
String cfg_apn_user  = "";
String cfg_apn_pass  = "";
bool   cfg_auto_apn  = true;  // true = tự quét nhà mạng, false = dùng APN thủ công

// MQTT
String cfg_mqtt_host   = "fan-auto.cloud";
int    cfg_mqtt_port   = 1883;
String cfg_mqtt_user   = "";
String cfg_mqtt_pass   = "";
String cfg_mqtt_prefix = "fanjet/basement";
String cfg_client_id   = "esp32-gw-01";

// Unit & Modbus
String cfg_unit_id      = "F01";
int    cfg_modbus_addr  = 1;
int    cfg_pub_interval = 3;

// ══════════════════════════════════════════════════════════════════
//  OBJECTS
// ══════════════════════════════════════════════════════════════════

HardwareSerial SerialAT(1);        // UART1 cho A7680C
HardwareSerial SerialRS485(2);     // UART2 cho RS-485

TinyGsm        modem(SerialAT);
TinyGsmClient  gsmClient(modem);
PubSubClient   mqtt(gsmClient);
ModbusMaster   modbus;
Preferences    prefs;

// ══════════════════════════════════════════════════════════════════
//  STATE
// ══════════════════════════════════════════════════════════════════

// CO-Speed Profile lưu trong RAM (nhận từ MQTT, backup NVS)
struct ProfilePoint { float co; int speed; };
ProfilePoint profile[10];
int profileLen = 4;

// Telemetry cache
float   cur_co      = 0.0;
int     cur_speed   = 0;
bool    cur_tripped = false;
String  cur_mode    = "auto";

// Signal monitoring
int     cur_csq         = 0;      // Raw CSQ (0-31, 99=unknown)
int     cur_rssi        = -999;   // dBm
String  cur_carrier     = "N/A";
String  cur_signal_label = "unknown";  // excellent/good/fair/weak/critical/unknown
bool    signal_warned   = false;       // Đã gửi cảnh báo sóng yếu?
unsigned long lastSignalCheck = 0;

// Timing
unsigned long lastPub      = 0;
unsigned long lastModbus   = 0;
unsigned long lastReconn   = 0;
unsigned long lastLedBlink = 0;

// LED pattern
bool ledState = false;
int  ledInterval = 1000;

// ══════════════════════════════════════════════════════════════════
//  RS-485 DE/RE control cho ModbusMaster
// ══════════════════════════════════════════════════════════════════

void rs485PreTransmit()  { digitalWrite(PIN_RS485_DE, HIGH); delayMicroseconds(50); }
void rs485PostTransmit() { delayMicroseconds(50); digitalWrite(PIN_RS485_DE, LOW); }

// ══════════════════════════════════════════════════════════════════
//  NVS – Load / Save config
// ══════════════════════════════════════════════════════════════════

void loadConfig() {
  prefs.begin("fanjet", true);  // read-only
  cfg_apn          = prefs.getString("apn",       cfg_apn);
  cfg_mqtt_host    = prefs.getString("mqtt_host", cfg_mqtt_host);
  cfg_mqtt_port    = prefs.getInt("mqtt_port",    cfg_mqtt_port);
  cfg_mqtt_user    = prefs.getString("mqtt_user", cfg_mqtt_user);
  cfg_mqtt_pass    = prefs.getString("mqtt_pass", cfg_mqtt_pass);
  cfg_mqtt_prefix  = prefs.getString("mqtt_pfx",  cfg_mqtt_prefix);
  cfg_client_id    = prefs.getString("client_id",  cfg_client_id);
  cfg_unit_id      = prefs.getString("unit_id",   cfg_unit_id);
  cfg_modbus_addr  = prefs.getInt("mb_addr",      cfg_modbus_addr);
  cfg_pub_interval = prefs.getInt("pub_int",      cfg_pub_interval);

  // Load profile
  profileLen = prefs.getInt("prof_len", 4);
  if (profileLen > 10) profileLen = 10;
  for (int i = 0; i < profileLen; i++) {
    String kc = "prof_co_" + String(i);
    String ks = "prof_sp_" + String(i);
    profile[i].co    = prefs.getFloat(kc.c_str(), 15.0 + i * 12.0);
    profile[i].speed = prefs.getInt(ks.c_str(),   30 + i * 20);
  }
  prefs.end();
}

void saveConfig() {
  prefs.begin("fanjet", false);  // read-write
  prefs.putString("apn",       cfg_apn);
  prefs.putString("mqtt_host", cfg_mqtt_host);
  prefs.putInt("mqtt_port",    cfg_mqtt_port);
  prefs.putString("mqtt_user", cfg_mqtt_user);
  prefs.putString("mqtt_pass", cfg_mqtt_pass);
  prefs.putString("mqtt_pfx",  cfg_mqtt_prefix);
  prefs.putString("client_id", cfg_client_id);
  prefs.putString("unit_id",   cfg_unit_id);
  prefs.putInt("mb_addr",      cfg_modbus_addr);
  prefs.putInt("pub_int",      cfg_pub_interval);
  prefs.end();
  Serial.println(F("[NVS] Config saved!"));
}

void saveProfile() {
  prefs.begin("fanjet", false);
  prefs.putInt("prof_len", profileLen);
  for (int i = 0; i < profileLen; i++) {
    prefs.putFloat(("prof_co_" + String(i)).c_str(), profile[i].co);
    prefs.putInt(("prof_sp_" + String(i)).c_str(),   profile[i].speed);
  }
  prefs.end();
  Serial.println(F("[NVS] Profile saved!"));
}

// ══════════════════════════════════════════════════════════════════
//  A7680C 4G INIT
// ══════════════════════════════════════════════════════════════════

void powerOnModem() {
  Serial.println(F("[4G] Power on A7680C..."));
  pinMode(PIN_4G_PWR, OUTPUT);
  digitalWrite(PIN_4G_PWR, LOW);
  delay(100);
  digitalWrite(PIN_4G_PWR, HIGH);
  delay(1500);
  digitalWrite(PIN_4G_PWR, LOW);
  delay(5000);
}

bool initModem() {
  Serial.println(F("[4G] Initializing modem..."));

  // Test AT
  int tries = 0;
  while (!modem.testAT(1000) && tries < 15) {
    Serial.print(".");
    tries++;
  }
  if (tries >= 15) {
    Serial.println(F("\n[4G] ERROR: Modem not responding!"));
    return false;
  }
  Serial.println(F("\n[4G] Modem OK"));

  // Modem info
  String info = modem.getModemInfo();
  Serial.println("[4G] Modem: " + info);

  // SIM
  int simSt = modem.getSimStatus();
  Serial.println("[4G] SIM status: " + String(simSt));
  if (simSt != 1 && simSt != 3) {
    Serial.println(F("[4G] WARNING: SIM not ready!"));
  }

  // Register network
  Serial.println(F("[4G] Waiting for network..."));
  if (!modem.waitForNetwork(60000L)) {
    Serial.println(F("[4G] ERROR: Network registration failed!"));
    return false;
  }
  Serial.println("[4G] Network OK. Signal: " + String(modem.getSignalQuality()));

  // GPRS connect
  Serial.println("[4G] Connecting GPRS: APN=" + cfg_apn);
  if (!modem.gprsConnect(cfg_apn.c_str(), cfg_apn_user.c_str(), cfg_apn_pass.c_str())) {
    Serial.println(F("[4G] ERROR: GPRS connect failed!"));
    return false;
  }
  Serial.println("[4G] GPRS connected! IP: " + modem.getLocalIP());
  return true;
}

// ══════════════════════════════════════════════════════════════════
//  MQTT
// ══════════════════════════════════════════════════════════════════

// Build topic strings
String topicTelemetry() { return cfg_mqtt_prefix + "/" + cfg_unit_id + "/telemetry"; }
String topicCommand()   { return cfg_mqtt_prefix + "/" + cfg_unit_id + "/command"; }
String topicProfile()   { return cfg_mqtt_prefix + "/" + cfg_unit_id + "/profile"; }
String topicStatus()    { return cfg_mqtt_prefix + "/" + cfg_unit_id + "/status"; }

void mqttCallback(char* topic, byte* payload, unsigned int len) {
  String sTopic = String(topic);
  String sPayload;
  sPayload.reserve(len);
  for (unsigned int i = 0; i < len; i++) sPayload += (char)payload[i];

  Serial.println("[MQTT RX] " + sTopic + " → " + sPayload);

  // Parse JSON
  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, sPayload);
  if (err) {
    Serial.println("[MQTT] JSON parse error: " + String(err.c_str()));
    return;
  }

  // ── Handle /command ──
  if (sTopic.endsWith("/command")) {
    handleCommand(doc);
  }
  // ── Handle /profile ──
  else if (sTopic.endsWith("/profile")) {
    handleProfile(doc);
  }
}

void handleCommand(JsonDocument& doc) {
  /*  Payload: {"mode": "manual", "speed": 80}
   *  Ghi xuống PLC Holding Registers:
   *    HR[0] = mode  (0=auto, 1=manual)
   *    HR[1] = speed (0-100%)
   */
  bool hasMode  = doc.containsKey("mode");
  bool hasSpeed = doc.containsKey("speed");

  if (hasMode) {
    String mode = doc["mode"].as<String>();
    uint16_t modeVal = (mode == "manual") ? 1 : 0;
    uint8_t result = modbus.writeSingleRegister(0x00, modeVal);
    if (result == modbus.ku8MBSuccess) {
      cur_mode = mode;
      Serial.println("[CMD] Mode → " + mode);
    } else {
      Serial.println("[CMD] Modbus write mode FAILED: 0x" + String(result, HEX));
    }
  }

  if (hasSpeed) {
    uint16_t speed = doc["speed"].as<int>();
    if (speed > 100) speed = 100;
    uint8_t result = modbus.writeSingleRegister(0x01, speed);
    if (result == modbus.ku8MBSuccess) {
      cur_speed = speed;
      Serial.println("[CMD] Speed → " + String(speed) + "%");
    } else {
      Serial.println("[CMD] Modbus write speed FAILED: 0x" + String(result, HEX));
    }
  }
}

void handleProfile(JsonDocument& doc) {
  /*  Payload: {"profile": [{"co":10,"speed":20}, {"co":30,"speed":60}, ...]}
   *  Lưu vào RAM + NVS Flash
   */
  if (!doc.containsKey("profile")) return;

  JsonArray arr = doc["profile"].as<JsonArray>();
  int n = min((int)arr.size(), 10);
  for (int i = 0; i < n; i++) {
    profile[i].co    = arr[i]["co"].as<float>();
    profile[i].speed = arr[i]["speed"].as<int>();
  }
  profileLen = n;
  saveProfile();

  Serial.print("[PROFILE] Updated " + String(n) + " points: ");
  for (int i = 0; i < n; i++) {
    Serial.print(String(profile[i].co, 1) + "→" + String(profile[i].speed) + "% ");
  }
  Serial.println();
}

bool mqttConnect() {
  Serial.println("[MQTT] Connecting to " + cfg_mqtt_host + ":" + String(cfg_mqtt_port));
  mqtt.setServer(cfg_mqtt_host.c_str(), cfg_mqtt_port);
  mqtt.setCallback(mqttCallback);
  mqtt.setKeepAlive(60);
  mqtt.setBufferSize(512);

  bool ok;
  if (cfg_mqtt_user.length() > 0) {
    ok = mqtt.connect(cfg_client_id.c_str(), cfg_mqtt_user.c_str(), cfg_mqtt_pass.c_str());
  } else {
    ok = mqtt.connect(cfg_client_id.c_str());
  }

  if (ok) {
    Serial.println(F("[MQTT] Connected!"));
    // Subscribe to command & profile topics
    mqtt.subscribe(topicCommand().c_str(), 1);
    mqtt.subscribe(topicProfile().c_str(), 1);
    Serial.println("[MQTT] Subscribed: " + topicCommand());
    Serial.println("[MQTT] Subscribed: " + topicProfile());

    // Publish online status
    mqtt.publish(topicStatus().c_str(), "{\"status\":\"online\"}", true);

    ledInterval = 0;  // solid ON
    return true;
  } else {
    Serial.println("[MQTT] Failed, rc=" + String(mqtt.state()));
    ledInterval = 500;
    return false;
  }
}

// ══════════════════════════════════════════════════════════════════
//  MODBUS – Đọc telemetry từ PLC
// ══════════════════════════════════════════════════════════════════

void readPLCTelemetry() {
  /*  Đọc 4 Input Registers bắt đầu từ 0x00:
   *    IR[0] = CO (ppm × 10, ví dụ: 352 = 35.2 ppm)
   *    IR[1] = Speed (0-100 %)
   *    IR[2] = Tripped (0 hoặc 1)
   *    IR[3] = Mode (0=auto, 1=manual)
   */
  uint8_t result = modbus.readInputRegisters(0x00, 4);

  if (result == modbus.ku8MBSuccess) {
    cur_co      = modbus.getResponseBuffer(0) / 10.0;
    cur_speed   = modbus.getResponseBuffer(1);
    cur_tripped = modbus.getResponseBuffer(2) != 0;
    cur_mode    = (modbus.getResponseBuffer(3) == 1) ? "manual" : "auto";
  } else {
    Serial.println("[MODBUS] Read failed: 0x" + String(result, HEX));
  }
}

// ══════════════════════════════════════════════════════════════════
//  PUBLISH TELEMETRY
// ══════════════════════════════════════════════════════════════════

void publishTelemetry() {
  JsonDocument doc;
  doc["co"]      = round(cur_co * 10.0) / 10.0;  // 1 decimal
  doc["speed"]   = cur_speed;
  doc["tripped"] = cur_tripped;
  doc["mode"]    = cur_mode;

  char buf[128];
  serializeJson(doc, buf, sizeof(buf));

  String topic = topicTelemetry();
  if (mqtt.publish(topic.c_str(), buf)) {
    Serial.println("[MQTT TX] " + topic + " → " + String(buf));
  } else {
    Serial.println(F("[MQTT TX] Publish FAILED!"));
  }
}

// ══════════════════════════════════════════════════════════════════
//  SERIAL CLI – Cấu hình qua Serial Monitor
// ══════════════════════════════════════════════════════════════════

void processSerialCommand(String line) {
  line.trim();
  if (line.length() == 0) return;

  if (line.startsWith("set ")) {
    String rest = line.substring(4);
    int sp = rest.indexOf(' ');
    if (sp < 0) { Serial.println(F("Usage: set <key> <value>")); return; }
    String key = rest.substring(0, sp);
    String val = rest.substring(sp + 1);
    val.trim();

    if      (key == "apn")         cfg_apn = val;
    else if (key == "mqtt_host")   cfg_mqtt_host = val;
    else if (key == "mqtt_port")   cfg_mqtt_port = val.toInt();
    else if (key == "mqtt_user")   cfg_mqtt_user = val;
    else if (key == "mqtt_pass")   cfg_mqtt_pass = val;
    else if (key == "mqtt_prefix") cfg_mqtt_prefix = val;
    else if (key == "client_id")   cfg_client_id = val;
    else if (key == "unit_id")     cfg_unit_id = val;
    else if (key == "modbus_addr") cfg_modbus_addr = val.toInt();
    else if (key == "pub_interval") cfg_pub_interval = val.toInt();
    else { Serial.println("Unknown key: " + key); return; }
    Serial.println("[SET] " + key + " = " + val);
  }
  else if (line == "save") {
    saveConfig();
  }
  else if (line == "restart" || line == "reboot") {
    Serial.println(F("[SYS] Restarting..."));
    delay(500);
    ESP.restart();
  }
  else if (line == "status") {
    Serial.println(F("═══ FanJet Gateway Status ═══"));
    Serial.println("Unit ID      : " + cfg_unit_id);
    Serial.println("MQTT Host    : " + cfg_mqtt_host + ":" + String(cfg_mqtt_port));
    Serial.println("MQTT Prefix  : " + cfg_mqtt_prefix);
    Serial.println("MQTT State   : " + String(mqtt.connected() ? "Connected" : "Disconnected"));
    Serial.println("Modbus Addr  : " + String(cfg_modbus_addr));
    Serial.println("Pub Interval : " + String(cfg_pub_interval) + "s");
    Serial.println("APN          : " + cfg_apn);
    Serial.println("Signal (CSQ) : " + String(modem.getSignalQuality()));
    Serial.println("CO=" + String(cur_co, 1) + " Speed=" + String(cur_speed) +
                   "% Trip=" + String(cur_tripped) + " Mode=" + cur_mode);
    Serial.print("Profile (" + String(profileLen) + "): ");
    for (int i = 0; i < profileLen; i++)
      Serial.print(String(profile[i].co, 0) + "→" + String(profile[i].speed) + "% ");
    Serial.println();
  }
  else if (line == "help") {
    Serial.println(F("═══ Commands ═══"));
    Serial.println(F("set <key> <value>  – Set config"));
    Serial.println(F("  Keys: apn, mqtt_host, mqtt_port, mqtt_user, mqtt_pass,"));
    Serial.println(F("        mqtt_prefix, client_id, unit_id, modbus_addr, pub_interval"));
    Serial.println(F("save               – Save config to NVS Flash"));
    Serial.println(F("restart            – Reboot ESP32"));
    Serial.println(F("status             – Show current status"));
    Serial.println(F("read               – Force read PLC now"));
    Serial.println(F("pub                – Force publish telemetry now"));
  }
  else if (line == "read") {
    readPLCTelemetry();
    Serial.println("CO=" + String(cur_co, 1) + " Speed=" + String(cur_speed) +
                   " Trip=" + String(cur_tripped) + " Mode=" + cur_mode);
  }
  else if (line == "pub") {
    readPLCTelemetry();
    publishTelemetry();
  }
  else {
    Serial.println("Unknown command. Type 'help'.");
  }
}

// ══════════════════════════════════════════════════════════════════
//  LED STATUS INDICATOR
// ══════════════════════════════════════════════════════════════════

void updateLED() {
  if (ledInterval == 0) {
    // Solid ON = connected
    digitalWrite(PIN_LED, HIGH);
    return;
  }
  unsigned long now = millis();
  if (now - lastLedBlink >= (unsigned long)ledInterval) {
    lastLedBlink = now;
    ledState = !ledState;
    digitalWrite(PIN_LED, ledState ? HIGH : LOW);
  }
}

// ══════════════════════════════════════════════════════════════════
//  SETUP
// ══════════════════════════════════════════════════════════════════

void setup() {
  // Serial debug
  Serial.begin(115200);
  delay(100);
  Serial.println(F("\n══════════════════════════════════════"));
  Serial.println(F("  FanJet BMS – ESP32 PLC↔MQTT Gateway"));
  Serial.println(F("  4G: A7680C  |  PLC: RS-485 Modbus"));
  Serial.println(F("══════════════════════════════════════"));

  // LED
  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_LED, LOW);

  // Load config from NVS
  loadConfig();
  Serial.println("[CFG] Unit=" + cfg_unit_id + " MQTT=" + cfg_mqtt_host +
                 ":" + String(cfg_mqtt_port) + " MB_Addr=" + String(cfg_modbus_addr));

  // Default profile nếu chưa có
  if (profileLen == 0) {
    profile[0] = {15.0, 30};
    profile[1] = {25.0, 50};
    profile[2] = {35.0, 70};
    profile[3] = {50.0, 100};
    profileLen = 4;
  }

  // ── Init RS-485 / Modbus ──
  pinMode(PIN_RS485_DE, OUTPUT);
  digitalWrite(PIN_RS485_DE, LOW);  // RX mode mặc định
  SerialRS485.begin(BAUD_RS485, SERIAL_8N1, PIN_RS485_RX, PIN_RS485_TX);
  modbus.begin(cfg_modbus_addr, SerialRS485);
  modbus.preTransmission(rs485PreTransmit);
  modbus.postTransmission(rs485PostTransmit);
  Serial.println("[RS485] Modbus RTU initialized, slave addr=" + String(cfg_modbus_addr));

  // ── Init A7680C 4G ──
  SerialAT.begin(BAUD_4G, SERIAL_8N1, PIN_4G_RX, PIN_4G_TX);
  delay(100);
  powerOnModem();

  ledInterval = 200;  // fast blink = connecting
  if (initModem()) {
    // ── Init MQTT ──
    mqttConnect();
  } else {
    Serial.println(F("[4G] Will retry in loop..."));
    ledInterval = 1000;  // slow blink = no connection
  }

  Serial.println(F("[SYS] Setup complete. Type 'help' for commands."));
}

// ══════════════════════════════════════════════════════════════════
//  LOOP
// ══════════════════════════════════════════════════════════════════

void loop() {
  unsigned long now = millis();

  // ── 1. MQTT loop ──
  if (mqtt.connected()) {
    mqtt.loop();
  }

  // ── 2. Đọc PLC mỗi 1 giây ──
  if (now - lastModbus >= 1000) {
    lastModbus = now;
    readPLCTelemetry();
  }

  // ── 3. Publish telemetry theo interval ──
  if (now - lastPub >= (unsigned long)(cfg_pub_interval * 1000)) {
    lastPub = now;
    if (mqtt.connected()) {
      publishTelemetry();
    }
  }

  // ── 4. Reconnect MQTT nếu mất kết nối ──
  if (!mqtt.connected() && (now - lastReconn >= 15000)) {
    lastReconn = now;
    ledInterval = 200;
    Serial.println(F("[MQTT] Reconnecting..."));

    // Kiểm tra GPRS
    if (!modem.isGprsConnected()) {
      Serial.println(F("[4G] GPRS lost, re-connecting..."));
      modem.gprsConnect(cfg_apn.c_str(), cfg_apn_user.c_str(), cfg_apn_pass.c_str());
    }

    mqttConnect();
  }

  // ── 5. Serial CLI ──
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    processSerialCommand(line);
  }

  // ── 6. LED indicator ──
  updateLED();

  delay(10);  // nhường CPU
}
