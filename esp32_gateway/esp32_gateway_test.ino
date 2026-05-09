/*
 * FanJet BMS – ESP32 Gateway TEST BUILD
 * Giả lập CO/Quạt + Kết nối thật A7680C 4G (SIM Vinaphone)
 * Upload lên ESP32, mở Serial Monitor 115200 để theo dõi.
 */

#define TINY_GSM_MODEM_A7680
#define TINY_GSM_RX_BUFFER 1024

#include <Arduino.h>
#include <HardwareSerial.h>
#include <Preferences.h>
#include <TinyGsmClient.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// ── PINOUT ──
#define PIN_4G_TX   26
#define PIN_4G_RX   27
#define PIN_4G_PWR  4
#define PIN_LED     2
#define BAUD_4G     115200

// ── CARRIER DB (VN) ──
struct CarrierInfo { const char* kw; const char* apn; const char* u; const char* p; const char* name; };
const CarrierInfo CARRIERS[] = {
  {"VIETTEL",     "v-internet", "", "", "Viettel"},
  {"452 01",      "v-internet", "", "", "Viettel"},
  {"VINAPHONE",   "m3-world",   "mms","mms","Vinaphone"},
  {"VN VNPT",     "m3-world",   "mms","mms","Vinaphone"},
  {"452 02",      "m3-world",   "mms","mms","Vinaphone"},
  {"MOBIFONE",    "m-wap",      "mms","mms","Mobifone"},
  {"VN MOB",      "m-wap",      "mms","mms","Mobifone"},
  {"452 04",      "m-wap",      "mms","mms","Mobifone"},
  {"VIETNAMOBILE","internet",   "", "", "Vietnamobile"},
  {"452 05",      "internet",   "", "", "Vietnamobile"},
};
const int NUM_CARRIERS = sizeof(CARRIERS)/sizeof(CARRIERS[0]);

// ── SIGNAL THRESHOLDS (CSQ 0-31) ──
#define SIG_EXCELLENT 20
#define SIG_GOOD      15
#define SIG_FAIR      10
#define SIG_WEAK       5

// ── CONFIG (sửa trực tiếp hoặc dùng Serial CLI) ──
String cfg_mqtt_host   = "fan-auto.cloud";
int    cfg_mqtt_port   = 1883;
String cfg_mqtt_user   = "";
String cfg_mqtt_pass   = "";
String cfg_mqtt_prefix = "fanjet/basement";
String cfg_client_id   = "esp32-test-01";
String cfg_unit_id     = "F01";
int    cfg_pub_interval = 3;  // giây

// ── OBJECTS ──
HardwareSerial SerialAT(1);
TinyGsm        modem(SerialAT);
TinyGsmClient  gsmClient(modem);
PubSubClient   mqtt(gsmClient);
Preferences    prefs;

// ── SIM STATE ──
String  det_apn      = "m3-world";   // Vinaphone mặc định
String  det_apn_user = "mms";
String  det_apn_pass = "mms";
String  det_carrier  = "Vinaphone";

// ── SIGNAL STATE ──
int     cur_csq          = 0;
int     cur_rssi         = -999;
String  cur_signal_label = "unknown";

// ── SIMULATED TELEMETRY ──
float   sim_co       = 8.0;    // CO giả lập (ppm)
float   sim_co_target = 15.0;  // Mục tiêu CO dao động
int     sim_speed    = 0;
bool    sim_tripped  = false;
String  sim_mode     = "auto";

// CO-Speed Profile
struct ProfPt { float co; int spd; };
ProfPt profile[] = {{10,20},{25,50},{35,70},{50,100}};
int profLen = 4;

// ── TIMING ──
unsigned long lastPub = 0, lastSim = 0, lastSig = 0, lastReconn = 0, lastBlink = 0;
bool ledState = false;
int  ledMs = 1000;

// ══════════════════════════════════════════════════
//  CARRIER AUTO-DETECT
// ══════════════════════════════════════════════════

