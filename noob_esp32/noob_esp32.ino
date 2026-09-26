/*
  NOOB - ESP32-S3 AI voice assistant (device firmware)
  ----------------------------------------------------
  Hold the button and speak, then release it. NOOB sends your voice to the NOOB
  server on your PC, which understands it (any language), asks the free AI, and
  sends back NOOB's spoken answer, which plays on the speaker.

  First use: open the NOOB App on your PC > Devices > Scan now > Connect, and type
  the 4-digit code shown on NOOB's screen. The pairing is saved, even after power-off.

  Board   : ESP32-S3-DevKitC-1 N16R8 (MUST have PSRAM)
  Arduino : "esp32 by Espressif Systems" board package version 3.x
  Tools   : Board "ESP32S3 Dev Module", PSRAM "OPI PSRAM", Flash Size "16MB (128Mb)"
  Library : "Adafruit SSD1306" (installs "Adafruit GFX Library" with it)
*/

#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <HTTPClient.h>
#include <Preferences.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include "driver/i2s_std.h"

// ===================== CHANGE THESE 2 LINES =====================
const char* WIFI_SSID = "YOUR_WIFI_NAME";       // tip: use your phone's hotspot, then NOOB works anywhere
const char* WIFI_PASS = "YOUR_WIFI_PASSWORD";
// ================================================================
// The PC's address and the secret key are set by pairing in the NOOB App.

#define FW_VERSION  "1.2"
#define DEVICE_PORT 4210         // NOOB listens here for the NOOB App
#define SERVER_PORT 4211         // the NOOB server listens here
#define PAIR_WINDOW_MS 120000    // a pairing code is valid for 2 minutes
#define PING_ONLINE_MS  15000    // say hello to the PC this often while it answers
#define PING_OFFLINE_MS 30000    // ...and this often while it does not

// ---------- Pins (see wiring table) ----------
#define MIC_SCK     5    // INMP441 SCK
#define MIC_WS      4    // INMP441 WS
#define MIC_SD      6    // INMP441 SD
#define AMP_BCLK    15   // MAX98357A BCLK
#define AMP_LRC     16   // MAX98357A LRC
#define AMP_DIN     7    // MAX98357A DIN
#define BUTTON_PIN  12   // push button to GND
#define OLED_SDA    8
#define OLED_SCL    9

// ---------- Audio settings ----------
#define SAMPLE_RATE        16000   // must match the server
#define MAX_RECORD_SECONDS 10
#define MIN_RECORD_MS      400     // shorter presses are ignored
#define MIC_GAIN_SHIFT     12      // lower number = louder mic (11 = louder, 13 = quieter)
#define VOLUME_PERCENT     60      // speaker volume 0..100

const size_t MAX_SAMPLES = (size_t)SAMPLE_RATE * MAX_RECORD_SECONDS;

i2s_chan_handle_t micChan = NULL;
i2s_chan_handle_t spkChan = NULL;
int16_t* recBuf = NULL;           // recording buffer, lives in PSRAM

Adafruit_SSD1306 display(128, 64, &Wire, -1);
bool oledOk = false;

WiFiUDP udp;
bool udpStarted = false;
Preferences prefs;                // pairing is saved in flash memory
String serverUrl, deviceKey, deviceName;
int pairCode = 0;
unsigned long pairUntil = 0;      // 0 = not in pairing mode
unsigned long lastWifiTry = 0;
unsigned long lastPing = 0;
bool pcOnline = false;            // does the NOOB server on the PC answer?
String ownerName;                 // first name of the account NOOB belongs to

// ------------------------------------------------------------------ screen
void showStatus(const char* line1, const char* line2 = "") {
  Serial.printf("[NOOB] %s %s\n", line1, line2);
  if (!oledOk) return;
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(2);
  display.setCursor(0, 0);
  display.println("NOOB");
  display.setTextSize(1);
  display.setCursor(0, 28);
  display.println(line1);
  display.setCursor(0, 44);
  display.println(line2);
  display.display();
}

