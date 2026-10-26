// TinyML Env Anomaly Detection - Offline Logger (3 features)
// Stores fixed-width, checksummed records in the ESP32's flash (LittleFS), so the board
// can log without a PC (powered from a charger or power bank). Dump them afterwards with
// tools/offline_dump.py.
//
// Record (32 bytes, ASCII):  bbb,tttttttttt,TTT.T,HHH.H,m*CC\n
//   bbb = boot id, t_ms = millis(), temp, humidity, motion,
//   CC  = XOR checksum (hex) of the text before '*'
//
// Serial protocol (only in "service mode", entered when the PC sends HELLO within
// the first seconds after boot):
//   INFO      -> #INFO,rows=N,rec=32,boot=B,free=BYTES
//   GET i n   -> n records starting at row i, then #END
//   ERASE     -> deletes the log -> #OK

#include <Arduino.h>
#include <Wire.h>
#include <LittleFS.h>
#include <Preferences.h>
#include <DHT.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

// ---------- Pins ----------
#define PIN_DHT 4
#define PIN_PIR 27
#define PIN_LED 26

// ---------- Config ----------
#define SAMPLE_PERIOD_MS  5000UL
#define PIR_WARMUP_MS     30000UL   // HC-SR501 outputs garbage while it calibrates
#define HELLO_WINDOW_MS   6000UL    // time given to the PC to take over after boot
#define FLUSH_ROWS        12        // flash write every 60 s (<= 12 rows lost on power loss)
#define OLED_AUTO_OFF_MS  150000UL  // screen off 2.5 min after boot (not distracting in a room)
#define HEARTBEAT_LED     1         // 0 = LED stays dark while logging
#define OLED_ADDR         0x3C
#define LOG_PATH          "/log.bin"
#define REC               32        // bytes per record, including '\n'
#define MIN_FREE_BYTES    8192

DHT dht(PIN_DHT, DHT11);
Adafruit_SSD1306 oled(128, 64, &Wire, -1);
Preferences prefs;
File logFile;

// Latch: a PIR pulse can be shorter than the 5 s sampling period.
volatile bool motionLatched = false;
void IRAM_ATTR onMotion() { motionLatched = true; }

char wbuf[REC * FLUSH_ROWS];
size_t wlen = 0;
uint32_t rowsOnFlash = 0;   // rows in the file, including rows still in the RAM buffer
uint16_t bootId = 0;
uint32_t nextTick = 0;
uint32_t dhtFails = 0;
bool oledOn = true;
bool full = false;

// ---------- Display ----------
void showMsg(const char* l1, const char* l2 = "") {
  oled.clearDisplay();
  oled.setTextSize(1);
  oled.setTextColor(SSD1306_WHITE);
  oled.setCursor(0, 0);  oled.println(l1);
  oled.setCursor(0, 16); oled.println(l2);
  oled.display();
}

void updateOled(float t, float h, int motion) {
  if (!oledOn) return;
  if (millis() > OLED_AUTO_OFF_MS) {
    oled.ssd1306_command(SSD1306_DISPLAYOFF);
    oledOn = false;
    return;
  }
  size_t total = LittleFS.totalBytes();
  unsigned freePct = total ? (unsigned)(100ULL * (total - LittleFS.usedBytes()) / total) : 0;
  oled.clearDisplay();
  oled.setTextSize(1);
  oled.setCursor(0, 0);  oled.printf("REC boot %u", (unsigned)bootId);
  oled.setCursor(0, 16); oled.printf("T:%.1f H:%.0f M:%d", t, h, motion);
  oled.setCursor(0, 32); oled.printf("rows %lu", (unsigned long)rowsOnFlash);
  oled.setCursor(0, 48);
  if (full) oled.print("FLASH FULL");
  else      oled.printf("free %u%% fail %lu", freePct, (unsigned long)dhtFails);
  oled.display();
}

// ---------- Records ----------
// Returns true if the record has exactly REC bytes.
bool makeRecord(char* out, uint32_t tms, float t, float h, int motion) {
  char body[REC];
  int n = snprintf(body, sizeof(body), "%03u,%010lu,%05.1f,%05.1f,%d",
                   (unsigned)bootId, (unsigned long)tms, t, h, motion);
  if (n != REC - 4) return false;          // 28 chars before "*CC\n"
  uint8_t cs = 0;
  for (int i = 0; i < n; i++) cs ^= (uint8_t)body[i];
  snprintf(out, REC + 1, "%s*%02X\n", body, cs);
  return true;
}

void flushBuffer() {
  if (wlen == 0) return;
  size_t w = logFile.write((const uint8_t*)wbuf, wlen);
  logFile.flush();
  if (w != wlen) full = true;
  wlen = 0;
  if (LittleFS.totalBytes() - LittleFS.usedBytes() < MIN_FREE_BYTES) full = true;
  Serial.printf("# flushed, rows=%lu\n", (unsigned long)rowsOnFlash);
}

void appendRecord(uint32_t tms, float t, float h, int motion) {
  if (full) return;
  char rec[REC + 1];
  if (!makeRecord(rec, tms, t, h, motion)) return;
  memcpy(wbuf + wlen, rec, REC);
  wlen += REC;
  rowsOnFlash++;
  if (wlen >= sizeof(wbuf)) flushBuffer();
}