bool detectCarrier() {
  String op = modem.getOperator();
  op.toUpperCase();
  Serial.println("[4G] Operator raw: " + op);

  for (int i = 0; i < NUM_CARRIERS; i++) {
    String kw = String(CARRIERS[i].kw);
    kw.toUpperCase();
    if (op.indexOf(kw) >= 0) {
      det_apn      = CARRIERS[i].apn;
      det_apn_user = CARRIERS[i].u;
      det_apn_pass = CARRIERS[i].p;
      det_carrier  = CARRIERS[i].name;
      Serial.println("[4G] ✓ Detected: " + det_carrier + " → APN: " + det_apn);
      return true;
    }
  }

  // Fallback: thử IMSI prefix
  String imsi = modem.getIMSI();
  Serial.println("[4G] IMSI: " + imsi);
  for (int i = 0; i < NUM_CARRIERS; i++) {
    if (imsi.startsWith(String(CARRIERS[i].kw).substring(0,5))) {
      det_apn      = CARRIERS[i].apn;
      det_apn_user = CARRIERS[i].u;
      det_apn_pass = CARRIERS[i].p;
      det_carrier  = CARRIERS[i].name;
      Serial.println("[4G] ✓ Detected (IMSI): " + det_carrier + " → APN: " + det_apn);
      return true;
    }
  }

  Serial.println("[4G] ✗ Unknown carrier! Using Vinaphone default.");
  return false;
}

// ══════════════════════════════════════════════════
//  SIGNAL STRENGTH
// ══════════════════════════════════════════════════

void checkSignal() {
  cur_csq = modem.getSignalQuality();
  if (cur_csq == 99 || cur_csq == 0) {
    cur_rssi = -999;
    cur_signal_label = "unknown";
  } else {
    cur_rssi = -113 + 2 * cur_csq;  // CSQ → dBm conversion
    if      (cur_csq >= SIG_EXCELLENT) cur_signal_label = "excellent";
    else if (cur_csq >= SIG_GOOD)      cur_signal_label = "good";
    else if (cur_csq >= SIG_FAIR)      cur_signal_label = "fair";
    else if (cur_csq >= SIG_WEAK)      cur_signal_label = "weak";
    else                               cur_signal_label = "critical";
  }
  Serial.println("[SIG] CSQ=" + String(cur_csq) + " RSSI=" + String(cur_rssi) +
                 "dBm → " + cur_signal_label);
}

// ══════════════════════════════════════════════════
//  SIMULATED FAN LOGIC
// ══════════════════════════════════════════════════

int autoSpeed(float co) {
  if (profLen == 0 || co <= profile[0].co) return 0;
  if (co >= profile[profLen-1].co) return profile[profLen-1].spd;
  for (int i = 0; i < profLen - 1; i++) {
    if (co >= profile[i].co && co <= profile[i+1].co) {
      float r = (co - profile[i].co) / (profile[i+1].co - profile[i].co);
      return (int)(profile[i].spd + r * (profile[i+1].spd - profile[i].spd));
    }
  }
  return 0;
}

void simTick() {
  // CO dao động ngẫu nhiên hướng về target
  float noise = ((float)random(-30, 30)) / 100.0;
  sim_co += (sim_co_target - sim_co) * 0.08 + noise;
  if (sim_co < 0) sim_co = 0;
  sim_co = ((int)(sim_co * 10)) / 10.0;

  // Đổi target ngẫu nhiên mỗi ~30 tick
  if (random(0, 30) == 0) {
    sim_co_target = random(5, 65);
    Serial.println("[SIM] New CO target: " + String(sim_co_target, 1) + " ppm");
  }

  // Speed logic
  if (sim_tripped) {
    sim_speed = 0;
  } else if (sim_mode == "auto") {
    sim_speed = autoSpeed(sim_co);
  }
  // manual: giữ nguyên speed từ command
}

// ══════════════════════════════════════════════════
//  MQTT TOPICS
// ══════════════════════════════════════════════════

String tTelemetry() { return cfg_mqtt_prefix + "/" + cfg_unit_id + "/telemetry"; }
String tCommand()   { return cfg_mqtt_prefix + "/" + cfg_unit_id + "/command"; }
String tProfile()   { return cfg_mqtt_prefix + "/" + cfg_unit_id + "/profile"; }
String tStatus()    { return cfg_mqtt_prefix + "/" + cfg_unit_id + "/status"; }