bool isPaired() {
  return serverUrl.length() > 0 && deviceKey.length() > 0;
}

void showReady() {
  if (WiFi.status() != WL_CONNECTED) showStatus("No WiFi", WIFI_SSID);
  else if (!isPaired())              showStatus("Not paired yet", "NOOB App > Devices");
  else if (!pcOnline)                showStatus("PC offline", "open NOOB App on PC");
  else {
    String hello = "Hi " + (ownerName.length() ? ownerName : String("friend")) + "! Hold to talk";
    showStatus("Ready", hello.c_str());
  }
}

void showPairCode() {
  Serial.printf("[NOOB] Pairing code: %d\n", pairCode);
  if (!oledOk) return;
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.println("Pairing code:");
  display.setTextSize(3);
  display.setCursor(28, 20);
  display.println(pairCode);
  display.setTextSize(1);
  display.setCursor(0, 54);
  display.println("Type it in NOOB App");
  display.display();
}

void haltWithError() {           // stop here; the reason is on the OLED + Serial Monitor
  while (true) delay(1000);
}

// ------------------------------------------------------------------ audio
bool setupMic() {
  i2s_chan_config_t chanCfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
  if (i2s_new_channel(&chanCfg, NULL, &micChan) != ESP_OK) return false;

  i2s_std_config_t stdCfg = {
    .clk_cfg  = I2S_STD_CLK_DEFAULT_CONFIG(SAMPLE_RATE),
    .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_MONO),
    .gpio_cfg = {
      .mclk = I2S_GPIO_UNUSED,
      .bclk = (gpio_num_t)MIC_SCK,
      .ws   = (gpio_num_t)MIC_WS,
      .dout = I2S_GPIO_UNUSED,
      .din  = (gpio_num_t)MIC_SD,
      .invert_flags = { .mclk_inv = false, .bclk_inv = false, .ws_inv = false },
    },
  };
  stdCfg.slot_cfg.slot_mask = I2S_STD_SLOT_LEFT;   // INMP441 L/R pin tied to GND = left

  if (i2s_channel_init_std_mode(micChan, &stdCfg) != ESP_OK) return false;
  return i2s_channel_enable(micChan) == ESP_OK;
}

bool setupSpeaker() {
  i2s_chan_config_t chanCfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_1, I2S_ROLE_MASTER);
  chanCfg.auto_clear = true;   // play silence (not noise) when there is no data
  if (i2s_new_channel(&chanCfg, &spkChan, NULL) != ESP_OK) return false;

  i2s_std_config_t stdCfg = {
    .clk_cfg  = I2S_STD_CLK_DEFAULT_CONFIG(SAMPLE_RATE),
    .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO),
    .gpio_cfg = {
      .mclk = I2S_GPIO_UNUSED,
      .bclk = (gpio_num_t)AMP_BCLK,
      .ws   = (gpio_num_t)AMP_LRC,
      .dout = (gpio_num_t)AMP_DIN,
      .din  = I2S_GPIO_UNUSED,
      .invert_flags = { .mclk_inv = false, .bclk_inv = false, .ws_inv = false },
    },
  };
  stdCfg.slot_cfg.slot_mask = I2S_STD_SLOT_BOTH;   // same sound on left + right

  if (i2s_channel_init_std_mode(spkChan, &stdCfg) != ESP_OK) return false;
  return i2s_channel_enable(spkChan) == ESP_OK;
}

// ------------------------------------------------------------------ Wi-Fi + pairing
void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  showStatus("Connecting WiFi...", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 20000) delay(250);
  if (WiFi.status() == WL_CONNECTED) {
    showStatus("WiFi connected", WiFi.localIP().toString().c_str());
    if (!udpStarted) udpStarted = udp.begin(DEVICE_PORT);
  } else {
    showStatus("WiFi FAILED", "check name/password");
  }
}