// After a power loss the file may end in a partial record; pad it so that
// every record starts at a multiple of REC. The padded record fails its checksum.
void repairTail() {
  File f = LittleFS.open(LOG_PATH, FILE_APPEND);
  if (!f) return;
  size_t sz = f.size();
  size_t rem = sz % REC;
  if (rem) {
    char pad[REC];
    memset(pad, ' ', sizeof(pad));
    pad[REC - rem - 1] = '\n';
    f.write((const uint8_t*)pad, REC - rem);
    f.flush();
    sz += REC - rem;
  }
  rowsOnFlash = sz / REC;
  f.close();
}

uint32_t fileRows() {
  File f = LittleFS.open(LOG_PATH, FILE_READ);
  if (!f) return 0;
  uint32_t r = f.size() / REC;
  f.close();
  return r;
}

uint16_t storedBoot() {
  prefs.begin("logger", true);
  uint16_t b = prefs.getUShort("boot", 0);
  prefs.end();
  return b;
}

// ---------- Service mode (PC takes over) ----------
bool waitForHello(uint32_t ms) {
  uint32_t t0 = millis();
  String line;
  while (millis() - t0 < ms) {
    while (Serial.available()) {
      char c = (char)Serial.read();
      if (c == '\n') {
        if (line.startsWith("HELLO")) return true;
        line = "";
      } else if (c != '\r' && line.length() < 32) {
        line += c;
      }
    }
    delay(5);
  }
  return false;
}

void sendRows(long i, long n) {
  File f = LittleFS.open(LOG_PATH, FILE_READ);
  if (f) {
    uint32_t rows = f.size() / REC;
    uint8_t rec[REC];
    for (long k = i; k < i + n && k >= 0 && (uint32_t)k < rows; k++) {
      f.seek((uint32_t)k * REC);
      if (f.read(rec, REC) != REC) break;
      Serial.write(rec, REC);
    }
    f.close();
  }
  Serial.println("#END");
}

void handleCommand(const String& cmd) {
  if (cmd.startsWith("INFO")) {
    Serial.printf("#INFO,rows=%lu,rec=%d,boot=%u,free=%lu\n",
                  (unsigned long)fileRows(), REC, (unsigned)storedBoot(),
                  (unsigned long)(LittleFS.totalBytes() - LittleFS.usedBytes()));
  } else if (cmd.startsWith("GET")) {
    long i = 0, n = 0;
    if (sscanf(cmd.c_str(), "GET %ld %ld", &i, &n) == 2) sendRows(i, n);
    else Serial.println("#ERR GET");
  } else if (cmd.startsWith("ERASE")) {
    LittleFS.remove(LOG_PATH);
    prefs.begin("logger", false);
    prefs.putUShort("boot", 0);
    prefs.end();
    Serial.println("#OK");
  } else if (cmd.startsWith("HELLO")) {
    Serial.println("#SERVICE");   // answer repeated HELLOs
  }
}

void serviceMode() {
  Serial.println("#SERVICE");
  char buf[24];
  snprintf(buf, sizeof(buf), "rows: %lu", (unsigned long)fileRows());
  showMsg("PC SERVICE", buf);
  String line;
  for (;;) {
    while (Serial.available()) {
      char c = (char)Serial.read();
      if (c == '\n') { handleCommand(line); line = ""; }
      else if (c != '\r' && line.length() < 48) line += c;
    }
    delay(2);
  }
}

// ---------- Arduino ----------
void setup() {
  Serial.begin(115200);
  pinMode(PIN_LED, OUTPUT);
  pinMode(PIN_PIR, INPUT);
  dht.begin();
  Wire.begin(21, 22);
  if (!oled.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
    Serial.println("# OLED_INIT_FAIL (continuing without display)");
  }
  oled.setTextColor(SSD1306_WHITE);

  if (!LittleFS.begin(true)) {      // true = format on first use
    showMsg("FLASH FAIL", "LittleFS");
    Serial.println("#ERR LittleFS");
    for (;;) delay(1000);
  }

  showMsg("Offline logger", "PC? waiting 6 s");
  if (waitForHello(HELLO_WINDOW_MS)) serviceMode();   // never returns

  prefs.begin("logger", false);
  bootId = prefs.getUShort("boot", 0) + 1;
  if (bootId > 999) bootId = 999;
  prefs.putUShort("boot", bootId);
  prefs.end();

  repairTail();
  logFile = LittleFS.open(LOG_PATH, FILE_APPEND);
  if (!logFile) {
    showMsg("FLASH FAIL", "open log");
    Serial.println("#ERR open log");
    for (;;) delay(1000);
  }

  for (uint32_t s = PIR_WARMUP_MS / 1000; s > 0; s--) {
    char buf[24];
    snprintf(buf, sizeof(buf), "PIR warm-up %lus", (unsigned long)s);
    showMsg("Offline logger", buf);
    delay(1000);
  }

  attachInterrupt(digitalPinToInterrupt(PIN_PIR), onMotion, RISING);
  motionLatched = false;
  Serial.printf("# LOGGING boot=%u rows=%lu\n", (unsigned)bootId, (unsigned long)rowsOnFlash);
  nextTick = millis();
}

void loop() {
  uint32_t now = millis();
  if ((int32_t)(now - nextTick) < 0) return;
  nextTick += SAMPLE_PERIOD_MS;

  float t = dht.readTemperature();
  float h = dht.readHumidity();
  if (isnan(t) || isnan(h)) {
    dhtFails++;          // skip the row; the motion latch is kept for the next one
    return;
  }

  int motion = motionLatched ? 1 : 0;
  motionLatched = false;

  appendRecord(millis(), t, h, motion);
#if HEARTBEAT_LED
  digitalWrite(PIN_LED, HIGH); delay(30); digitalWrite(PIN_LED, LOW);
#endif
  updateOled(t, h, motion);
}