// ══════════════════════════════════════════════════
//  MQTT CALLBACK
// ══════════════════════════════════════════════════

void mqttCb(char* topic, byte* payload, unsigned int len) {
  String sT(topic);
  String sP; sP.reserve(len);
  for (unsigned int i = 0; i < len; i++) sP += (char)payload[i];
  Serial.println("[RX] " + sT + " → " + sP);

  JsonDocument doc;
  if (deserializeJson(doc, sP)) return;

  if (sT.endsWith("/command")) {
    if (doc.containsKey("mode")) {
      sim_mode = doc["mode"].as<String>();
      Serial.println("[CMD] Mode → " + sim_mode);
    }
    if (doc.containsKey("speed") && sim_mode == "manual") {
      sim_speed = constrain(doc["speed"].as<int>(), 0, 100);
      Serial.println("[CMD] Speed → " + String(sim_speed) + "%");
    }
  }
  else if (sT.endsWith("/profile")) {
    if (doc.containsKey("profile")) {
      JsonArray arr = doc["profile"].as<JsonArray>();
      int n = min((int)arr.size(), 10);
      for (int i = 0; i < n; i++) {
        profile[i].co  = arr[i]["co"].as<float>();
        profile[i].spd = arr[i]["speed"].as<int>();
      }
      profLen = n;
      Serial.print("[PROFILE] Updated " + String(n) + " pts: ");
      for (int i = 0; i < n; i++)
        Serial.print(String(profile[i].co,0) + "→" + String(profile[i].spd) + "% ");
      Serial.println();
    }
  }
}

// ══════════════════════════════════════════════════
//  MQTT CONNECT
// ══════════════════════════════════════════════════

bool mqttConnect() {
  Serial.println("[MQTT] Connecting " + cfg_mqtt_host + ":" + String(cfg_mqtt_port));
  mqtt.setServer(cfg_mqtt_host.c_str(), cfg_mqtt_port);
  mqtt.setCallback(mqttCb);
  mqtt.setKeepAlive(60);
  mqtt.setBufferSize(512);

  bool ok = cfg_mqtt_user.length() > 0
    ? mqtt.connect(cfg_client_id.c_str(), cfg_mqtt_user.c_str(), cfg_mqtt_pass.c_str())
    : mqtt.connect(cfg_client_id.c_str());

  if (ok) {
    Serial.println("[MQTT] ✓ Connected!");
    mqtt.subscribe(tCommand().c_str(), 1);
    mqtt.subscribe(tProfile().c_str(), 1);

    // Publish online + carrier info
    JsonDocument st;
    st["status"]  = "online";
    st["carrier"] = det_carrier;
    st["rssi"]    = cur_rssi;
    st["signal"]  = cur_signal_label;
    st["sim_mode"]= "test";
    char buf[200];
    serializeJson(st, buf);
    mqtt.publish(tStatus().c_str(), buf, true);

    ledMs = 0;  // solid ON
    return true;
  }
  Serial.println("[MQTT] ✗ Failed rc=" + String(mqtt.state()));
  ledMs = 500;
  return false;
}

// ══════════════════════════════════════════════════
//  PUBLISH TELEMETRY (bao gồm signal info)
// ══════════════════════════════════════════════════

void publishTelemetry() {
  JsonDocument doc;
  doc["co"]      = ((int)(sim_co * 10)) / 10.0;
  doc["speed"]   = sim_speed;
  doc["tripped"] = sim_tripped;
  doc["mode"]    = sim_mode;
  // Thông tin gateway/signal
  doc["rssi"]    = cur_rssi;
  doc["csq"]     = cur_csq;
  doc["signal"]  = cur_signal_label;
  doc["carrier"] = det_carrier;

  char buf[256];
  serializeJson(doc, buf);
  String topic = tTelemetry();
  if (mqtt.publish(topic.c_str(), buf)) {
    Serial.println("[TX] " + topic + " → " + String(buf));
  } else {
    Serial.println("[TX] FAILED!");
  }

  // Cảnh báo sóng yếu lên status topic
  if (cur_signal_label == "weak" || cur_signal_label == "critical") {
    JsonDocument warn;
    warn["warning"]  = "low_signal";
    warn["rssi"]     = cur_rssi;
    warn["csq"]      = cur_csq;
    warn["signal"]   = cur_signal_label;
    warn["carrier"]  = det_carrier;
    char wbuf[200];
    serializeJson(warn, wbuf);
    mqtt.publish(tStatus().c_str(), wbuf);
    Serial.println("[⚠] Signal warning published!");
  }
}