void udpReply(const String& message) {
  udp.beginPacket(udp.remoteIP(), udp.remotePort());
  udp.print(message);
  udp.endPacket();
}

// Reads one UDP message into `msg`. Returns false if there is none.
bool readUdp(char* msg, size_t size) {
  if (!udpStarted || udp.parsePacket() <= 0) return false;
  int len = udp.read(msg, size - 1);
  if (len <= 0) return false;
  msg[len] = 0;
  while (len > 0 && (msg[len - 1] == '\n' || msg[len - 1] == '\r' || msg[len - 1] == ' ')) msg[--len] = 0;
  return true;
}

void savePairing(const String& url, const String& key) {
  serverUrl = url;
  deviceKey = key;
  prefs.putString("url", url);
  prefs.putString("key", key);
}

// Answers the NOOB App: "Connect to nearby devices".
void handleUdp() {
  char msg[300];
  if (!readUdp(msg, sizeof(msg))) return;

  if (strcmp(msg, "NOOB?DISCOVER") == 0) {
    udpReply("NOOB!DEVICE|" + deviceName + "|" + WiFi.macAddress() + "|" + (isPaired() ? "1" : "0") + "|" FW_VERSION);

  } else if (strcmp(msg, "NOOB?PAIRSTART") == 0) {
    if (pairUntil == 0) pairCode = 1000 + (esp_random() % 9000);   // keep the same code if asked again
    pairUntil = millis() + PAIR_WINDOW_MS;
    showPairCode();
    udpReply("NOOB!CODE");

  } else if (strncmp(msg, "NOOB?PAIR|", 10) == 0) {          // NOOB?PAIR|code|server_url|device_key
    char* code = strtok(msg + 10, "|");
    char* url  = strtok(NULL, "|");
    char* key  = strtok(NULL, "|");
    String paired = "NOOB!PAIRED|" + deviceName + "|" + WiFi.macAddress();
    if (!code || !url || !key) return;
    if (isPaired() && serverUrl == url && deviceKey == key) {   // already done (the reply was lost)
      udpReply(paired);
    } else if (pairUntil != 0 && atoi(code) == pairCode) {
      savePairing(url, key);
      pairUntil = 0;
      udpReply(paired);
      showStatus("Paired!", "saying hello to PC");
      lastPing = 0;                                  // say hello right away
    } else {
      udpReply("NOOB!BADCODE");
    }

  } else if (strncmp(msg, "NOOB?UNPAIR|", 12) == 0) {
    if (isPaired() && deviceKey == String(msg + 12)) {
      savePairing("", "");
      udpReply("NOOB!UNPAIRED");
      showReady();
    }
  }
}

// Asks the network where the NOOB server is (used when the PC's IP address changed).
bool findServer(bool quiet = false) {
  if (!udpStarted) return false;
  if (!quiet) showStatus("Looking for PC...", "");
  char msg[300];
  for (int attempt = 0; attempt < 3; attempt++) {
    udp.beginPacket(IPAddress(255, 255, 255, 255), SERVER_PORT);
    udp.print("NOOB?SERVER");
    udp.endPacket();
    unsigned long start = millis();
    while (millis() - start < 700) {
      if (readUdp(msg, sizeof(msg)) && strncmp(msg, "NOOB!SERVER|", 12) == 0) {
        savePairing(String(msg + 12), deviceKey);
        Serial.printf("[NOOB] Server found at %s\n", serverUrl.c_str());
        return true;
      }
      delay(10);
    }
  }
  return false;
}

