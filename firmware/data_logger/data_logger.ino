// TinyML Env Anomaly Detection - Data Logger (3 features)
// Output (115200 baud): t_ms,temp_c,hum_pct,motion
// Lines starting with '#' are diagnostics, not data.

#include <Arduino.h>
#include <Wire.h>
#include <DHT.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

// ---------- Pins ----------
#define PIN_DHT 4
#define PIN_PIR 27
#define PIN_LED 26

// ---------- Config ----------
#define SAMPLE_PERIOD_MS 5000UL
#define PIR_WARMUP_MS    30000UL   // HC-SR501 outputs garbage while it calibrates
#define OLED_ADDR        0x3C

DHT dht(PIN_DHT, DHT11);
Adafruit_SSD1306 oled(128, 64, &Wire, -1);

// WHY a latch: we sample every 5 s, but a PIR pulse can be shorter than that.
// Reading the pin at the sampling instant would miss most motion events.
// The ISR latches "any motion since last sample", so the feature is 1 if
// motion occurred anywhere in the 5 s window.
volatile bool motionLatched = false;
void IRAM_ATTR onMotion() { motionLatched = true; }

uint32_t nextTick;
uint32_t rowCount = 0;

static void showMsg(const char* l1, const char* l2 = "") {
  oled.clearDisplay();
  oled.setTextSize(1);
  oled.setTextColor(SSD1306_WHITE);
  oled.setCursor(0, 0);  oled.println(l1);
  oled.setCursor(0, 16); oled.println(l2);
  oled.display();
}

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

  // PIR warm-up with countdown
  for (uint32_t s = PIR_WARMUP_MS / 1000; s > 0; s--) {
    char buf[24]; snprintf(buf, sizeof(buf), "PIR warm-up %lus", (unsigned long)s);
    showMsg("Data Logger", buf);
    delay(1000);
  }

  attachInterrupt(digitalPinToInterrupt(PIN_PIR), onMotion, RISING);
  motionLatched = false;

  Serial.println("t_ms,temp_c,hum_pct,motion");  // header on every boot
  nextTick = millis();
}

void loop() {
  // Drift-free scheduling: advance by a fixed period instead of "now + 5000",
  // so DHT read time / printing time doesn't accumulate into the sample interval.
  uint32_t now = millis();
  if ((int32_t)(now - nextTick) < 0) return;
  nextTick += SAMPLE_PERIOD_MS;

  float t = dht.readTemperature();
  float h = dht.readHumidity();
  if (isnan(t) || isnan(h)) {
    // Skip the row instead of inventing a value. Fabricated data would
    // silently become part of the "normal" distribution.
    Serial.println("# DHT_READ_FAIL");
    return;
  }

  // Read-and-clear. A PIR edge landing in between is negligible:
  // it would simply be latched into the next window.
  int motion = motionLatched ? 1 : 0;
  motionLatched = false;

  Serial.printf("%lu,%.1f,%.1f,%d\n", (unsigned long)millis(), t, h, motion);
  rowCount++;

  // Heartbeat LED
  digitalWrite(PIN_LED, HIGH); delay(30); digitalWrite(PIN_LED, LOW);

  // OLED live view, useful for sanity-checking sensors while the logger runs
  oled.clearDisplay();
  oled.setTextSize(1);
  oled.setCursor(0, 0);  oled.printf("T:%.1fC  H:%.0f%%", t, h);
  oled.setCursor(0, 16); oled.printf("Motion:%d", motion);
  oled.setCursor(0, 32); oled.printf("Rows:%lu", (unsigned long)rowCount);
  oled.display();
}