// ══════════════════════════════════════════════════
//  MODEM INIT + AUTO-DETECT
// ══════════════════════════════════════════════════

void powerOn() {
  Serial.println("[4G] Power on A7680C...");
  pinMode(PIN_4G_PWR, OUTPUT);
  digitalWrite(PIN_4G_PWR, LOW);  delay(100);
  digitalWrite(PIN_4G_PWR, HIGH); delay(1500);
  digitalWrite(PIN_4G_PWR, LOW);  delay(5000);
}

bool initModem() {
  Serial.println("[4G] Init modem...");
  int tries = 0;
  while (!modem.testAT(1000) && tries < 15) { Serial.print("."); tries++; }
  if (tries >= 15) { Serial.println("\n[4G] ✗ Modem not responding!"); return false; }
  Serial.println("\n[4G] Modem OK: " + modem.getModemInfo());
  Serial.println("[4G] SIM status: " + String(modem.getSimStatus()));

  // Chờ đăng ký mạng
  Serial.println("[4G] Waiting network...");
  if (!modem.waitForNetwork(60000L)) {
    Serial.println("[4G] ✗ Network failed!"); return false;
  }

  // Auto-detect nhà mạng
  Serial.println("[4G] Detecting carrier...");
  detectCarrier();

  // Đọc signal
  checkSignal();

  // Kết nối GPRS
  Serial.println("[4G] GPRS connect: APN=" + det_apn + " Carrier=" + det_carrier);
  if (!modem.gprsConnect(det_apn.c_str(), det_apn_user.c_str(), det_apn_pass.c_str())) {
    Serial.println("[4G] ✗ GPRS failed!"); return false;
  }
  Serial.println("[4G] ✓ GPRS OK! IP: " + modem.getLocalIP());
  return true;
}

// ══════════════════════════════════════════════════
//  SERIAL CLI
// ══════════════════════════════════════════════════

void handleSerial(String line) {
  line.trim();
  if (!line.length()) return;

  if (line.startsWith("set ")) {
    int sp = line.indexOf(' ', 4);
    if (sp < 0) { Serial.println("Usage: set <key> <val>"); return; }
    String k = line.substring(4, sp), v = line.substring(sp+1); v.trim();
    if      (k=="mqtt_host")   cfg_mqtt_host=v;
    else if (k=="mqtt_port")   cfg_mqtt_port=v.toInt();
    else if (k=="mqtt_user")   cfg_mqtt_user=v;
    else if (k=="mqtt_pass")   cfg_mqtt_pass=v;
    else if (k=="mqtt_prefix") cfg_mqtt_prefix=v;
    else if (k=="unit_id")     cfg_unit_id=v;
    else if (k=="pub_interval") cfg_pub_interval=v.toInt();
    else if (k=="co_target")   sim_co_target=v.toFloat();
    else { Serial.println("Unknown: "+k); return; }
    Serial.println("[SET] "+k+" = "+v);
  }
  else if (line=="status") {
    Serial.println(F("═══ TEST Gateway Status ═══"));
    Serial.println("Unit      : " + cfg_unit_id);
    Serial.println("Carrier   : " + det_carrier + " (APN: " + det_apn + ")");
    Serial.println("Signal    : CSQ=" + String(cur_csq) + " RSSI=" + String(cur_rssi) + "dBm [" + cur_signal_label + "]");
    Serial.println("MQTT      : " + cfg_mqtt_host + ":" + String(cfg_mqtt_port) + " " + (mqtt.connected()?"✓":"✗"));
    Serial.println("CO=" + String(sim_co,1) + "ppm Speed=" + String(sim_speed) + "% Mode=" + sim_mode +
                   " Trip=" + String(sim_tripped));
    Serial.print("Profile(" + String(profLen) + "): ");
    for(int i=0;i<profLen;i++) Serial.print(String(profile[i].co,0)+"→"+String(profile[i].spd)+"% ");
    Serial.println();
  }
  else if (line=="trip")  { sim_tripped=true;  Serial.println("[SIM] TRIPPED!"); }
  else if (line=="reset") { sim_tripped=false; Serial.println("[SIM] Trip reset"); }
  else if (line=="auto")  { sim_mode="auto";   Serial.println("[SIM] Mode → auto"); }
  else if (line=="manual"){ sim_mode="manual"; sim_speed=50; Serial.println("[SIM] Mode → manual 50%"); }
  else if (line=="restart") { ESP.restart(); }
  else if (line=="signal") { checkSignal(); }
  else if (line=="pub")   { publishTelemetry(); }
  else if (line=="help") {
    Serial.println(F("═══ Test Commands ═══"));
    Serial.println(F("status          – Trạng thái hiện tại"));
    Serial.println(F("set <key> <val> – Cấu hình (mqtt_host/port/user/pass/prefix/unit_id/pub_interval/co_target)"));
    Serial.println(F("trip / reset    – Giả lập trip/reset"));
    Serial.println(F("auto / manual   – Đổi mode"));
    Serial.println(F("signal          – Đọc sóng ngay"));
    Serial.println(F("pub             – Force publish"));
    Serial.println(F("restart         – Reboot ESP32"));
  }
  else Serial.println("? Type 'help'");
}