// Says hello to the NOOB server, so the app shows NOOB as online and NOOB knows the PC is on.
void pingServer(bool retry = true) {
  if (!isPaired() || WiFi.status() != WL_CONNECTED) return;
  bool wasOnline = pcOnline;
  String url = serverUrl;
  url.replace("/ask", "/device/ping");
  HTTPClient http;
  http.begin(url);
  http.setConnectTimeout(2500);
  http.setTimeout(3000);
  http.addHeader("X-Device-Key", deviceKey);
  int code = http.GET();
  if (code == 200) {
    pcOnline = true;
    String body = http.getString();                  // {"name":"Padmanabh","ok":true}
    int start = body.indexOf("\"name\":\"");
    if (start >= 0) {
      start += 8;
      ownerName = body.substring(start, body.indexOf('"', start));
    }
  } else {
    pcOnline = false;
    if (code == 403) {                               // this PC no longer knows NOOB
      http.end();
      savePairing("", "");
      showReady();
      return;
    }
  }
  http.end();
  if (!pcOnline && retry && findServer(true)) {      // the PC may have a new IP address
    pingServer(false);
    return;
  }
  if (pcOnline != wasOnline && pairUntil == 0) showReady();
}

// ------------------------------------------------------------------ talking
// Records while the button is held. Returns number of samples recorded.
size_t recordWhileHeld() {
  static int32_t raw[512];
  size_t count = 0;
  float prevIn = 0, prevOut = 0;   // DC-blocking filter state

  showStatus("Listening...", "release to send");

  while (digitalRead(BUTTON_PIN) == LOW && count < MAX_SAMPLES) {
    size_t bytesRead = 0;
    if (i2s_channel_read(micChan, raw, sizeof(raw), &bytesRead, 1000) != ESP_OK) continue;
    size_t n = bytesRead / sizeof(int32_t);
    for (size_t i = 0; i < n && count < MAX_SAMPLES; i++) {
      float x = (float)(raw[i] >> MIC_GAIN_SHIFT);
      float y = x - prevIn + 0.995f * prevOut;       // remove DC offset
      prevIn = x; prevOut = y;
      if (y > 32767.0f) y = 32767.0f;
      if (y < -32768.0f) y = -32768.0f;
      recBuf[count++] = (int16_t)y;
    }
  }
  return count;
}

// Everything written here goes straight to the speaker (16-bit samples, with the volume applied).
class SpeakerStream : public Stream {
 public:
  size_t write(const uint8_t* data, size_t len) override {
    static int16_t out[512];
    size_t count = 0, i = 0;
    if (hasCarry && len > 0) {                          // a sample that was split between two pieces
      out[count++] = scale((int16_t)(carry | (data[0] << 8)));
      i = 1;
      hasCarry = false;
    }
    for (; i + 1 < len; i += 2) {
      out[count++] = scale((int16_t)(data[i] | (data[i + 1] << 8)));
      if (count == 512) { play(out, count); count = 0; }
    }
    if (i < len) { carry = data[i]; hasCarry = true; }
    play(out, count);
    return len;
  }
  size_t write(uint8_t b) override { return write(&b, 1); }
  int available() override { return 0; }
  int read() override { return -1; }
  int peek() override { return -1; }

 private:
  uint8_t carry = 0;
  bool hasCarry = false;
  static int16_t scale(int16_t s) { return (int16_t)(((int32_t)s * VOLUME_PERCENT) / 100); }
  static void play(const int16_t* samples, size_t count) {
    if (count == 0) return;
    size_t written = 0;
    i2s_channel_write(spkChan, samples, count * sizeof(int16_t), &written, portMAX_DELAY);
  }
};

int postAudio(HTTPClient& http, size_t samples) {
  http.begin(serverUrl);
  http.setConnectTimeout(8000);
  http.setTimeout(60000);   // NOOB may take a while to think / search
  http.addHeader("Content-Type", "application/octet-stream");
  http.addHeader("X-Device-Key", deviceKey);
  return http.POST((uint8_t*)recBuf, samples * sizeof(int16_t));
}

// Sends audio to the server and plays the spoken reply as it arrives.
void askServerAndPlay(size_t samples) {
  connectWiFi();
  if (WiFi.status() != WL_CONNECTED) return;

  showStatus("Thinking...", "");
  HTTPClient http;
  int code = postAudio(http, samples);
  if (code < 0) {                           // PC not found: its IP address may have changed
    http.end();
    if (findServer()) {
      showStatus("Thinking...", "");
      code = postAudio(http, samples);
    }
  }
  if (code != 200) {
    Serial.printf("[NOOB] HTTP error: %d (%s)\n", code, http.errorToString(code).c_str());
    if (code == 403)    { savePairing("", ""); showStatus("Not paired with PC", "pair again in app"); }
    else if (code < 0)  showStatus("PC not found", "is NOOB App open?");
    else                showStatus("Server error", "see NOOB App log");
    delay(2500);
    http.end();
    showReady();
    return;
  }

  // The answer arrives sentence by sentence while the PC is still making the rest, so NOOB starts
  // speaking at once. writeToStream() unwraps the web "chunks" and passes pure audio to the speaker.
  showStatus("Speaking...", "");
  SpeakerStream speaker;
  int result = http.writeToStream(&speaker);
  if (result < 0) Serial.printf("[NOOB] Stream ended early: %s\n", http.errorToString(result).c_str());

  http.end();
  pcOnline = true;
  showReady();
}

// ------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  delay(500);
  pinMode(BUTTON_PIN, INPUT_PULLUP);

  Wire.begin(OLED_SDA, OLED_SCL);
  oledOk = display.begin(SSD1306_SWITCHCAPVCC, 0x3C) || display.begin(SSD1306_SWITCHCAPVCC, 0x3D);
  if (!oledOk) Serial.println("[NOOB] OLED not found - continuing without screen");
  showStatus("Starting...", "");

  if (!psramFound()) {
    showStatus("NO PSRAM!", "Tools > PSRAM > OPI");
    haltWithError();
  }
  recBuf = (int16_t*)ps_malloc(MAX_SAMPLES * sizeof(int16_t));
  if (!recBuf) {
    showStatus("Memory error", "");
    haltWithError();
  }

  if (!setupMic())     { showStatus("Mic init failed", "");     haltWithError(); }
  if (!setupSpeaker()) { showStatus("Speaker init failed", ""); haltWithError(); }

  prefs.begin("noob", false);
  serverUrl = prefs.getString("url", "");
  deviceKey = prefs.getString("key", "");

  connectWiFi();
  String mac = WiFi.macAddress();              // e.g. "AA:BB:CC:DD:EE:FF" -> name "NOOB-EEFF"
  deviceName = "NOOB-" + mac.substring(12, 14) + mac.substring(15, 17);
  lastWifiTry = millis();
  pingServer();
  lastPing = millis();
  showReady();
}

void loop() {
  handleUdp();

  if (pairUntil != 0 && (long)(millis() - pairUntil) > 0) {     // pairing code expired
    pairUntil = 0;
    showReady();
  }
  if (WiFi.status() != WL_CONNECTED && millis() - lastWifiTry > 30000) {
    lastWifiTry = millis();
    connectWiFi();
    showReady();
  }
  if (pairUntil == 0 && millis() - lastPing > (pcOnline ? PING_ONLINE_MS : PING_OFFLINE_MS)) {
    lastPing = millis();
    pingServer();
  }

  if (digitalRead(BUTTON_PIN) == LOW) {
    delay(30);                                   // debounce
    if (digitalRead(BUTTON_PIN) != LOW) return;

    if (!isPaired()) {
      showStatus("Not paired yet", "NOOB App > Devices");
      while (digitalRead(BUTTON_PIN) == LOW) delay(10);
      return;
    }

    unsigned long pressedAt = millis();
    size_t samples = recordWhileHeld();
    unsigned long heldMs = millis() - pressedAt;

    if (heldMs < MIN_RECORD_MS || samples < SAMPLE_RATE / 4) {
      showStatus("Too short", "hold while speaking");
      delay(800);
      showReady();
    } else {
      askServerAndPlay(samples);
    }
    while (digitalRead(BUTTON_PIN) == LOW) delay(10);   // wait for release (10 s limit case)
  }
  delay(10);
}