// ══════════════════════════════════════════════════
//  LED
// ══════════════════════════════════════════════════

void updateLED() {
  if (ledMs == 0) { digitalWrite(PIN_LED, HIGH); return; }
  if (millis() - lastBlink >= (unsigned long)ledMs) {
    lastBlink = millis();
    ledState = !ledState;
    digitalWrite(PIN_LED, ledState);
  }
}

// ══════════════════════════════════════════════════
//  SETUP
// ══════════════════════════════════════════════════

void setup() {
  Serial.begin(115200);
  delay(100);
  Serial.println(F("\n╔══════════════════════════════════════╗"));
  Serial.println(F("║ FanJet Gateway - TEST BUILD          ║"));
  Serial.println(F("║ Simulated CO/Fan + Real 4G + MQTT    ║"));
  Serial.println(F("╚══════════════════════════════════════╝"));

  pinMode(PIN_LED, OUTPUT);
  randomSeed(analogRead(0));

  // Init A7680C
  SerialAT.begin(BAUD_4G, SERIAL_8N1, PIN_4G_RX, PIN_4G_TX);
  delay(100);
  powerOn();

  ledMs = 200;  // fast blink = connecting
  if (initModem()) {
    mqttConnect();
  } else {
    Serial.println("[4G] Will retry in loop...");
    ledMs = 1000;
  }
  Serial.println(F("[SYS] Ready! Type 'help' for commands."));
}

// ══════════════════════════════════════════════════
//  LOOP
// ══════════════════════════════════════════════════

void loop() {
  unsigned long now = millis();

  // MQTT loop
  if (mqtt.connected()) mqtt.loop();

  // Simulate telemetry mỗi 1 giây
  if (now - lastSim >= 1000) {
    lastSim = now;
    simTick();
  }

  // Publish mỗi N giây
  if (now - lastPub >= (unsigned long)(cfg_pub_interval * 1000)) {
    lastPub = now;
    if (mqtt.connected()) publishTelemetry();
  }

  // Check signal mỗi 30 giây
  if (now - lastSig >= 30000) {
    lastSig = now;
    checkSignal();
  }

  // Reconnect
  if (!mqtt.connected() && (now - lastReconn >= 15000)) {
    lastReconn = now;
    ledMs = 200;
    Serial.println("[MQTT] Reconnecting...");
    if (!modem.isGprsConnected()) {
      Serial.println("[4G] GPRS reconnect...");
      modem.gprsConnect(det_apn.c_str(), det_apn_user.c_str(), det_apn_pass.c_str());
    }
    mqttConnect();
  }

  // Serial CLI
  if (Serial.available()) handleSerial(Serial.readStringUntil('\n'));

  // LED
  updateLED();
  delay(10);
}
